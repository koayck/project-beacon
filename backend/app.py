from __future__ import annotations

import asyncio
import json
import re
import subprocess
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastmcp.utilities.lifespan import combine_lifespans
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from pydantic import BaseModel

from backend.db.models import MissionLog
from backend.db.repository import asset_repo, init_db, mission_log_repo
from backend.licensing.routes import router as license_router
from backend.mcp.server import beacon_mcp
from backend.runtime import grpc_client, udp_listener, ws_broadcaster
from backend.services.fleet import (
    discover_fleet,
    ensure_uplink,
    restore_registered_connections,
    scan_frequencies as scan_unlinked_frequencies,
)

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

_adk_runner: Runner | None = None

_ASSET_ID_PATTERN = re.compile(r"^BEACON-(\d+)$")
_DOCKER_IMAGE = "project-beacon-drone-sim"
_DOCKER_NETWORK = "beacon-net"


_mcp_http_app = beacon_mcp.http_app(path="/", transport="streamable-http")


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global _adk_runner

    await init_db()
    await udp_listener.start(on_update=ws_broadcaster.broadcast)
    await restore_registered_connections()

    for asset in await asset_repo.list_all():
        logging.getLogger(__name__).info(
            "Restored gRPC connection: %s -> %s:%s",
            asset.asset_id, asset.grpc_host, asset.grpc_port,
        )

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


app = FastAPI(
    title="Project Beacon",
    version="0.1.0",
    lifespan=combine_lifespans(app_lifespan, _mcp_http_app.lifespan),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/mcp", _mcp_http_app)
app.include_router(license_router, prefix="/license", tags=["license"])


class SpawnRequest(BaseModel):
    asset_class: str = "scout_quadcopter"


class UplinkResponse(BaseModel):
    asset_id: str
    grpc_host: str
    grpc_port: int
    message: str


class CommandRequest(BaseModel):
    asset_id: str | None = None
    prompt: str


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


def _build_agent_prompt(req: CommandRequest) -> str:
    prompt_parts: list[str] = []
    if req.asset_id:
        prompt_parts.append(
            f"Preferred asset: {req.asset_id}. Use it if it is active and suitable, "
            "but discover the fleet first before committing to it."
        )
    prompt_parts.append(f"Mission: {req.prompt}")
    return " ".join(prompt_parts)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/assets")
async def list_assets() -> list[dict]:
    """Return all registered drone assets."""
    assets = await asset_repo.list_all()
    return [a.model_dump() for a in assets]


@app.get("/fleet")
async def list_fleet() -> dict:
    """Return the active fleet state the MCP agent reasons over."""
    return await discover_fleet(auto_uplink=False, include_registered=True)


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
                "-e", "GRPC_PORT=50051",
                "-e", "TELEMETRY_HOST=host.docker.internal",
                "-p", f"{grpc_port}:50051",
                "--name", container_name,
                _DOCKER_IMAGE,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail="Docker not available") from exc

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
    The drone must already be broadcasting heartbeats.
    """
    try:
        result = await ensure_uplink(asset_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc

    return UplinkResponse(**result)


@app.get("/scan")
async def scan_frequencies() -> dict:
    """Return drones currently broadcasting heartbeats and not yet uplinked."""
    return {"discovered": await scan_unlinked_frequencies()}


@app.post("/command")
async def send_command(req: CommandRequest) -> dict:
    """
    Send a natural language mission through the ADK commander, which calls MCP
    tools for fleet discovery and drone control.
    """
    if _adk_runner is None:
        raise HTTPException(status_code=503, detail="ADK runner not initialised")

    prompt = _build_agent_prompt(req)
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
        asset_id=req.asset_id or "FLEET",
        command="natural_language",
        params=req.prompt,
        result=response_text,
    ))

    return {
        "asset_id": req.asset_id or "FLEET",
        "response": response_text,
        "prompt": req.prompt,
    }


@app.post("/command/stream")
async def send_command_stream(req: CommandRequest) -> StreamingResponse:
    """
    Stream ADK agent events via Server-Sent Events.
    Emits tool_call, tool_result, text, and done events as they happen.
    """
    if _adk_runner is None:
        raise HTTPException(status_code=503, detail="ADK runner not initialised")

    prompt = _build_agent_prompt(req)
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
                asset_id=req.asset_id or "FLEET",
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


@app.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket):
    await websocket.accept()
    ws_broadcaster.connect(websocket)
    try:
        while True:
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        ws_broadcaster.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
