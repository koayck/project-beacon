from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastmcp.utilities.lifespan import combine_lifespans
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types
from pydantic import BaseModel

from backend.db.repository import init_db, asset_repo, mission_log_repo
from backend.db.models import Asset, MissionLog
from backend.grpc.client import DroneGrpcClient
from backend.output_format import (
    is_structured_sweep_report,
    is_sweep_scan_prompt,
    prefer_structured_sweep_report,
)
from backend.telemetry.udp_listener import UDPTelemetryListener
from backend.telemetry.ws_bridge import TelemetryBroadcaster
from backend.licensing.routes import router as license_router
from backend.mcp.server import beacon_mcp
from backend.runtime import grpc_client, udp_listener, ws_broadcaster
from backend.services.api import (
    discover_fleet,
    ensure_uplink,
    list_all_drones,
    recall_swarm,
    return_to_base as rtb_service,
    restore_registered_connections,
    scan_frequencies as scan_unlinked_frequencies,
    set_drone_speed,
)
from backend.services.auto_recall import AutoRecallMonitor

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

_adk_runner: Runner | None = None
_auto_recall_monitor: AutoRecallMonitor | None = None

_ASSET_ID_PATTERN = re.compile(r"^BEACON-(\d+)$")
_DOCKER_IMAGE = "project-beacon-drone-sim"
_DOCKER_NETWORK = "beacon-net"
_AUTO_RECALL_ENABLED = os.environ.get("AUTO_RECALL_ENABLED", "false").strip().lower() in {
    "1", "true", "yes", "on",
}
_AUTO_RECALL_BATTERY_THRESHOLD = float(
    os.environ.get("AUTO_RECALL_BATTERY_THRESHOLD", "10")
)
_AUTO_RECALL_COOLDOWN_SECONDS = float(
    os.environ.get("AUTO_RECALL_COOLDOWN_SECONDS", "60")
)
_STARLINK_STATUS_FILE = Path(
    os.environ.get(
        "STARLINK_MOCK_STATUS_FILE",
        Path(__file__).resolve().parents[1] / ".starlink-mock-status",
    )
)


_mcp_http_app = beacon_mcp.http_app(path="/", transport="streamable-http")


def _first_exception_message(exc: BaseException) -> str:
    """Return the first concrete nested exception message for ExceptionGroup errors."""
    current: BaseException = exc
    while isinstance(current, BaseExceptionGroup) and current.exceptions:
        next_exc = current.exceptions[0]
        if isinstance(next_exc, BaseException):
            current = next_exc
        else:
            break
    return f"{type(current).__name__}: {current}"


def _extract_survivor_coords(payload: object) -> list[dict[str, float]]:
    """Extract unique survivor coordinates from nested tool responses."""
    seen: set[tuple[float, float, float]] = set()
    survivors: list[dict[str, float]] = []
    survivor_collection_keys = {
        "unique_survivors_detected",
        "detected_survivors",
        "detected_survivors_within_scan_radius",
        "survivors_visible",
        "survivors",
    }

    def _add_point(candidate: object) -> None:
        if not isinstance(candidate, dict):
            return
        x = candidate.get("x")
        y = candidate.get("y")
        z = candidate.get("z")
        if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not isinstance(z, (int, float)):
            return
        key = (round(float(x), 3), round(float(y), 3), round(float(z), 3))
        if key in seen:
            return
        seen.add(key)
        survivors.append({"x": key[0], "y": key[1], "z": key[2]})

    def _walk(node: object, from_survivor_collection: bool = False) -> None:
        if isinstance(node, dict):
            if from_survivor_collection or (
                node.get("object_type") == "survivor"
                or "submerged" in node
                or "distance" in node
            ):
                _add_point(node)
            for key, value in node.items():
                if key == "objects" and isinstance(value, list):
                    for obj in value:
                        if isinstance(obj, dict) and obj.get("object_type") == "survivor":
                            _add_point(obj)
                _walk(value, key in survivor_collection_keys)
            return
        if isinstance(node, list):
            for item in node:
                _walk(item, from_survivor_collection)

    _walk(payload)
    return survivors


