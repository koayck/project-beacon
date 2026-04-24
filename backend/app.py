from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import subprocess
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.genai import types
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from backend.db.repository import (
    init_db,
    asset_repo,
    mission_log_repo,
    mission_run_repo,
    mission_run_events_repo,
)
from backend.db.models import Asset, MissionLog, MissionRun, MissionRunEvent
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
    add_supply_station,
    discover_fleet,
    ensure_uplink,
    list_all_drones,
    list_supply_stations,
    recall_swarm,
    remove_supply_station,
    return_to_base as rtb_service,
    restore_registered_connections,
    scan_frequencies as scan_unlinked_frequencies,
    set_drone_speed,
)
from backend.services import supply_stations as _supply_stations_registry
from backend.services.auto_recall import AutoRecallMonitor
from backend.services.langfuse_enrichment import fetch_trace_metrics
from backend.services.mission_runs import MissionRunAccumulator
from backend.services.simulation_store import ParsedScanTargets, SimulationStore

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


def combine_lifespans(*lifespans):
    @asynccontextmanager
    async def _combined_lifespan(app: FastAPI):
        async with AsyncExitStack() as exit_stack:
            for lifespan in lifespans:
                await exit_stack.enter_async_context(lifespan(app))
            yield

    return _combined_lifespan

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

_adk_runner: Runner | None = None
_auto_recall_monitor: AutoRecallMonitor | None = None
_simulation_store: SimulationStore | None = None
_ADK_APP_NAME = "beacon"
_ADK_USER_ID = "gcs"
_ADK_SHARED_SESSION_ID = "gcs-shared-session"
_BEACON_DB_PATH = (
    Path(os.environ.get("BEACON_DB_PATH", "./beacon.db")).expanduser().resolve()
)
_BEACON_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
_ADK_SESSION_DB_URL = f"sqlite+aiosqlite:///{_BEACON_DB_PATH}"

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


def _get_langfuse_client():
    """Return the authenticated Langfuse client, or None if unavailable."""
    try:
        from langfuse import get_client
        client = get_client()
        if client.auth_check():
            return client
    except Exception:
        pass
    return None


class _nullcontext:
    """Minimal sync context manager used when Langfuse is unavailable."""
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


def _as_dict(value: object) -> dict | None:
    try:
        value.get  # type: ignore[attr-defined]
    except AttributeError:
        return None
    return value  # type: ignore[return-value]


def _as_list(value: object) -> list | None:
    try:
        value.append  # type: ignore[attr-defined]
        value.__iter__  # type: ignore[attr-defined]
    except AttributeError:
        return None
    return value  # type: ignore[return-value]


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_exception_message(exc: BaseException) -> str:
    """Return the first concrete nested exception message for ExceptionGroup errors."""
    current: BaseException = exc
    while True:
        try:
            next_exc = current.exceptions[0]  # type: ignore[attr-defined]
        except (AttributeError, IndexError, TypeError):
            break
        try:
            raise next_exc
        except BaseException as nested:
            current = nested
    return f"{type(current).__name__}: {current}"


def _enrich_scout_telemetry(payload: dict) -> dict:
    """Add scout exploration fields to telemetry payloads.

    Args:
        payload: Raw telemetry payload received from UDP heartbeat.

    Returns:
        A new payload dictionary. For scout heartbeats, the dictionary includes
        `explored_sectors` and (when present) `sector_reveals` so the frontend
        can progressively clear fog-of-war. Non-scout payloads are returned
        unchanged except for being copied.
    """
    from backend.services.scout import SCOUT_ASSET_ID, exploration_tracker

    enriched_payload = dict(payload)
    asset_id = str(enriched_payload.get("asset_id", "")).strip()
    if asset_id != SCOUT_ASSET_ID:
        return enriched_payload

    exploration_tracker.process_heartbeat(enriched_payload)
    enriched_payload["explored_sectors"] = exploration_tracker.explored_sectors
    pending_reveals = exploration_tracker.pop_pending_reveals()
    if pending_reveals:
        enriched_payload["sector_reveals"] = pending_reveals
    return enriched_payload


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
        candidate_dict = _as_dict(candidate)
        if candidate_dict is None:
            return
        x = _to_float(candidate_dict.get("x"))
        y = _to_float(candidate_dict.get("y"))
        z = _to_float(candidate_dict.get("z"))
        if x is None or y is None or z is None:
            return
        key = (round(x, 3), round(y, 3), round(z, 3))
        if key in seen:
            return
        seen.add(key)
        survivors.append({"x": key[0], "y": key[1], "z": key[2]})

    def _walk(node: object, from_survivor_collection: bool = False) -> None:
        node_dict = _as_dict(node)
        if node_dict is not None:
            if from_survivor_collection or (
                node_dict.get("object_type") == "survivor"
                or "submerged" in node_dict
                or "distance" in node_dict
            ):
                _add_point(node_dict)
            for key, value in node_dict.items():
                if key == "objects" and _as_list(value) is not None:
                    for obj in value:
                        obj_dict = _as_dict(obj)
                        if obj_dict is not None and obj_dict.get("object_type") == "survivor":
                            _add_point(obj_dict)
                _walk(value, key in survivor_collection_keys)
            return
        node_list = _as_list(node)
        if node_list is not None:
            for item in node_list:
                _walk(item, from_survivor_collection)

    _walk(payload)
    return survivors


