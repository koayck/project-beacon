from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Iterable

from backend.services.fleet_assignment import (
    assign_fleet_to_buildings as _assign_fleet_to_buildings_service,
)
from backend.services.fleet_assignment import (
    parallel_fleet_scan as _parallel_fleet_scan_service,
)
from backend.services.navigation.internal.corner_ops import (
    _build_ring,
    _nearest_corner,
    _push_xz_clear,
    _west_face_stop_z,
    _window_sort_reverse,
)
from backend.services.navigation.internal.safety_ops import (
    _route_sweep_segment,
    _safe_standoff_per_face,
)
from backend.services.navigation.internal.window_ops import (
    select_window_waypoint as _select_window_waypoint,
)
from backend.services.navigation.route_planner import (
    find_buildings_in_area,
    find_survivors_in_area,
    plan_route,
    plan_sweep_pattern,
)
from backend.services.navigation.sweep_planner import (
    plan_building_vertical_sweep as _plan_building_vertical_sweep,
)
from backend.services.navigation.target_resolution import (
    resolve_scan_target as _resolve_scan_target,
)
from backend.grpc.client import DroneGrpcClient
from backend.services.core import context as service_context
from backend.services.scan_reporting import build_sweep_scan_report as _build_sweep_scan_report
from backend.services.swarm_control import deploy_swarm as _deploy_swarm_service
from backend.services.swarm_control import recall_swarm as _recall_swarm_service
from backend.services.workflows.supply_workflow import (
    dispatch_supply_to_building as _dispatch_supply_to_building_workflow,
)
from backend.services.workflows.supply_workflow import (
    parallel_fleet_supply as _parallel_fleet_supply_workflow,
)
from backend.services.workflows.return_workflow import return_to_base as _return_to_base_workflow
from backend.services.workflows.sweep_workflow import sweep_scan_building as _sweep_scan_workflow
from backend.runtime import grpc_client as _runtime_grpc_client
from backend.world.model import (
    WORLD,
)

# Module-level client reference supports test injection via set_client().
grpc_client: DroneGrpcClient = _runtime_grpc_client

_NORMAL_SPEED = 5.0
_MIN_ELIGIBLE_BATTERY_PCT = 20
# _FAST_SPEED = 20.0
_drone_speeds: dict[str, float] = {}
# Default sweep radius should cover window-standoff waypoints (~6m to interior
# survivors in current maps) without requiring the operator to specify radius.
DEFAULT_SWEEP_SCAN_RADIUS = 8.0
# Half-angle of the drone's forward-facing thermal camera cone (degrees).
# Survivors beyond this angle off the drone's heading are not detected.
THERMAL_HORIZ_FOV_HALF_DEG: float = 60.0
WINDOW_SCAN_STANDOFF_M = service_context.get_window_scan_standoff_m()
BUILDING_PROXIMITY_MARGIN_M = service_context.get_building_proximity_margin_m()
FLOOD_LEVEL = service_context.get_flood_level()
FLOOR_HEIGHT_M = service_context.get_floor_height_m()

def _is_eligible_idle_drone(status: dict) -> bool:
    battery_raw = status.get("battery", 0)
    try:
        battery = float(battery_raw)
    except (TypeError, ValueError):
        battery = 0.0
    state = str(status.get("status", "")).upper()
    return (
        battery > _MIN_ELIGIBLE_BATTERY_PCT
        and state == "IDLE"
    )


def _no_eligible_drones_result(statuses: list[dict | Exception]) -> dict:
    responded_count = 0
    status_summaries: list[str] = []
    for status in statuses:
        if isinstance(status, Exception):
            continue

        responded_count += 1
        state = str(status.get("status", "UNKNOWN")).upper()
        battery_raw = status.get("battery", "?")
        try:
            battery = f"{float(battery_raw):.1f}%"
        except (TypeError, ValueError):
            battery = "?%"
        asset_id = str(status.get("asset_id", "UNKNOWN"))
        status_summaries.append(f"{asset_id}:{state}@{battery}")

    total_registered = len(statuses)
    status_summary_text = ", ".join(status_summaries) if status_summaries else "none"
    return {
        "error": "No eligible drones available (all busy or low battery).",
        "suggestion": (
            f"{total_registered} drone(s) registered; {responded_count} responded to status checks. "
            f"Eligibility requires status=IDLE and battery > {_MIN_ELIGIBLE_BATTERY_PCT}%. "
            f"Current statuses: {status_summary_text}."
        ),
    }