def _extract_supply_dispatches(tool_name: str, payload: object) -> list[dict[str, object]]:
    """Extract structured supply-dispatch rows from tool responses."""
    if tool_name == "build_aggregated_supply_report":
        # Final report returns historical rows; don't re-emit old dispatches.
        return []
    if not isinstance(payload, dict):
        return []

    rows = payload.get("results")
    if not isinstance(rows, list):
        return []

    dispatches: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        supply_result = row.get("supply_result")
        if not isinstance(supply_result, dict):
            continue
        if "error" in supply_result:
            continue

        asset_id = row.get("asset_id")
        target = row.get("target", row.get("survivor", row.get("building")))
        drop_point = supply_result.get("drop_point")
        if not isinstance(asset_id, str):
            continue
        if not isinstance(target, dict):
            continue
        if not isinstance(drop_point, dict):
            continue

        sx = target.get("x")
        sy = target.get("y")
        sz = target.get("z")
        dx = drop_point.get("x")
        dy = drop_point.get("y")
        dz = drop_point.get("z")
        if not isinstance(sx, (int, float)) or not isinstance(sz, (int, float)):
            continue
        if not isinstance(dx, (int, float)) or not isinstance(dy, (int, float)) or not isinstance(dz, (int, float)):
            continue

        item: dict[str, object] = {
            "asset_id": asset_id,
            "survivor": {
                "x": float(sx),
                "y": float(sy) if isinstance(sy, (int, float)) else 0.0,
                "z": float(sz),
            },
            "drop_point": {"x": float(dx), "y": float(dy), "z": float(dz)},
        }
        matched_building = supply_result.get("matched_building")
        if isinstance(matched_building, dict):
            bx = matched_building.get("center_x")
            bz = matched_building.get("center_z")
            if isinstance(bx, (int, float)) and isinstance(bz, (int, float)):
                item["building"] = {"x": float(bx), "z": float(bz)}
        dispatches.append(item)
    return dispatches


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global _adk_runner, _auto_recall_monitor

    await init_db()
    _auto_recall_monitor = AutoRecallMonitor(
        enabled=_AUTO_RECALL_ENABLED,
        battery_threshold=_AUTO_RECALL_BATTERY_THRESHOLD,
        cooldown_seconds=_AUTO_RECALL_COOLDOWN_SECONDS,
    )
    _auto_recall_monitor.start()

    def _on_telemetry_update(payload: dict) -> None:
        ws_broadcaster.broadcast(payload)
        if _auto_recall_monitor is not None:
            _auto_recall_monitor.handle_telemetry(payload)

    await udp_listener.start(on_update=_on_telemetry_update)
    await restore_registered_connections()

    # from backend.tools.drone_commands import set_client as _set_drone_cmd_client
    # _set_drone_cmd_client(grpc_client)

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

    try:
        yield
    finally:
        if _adk_runner is not None:
            await _adk_runner.close()
            _adk_runner = None
        await udp_listener.stop()
        if _auto_recall_monitor is not None:
            await _auto_recall_monitor.stop()
            _auto_recall_monitor = None
        grpc_client.close_all()


