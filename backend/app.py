from __future__ import annotations

import asyncio
import json
import re
import subprocess
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from pydantic import BaseModel

from backend.db.repository import init_db, asset_repo, mission_log_repo
from backend.db.models import Asset, MissionLog
from backend.grpc.client import DroneGrpcClient
from backend.telemetry.udp_listener import UDPTelemetryListener
from backend.telemetry.ws_bridge import TelemetryBroadcaster
from backend.licensing.routes import router as license_router

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

# ── Shared state ──────────────────────────────────────────────────────────────

udp_listener = UDPTelemetryListener()
ws_broadcaster = TelemetryBroadcaster()
grpc_client = DroneGrpcClient()
_adk_runner: Runner | None = None

_ASSET_ID_PATTERN = re.compile(r"^BEACON-(\d+)$")
_DOCKER_IMAGE = "project-beacon-drone-sim"
_DOCKER_NETWORK = "beacon-net"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _adk_runner

    await init_db()
    await udp_listener.start(on_update=ws_broadcaster.broadcast)

    # Inject gRPC client into tool layer
    from backend.tools.drone_commands import set_client
    set_client(grpc_client)

    # Re-register gRPC connections for assets already in the DB (survive restarts)
    for asset in await asset_repo.list_all():
        grpc_client.register(asset.asset_id, asset.grpc_host, asset.grpc_port)
        logging.getLogger(__name__).info(
            "Restored gRPC connection: %s → %s:%s",
            asset.asset_id, asset.grpc_host, asset.grpc_port,
        )

    # Build ADK runner (lazy import avoids circular deps at module load)
    from backend.agents.commander import commander
    _adk_runner = Runner(
        agent=commander,
        session_service=InMemorySessionService(),
        app_name="beacon",
    )
    logging.getLogger(__name__).info("ADK commander agent ready")

    yield

    await udp_listener.stop()
    grpc_client.close_all()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Project Beacon", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(license_router, prefix="/license", tags=["license"])


# ── Request / Response schemas ────────────────────────────────────────────────

class SpawnRequest(BaseModel):
    asset_class: str = "scout_quadcopter"

class UplinkResponse(BaseModel):
    asset_id: str
    grpc_host: str
    grpc_port: int
    message: str

class CommandRequest(BaseModel):
    asset_id: str
    prompt: str  # natural language — routed through ADK (Phase 3)


# ── Routes ────────────────────────────────────────────────────────────────────

def _extract_asset_index(asset_id: str) -> int | None:
    match = _ASSET_ID_PATTERN.fullmatch(asset_id.upper())
    if not match:
        return None
    return int(match.group(1))


def _list_docker_asset_ids() -> set[str]:
    try:
        result = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return set()

    if result.returncode != 0:
        return set()

    asset_ids: set[str] = set()
    for raw_name in result.stdout.splitlines():
        asset_id = raw_name.strip().upper()
        if _extract_asset_index(asset_id) is not None:
            asset_ids.add(asset_id)
    return asset_ids


async def _allocate_spawn_identity() -> tuple[str, int]:
    registered = {asset.asset_id for asset in await asset_repo.list_all()}
    discovered = set(udp_listener.get_known_assets())
    docker_assets = _list_docker_asset_ids()

    used_indices = {
        idx
        for asset_id in registered | discovered | docker_assets
        if (idx := _extract_asset_index(asset_id)) is not None
    }

    next_idx = 1
    while next_idx in used_indices:
        next_idx += 1

    return f"BEACON-{next_idx:02d}", 50050 + next_idx


def _assert_container_running(container_name: str) -> None:
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", container_name],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0 and result.stdout.strip().lower() == "true":
        return

    detail = result.stderr.strip() or result.stdout.strip() or "container exited immediately"
    raise HTTPException(status_code=500, detail=f"Spawn failed for {container_name}: {detail}")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/assets")
async def list_assets() -> list[dict]:
    """Return all registered drone assets."""
    assets = await asset_repo.list_all()
    return [a.model_dump() for a in assets]


