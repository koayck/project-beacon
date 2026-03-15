from __future__ import annotations

import asyncio
import json
import math
from typing import TYPE_CHECKING

from backend.grpc.client import DroneGrpcClient
from backend.runtime import grpc_client
from backend.world.model import (
    BUILDING_PROXIMITY_MARGIN_M,
    FLOOD_LEVEL,
    WINDOW_SCAN_STANDOFF_M,
    WORLD,
)

_NORMAL_SPEED = 5.0
# _FAST_SPEED = 20.0
_drone_speeds: dict[str, float] = {}
# Match world vision survivor sensor range to avoid sweep summary undercounting.
DEFAULT_SWEEP_SCAN_RADIUS = 12.0

# Pre-defined formation offsets (x, y, z) relative to base.
_FORMATIONS: dict[str, list[tuple[float, float, float]]] = {
    "spread": [(0, 0, 10), (10, 0, 10), (-10, 0, 10), (0, 10, 10), (0, -10, 10)],
    "line": [(i * 8, 0, 10) for i in range(5)],
    "triangle": [(0, 0, 10), (6, 6, 10), (-6, 6, 10)],
}


def _format_sweep_levels(levels: list[float]) -> str:
    return ", ".join(f"{level:g}" for level in levels)


def _format_sweep_findings(survivor_count: int) -> str:
    if survivor_count <= 0:
        return "No heat signatures detected."
    return f"{survivor_count} heat signature(s) detected."


def _build_sweep_scan_report(
    asset_id: str,
    building: dict,
    levels: list[float],
    flood_level: float,
    waypoint_count: int,
    survivor_count: int,
    battery: float,
    sensor_summary: str,
) -> str:
    return (
        f"SWEEP SCAN COMPLETE — {asset_id}\n"
        f"  Building  : X=({building['min_x']:.1f} to {building['max_x']:.1f}), "
        f"Z=({building['min_z']:.1f} to {building['max_z']:.1f})\n"
        f"  Levels    : {_format_sweep_levels(levels)} "
        f"(above flood level {flood_level:.1f}m)\n"
        f"  Waypoints : {waypoint_count}\n"
        f"  Findings  : {_format_sweep_findings(survivor_count)}\n"
        f"  Battery   : {battery:.1f}% remaining\n"
        f"  Sensor    : {sensor_summary}"
    )


def set_drone_speed(asset_id: str, speed: float) -> None:
    _drone_speeds[asset_id] = speed


def get_drone_speed(asset_id: str) -> float:
    return _drone_speeds.get(asset_id, _NORMAL_SPEED)

def set_client(client: DroneGrpcClient | None) -> None:
    global _client
    _client = client


# def grpc_client -> DroneGrpcClient:
#     return _client if _client is not None else grpc_client


def set_drone_speed(asset_id: str, speed: float) -> None:
    _drone_speeds[asset_id] = speed


def get_drone_speed(asset_id: str) -> float:
    return _drone_speeds.get(asset_id, _NORMAL_SPEED)


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
        else:
            drones.append(status)
    return {"drones": drones}


async def move_drone_to(
    asset_id: str, x: float, y: float, z: float, speed: float | None = None
) -> dict:
    """Move a drone to the given X/Y/Z coordinates at the specified speed."""
    return await grpc_client.move_to(
        asset_id,
        x,
        y,
        z,
        speed if speed is not None else get_drone_speed(asset_id),
    )