app = FastAPI(
    title="Project Beacon",
    version="0.1.0",
    lifespan=combine_lifespans(_mcp_http_app.lifespan, app_lifespan),
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


class SpeedRequest(BaseModel):
    speed: float


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
    if req.asset_id and req.asset_id.upper() not in ("AUTO", ""):
        prompt_parts.append(
            f"Preferred asset: {req.asset_id}. Use it if it is active and suitable, "
            "but discover the fleet first before committing to it."
        )
    prompt_parts.append(f"Mission: {req.prompt}")
    return " ".join(prompt_parts)


def _read_starlink_mock_status() -> dict[str, object]:
    status: dict[str, object] = {
        "mode": "unknown",
        "updated_at": None,
        "source": None,
        "target_ssid": "Starlink",
        "active_ssids": [],
        "container_count": 0,
        "status_file": str(_STARLINK_STATUS_FILE),
    }

    if not _STARLINK_STATUS_FILE.exists():
        return status

    try:
        content = _STARLINK_STATUS_FILE.read_text(encoding="utf-8")
    except OSError:
        return status

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "active_ssids":
            status["active_ssids"] = [ssid for ssid in value.split(",") if ssid]
        elif key == "container_count":
            try:
                status["container_count"] = int(value)
            except ValueError:
                status["container_count"] = 0
        elif key in status:
            status[key] = value if value else None
    return status


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/config/auto-recall")
async def auto_recall_config() -> dict:
    return {
        "enabled": _AUTO_RECALL_ENABLED,
        "battery_threshold": _AUTO_RECALL_BATTERY_THRESHOLD,
        "cooldown_seconds": _AUTO_RECALL_COOLDOWN_SECONDS,
    }


@app.get("/network/mock-status")
async def network_mock_status() -> dict[str, object]:
    """Return host-driven Starlink tc mock status for frontend visibility."""
    return _read_starlink_mock_status()


@app.post("/drone/{asset_id}/speed")
async def set_speed(asset_id: str, req: SpeedRequest) -> dict:
    """Set the movement speed for all future commands issued to this drone."""
    set_drone_speed(asset_id, req.speed)
    return {"asset_id": asset_id, "speed": req.speed}


@app.post("/world/{world_id}")
async def switch_world(world_id: int) -> dict:
    """Switch the active world for backend and all connected drones."""
    from backend.world.model import load_world as load_backend_world
    load_backend_world(world_id)
    # Tell each connected drone container to reload its world data
    results = {}
    for aid in grpc_client.registered_asset_ids():
        try:
            r = await grpc_client.switch_world(aid, world_id)
            results[aid] = r
        except Exception as e:
            results[aid] = {"success": False, "message": str(e)}
    return {"world_id": world_id, "drones": results}


@app.post("/drone/{asset_id}/reset")
async def reset_drone_to_base(asset_id: str) -> dict:
    """Command a drone to return to base using obstacle-aware routing."""
    result = await rtb_service(asset_id)
    return {"asset_id": asset_id, **result}


@app.get("/assets")
async def list_assets() -> list[dict]:
    """Return all registered drone assets."""
    assets = await asset_repo.list_all()
    return [a.model_dump() for a in assets]


@app.get("/fleet")
async def list_fleet() -> dict:
    """Return the active fleet state the MCP agent reasons over."""
    return await discover_fleet(auto_uplink=False, include_registered=True)


@app.post("/fleet/recall")
async def fleet_recall() -> dict:
    """Command all registered drones to return to base concurrently."""
    drone_info = await list_all_drones()
    asset_ids = [d["asset_id"] for d in drone_info.get("drones", [])]
    if not asset_ids:
        return {"recalled": [], "message": "No drones registered"}
    return await recall_swarm(asset_ids)


@app.post("/fleet/speed")
async def fleet_speed(req: SpeedRequest) -> dict:
    """Set speed for all registered drones."""
    drone_info = await list_all_drones()
    asset_ids = [d["asset_id"] for d in drone_info.get("drones", [])]
    for aid in asset_ids:
        set_drone_speed(aid, req.speed)
    return {"asset_ids": asset_ids, "speed": req.speed}


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
    text_candidates: list[str] = []
    sweep_prompt = is_sweep_scan_prompt(req.prompt)
    async for event in _adk_runner.run_async(
        user_id="gcs",
        session_id=session_id,
        new_message=content,
    ):
        if not event.content or not event.content.parts:
            continue

        for part in event.content.parts:
            if part.text and part.text.strip():
                text_candidates.append(part.text)
            elif part.function_response:
                resp = dict(part.function_response.response or {})
                message = resp.get("message")
                if isinstance(message, str) and message.strip():
                    text_candidates.append(message)

        if event.is_final_response():
            for part in event.content.parts:
                if part.text and part.text.strip():
                    response_text = part.text
                    break

    if sweep_prompt:
        response_text = prefer_structured_sweep_report(
            prompt=req.prompt,
            text_candidates=text_candidates,
            fallback_text=response_text,
        )

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
        stream_start = time.perf_counter()
        first_token_time: float | None = None
        total_chars = 0
        sweep_prompt = is_sweep_scan_prompt(req.prompt)
        preferred_sweep_report: str | None = None

        async def adk_loop() -> None:
            try:
                async for event in _adk_runner.run_async(
                    user_id="gcs",
                    session_id=session_id,
                    new_message=content,
                ):
                    await queue.put(("event", event))
            except Exception as exc:
                err_text = _first_exception_message(exc)
                logging.getLogger(__name__).exception("ADK stream error: %s", err_text)
                await queue.put(("error", err_text))
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
                        message = resp.get("message")
                        survivors_payload = _extract_survivor_coords(resp)
                        supply_dispatches = _extract_supply_dispatches(part.function_response.name, resp)
                        if (
                            sweep_prompt
                            and isinstance(message, str)
                            and is_structured_sweep_report(message)
                        ):
                            preferred_sweep_report = message
                            final_text = message
                            if first_token_time is None:
                                first_token_time = time.perf_counter()
                            total_chars += len(message)
                            payload: dict = {"type": "text", "text": message, "agent": event.author}
                            if survivors_payload:
                                payload["survivors"] = survivors_payload
                            if supply_dispatches:
                                payload["supply_dispatches"] = supply_dispatches
                            yield f"data: {json.dumps(payload)}\n\n"
                            continue
                        payload = {
                            "type": "tool_result",
                            "name": part.function_response.name,
                            "success": resp.get("success", True),
                            "result": resp.get("message", str(resp)),
                        }
                        if survivors_payload:
                            payload["survivors"] = survivors_payload
                        if supply_dispatches:
                            payload["supply_dispatches"] = supply_dispatches
                        yield f"data: {json.dumps(payload)}\n\n"
                    elif part.text and part.text.strip():
                        if sweep_prompt and is_structured_sweep_report(part.text):
                            if preferred_sweep_report is None:
                                preferred_sweep_report = part.text
                                if first_token_time is None:
                                    first_token_time = time.perf_counter()
                                total_chars += len(part.text)
                                payload = {"type": "text", "text": part.text, "agent": event.author}
                                yield f"data: {json.dumps(payload)}\n\n"
                            final_text = preferred_sweep_report
                            continue

                        if sweep_prompt and preferred_sweep_report is not None:
                            # Suppress follow-on paraphrase text after structured sweep report.
                            if event.is_final_response():
                                final_text = preferred_sweep_report
                            continue

                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                        total_chars += len(part.text)
                        if event.is_final_response():
                            final_text = part.text
                            payload = {"type": "final", "text": part.text, "agent": event.author}
                        else:
                            payload = {"type": "text", "text": part.text, "agent": event.author}
                        yield f"data: {json.dumps(payload)}\n\n"
        finally:
            hb_task.cancel()
            adk_task.cancel()
            await asyncio.gather(adk_task, hb_task, return_exceptions=True)
            await mission_log_repo.create(MissionLog(
                asset_id=req.asset_id or "FLEET",
                command="natural_language",
                params=req.prompt,
                result=final_text,
            ))
            now = time.perf_counter()
            ttft_ms = round((first_token_time - stream_start) * 1000, 1) if first_token_time else None
            gen_secs = (now - first_token_time) if first_token_time else None
            tps = round((total_chars / 4) / gen_secs, 1) if gen_secs and gen_secs > 0 else None
            yield f"data: {json.dumps({'type': 'done', 'ttft_ms': ttft_ms, 'tps': tps})}\n\n"

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