def _extract_scanned_building_rows(payload: object) -> list[dict[str, object]]:
    """Extract scanned-building survivor rows from nested sweep tool responses.

    Args:
        payload: Arbitrary tool response payload that may contain sweep results.

    Returns:
        A list of rows matching the simulation schema shape:
        [{"building_id": int, "detected_survivors": [{"x": float, "y": float, "z": float}, ...]}, ...].
    """
    by_building_id: dict[int, dict[str, object]] = {}

    def _collect(node: object) -> None:
        node_dict = _as_dict(node)
        if node_dict is not None:
            building = _as_dict(node_dict.get("building"))
            building_id_value = building.get("id") if building is not None else node_dict.get("building_id")
            building_id_float = _to_float(building_id_value)
            if building_id_float is not None and building_id_float.is_integer():
                building_id = int(building_id_float)
                survivors = _extract_survivor_coords(
                    [
                        node_dict.get("unique_survivors_detected", []),
                        node_dict.get("detected_survivors", []),
                        node_dict.get("detected_survivors_within_scan_radius", []),
                        node_dict.get("scan_reports", []),
                    ]
                )
                if not survivors:
                    survivors = _extract_survivor_coords(node_dict)
                existing_row = by_building_id.get(building_id)
                if existing_row is None:
                    by_building_id[building_id] = {
                        "building_id": building_id,
                        "detected_survivors": survivors,
                    }
                else:
                    combined_map: dict[tuple[float, float, float], dict[str, float]] = {}
                    existing_detected = _as_list(existing_row.get("detected_survivors")) or []
                    for item in [*existing_detected, *survivors]:
                        item_dict = _as_dict(item)
                        if item_dict is None:
                            continue
                        x = _to_float(item_dict.get("x"))
                        y = _to_float(item_dict.get("y"))
                        z = _to_float(item_dict.get("z"))
                        if x is None or y is None or z is None:
                            continue
                        key = (round(x, 3), round(y, 3), round(z, 3))
                        combined_map[key] = {"x": key[0], "y": key[1], "z": key[2]}
                    combined = list(combined_map.values())
                    existing_row["detected_survivors"] = combined

            for value in node_dict.values():
                _collect(value)
            return

        node_list = _as_list(node)
        if node_list is not None:
            for item in node_list:
                _collect(item)

    _collect(payload)
    return list(by_building_id.values())


def _extract_supply_dispatches(tool_name: str, payload: object) -> list[dict[str, object]]:
    """Extract structured supply-dispatch rows from tool responses."""
    if tool_name == "build_aggregated_supply_report":
        # Final report returns historical rows; don't re-emit old dispatches.
        return []
    payload_dict = _as_dict(payload)
    if payload_dict is None:
        return []

    rows = _as_list(payload_dict.get("results"))
    if rows is None:
        return []

    dispatches: list[dict[str, object]] = []
    for row in rows:
        row_dict = _as_dict(row)
        if row_dict is None:
            continue
        supply_result = _as_dict(row_dict.get("supply_result"))
        if supply_result is None:
            continue
        if "error" in supply_result:
            continue
        if bool(supply_result.get("skipped", False)):
            continue

        asset_id = row_dict.get("asset_id")
        asset_id_str = str(asset_id).strip() if asset_id is not None else ""
        if not asset_id_str:
            continue
        target = _as_dict(row_dict.get("target", row_dict.get("survivor", row_dict.get("building"))))
        if target is None:
            continue
        drop_point = _as_dict(supply_result.get("drop_point"))
        if drop_point is None:
            continue

        sx = _to_float(target.get("x"))
        sy = _to_float(target.get("y"))
        sz = _to_float(target.get("z"))
        dx = _to_float(drop_point.get("x"))
        dy = _to_float(drop_point.get("y"))
        dz = _to_float(drop_point.get("z"))
        if sx is None or sz is None:
            continue
        if dx is None or dy is None or dz is None:
            continue

        item: dict[str, object] = {
            "asset_id": asset_id_str,
            "survivor": {
                "x": sx,
                "y": sy if sy is not None else 0.0,
                "z": sz,
            },
            "drop_point": {"x": dx, "y": dy, "z": dz},
        }
        matched_building = _as_dict(supply_result.get("matched_building"))
        if matched_building is not None:
            bx = _to_float(matched_building.get("center_x"))
            bz = _to_float(matched_building.get("center_z"))
            if bx is not None and bz is not None:
                item["building"] = {"x": bx, "z": bz}
        dispatches.append(item)
    return dispatches