async def _wait_until_waypoint_reached(
    asset_id: str,
    x: float,
    y: float,
    z: float,
    tolerance: float = 0.6,
    timeout_s: float = 60.0,
    poll_s: float = 0.2,
    blocked_retries: int = 2,
) -> dict:
    """
    Poll drone status until it reaches a waypoint, is blocked, or times out.

    On BLOCKED, re-plans from the drone's current position to the target waypoint
    up to ``blocked_retries`` times.
    """
    client = grpc_client
    elapsed = 0.0
    while elapsed <= timeout_s:
        status = await client.get_status(asset_id)

        if status.get("status") == "BLOCKED" and blocked_retries > 0:
            route = await plan_route(asset_id, x, z, y)
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
                        blocked_retries=0,
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
    """
    Return a drone to home with obstacle-aware routing.

    Plans a safe route to home approach, executes each waypoint with status
    polling, then performs a final explicit landing leg to (0,0,0).
    """
    client = grpc_client
    route = await plan_route(asset_id, 0.0, 0.0, 5.0)
    if "error" in route:
        return {
            "asset_id": asset_id,
            "error": "Return route blocked",
            "route_error": route["error"],
            "obstacles": route.get("obstacles", []),
        }

    waypoints = route.get("waypoints", [])
    for wp in waypoints:
        move_result = await client.move_to(
            asset_id,
            wp["x"],
            wp["y"],
            wp["z"],
            get_drone_speed(asset_id),
        )
        if not move_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Failed while executing return route waypoint",
                "waypoint": wp,
                "move_result": move_result,
            }

        wait_result = await _wait_until_waypoint_reached(asset_id, wp["x"], wp["y"], wp["z"])
        if not wait_result.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": wait_result.get("error", "Return route waypoint not reached"),
                "waypoint": wp,
                "status": wait_result.get("status"),
            }

    final_wp = {"x": 0.0, "y": 0.0, "z": 0.0, "reason": "final landing at home pad"}
    final_move_result = await client.move_to(
        asset_id,
        final_wp["x"],
        final_wp["y"],
        final_wp["z"],
        get_drone_speed(asset_id),
    )
    if not final_move_result.get("success", True):
        return {
            "asset_id": asset_id,
            "error": "Failed while executing final home landing leg",
            "waypoint": final_wp,
            "move_result": final_move_result,
        }

    final_wait = await _wait_until_waypoint_reached(
        asset_id,
        final_wp["x"],
        final_wp["y"],
        final_wp["z"],
    )
    if not final_wait.get("ok", False):
        return {
            "asset_id": asset_id,
            "error": final_wait.get("error", "Final home landing leg not reached"),
            "waypoint": final_wp,
            "status": final_wait.get("status"),
        }

    final_status = await client.get_status(asset_id)
    return {
        "success": True,
        "message": "Returned to base",
        "asset_id": asset_id,
        "strategy": "routed_return",
        "waypoint_count": len(waypoints) + 1,
        "route_summary": route.get("summary"),
        "final_status": final_status,
    }


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