def register_detected_survivors(rows: Iterable[dict]) -> int:
    """Persist survivor IDs detected during prior scans for later supply gating."""
    return service_context.register_detected_survivors(rows)


def clear_detected_survivors() -> None:
    """Reset detected-survivor memory (used by tests)."""
    service_context.clear_detected_survivors()


def register_supplied_targets(rows: Iterable[dict]) -> int:
    """Persist targets that have already received supplies."""
    return service_context.register_supplied_targets(rows)


def clear_supplied_targets() -> None:
    """Reset supplied-target memory (used by tests)."""
    service_context.clear_supplied_targets()




def set_drone_speed(asset_id: str, speed: float) -> None:
    _drone_speeds[asset_id] = speed


def get_drone_speed(asset_id: str) -> float:
    return _drone_speeds.get(asset_id, _NORMAL_SPEED)


def set_client(client: DroneGrpcClient | None) -> None:
    """Override the active gRPC client for tests; None restores runtime default."""
    global grpc_client
    grpc_client = client if client is not None else _runtime_grpc_client
    service_context.set_grpc_client(client)


def resolve_scan_target(
    target_x: float,
    target_z: float,
    margin: float | None = None,
) -> dict:
    resolved_margin = (
        service_context.get_building_proximity_margin_m() if margin is None else float(margin)
    )
    return _resolve_scan_target(target_x, target_z, margin=resolved_margin)


def plan_building_vertical_sweep(
    target_x: float,
    target_z: float,
    level_step: float = 3.0,
    standoff: float = 2.0,
    flood_clearance: float = 0.5,
    approach_x: float | None = None,
    approach_z: float | None = None,
) -> dict:
    return _plan_building_vertical_sweep(
        target_x=target_x,
        target_z=target_z,
        level_step=level_step,
        standoff=standoff,
        flood_clearance=flood_clearance,
        approach_x=approach_x,
        approach_z=approach_z,
    )


_move_locks: dict[str, asyncio.Lock] = {}


def _move_lock_for(asset_id: str) -> asyncio.Lock:
    """Return (creating on first use) a per-drone async lock.

    LLM agents often emit multiple ``move_drone_to`` tool calls as a parallel
    batch when issuing multi-waypoint routes. Without serialization, the three
    concurrent calls all issue gRPC ``move_to`` commands in rapid succession;
    each overwrites the drone's target, the last one wins, and the drone flies
    a single 3D diagonal from its start position to the final waypoint —
    skipping every intermediate waypoint and clipping obstacles that the plan
    had explicitly routed around. A per-asset lock serializes calls for the
    same drone while preserving concurrency across different drones.
    """
    lock = _move_locks.get(asset_id)
    if lock is None:
        lock = asyncio.Lock()
        _move_locks[asset_id] = lock
    return lock


async def move_drone_to(
    asset_id: str,
    x: float,
    y: float,
    z: float,
    speed: float | None = None,
) -> dict:
    """Issue a move command and await arrival at the target waypoint.

    Blocking semantics + per-drone lock guarantee that multi-waypoint routes
    actually follow waypoints: the drone reaches each waypoint before the next
    move command overwrites its target. On BLOCKED, the wait helper re-plans
    from the drone's current position and resumes, so single-call recovery is
    handled transparently.
    """
    async with _move_lock_for(asset_id):
        target_speed = get_drone_speed(asset_id) if speed is None else speed
        command_result = await grpc_client.move_to(asset_id, x, y, z, target_speed)
        if not command_result.get("success", True):
            return command_result

        wait_result = await _wait_until_waypoint_reached(asset_id, x, y, z)
        if wait_result.get("ok", False):
            return {
                "success": True,
                "message": f"Arrived at ({x}, {y}, {z})",
                "status": wait_result.get("status"),
            }
        return {
            "success": False,
            "message": wait_result.get("error", "Move failed"),
            "status": wait_result.get("status"),
        }