@app.post("/spawn")
async def spawn_drone(req: SpawnRequest) -> dict:
    """
    Spin up a new simulated drone Docker container.
    The container will start broadcasting UDP heartbeats immediately.
    """
    asset_id, grpc_port = await _allocate_spawn_identity()
    container_name = asset_id.lower()

    try:
        result = subprocess.run(
            [
                "docker", "run", "-d", "--rm",
                "--network", _DOCKER_NETWORK,
                "-e", f"ASSET_ID={asset_id}",
                "-e", f"GRPC_PORT=50051",
                "-p", f"{grpc_port}:50051",
                "--name", container_name,
                _DOCKER_IMAGE,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Docker not available")

    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "docker run failed"
        raise HTTPException(status_code=500, detail=f"Failed to spawn {asset_id}: {detail}")

    _assert_container_running(container_name)

    return {
        "asset_id": asset_id,
        "asset_class": req.asset_class,
        "grpc_port": grpc_port,
        "message": f"Spawned {asset_id}, waiting for heartbeat...",
    }


@app.post("/uplink/{asset_id}", response_model=UplinkResponse)
async def establish_uplink(asset_id: str) -> UplinkResponse:
    """
    Lock gRPC channel to a discovered drone and register it in the database.
    The drone must already be broadcasting heartbeats (detected via UDP scan).
    """
    # Check the drone is broadcasting telemetry
    known = udp_listener.get_known_assets()
    if asset_id not in known:
        raise HTTPException(
            status_code=404,
            detail=f"{asset_id} not found. Run /scan first.",
        )

    # Determine gRPC address from asset_id index
    idx = int(asset_id.split("-")[1])
    grpc_host = "localhost"
    grpc_port = 50050 + idx

    # Register in DB
    asset = Asset(
        asset_id=asset_id,
        asset_class="scout_quadcopter",
        grpc_host=grpc_host,
        grpc_port=grpc_port,
    )
    await asset_repo.upsert(asset)

    # Open gRPC channel
    grpc_client.register(asset_id, grpc_host, grpc_port)

    return UplinkResponse(
        asset_id=asset_id,
        grpc_host=grpc_host,
        grpc_port=grpc_port,
        message=f"Uplink established with {asset_id}",
    )


@app.get("/scan")
async def scan_frequencies() -> dict:
    """Return drones currently broadcasting heartbeats (not yet uplinked)."""
    known = udp_listener.get_known_assets()
    registered = {a.asset_id for a in await asset_repo.list_all()}
    unlinked = [k for k in known if k not in registered]
    return {
        "discovered": [
            {**known[k], "signal_pct": 98}
            for k in unlinked
        ]
    }


@app.post("/command")
async def send_command(req: CommandRequest) -> dict:
    """
    Send a natural language command through the ADK Commander Agent.
    The agent routes to Navigation or Thermal sub-agents via LiteLLM → Ollama.
    """
    if _adk_runner is None:
        raise HTTPException(status_code=503, detail="ADK runner not initialised")

    asset = await asset_repo.get(req.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"{req.asset_id} not uplinked")

    # Include asset context so the agent knows which drone to act on
    prompt = f"Asset: {req.asset_id}. Command: {req.prompt}"
    content = genai_types.Content(
        role="user", parts=[genai_types.Part(text=prompt)]
    )

    session_id = str(uuid.uuid4())
    await _adk_runner.session_service.create_session(
        app_name="beacon",
        user_id="gcs",
        session_id=session_id,
    )

    response_text = ""
    async for event in _adk_runner.run_async(
        user_id="gcs",
        session_id=session_id,
        new_message=content,
    ):
        if event.is_final_response() and event.content and event.content.parts:
            response_text = event.content.parts[0].text

    await mission_log_repo.create(MissionLog(
        asset_id=req.asset_id,
        command="natural_language",
        params=req.prompt,
        result=response_text,
    ))

    return {"asset_id": req.asset_id, "response": response_text, "prompt": req.prompt}


@app.post("/command/stream")
async def send_command_stream(req: CommandRequest) -> StreamingResponse:
    """
    Stream ADK agent events via Server-Sent Events.
    Emits tool_call, tool_result, text, and done events as they happen.
    """
    if _adk_runner is None:
        raise HTTPException(status_code=503, detail="ADK runner not initialised")

    asset = await asset_repo.get(req.asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"{req.asset_id} not uplinked")

    prompt = f"Asset: {req.asset_id}. Command: {req.prompt}"
    content = genai_types.Content(
        role="user", parts=[genai_types.Part(text=prompt)]
    )

    session_id = str(uuid.uuid4())
    await _adk_runner.session_service.create_session(
        app_name="beacon",
        user_id="gcs",
        session_id=session_id,
    )

    async def generate() -> AsyncGenerator[str, None]:
        final_text = ""
        queue: asyncio.Queue = asyncio.Queue()

        async def adk_loop() -> None:
            """Run ADK in a background task, pushing events to the queue."""
            try:
                async for event in _adk_runner.run_async(
                    user_id="gcs",
                    session_id=session_id,
                    new_message=content,
                ):
                    await queue.put(("event", event))
            except Exception as exc:
                await queue.put(("error", exc))
            finally:
                await queue.put(("end", None))

        async def heartbeat() -> None:
            """Emit periodic keepalive so the frontend knows we're alive."""
            elapsed = 0
            while True:
                await asyncio.sleep(3)
                elapsed += 3
                await queue.put(("heartbeat", elapsed))

        adk_task = asyncio.create_task(adk_loop())
        hb_task = asyncio.create_task(heartbeat())

        try:
            while True:
                kind, data = await queue.get()

                if kind == "heartbeat":
                    yield f"data: {json.dumps({'type': 'heartbeat', 'elapsed': data})}\n\n"
                    continue

                if kind == "error":
                    yield f"data: {json.dumps({'type': 'error', 'text': str(data)})}\n\n"
                    break

                if kind == "end":
                    break

                # kind == "event"
                event = data
                if not event.content or not event.content.parts:
                    continue
                for part in event.content.parts:
                    if part.function_call:
                        payload = {
                            "type": "tool_call",
                            "name": part.function_call.name,
                            "args": dict(part.function_call.args or {}),
                            "agent": event.author,
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                    elif part.function_response:
                        resp = dict(part.function_response.response or {})
                        payload = {
                            "type": "tool_result",
                            "name": part.function_response.name,
                            "success": resp.get("success", True),
                            "result": resp.get("message", str(resp)),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                    elif part.text and part.text.strip():
                        if event.is_final_response():
                            final_text = part.text
                            payload = {"type": "final", "text": part.text, "agent": event.author}
                        else:
                            payload = {"type": "text", "text": part.text, "agent": event.author}
                        yield f"data: {json.dumps(payload)}\n\n"
        finally:
            hb_task.cancel()
            await asyncio.gather(adk_task, return_exceptions=True)
            await mission_log_repo.create(MissionLog(
                asset_id=req.asset_id,
                command="natural_language",
                params=req.prompt,
                result=final_text,
            ))
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── WebSocket telemetry stream ─────────────────────────────────────────────────

@app.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket):
    await websocket.accept()
    ws_broadcaster.connect(websocket)
    try:
        while True:
            await asyncio.sleep(30)  # keep-alive; data pushed by broadcaster
    except WebSocketDisconnect:
        ws_broadcaster.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