async def thermal_scan(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """SAR-specific alias for area scanning."""
    return await scan_area(asset_id, cx, cy, cz, radius)


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


def _select_window_waypoint(
    waypoints: list[dict],
    ref_x: float,
    ref_z: float,
    preferred_y: float | None = None,
) -> dict | None:
    if not waypoints:
        return None

    def _score(wp: dict) -> tuple[float, float]:
        y_delta = abs(float(wp["y"]) - preferred_y) if preferred_y is not None else 0.0
        x_delta = float(wp["x"]) - ref_x
        z_delta = float(wp["z"]) - ref_z
        xz_dist = math.sqrt(x_delta * x_delta + z_delta * z_delta)
        return (y_delta, xz_dist)

    return min(waypoints, key=_score)


def resolve_scan_target(
    target_x: float,
    target_z: float,
    margin: float = BUILDING_PROXIMITY_MARGIN_M,
) -> dict:
    """
    Resolve a scan target to a building footprint when the point is on/near one.

    Returns the resolved scan center and building bounds so agents can explain
    why a target was normalised.
    """
    building = WORLD.building_near_xz(target_x, target_z, margin=margin)
    if building is None:
        return {
            "matched_building": False,
            "input": {"x": target_x, "z": target_z},
            "resolved_target": {"x": target_x, "z": target_z},
            "summary": "No nearby building footprint; using provided coordinates.",
        }

    window_waypoints = building.window_scan_waypoints(standoff=WINDOW_SCAN_STANDOFF_M)
    preferred_y = building.h / 2 if window_waypoints else None
    recommended_window = _select_window_waypoint(
        window_waypoints,
        ref_x=target_x,
        ref_z=target_z,
        preferred_y=preferred_y,
    )
    recommended_scan_y = (
        float(recommended_window["y"])
        if recommended_window is not None
        else building.max_y + 5.0
    )

    summary = (
        f"Matched building {building.id}; footprint "
        f"x[{building.min_x:.1f},{building.max_x:.1f}] "
        f"z[{building.min_z:.1f},{building.max_z:.1f}] "
        f"→ center ({building.cx:.1f}, {building.cz:.1f})."
    )
    if recommended_window is not None:
        summary += (
            " Recommended window approach "
            f"{recommended_window['face']} floor {recommended_window['floor']} "
            f"at ({recommended_window['x']:.1f}, {recommended_window['y']:.1f}, {recommended_window['z']:.1f})."
        )

    return {
        "matched_building": True,
        "building": {
            "id": building.id,
            "min_x": building.min_x,
            "max_x": building.max_x,
            "min_z": building.min_z,
            "max_z": building.max_z,
            "center_x": building.cx,
            "center_z": building.cz,
            "height": building.h,
        },
        "input": {"x": target_x, "z": target_z},
        "resolved_target": {"x": building.cx, "z": building.cz},
        "recommended_scan_y": recommended_scan_y,
        "window_waypoints": window_waypoints,
        "recommended_window_waypoint": recommended_window,
        "summary": summary,
    }


def plan_building_vertical_sweep(
    target_x: float,
    target_z: float,
    level_step: float = 3.0,
    standoff: float = 2.0,
    flood_clearance: float = 0.5,
) -> dict:
    """
    Plan a perimeter sweep around a building across all heights above water level.
    """
    building = WORLD.building_near_xz(target_x, target_z, margin=BUILDING_PROXIMITY_MARGIN_M)
    if building is None:
        return {
            "matched_building": False,
            "error": "No nearby building for sweep scan",
            "input": {"x": target_x, "z": target_z},
        }

    safe_standoff = max(standoff, 0.5)
    safe_step = max(level_step, 0.5)
    start_y = max(FLOOD_LEVEL + max(flood_clearance, 0.0), 0.5)
    top_y = building.max_y
    if start_y > top_y:
        return {
            "matched_building": True,
            "error": "Building has no scanable height above water level",
            "building": {
                "id": building.id,
                "min_x": building.min_x,
                "max_x": building.max_x,
                "min_z": building.min_z,
                "max_z": building.max_z,
                "center_x": building.cx,
                "center_z": building.cz,
                "height": building.h,
            },
            "flood_level": FLOOD_LEVEL,
        }

    levels: list[float] = []
    y = start_y
    while y < top_y:
        levels.append(round(y, 2))
        y += safe_step
    if not levels or levels[-1] < top_y:
        levels.append(round(top_y, 2))

    min_x = building.min_x - safe_standoff
    max_x = building.max_x + safe_standoff
    min_z = building.min_z - safe_standoff
    max_z = building.max_z + safe_standoff

    waypoints: list[dict] = []
    for level_y in levels:
        ring = [
            (min_x, level_y, min_z, "perimeter corner NW"),
            (max_x, level_y, min_z, "perimeter corner NE"),
            (max_x, level_y, max_z, "perimeter corner SE"),
            (min_x, level_y, max_z, "perimeter corner SW"),
            (min_x, level_y, min_z, "close perimeter ring"),
        ]
        for x, y_val, z, reason in ring:
            waypoints.append(
                {
                    "x": x,
                    "y": y_val,
                    "z": z,
                    "level_y": level_y,
                    "reason": reason,
                }
            )

    return {
        "matched_building": True,
        "input": {"x": target_x, "z": target_z},
        "building": {
            "id": building.id,
            "min_x": building.min_x,
            "max_x": building.max_x,
            "min_z": building.min_z,
            "max_z": building.max_z,
            "center_x": building.cx,
            "center_z": building.cz,
            "height": building.h,
        },
        "flood_level": FLOOD_LEVEL,
        "levels": levels,
        "level_count": len(levels),
        "waypoints": waypoints,
        "waypoint_count": len(waypoints),
        "summary": (
            f"Vertical perimeter sweep for building {building.id}: "
            f"{len(levels)} level(s), {len(waypoints)} waypoint(s), "
            f"covering y={levels[0]:.1f}..{levels[-1]:.1f} above flood={FLOOD_LEVEL:.1f}."
        ),
    }


async def sweep_scan_building(
    asset_id: str,
    target_x: float | None = None,
    target_z: float | None = None,
    scan_radius: float = DEFAULT_SWEEP_SCAN_RADIUS,
    level_step: float = 3.0,
    standoff: float = 2.0,
) -> dict:
    """
    Execute a full-height-above-water perimeter sweep scan around a building.
    """
    client = grpc_client
    if target_x is None or target_z is None:
        status = await client.get_status(asset_id)
        if target_x is None:
            target_x = status["x"]
        if target_z is None:
            target_z = status["z"]

    plan = plan_building_vertical_sweep(
        target_x=target_x,
        target_z=target_z,
        level_step=level_step,
        standoff=standoff,
    )
    if not plan.get("matched_building", False):
        return {
            "asset_id": asset_id,
            "error": plan.get("error", "No building found for sweep scan"),
            "input": plan.get("input", {"x": target_x, "z": target_z}),
        }
    if "error" in plan:
        return {
            "asset_id": asset_id,
            "error": plan["error"],
            "building": plan.get("building"),
            "flood_level": plan.get("flood_level"),
        }

    waypoint_reports: list[dict] = []
    for index, wp in enumerate(plan["waypoints"], start=1):
        route = await plan_route(
            asset_id=asset_id,
            target_x=wp["x"],
            target_z=wp["z"],
            target_y=wp["y"],
        )
        if "error" in route:
            return {
                "asset_id": asset_id,
                "error": "Sweep route blocked",
                "route_error": route["error"],
                "failed_waypoint": wp,
                "route_obstacles": route.get("obstacles", []),
                "completed_waypoints": index - 1,
            }

        for route_wp in route.get("waypoints", []):
            move_result = await client.move_to(
                asset_id,
                route_wp["x"],
                route_wp["y"],
                route_wp["z"],
                get_drone_speed(asset_id),
            )
            if not move_result.get("success", True):
                return {
                    "asset_id": asset_id,
                    "error": "Failed while moving to sweep waypoint",
                    "failed_route_waypoint": route_wp,
                    "move_result": move_result,
                    "completed_waypoints": index - 1,
                }

            wait_result = await _wait_until_waypoint_reached(
                asset_id,
                route_wp["x"],
                route_wp["y"],
                route_wp["z"],
            )
            if not wait_result.get("ok", False):
                return {
                    "asset_id": asset_id,
                    "error": wait_result.get("error", "Sweep waypoint not reached"),
                    "failed_route_waypoint": route_wp,
                    "status": wait_result.get("status"),
                    "completed_waypoints": index - 1,
                }

        scan_result = await client.scan_area(asset_id, wp["x"], wp["y"], wp["z"], scan_radius)
        if not scan_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Scan tool failed during vertical sweep",
                "failed_scan_waypoint": wp,
                "scan_result": scan_result,
                "completed_waypoints": index - 1,
            }

        scan_wait = await _wait_until_waypoint_reached(
            asset_id,
            wp["x"],
            wp["y"],
            wp["z"],
            timeout_s=15.0,
        )
        if not scan_wait.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": scan_wait.get("error", "Sweep scan point did not stabilise"),
                "failed_scan_waypoint": wp,
                "status": scan_wait.get("status"),
                "completed_waypoints": index - 1,
            }

        view = await client.get_view(asset_id, heading_deg=0.0, detection_range=25.0)
        detected_survivors: list[dict] = []
        for obj in view.get("objects", []):
            if obj.get("object_type") != "survivor":
                continue
            detail_raw = obj.get("detail", "")
            detail: dict = {}
            if isinstance(detail_raw, str) and detail_raw:
                try:
                    parsed = json.loads(detail_raw)
                    if isinstance(parsed, dict):
                        detail = parsed
                except json.JSONDecodeError:
                    detail = {}
            detected_survivors.append(
                {
                    "id": obj.get("object_id"),
                    "x": obj.get("x"),
                    "y": obj.get("y"),
                    "z": obj.get("z"),
                    "distance": obj.get("distance"),
                    "direction": obj.get("direction"),
                    "submerged": bool(detail.get("submerged", False)),
                }
            )

        survivors_in_scan_radius = [
            det
            for det in detected_survivors
            if isinstance(det.get("distance"), (int, float))
            and math.isfinite(float(det["distance"]))
            and float(det["distance"]) <= scan_radius
        ]
        waypoint_reports.append(
            {
                "index": index,
                "x": wp["x"],
                "y": wp["y"],
                "z": wp["z"],
                "level_y": wp["level_y"],
                "survivors_in_range": len(survivors_in_scan_radius),
                "detected_survivors": survivors_in_scan_radius,
                "sensor_summary": view.get("summary", ""),
            }
        )

    max_survivors_seen = max((r["survivors_in_range"] for r in waypoint_reports), default=0)

    survivor_detection_index: dict[int, dict] = {}
    for report in waypoint_reports:
        for det in report.get("detected_survivors", []):
            sid = det.get("id")
            if not isinstance(sid, int):
                continue
            entry = survivor_detection_index.get(sid)
            if entry is None:
                survivor_detection_index[sid] = {
                    "id": sid,
                    "x": det.get("x"),
                    "y": det.get("y"),
                    "z": det.get("z"),
                    "direction": det.get("direction"),
                    "submerged": bool(det.get("submerged", False)),
                    "first_detected_waypoint": report.get("index"),
                    "detected_waypoint_count": 1,
                    "closest_distance": det.get("distance"),
                }
                continue

            entry["detected_waypoint_count"] = int(entry["detected_waypoint_count"]) + 1
            entry["submerged"] = bool(entry["submerged"]) or bool(det.get("submerged", False))
            distance = det.get("distance")
            current_min = entry.get("closest_distance")
            if isinstance(distance, (int, float)) and (
                not isinstance(current_min, (int, float)) or distance < current_min
            ):
                entry["closest_distance"] = distance
                entry["direction"] = det.get("direction")

    unique_survivors_detected = sorted(
        survivor_detection_index.values(),
        key=lambda row: int(row["id"]),
    )
    # Use whichever signal is stronger: unique survivor IDs or per-waypoint in-range count.
    # This avoids false zeroes in summary when IDs are unavailable but detections exist.
    reported_survivor_count = max(len(unique_survivors_detected), max_survivors_seen)
    final_status = await client.get_status(asset_id)
    latest_sensor_summary = waypoint_reports[-1]["sensor_summary"] if waypoint_reports else ""
    message = _build_sweep_scan_report(
        asset_id=asset_id,
        building=plan["building"],
        levels=plan["levels"],
        flood_level=plan["flood_level"],
        waypoint_count=plan["waypoint_count"],
        survivor_count=reported_survivor_count,
        battery=float(final_status.get("battery", 0.0)),
        sensor_summary=str(latest_sensor_summary),
    )

    return {
        "success": True,
        "message": message,
        "asset_id": asset_id,
        "strategy": "vertical_building_sweep",
        "building": plan["building"],
        "flood_level": plan["flood_level"],
        "levels": plan["levels"],
        "level_count": plan["level_count"],
        "waypoint_count": plan["waypoint_count"],
        "scan_reports": waypoint_reports,
        "max_survivors_in_range": max_survivors_seen,
        "reported_survivor_count": reported_survivor_count,
        "total_survivor_detections": sum(
            len(report.get("detected_survivors", [])) for report in waypoint_reports
        ),
        "unique_survivors_detected": unique_survivors_detected,
        "unique_survivor_count": len(unique_survivors_detected),
        "summary": message,
    }