@asynccontextmanager
async def app_lifespan(app: FastAPI):
    global _adk_runner, _auto_recall_monitor, _simulation_store

    await init_db()
    _auto_recall_monitor = AutoRecallMonitor(
        enabled=_AUTO_RECALL_ENABLED,
        battery_threshold=_AUTO_RECALL_BATTERY_THRESHOLD,
        cooldown_seconds=_AUTO_RECALL_COOLDOWN_SECONDS,
        publish_event=ws_broadcaster.broadcast,
    )
    _auto_recall_monitor.start()

    def _on_telemetry_update(payload: dict) -> None:
        enriched_payload = _enrich_scout_telemetry(payload)
        ws_broadcaster.broadcast(enriched_payload)
        if _auto_recall_monitor is not None:
            _auto_recall_monitor.handle_telemetry(enriched_payload)

    await udp_listener.start(on_update=_on_telemetry_update)
    await restore_registered_connections()
    _supply_stations_registry.reset()

    # from backend.tools.drone_commands import set_client as _set_drone_cmd_client
    # _set_drone_cmd_client(grpc_client)

    for asset in await asset_repo.list_all():
        logging.getLogger(__name__).info(
            "Restored gRPC connection: %s -> %s:%s",
            asset.asset_id, asset.grpc_host, asset.grpc_port,
        )

    from backend.agents.commander import commander

    try:
        _simulation_store = SimulationStore(_BEACON_DB_PATH)
        await _simulation_store.start()
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "Simulation store unavailable; continuing without persistence: %s",
            exc,
        )
        _simulation_store = None

    _adk_runner = Runner(
        agent=commander,
        session_service=_create_adk_session_service(),
        app_name=_ADK_APP_NAME,
    )
    try:
        await _ensure_adk_shared_session(_adk_runner)
    except OSError as exc:
        logging.getLogger(__name__).error("Failed to create ADK session service: %s", exc)
        raise RuntimeError("ADK session service initialization failed") from exc
    logging.getLogger(__name__).info("ADK enhanced commander agent ready")

    try:
        yield
    finally:
        if _adk_runner is not None:
            await _adk_runner.close()
            _adk_runner = None
        if _simulation_store is not None:
            await _simulation_store.stop()
            _simulation_store = None
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
    simulation_id: str | None = None
    confirm_rescan: bool = False


class SimulationCreateRequest(BaseModel):
    simulation_id: str | None = None


class SimulationSurvivor(BaseModel):
    x: float
    y: float
    z: float
    supplied: bool = False


class SimulationBuilding(BaseModel):
    building_id: int
    detected_survivors: list[SimulationSurvivor] = Field(default_factory=list)


class SimulationStateSyncRequest(BaseModel):
    scanned_buildings: list[SimulationBuilding]


class SupplyStationCreateRequest(BaseModel):
    x: float
    z: float


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


async def _ensure_adk_shared_session(runner: Runner) -> str:
    """Ensure a stable ADK session exists for this process lifespan.

    Args:
        runner: Active ADK runner with a session service.

    Returns:
        Stable session ID reused across all command requests in this process.
    """
    try:
        await runner.session_service.create_session(
            app_name=_ADK_APP_NAME,
            user_id=_ADK_USER_ID,
            session_id=_ADK_SHARED_SESSION_ID,
        )
    except (ValueError, AlreadyExistsError):
        # ADK session backends may raise either ValueError or AlreadyExistsError
        # when the same shared session is created concurrently.
        pass
    return _ADK_SHARED_SESSION_ID


def _create_adk_session_service() -> DatabaseSessionService:
    """Create a persistent ADK session service backed by the SQLite database.

    Returns:
        Configured DatabaseSessionService instance using the SQLite DB URL.
    """
    return DatabaseSessionService(db_url=_ADK_SESSION_DB_URL)


def _known_building_rows() -> list[dict[str, float | int]]:
    """Build minimal building rows for scan target resolution.

    Returns:
        List of building dictionaries with id/cx/cz fields.
    """
    from backend.services.core import context as service_context

    world = service_context.get_world()
    return [
        {
            "id": b.id,
            "cx": b.cx,
            "cz": b.cz,
            "min_x": b.min_x,
            "max_x": b.max_x,
            "min_z": b.min_z,
            "max_z": b.max_z,
        }
        for b in world.buildings
    ]