async def list_all_drones() -> dict:
    """
    Return the current position, battery, and status of all registered drones.
    """
    client = grpc_client
    asset_ids = client.registered_asset_ids()
    if not asset_ids:
        return {"drones": [], "message": "No drones uplinked. Use /uplink to connect a drone."}

    statuses = await asyncio.gather(
        *[client.get_status(aid) for aid in asset_ids],
        return_exceptions=True,
    )
    drones = []
    for aid, status in zip(asset_ids, statuses):
        if isinstance(status, Exception):
            drones.append({"asset_id": aid, "error": str(status)})
            continue
        drones.append(status)
    return {"drones": drones}


async def deploy_swarm(asset_ids: list[str], formation: str = "spread") -> dict:
    return await _deploy_swarm_service(asset_ids, formation, move_to_fn=grpc_client.move_to)


async def recall_swarm(asset_ids: list[str]) -> dict:
    return await _recall_swarm_service(asset_ids, return_to_base_fn=return_to_base)





async def _wait_until_waypoint_reached(
    asset_id: str,
    x: float,
    y: float,
    z: float,
    tolerance: float = 0.6,
    timeout_s: float = 60.0,
    poll_s: float = 0.2,
    blocked_retries: int = 2,
    exclude_building_id: int | None = None,
) -> dict:
    """
    Poll drone status until it reaches a waypoint, is blocked, or times out.

    On BLOCKED, re-plans from the drone's current position to the target waypoint
    up to ``blocked_retries`` times.

    ``exclude_building_id`` is forwarded to ``plan_route`` on re-plan so that the
    building being scanned is not treated as a full obstacle during sweep recovery.
    """
    client = grpc_client
    elapsed = 0.0
    while elapsed <= timeout_s:
        status = await client.get_status(asset_id)

        if status.get("status") == "BLOCKED" and blocked_retries > 0:
            route = await plan_route(
                asset_id, x, z, y,
                exclude_building_id=exclude_building_id,
            )
            if "error" not in route:
                for wp in route["waypoints"]:
                    await client.move_to(
                        asset_id,
                        wp["x"],
                        wp["y"],
                        wp["z"],
                        get_drone_speed(asset_id),
                    )
                    sub = await _wait_until_waypoint_reached(
                        asset_id,
                        wp["x"],
                        wp["y"],
                        wp["z"],
                        tolerance=tolerance,
                        timeout_s=timeout_s,
                        poll_s=poll_s,
                        blocked_retries=max(blocked_retries - 1, 0),
                        exclude_building_id=exclude_building_id,
                    )
                    if not sub["ok"]:
                        return sub
                return {"ok": True, "status": await client.get_status(asset_id)}

            return {
                "ok": False,
                "error": "Drone blocked and re-plan failed",
                "status": status,
            }

        if status.get("status") == "BLOCKED":
            return {
                "ok": False,
                "error": "Drone blocked while following return route",
                "status": status,
            }
        if status.get("status") == "ERROR":
            return {
                "ok": False,
                "error": "Drone entered ERROR state while following return route",
                "status": status,
            }

        dx = abs(status["x"] - x)
        dy = abs(status["y"] - y)
        dz = abs(status["z"] - z)
        if dx <= tolerance and dy <= tolerance and dz <= tolerance:
            return {"ok": True, "status": status}

        await asyncio.sleep(poll_s)
        elapsed += poll_s

    timeout_status = await client.get_status(asset_id)
    return {
        "ok": False,
        "error": "Timed out while following return route waypoint",
        "status": timeout_status,
    }


async def return_to_base(asset_id: str) -> dict:
    client = grpc_client
    return await _return_to_base_workflow(
        asset_id,
        plan_route_fn=plan_route,
        move_to=client.move_to,
        get_status=client.get_status,
        get_speed=get_drone_speed,
        wait_until_waypoint_reached=_wait_until_waypoint_reached,
    )