async def select_best_drone(target_x: float, target_z: float) -> dict:
    """
    Select the best available drone for a mission near (target_x, target_z).
    """
    client = grpc_client
    asset_ids = client.registered_asset_ids()
    if not asset_ids:
        return {
            "error": "No drones uplinked.",
            "suggestion": "Use /uplink to connect a drone first.",
        }

    statuses = await asyncio.gather(
        *[client.get_status(aid) for aid in asset_ids],
        return_exceptions=True,
    )

    eligible = []
    for status in statuses:
        if isinstance(status, Exception):
            continue
        if status.get("battery", 0) <= 20:
            continue
        if status.get("status", "") != "IDLE":
            continue
        dist = math.sqrt((status["x"] - target_x) ** 2 + (status["z"] - target_z) ** 2)
        eligible.append({**status, "distance_m": round(dist, 1)})

    if not eligible:
        busy = [s for s in statuses if not isinstance(s, Exception)]
        return {
            "error": "No eligible drones available (all busy or low battery).",
            "suggestion": f"{len(busy)} drone(s) registered but none are IDLE with battery > 20%.",
        }

    return min(eligible, key=lambda d: d["distance_m"])


async def plan_route(
    asset_id: str,
    target_x: float,
    target_z: float,
    target_y: float | None = None,
    snap_to_building_center: bool = False,
) -> dict:
    """
    Pre-compute a collision-free route from the drone's current position
    to the target (target_x, target_z) with optional altitude target_y.
    """
    client = grpc_client
    status = await client.get_status(asset_id)
    cx, cy, cz = status["x"], status["y"], status["z"]

    requested_x = target_x
    requested_z = target_z
    nearby = WORLD.building_near_xz(target_x, target_z)
    available_window_waypoints: list[dict] = []
    selected_window_waypoint: dict | None = None
    if nearby is not None and nearby.windows:
        available_window_waypoints = nearby.window_scan_waypoints(standoff=WINDOW_SCAN_STANDOFF_M)

    if snap_to_building_center and nearby is not None:
        target_x = nearby.cx
        target_z = nearby.cz
        selected_window_waypoint = _select_window_waypoint(
            available_window_waypoints,
            ref_x=requested_x,
            ref_z=requested_z,
            preferred_y=target_y if target_y is not None else nearby.h / 2,
        )
        if selected_window_waypoint is not None:
            target_x = float(selected_window_waypoint["x"])
            target_z = float(selected_window_waypoint["z"])

    if target_y is None:
        if selected_window_waypoint is not None:
            target_y = float(selected_window_waypoint["y"])
        elif nearby is not None:
            target_y = nearby.max_y + 5.0
        else:
            target_y = 10.0
    target_y = max(target_y, 5.0)

    target_resolution: dict | None = None
    if nearby is not None:
        target_resolution = {
            "building_id": nearby.id,
            "input": {"x": requested_x, "z": requested_z},
            "resolved": {"x": target_x, "z": target_z},
            "center": {"x": nearby.cx, "z": nearby.cz},
            "bounds": {
                "min_x": nearby.min_x,
                "max_x": nearby.max_x,
                "min_z": nearby.min_z,
                "max_z": nearby.max_z,
            },
        }
        if available_window_waypoints:
            target_resolution["window_waypoints"] = available_window_waypoints
        if selected_window_waypoint is not None:
            target_resolution["selected_window_waypoint"] = selected_window_waypoint

    window_summary_suffix = ""
    if selected_window_waypoint is not None:
        window_summary_suffix = (
            " Window approach "
            f"{selected_window_waypoint['face']} floor {selected_window_waypoint['floor']}."
        )

    obstacles = WORLD.obstacles_in_path(cx, cy, cz, target_x, target_y, target_z, samples=40, margin=1.0)
    if not obstacles:
        return {
            "asset_id": asset_id,
            "from": {"x": cx, "y": cy, "z": cz},
            "to": {"x": target_x, "y": target_y, "z": target_z},
            "waypoints": [
                {"x": target_x, "y": target_y, "z": target_z, "reason": "direct path clear"},
            ],
            "obstacle_count": 0,
            "strategy": "direct",
            "summary": f"1 waypoint, direct path clear. Scan alt={target_y}m.{window_summary_suffix}",
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    max_obstacle_h = max(b.max_y for b in obstacles)
    clearance_y = max_obstacle_h + 5.0

    seg_climb = WORLD.obstacles_in_path(cx, cy, cz, cx, clearance_y, cz, samples=20, margin=1.0)
    seg_cruise = WORLD.obstacles_in_path(
        cx,
        clearance_y,
        cz,
        target_x,
        clearance_y,
        target_z,
        samples=40,
        margin=1.0,
    )
    seg_descend = WORLD.obstacles_in_path(
        target_x,
        clearance_y,
        target_z,
        target_x,
        target_y,
        target_z,
        samples=20,
        margin=1.0,
    )

    if not seg_climb and not seg_cruise and not seg_descend:
        waypoints = [
            {
                "x": cx,
                "y": clearance_y,
                "z": cz,
                "reason": f"climb to clear obstacle (h={max_obstacle_h}m)",
            },
            {"x": target_x, "y": clearance_y, "z": target_z, "reason": "cruise above obstacles"},
            {"x": target_x, "y": target_y, "z": target_z, "reason": "descend to scan altitude"},
        ]
        return {
            "asset_id": asset_id,
            "from": {"x": cx, "y": cy, "z": cz},
            "to": {"x": target_x, "y": target_y, "z": target_z},
            "waypoints": waypoints,
            "obstacle_count": len(obstacles),
            "strategy": "over",
            "summary": (
                f"3 waypoints, clearing {len(obstacles)} obstacle via over "
                f"(max h={max_obstacle_h}m). Scan alt={target_y}m.{window_summary_suffix}"
            ),
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    dx = target_x - cx
    dz = target_z - cz
    length = math.sqrt(dx * dx + dz * dz)
    if length < 1e-6:
        return {
            "asset_id": asset_id,
            "error": "No clear route found",
            "obstacles": [{"id": b.id, "cx": b.cx, "cz": b.cz, "h": b.h} for b in obstacles],
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    perp_x = -dz / length
    perp_z = dx / length
    mid_x = (cx + target_x) / 2
    mid_z = (cz + target_z) / 2
    max_half_w = max(max(b.w, b.d) / 2 for b in obstacles)
    offset_dist = max_half_w + 5.0
    fly_y = max(target_y, clearance_y)

    for sign in (1.0, -1.0):
        wp_x = mid_x + sign * perp_x * offset_dist
        wp_z = mid_z + sign * perp_z * offset_dist

        seg1 = WORLD.obstacles_in_path(cx, cy, cz, wp_x, fly_y, wp_z, samples=40, margin=1.0)
        seg2 = WORLD.obstacles_in_path(
            wp_x,
            fly_y,
            wp_z,
            target_x,
            target_y,
            target_z,
            samples=40,
            margin=1.0,
        )
        if not seg1 and not seg2:
            waypoints = [
                {"x": wp_x, "y": fly_y, "z": wp_z, "reason": "detour around obstacle"},
                {"x": target_x, "y": target_y, "z": target_z, "reason": "proceed to target"},
            ]
            return {
                "asset_id": asset_id,
                "from": {"x": cx, "y": cy, "z": cz},
                "to": {"x": target_x, "y": target_y, "z": target_z},
                "waypoints": waypoints,
                "obstacle_count": len(obstacles),
                "strategy": "around",
                "summary": (
                    f"2 waypoints, clearing {len(obstacles)} obstacle via around. "
                    f"Scan alt={target_y}m.{window_summary_suffix}"
                ),
                **({"target_resolution": target_resolution} if target_resolution else {}),
            }

    return {
        "asset_id": asset_id,
        "error": "No clear route found",
        "obstacles": [{"id": b.id, "cx": b.cx, "cz": b.cz, "h": b.h} for b in obstacles],
        **({"target_resolution": target_resolution} if target_resolution else {}),
    }


def plan_sweep_pattern(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    altitude: float = 10.0,
    spacing: float = 5.0,
) -> dict:
    """
    Compute a lawnmower sweep pattern over a rectangular area.
    Returns a list of (x, y, z) waypoints for systematic coverage.
    """
    waypoints: list[dict] = []
    x = min_x
    direction = 1
    while x <= max_x:
        row = [
            {"x": x, "y": min_y, "z": altitude},
            {"x": x, "y": max_y, "z": altitude},
        ]
        waypoints.extend(row if direction == 1 else list(reversed(row)))
        x += spacing
        direction *= -1
    return {"waypoints": waypoints, "count": len(waypoints)}


async def deploy_swarm(asset_ids: list[str], formation: str = "spread") -> dict:
    """
    Deploy multiple drones in a named formation.
    Supported formations: 'spread', 'line', 'triangle'.
    """
    positions = _FORMATIONS.get(formation, _FORMATIONS["spread"])
    results = await asyncio.gather(
        *[
            grpc_client.move_to(aid, *positions[i % len(positions)])
            for i, aid in enumerate(asset_ids)
        ]
    )
    return {"deployed": asset_ids, "formation": formation, "results": list(results)}


async def recall_swarm(asset_ids: list[str]) -> dict:
    """Command all drones in the list to return to base immediately."""
    results = await asyncio.gather(
        *[grpc_client.return_to_base(aid) for aid in asset_ids]
    )
    return {"recalled": asset_ids, "results": list(results)}