async def _scan_confirmation_conflict(
    prompt: str,
    simulation_id: str | None,
    confirm_rescan: bool,
) -> tuple[list[int], ParsedScanTargets, list[dict[str, Any]], list[dict[str, Any]]]:
    """Evaluate whether a scan command should require confirmation.

    Args:
        prompt: User command text.
        simulation_id: Active simulation ID.
        confirm_rescan: Explicit override from caller.

    Returns:
        Tuple of already-scanned building IDs and parsed scan target info.
    """
    if simulation_id is None or confirm_rescan:
        return [], ParsedScanTargets(building_ids=[], has_scan_intent=False), [], []
    simulation_store = _simulation_store
    if simulation_store is None:
        return [], ParsedScanTargets(building_ids=[], has_scan_intent=False), [], []
    known_rows = _known_building_rows()
    parsed = SimulationStore.parse_scan_targets(prompt, known_rows)
    if not parsed.has_scan_intent or not parsed.building_ids:
        return [], parsed, [], []
    already = await simulation_store.get_already_scanned_buildings(simulation_id, parsed.building_ids)

    by_id = {
        int(row["id"]): row
        for row in known_rows
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }

    already_set = {int(item) for item in already}
    unscanned_ids = [building_id for building_id in parsed.building_ids if building_id not in already_set]

    simulation_snapshot = await simulation_store.get(simulation_id)
    scanned_rows = simulation_snapshot.get("scanned_buildings", []) if isinstance(simulation_snapshot, dict) else []
    scanned_by_id: dict[int, dict[str, Any]] = {}
    for row in scanned_rows:
        if not isinstance(row, dict):
            continue
        building_id = row.get("building_id")
        if isinstance(building_id, int):
            scanned_by_id[building_id] = row

    def _refs(ids: list[int], include_survivors: bool) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []
        for building_id in ids:
            row = by_id.get(int(building_id))
            if row is None:
                continue
            ref: dict[str, Any] = {
                "id": int(building_id),
                "x": float(row.get("cx", 0.0)),
                "z": float(row.get("cz", 0.0)),
            }
            if include_survivors:
                scanned_row = scanned_by_id.get(int(building_id), {})
                raw_survivors = scanned_row.get("detected_survivors", []) if isinstance(scanned_row, dict) else []
                survivors: list[dict[str, Any]] = []
                for survivor in raw_survivors:
                    if not isinstance(survivor, dict):
                        continue
                    x = survivor.get("x")
                    y = survivor.get("y")
                    z = survivor.get("z")
                    if not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or not isinstance(z, (int, float)):
                        continue
                    survivors.append(
                        {
                            "x": float(x),
                            "y": float(y),
                            "z": float(z),
                            "supplied": bool(survivor.get("supplied", False)),
                        }
                    )
                ref["detected_survivor_count"] = len(survivors)
                ref["detected_survivors"] = survivors
            refs.append(ref)
        return refs

    return already, parsed, _refs(list(already), include_survivors=True), _refs(unscanned_ids, include_survivors=False)


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
    from backend.services.scout import cancel_scout_sweep, exploration_tracker

    load_backend_world(world_id)
    # Fog-of-war lives in World 2 only — wipe exploration state on every switch
    # so re-entering a world starts fresh.
    cancel_scout_sweep()
    exploration_tracker.reset()
    # User-placed stations are world-specific (their coords may be inside
    # buildings in a different world). Reset the registry and notify clients.
    _supply_stations_registry.reset()
    ws_broadcaster.broadcast({"type": "supply_stations_reset"})
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


@app.get("/dashboard")
async def get_dashboard() -> dict:
    """Return dashboard payload: overview aggregates + recent runs + current mission.

    Enriches each run with Langfuse cost/token data (best-effort; falls back
    silently if Langfuse is unreachable or the run has no trace ID).
    """
    overview = await mission_run_repo.overview()
    runs = await mission_run_repo.list_recent(limit=50)

    run_dicts = [run.model_dump(mode="json") for run in runs]
    trace_ids: list[str] = [
        str(tid) for r in run_dicts if (tid := r.get("langfuse_trace_id"))
    ]
    trace_metrics = await fetch_trace_metrics(trace_ids)

    total_cost = 0.0
    total_tokens = 0
    for run_dict in run_dicts:
        tid = run_dict.get("langfuse_trace_id")
        metrics = trace_metrics.get(tid) if tid else None
        if metrics:
            run_dict.update(metrics)
            if metrics.get("cost_usd") is not None:
                total_cost += metrics["cost_usd"]
            if metrics.get("total_tokens") is not None:
                total_tokens += metrics["total_tokens"]
        else:
            run_dict.setdefault("input_tokens", None)
            run_dict.setdefault("output_tokens", None)
            run_dict.setdefault("total_tokens", None)
            run_dict.setdefault("cost_usd", None)

    overview["total_cost_usd"] = round(total_cost, 4) if total_cost > 0 else 0.0
    overview["total_tokens"] = total_tokens

    return {
        "overview": overview,
        "runs": run_dicts,
        "currentMission": None,
    }