async def get_drone_status(asset_id: str) -> dict:
    """Get the current position, battery level, and status of a drone."""
    return await grpc_client.get_status(asset_id)


async def scan_area(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """
    Command a drone to scan a circular area centred at (cx, cy, cz).
    Used for thermal imaging and survivor detection.
    """
    return await grpc_client.scan_area(asset_id, cx, cy, cz, radius)


async def get_drone_view(
    asset_id: str,
    heading_deg: float = 0.0,
    detection_range: float = 20.0,
) -> dict:
    """
    Get what the drone can currently see from its position.
    Returns nearby buildings, visible survivors, terrain type, altitude above
    ground level, and whether an obstacle is ahead.
    """
    return await grpc_client.get_view(asset_id, heading_deg, detection_range)


async def sweep_scan_building(
    asset_id: str,
    target_x: float | None = None,
    target_z: float | None = None,
    scan_radius: float = DEFAULT_SWEEP_SCAN_RADIUS,
    level_step: float = 3.0,
    standoff: float = 2.0,
) -> dict:
    client = grpc_client
    return await _sweep_scan_workflow(
        asset_id,
        target_x=target_x,
        target_z=target_z,
        scan_radius=scan_radius,
        level_step=level_step,
        standoff=standoff,
        floor_height_m=FLOOR_HEIGHT_M,
        thermal_horiz_fov_half_deg=THERMAL_HORIZ_FOV_HALF_DEG,
        plan_route_fn=plan_route,
        plan_building_vertical_sweep=plan_building_vertical_sweep,
        wait_until_waypoint_reached=_wait_until_waypoint_reached,
        get_status=client.get_status,
        move_to=client.move_to,
        scan_area=client.scan_area,
        get_view=client.get_view,
        end_scan=getattr(client, "end_scan", None),
        get_speed=get_drone_speed,
        register_detected_survivors=register_detected_survivors,
        build_sweep_scan_report=_build_sweep_scan_report,
    )


async def assign_fleet_to_buildings(buildings: list[dict]) -> dict:
    client = grpc_client
    return await _assign_fleet_to_buildings_service(
        buildings,
        registered_asset_ids=client.registered_asset_ids,
        get_status=client.get_status,
        is_eligible_idle_drone=_is_eligible_idle_drone,
        no_eligible_drones_result=_no_eligible_drones_result,
    )


async def parallel_fleet_scan(
    assignments: list[dict],
    unassigned_buildings: list[dict] | None = None,
) -> dict:
    async def _sweep_scan(asset_id: str, building: dict) -> dict:
        return await sweep_scan_building(
            asset_id=asset_id,
            target_x=building["x"],
            target_z=building["z"],
        )

    return await _parallel_fleet_scan_service(
        assignments,
        sweep_scan_building=_sweep_scan,
        unassigned_buildings=unassigned_buildings,
    )


async def dispatch_supply_to_building(asset_id: str, building: dict) -> dict:
    return await _dispatch_supply_to_building_workflow(
        asset_id,
        building,
        resolve_scan_target=resolve_scan_target,
        world=WORLD,
        window_scan_standoff_m=WINDOW_SCAN_STANDOFF_M,
        select_window_waypoint=_select_window_waypoint,
        return_to_base_fn=return_to_base,
        plan_route_fn=plan_route,
        move_drone_to_fn=move_drone_to,
        wait_until_waypoint_reached_fn=_wait_until_waypoint_reached,
        get_status_fn=grpc_client.get_status,
    )


async def parallel_fleet_supply(
    assignments: list[dict],
    unassigned_buildings: list[dict] | None = None,
    unassigned_targets: list[dict] | None = None,
) -> dict:
    return await _parallel_fleet_supply_workflow(
        assignments,
        dispatch_supply_to_building_fn=dispatch_supply_to_building,
        unassigned_buildings=unassigned_buildings,
        unassigned_targets=unassigned_targets,
    )