@app.get("/dashboard/runs/{run_id}/events")
async def get_mission_run_events(run_id: int) -> dict:
    """Return the recorded agent event timeline for one mission run.

    Args:
        run_id: Database ID of the mission run.

    Returns:
        {"run_id": int, "events": [{"seq", "ts", "event_type", "payload"}, ...]}
        where `payload` is the parsed JSON object (or {"raw": str} if the stored
        blob fails to parse — never crash on malformed payloads).
    """
    rows = await mission_run_events_repo.list_for_run(run_id)
    out_events: list[dict] = []
    for row in rows:
        try:
            parsed = json.loads(row.payload)
        except (TypeError, ValueError):
            parsed = {"raw": row.payload}
        out_events.append({
            "seq": row.seq,
            "ts": row.ts,
            "event_type": row.event_type,
            "payload": parsed,
        })
    return {"run_id": run_id, "events": out_events}


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

@app.post("/scout/sweep")
async def deploy_scout_sweep() -> dict:
    """Start the scout drone lawnmower sweep. Requires BEACON-SCOUT to be uplinked."""
    from backend.services.scout import start_scout_sweep, SCOUT_ASSET_ID
    if SCOUT_ASSET_ID not in grpc_client.registered_asset_ids():
        raise HTTPException(status_code=400, detail="BEACON-SCOUT not uplinked")
    start_scout_sweep()
    return {"status": "sweep_started", "asset_id": SCOUT_ASSET_ID}


@app.post("/scout/reset")
async def reset_scout_exploration() -> dict:
    """Clear the exploration tracker (e.g. on world switch)."""
    from backend.services.scout import exploration_tracker
    exploration_tracker.reset()
    return {"status": "reset"}


@app.post("/scout/cancel")
async def cancel_scout_sweep_endpoint() -> dict:
    """Cancel an in-flight scout sweep."""
    from backend.services.scout import cancel_scout_sweep
    cancelled = cancel_scout_sweep()
    return {"status": "cancelled" if cancelled else "not_running"}

@app.get("/scan")
async def scan_frequencies() -> dict:
    """Return drones currently broadcasting heartbeats and not yet uplinked."""
    return {"discovered": await scan_unlinked_frequencies()}


@app.get("/supply-stations")
async def get_supply_stations() -> dict:
    """Return all known supply stations (home + user-placed)."""
    return list_supply_stations()


@app.post("/supply-stations")
async def create_supply_station(req: SupplyStationCreateRequest) -> dict:
    """Place a new user station. 400 on invalid placement, 429 at station cap."""
    try:
        result = add_supply_station(x=req.x, z=req.z)
    except _supply_stations_registry.StationLimitReached as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ws_broadcaster.broadcast({"type": "supply_station_added", "station": result["station"]})
    return result


@app.delete("/supply-stations/{station_id}")
async def delete_supply_station(station_id: str) -> dict:
    """Remove a user station. 400 for 'home', 404 if unknown."""
    try:
        result = remove_supply_station(station_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    ws_broadcaster.broadcast({"type": "supply_station_removed", "id": station_id})
    return {"ok": True}


@app.post("/command")
async def send_command(req: CommandRequest) -> dict:
    """
    Send a natural language mission through the ADK commander, which calls MCP
    tools for fleet discovery and drone control.
    """
    if _adk_runner is None:
        raise HTTPException(status_code=503, detail="ADK runner not initialised")

    simulation_store = _simulation_store
    if req.simulation_id and simulation_store is not None:
        await simulation_store.create(req.simulation_id)
        already_scanned, _, already_scanned_refs, unscanned_refs = await _scan_confirmation_conflict(
            req.prompt,
            req.simulation_id,
            req.confirm_rescan,
        )
        if already_scanned:
            if unscanned_refs:
                options_text = "Choose: halt, rescan all, or rescan only new buildings."
            elif len(already_scanned) == 1:
                options_text = "Choose: halt or rescan."
            else:
                options_text = "Choose: halt or rescan all."
            return {
                "asset_id": req.asset_id or "FLEET",
                "response": (
                    "Scan already completed for building(s): "
                    + ", ".join(str(item) for item in already_scanned)
                    + ". "
                    + options_text
                ),
                "prompt": req.prompt,
                "requires_confirmation": True,
                "already_scanned_buildings": already_scanned,
                "already_scanned_building_refs": already_scanned_refs,
                "unscanned_buildings": unscanned_refs,
            }

    accumulator = MissionRunAccumulator(
        asset_id=req.asset_id or "FLEET",
        prompt=req.prompt,
        simulation_id=req.simulation_id,
    )
    stream_start = time.perf_counter()
    first_token_time: float | None = None
    status = "success"
    error_text: str | None = None
    langfuse_trace_id: str | None = None

    prompt = "Mission: " + req.prompt
    content = types.Content(
        role="user", parts=[types.Part(text=prompt)]
    )

    session_id = await _ensure_adk_shared_session(_adk_runner)

    response_text = ""
    text_candidates: list[str] = []
    scanned_building_rows: list[dict[str, object]] = []
    sweep_prompt = is_sweep_scan_prompt(req.prompt)
    runner = _adk_runner
    if runner is None:
        raise HTTPException(status_code=503, detail="ADK runner not initialised")

    lf_client = _get_langfuse_client()
    lf_ctx = (
        lf_client.start_as_current_observation(name="mission_run", as_type="span")
        if lf_client is not None
        else _nullcontext()
    )
    try:
        with lf_ctx:
            if lf_client is not None:
                try:
                    langfuse_trace_id = lf_client.get_current_trace_id()
                except Exception:
                    langfuse_trace_id = None
            async for event in runner.run_async(
                user_id=_ADK_USER_ID,
                session_id=session_id,
                new_message=content,
            ):
                if not event.content or not event.content.parts:
                    continue

                for part in event.content.parts:
                    if part.function_call:
                        accumulator.record_tool_call()
                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                    elif part.text and part.text.strip():
                        if first_token_time is None:
                            first_token_time = time.perf_counter()
                        text_candidates.append(part.text)
                    elif part.function_response:
                        resp = dict(part.function_response.response or {})
                        message = resp.get("message")
                        message_text = str(message).strip() if message is not None else ""
                        if message_text:
                            text_candidates.append(message_text)
                        scanned_building_rows.extend(_extract_scanned_building_rows(resp))
                        survivors_payload = _extract_survivor_coords(resp)
                        supply_dispatches = _extract_supply_dispatches(part.function_response.name or "", resp)
                        if survivors_payload:
                            accumulator.record_detections(survivors_payload)
                        if supply_dispatches:
                            accumulator.record_deliveries(supply_dispatches)

                if event.is_final_response():
                    for part in event.content.parts:
                        if part.text and part.text.strip():
                            response_text = part.text
                            break
    except Exception as exc:
        status = "failed"
        error_text = _first_exception_message(exc)
        raise
    finally:
        ttft_ms = round((first_token_time - stream_start) * 1000) if first_token_time else None
        try:
            run = accumulator.build(
                status=status,
                ttft_ms=ttft_ms,
                final_text=response_text,
                error=error_text,
                langfuse_trace_id=langfuse_trace_id,
            )
            await mission_run_repo.create(run)
        except Exception as exc:
            logging.getLogger(__name__).exception("Failed to persist mission_run: %s", exc)

    print(f"ADK final response: {response_text}")
    print(f"ADK text_candidates: {text_candidates}")

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

    if req.simulation_id and simulation_store is not None:
        parsed = SimulationStore.parse_scan_targets(req.prompt, _known_building_rows())
        if parsed.has_scan_intent and parsed.building_ids:
            await simulation_store.mark_buildings_scanned(req.simulation_id, parsed.building_ids)
        if scanned_building_rows:
            await simulation_store.merge_survivor_state(req.simulation_id, scanned_building_rows)

    return {
        "asset_id": req.asset_id or "FLEET",
        "response": response_text,
        "prompt": req.prompt,
    }


@app.post("/command/stream")
async def send_command_stream(req: CommandRequest, request: Request) -> StreamingResponse:
    """
    Stream ADK agent events via Server-Sent Events.
    Emits tool_call, tool_result, text, and done events as they happen.
    """
    if _adk_runner is None:
        raise HTTPException(status_code=503, detail="ADK runner not initialised")
    runner = _adk_runner
    simulation_store = _simulation_store

    parsed_targets = ParsedScanTargets(building_ids=[], has_scan_intent=False)
    if req.simulation_id and simulation_store is not None:
        await simulation_store.create(req.simulation_id)
        already_scanned, parsed_targets, already_scanned_refs, unscanned_refs = await _scan_confirmation_conflict(
            req.prompt,
            req.simulation_id,
            req.confirm_rescan,
        )
        if already_scanned:
            async def blocked_stream() -> AsyncGenerator[str, None]:
                if unscanned_refs:
                    options_text = "Choose: halt, rescan all, or rescan only new buildings."
                elif len(already_scanned) == 1:
                    options_text = "Choose: halt or rescan."
                else:
                    options_text = "Choose: halt or rescan all."
                message = (
                    "RESCAN_CONFIRM_REQUIRED|"
                    "Building(s) already scanned in this simulation: "
                    + ", ".join(str(item) for item in already_scanned)
                    + ". "
                    + options_text
                )
                yield f"data: {json.dumps({'type': 'error', 'text': message, 'already_scanned_buildings': already_scanned, 'already_scanned_building_refs': already_scanned_refs, 'unscanned_buildings': unscanned_refs})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'ttft_ms': None, 'tps': None})}\n\n"

            return StreamingResponse(
                blocked_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "X-Accel-Buffering": "no",
                    "Connection": "keep-alive",
                },
            )

    prompt = "Mission: " + req.prompt
    content = types.Content(
        role="user", parts=[types.Part(text=prompt)]
    )

    session_id = await _ensure_adk_shared_session(runner)

    async def generate() -> AsyncGenerator[str, None]:
        final_text = ""
        queue: asyncio.Queue = asyncio.Queue()
        stream_start = time.perf_counter()
        accumulator = MissionRunAccumulator(
            asset_id=req.asset_id or "FLEET",
            prompt=req.prompt,
            simulation_id=req.simulation_id,
        )
        status = "success"
        error_text: str | None = None
        aborted = False
        first_token_time: float | None = None
        total_chars = 0
        scanned_building_rows: list[dict[str, object]] = []
        sweep_prompt = is_sweep_scan_prompt(req.prompt)
        preferred_sweep_report: str | None = None
        langfuse_trace_id: str | None = None

        lf_client = _get_langfuse_client()
        lf_ctx = (
            lf_client.start_as_current_observation(name="mission_run", as_type="span")
            if lf_client is not None
            else _nullcontext()
        )

        async def adk_loop() -> None:
            try:
                async for event in runner.run_async(
                    user_id=_ADK_USER_ID,
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

        # Enter the Langfuse span BEFORE creating adk_task so the OTel context
        # propagates into the background task. Exit in the outer finally.
        lf_ctx.__enter__()
        if lf_client is not None:
            try:
                langfuse_trace_id = lf_client.get_current_trace_id()
            except Exception:
                langfuse_trace_id = None

        adk_task = asyncio.create_task(adk_loop())
        hb_task = asyncio.create_task(heartbeat())

        try:
            while True:
                if await request.is_disconnected():
                    aborted = True
                    break
                kind, data = await queue.get()

                if kind == "heartbeat":
                    yield f"data: {json.dumps({'type': 'heartbeat', 'elapsed': data})}\n\n"
                    continue

                if kind == "error":
                    status = "failed"
                    error_text = str(data)
                    yield f"data: {json.dumps({'type': 'error', 'text': str(data)})}\n\n"
                    break

                if kind == "end":
                    break

                event = data
                if not event.content or not event.content.parts:
                    continue
                for part in event.content.parts:
                    if getattr(part, "thought", False) and part.text and part.text.strip():
                        payload = {"type": "thinking", "text": part.text, "agent": event.author}
                        accumulator.record_event(payload["type"], payload)
                        yield f"data: {json.dumps(payload)}\n\n"
                        continue
                    if part.function_call:
                        accumulator.record_tool_call()
                        payload = {
                            "type": "tool_call",
                            "name": part.function_call.name,
                            "args": dict(part.function_call.args or {}),
                            "agent": event.author,
                        }
                        accumulator.record_event(payload["type"], payload)
                        yield f"data: {json.dumps(payload)}\n\n"
                    elif part.function_response:
                        resp = dict(part.function_response.response or {})
                        scanned_building_rows.extend(_extract_scanned_building_rows(resp))
                        message = resp.get("message")
                        survivors_payload = _extract_survivor_coords(resp)
                        supply_dispatches = _extract_supply_dispatches(part.function_response.name, resp)
                        if survivors_payload:
                            accumulator.record_detections(survivors_payload)
                        if supply_dispatches:
                            accumulator.record_deliveries(supply_dispatches)
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
                            accumulator.record_event(payload["type"], payload)
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
                        accumulator.record_event(payload["type"], payload)
                        yield f"data: {json.dumps(payload)}\n\n"
                    elif part.text and part.text.strip():
                        if sweep_prompt and is_structured_sweep_report(part.text):
                            if preferred_sweep_report is None:
                                preferred_sweep_report = part.text
                                if first_token_time is None:
                                    first_token_time = time.perf_counter()
                                total_chars += len(part.text)
                                payload = {"type": "text", "text": part.text, "agent": event.author}
                                accumulator.record_event(payload["type"], payload)
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
                        accumulator.record_event(payload["type"], payload)
                        yield f"data: {json.dumps(payload)}\n\n"
        finally:
            hb_task.cancel()
            adk_task.cancel()
            await asyncio.gather(adk_task, hb_task, return_exceptions=True)

            # Exit the Langfuse span so the trace is flushed and cost is computed.
            try:
                lf_ctx.__exit__(None, None, None)
            except Exception:
                pass

            # Compute both int and float variants of ttft_ms:
            # - int for the DB INTEGER column
            # - float (1 decimal) for the SSE `done` event (existing behaviour)
            ttft_ms_int = round((first_token_time - stream_start) * 1000) if first_token_time else None
            ttft_ms = round((first_token_time - stream_start) * 1000, 1) if first_token_time else None

            final_status = "aborted" if aborted else status
            try:
                run = accumulator.build(
                    status=final_status,
                    ttft_ms=ttft_ms_int,
                    final_text=final_text or "",
                    error=error_text,
                    langfuse_trace_id=langfuse_trace_id,
                )
                run_id = await mission_run_repo.create(run)
                if run_id and accumulator.events:
                    try:
                        rows = [
                            MissionRunEvent(**row)
                            for row in accumulator.serialise_events(run_id)
                        ]
                        await mission_run_events_repo.insert_many(rows)
                    except Exception as exc:
                        logging.getLogger(__name__).exception(
                            "Failed to persist mission_run_events: %s", exc
                        )
            except Exception as exc:
                logging.getLogger(__name__).exception("Failed to persist mission_run: %s", exc)

            await mission_log_repo.create(MissionLog(
                asset_id=req.asset_id or "FLEET",
                command="natural_language",
                params=req.prompt,
                result=final_text,
            ))

            now = time.perf_counter()
            gen_secs = (now - first_token_time) if first_token_time else None
            tps = round((total_chars / 4) / gen_secs, 1) if gen_secs and gen_secs > 0 else None

            # Existing simulation-store persistence logic (unchanged):
            if req.simulation_id and simulation_store is not None:
                if not parsed_targets.has_scan_intent:
                    parsed_targets_local = SimulationStore.parse_scan_targets(req.prompt, _known_building_rows())
                else:
                    parsed_targets_local = parsed_targets
                if parsed_targets_local.building_ids:
                    await simulation_store.mark_buildings_scanned(req.simulation_id, parsed_targets_local.building_ids)
                if scanned_building_rows:
                    await simulation_store.merge_survivor_state(req.simulation_id, scanned_building_rows)

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


@app.post("/simulation")
async def create_simulation(req: SimulationCreateRequest) -> dict[str, object]:
    """Create (or reuse) a simulation row in Supabase.

    Args:
        req: Optional simulation ID payload.

    Returns:
        Persisted simulation snapshot.
    """
    simulation_store = _simulation_store
    if simulation_store is None:
        raise HTTPException(status_code=503, detail="Simulation store not initialised")
    simulation_id = await simulation_store.create(req.simulation_id)
    snapshot = await simulation_store.get(simulation_id)
    return snapshot if snapshot is not None else {"id": simulation_id, "scanned_buildings": []}


@app.get("/simulation/{simulation_id}")
async def get_simulation(simulation_id: str) -> dict[str, object]:
    """Fetch a simulation snapshot from Supabase by ID.

    Args:
        simulation_id: Stable simulation ID.

    Returns:
        Simulation snapshot.
    """
    simulation_store = _simulation_store
    if simulation_store is None:
        raise HTTPException(status_code=503, detail="Simulation store not initialised")
    snapshot = await simulation_store.get(simulation_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Simulation not found")
    return snapshot


@app.post("/simulation/{simulation_id}/state")
async def sync_simulation_state(
    simulation_id: str,
    req: SimulationStateSyncRequest,
) -> dict[str, object]:
    """Merge frontend survivor supplied/detected state into simulation row.

    Args:
        simulation_id: Stable simulation ID.
        req: Scanned building payload with detected survivors and supplied flags.

    Returns:
        Updated simulation snapshot.
    """
    simulation_store = _simulation_store
    if simulation_store is None:
        raise HTTPException(status_code=503, detail="Simulation store not initialised")
    merged = await simulation_store.merge_survivor_state(
        simulation_id,
        [row.model_dump() for row in req.scanned_buildings],
    )
    return merged



@app.websocket("/ws/telemetry")
async def telemetry_ws(websocket: WebSocket):
    await websocket.accept()
    ws_broadcaster.connect(websocket)
    try:
        from backend.services.scout import exploration_tracker

        await websocket.send_text(json.dumps({
            "type": "exploration_snapshot",
            "explored_sectors": exploration_tracker.explored_sectors,
        }))
        while True:
            await asyncio.sleep(30)
    except WebSocketDisconnect:
        ws_broadcaster.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.app:app", host="0.0.0.0", port=8000, reload=True)
