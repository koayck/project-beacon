"""Compatibility wrappers over the shared drone control service layer."""
from __future__ import annotations

import asyncio
import math
from typing import TYPE_CHECKING

from backend.services.drone_control import (
    get_drone_status as service_get_drone_status,
    move_drone_to as service_move_drone_to,
    plan_sweep_pattern as service_plan_sweep_pattern,
    return_to_base as service_return_to_base,
    scan_area as service_scan_area,
)

from backend.world.model import BUILDING_PROXIMITY_MARGIN_M, FLOOD_LEVEL, WORLD

if TYPE_CHECKING:
    from backend.grpc.client import DroneGrpcClient

_client: DroneGrpcClient | None = None


def set_client(client: DroneGrpcClient) -> None:
    global _client
    _client = client


def _get_client() -> DroneGrpcClient:
    if _client is None:
        raise RuntimeError("gRPC client not initialised. Call set_client() at startup.")
    return _client


async def list_all_drones() -> dict:
    """
    Return the current position, battery, and status of ALL registered drones.
    Call this first whenever a command does not specify which drone to use,
    so you can apply Rule 1 (nearest eligible drone dispatch).
    Returns a dict with key 'drones': list of status objects, each containing
    asset_id, x, y, z, battery, status.
    If no drones are registered, returns {'drones': [], 'message': 'No drones uplinked'}.
    """
    client = _get_client()
    asset_ids = client.registered_asset_ids()
    if not asset_ids:
        return {"drones": [], "message": "No drones uplinked. Use /uplink to connect a drone."}
    statuses = await asyncio.gather(
        *[client.get_status(aid) for aid in asset_ids],
        return_exceptions=True,
    )
    drones = []
    for aid, s in zip(asset_ids, statuses):
        if isinstance(s, Exception):
            drones.append({"asset_id": aid, "error": str(s)})
        else:
            drones.append(s)
    return {"drones": drones}


async def move_drone_to(
    asset_id: str, x: float, y: float, z: float, speed: float = 5.0
) -> dict:
    """Move a drone to the given X/Y/Z coordinates at the specified speed."""
    return await _get_client().move_to(asset_id, x, y, z, speed)


async def _wait_until_waypoint_reached(
    asset_id: str,
    x: float,
    y: float,
    z: float,
    tolerance: float = 0.6,
    timeout_s: float = 60.0,
    poll_s: float = 0.2,
) -> dict:
    """
    Poll drone status until it reaches a waypoint, is blocked, or times out.
    """
    client = _get_client()
    elapsed = 0.0
    while elapsed <= timeout_s:
        status = await client.get_status(asset_id)
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

    The tool plans a safe path to a home-approach point, executes each waypoint
    with status polling, then performs a final explicit landing leg to (0,0,0).
    It intentionally avoids the simulator's direct ReturnToBase RPC to prevent
    straight-line reintroduction after routed movement.
    """
    client = _get_client()

    # Approach home at safe altitude first to avoid blind straight-line collisions.
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
        move_result = await client.move_to(asset_id, wp["x"], wp["y"], wp["z"], 5.0)
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
    final_move_result = await client.move_to(asset_id, final_wp["x"], final_wp["y"], final_wp["z"], 5.0)
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
    return await service_get_drone_status(asset_id)


async def scan_area(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """
    Command a drone to scan a circular area centred at (cx, cy, cz).
    Used for thermal imaging and survivor detection.
    """
    return await _get_client().scan_area(asset_id, cx, cy, cz, radius)


async def get_drone_view(
    asset_id: str,
    heading_deg: float = 0.0,
    detection_range: float = 20.0,
) -> dict:
    """
    Get what the drone can currently see from its position.
    Returns nearby buildings, visible survivors, terrain type,
    altitude above ground level, and whether an obstacle is ahead.
    Use this before moving to check for obstacles, and during scans
    to report survivor locations.
    """
    return await _get_client().get_view(asset_id, heading_deg, detection_range)


def resolve_scan_target(
    target_x: float,
    target_z: float,
    margin: float = BUILDING_PROXIMITY_MARGIN_M,
) -> dict:
    """
    Resolve a scan target to a building footprint when the point is on/near a building.

    Returns the resolved scan center and building bounds so agents can explain why
    a target was normalised.
    """
    building = WORLD.building_near_xz(target_x, target_z, margin=margin)
    if building is None:
        return {
            "matched_building": False,
            "input": {"x": target_x, "z": target_z},
            "resolved_target": {"x": target_x, "z": target_z},
            "summary": "No nearby building footprint; using provided coordinates.",
        }

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
        "recommended_scan_y": building.max_y + 5.0,
        "summary": (
            f"Matched building {building.id}; footprint "
            f"x[{building.min_x:.1f},{building.max_x:.1f}] "
            f"z[{building.min_z:.1f},{building.max_z:.1f}] "
            f"→ center ({building.cx:.1f}, {building.cz:.1f})."
        ),
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

    The sweep forms rectangular rings around the building footprint for each Y level
    from (flood level + clearance) up to roof height.
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
    scan_radius: float = 8.0,
    level_step: float = 3.0,
    standoff: float = 2.0,
) -> dict:
    """
    Execute a full-height-above-water perimeter sweep scan around a building.

    This function routes safely to each waypoint, runs scan_area at each point,
    and returns a structured coverage report.
    """
    client = _get_client()
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
                5.0,
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
        waypoint_reports.append(
            {
                "index": index,
                "x": wp["x"],
                "y": wp["y"],
                "z": wp["z"],
                "level_y": wp["level_y"],
                "survivors_in_range": view.get("survivors_in_range", 0),
                "sensor_summary": view.get("summary", ""),
            }
        )

    max_survivors_seen = max(
        (r["survivors_in_range"] for r in waypoint_reports),
        default=0,
    )
    return {
        "success": True,
        "asset_id": asset_id,
        "strategy": "vertical_building_sweep",
        "building": plan["building"],
        "flood_level": plan["flood_level"],
        "levels": plan["levels"],
        "level_count": plan["level_count"],
        "waypoint_count": plan["waypoint_count"],
        "scan_reports": waypoint_reports,
        "max_survivors_in_range": max_survivors_seen,
        "summary": plan["summary"],
    }


async def select_best_drone(target_x: float, target_z: float) -> dict:
    """
    Select the best available drone for a mission near (target_x, target_z).
    Filters eligible drones (battery > 20%, status IDLE), then returns
    the nearest one by Euclidean distance on the X/Z plane.
    Call this whenever the operator has not specified which drone to use.
    Returns: { asset_id, distance_m, battery, x, y, z } on success,
             or { error, suggestion } if no eligible drone is available.
    """
    client = _get_client()
    asset_ids = client.registered_asset_ids()
    if not asset_ids:
        return {"error": "No drones uplinked.", "suggestion": "Use /uplink to connect a drone first."}

    statuses = await asyncio.gather(
        *[client.get_status(aid) for aid in asset_ids],
        return_exceptions=True,
    )

    eligible = []
    for aid, s in zip(asset_ids, statuses):
        if isinstance(s, Exception):
            continue
        if s.get("battery", 0) <= 20:
            continue
        if s.get("status", "") != "IDLE":
            continue
        dist = math.sqrt((s["x"] - target_x) ** 2 + (s["z"] - target_z) ** 2)
        eligible.append({**s, "distance_m": round(dist, 1)})

    if not eligible:
        busy = [s for s in statuses if not isinstance(s, Exception)]
        return {
            "error": "No eligible drones available (all busy or low battery).",
            "suggestion": f"{len(busy)} drone(s) registered but none are IDLE with battery > 20%.",
        }

    best = min(eligible, key=lambda d: d["distance_m"])
    return best


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

    If target_y is omitted, altitude is auto-calculated:
    - If a building is near the target XZ, scan altitude = building top + 5 m.
    - Otherwise, default cruise altitude = 10 m.

    Returns waypoints that the caller should execute in order via move_drone_to.
    Each waypoint has x, y, z, and a reason string.
    """
    client = _get_client()
    status = await client.get_status(asset_id)
    cx, cy, cz = status["x"], status["y"], status["z"]

    requested_x = target_x
    requested_z = target_z
    nearby = WORLD.building_near_xz(target_x, target_z)
    if snap_to_building_center and nearby is not None:
        target_x = nearby.cx
        target_z = nearby.cz

    # ── Auto-calculate scan altitude ──────────────────────────────────────
    if target_y is None:
        if nearby is not None:
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

    # ── Check direct path ─────────────────────────────────────────────────
    obstacles = WORLD.obstacles_in_path(cx, cy, cz, target_x, target_y, target_z, samples=40)
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
            "summary": f"1 waypoint, direct path clear. Scan alt={target_y}m.",
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    # ── Strategy 1: go over ───────────────────────────────────────────────
    max_obstacle_h = max(b.max_y for b in obstacles)
    clearance_y = max_obstacle_h + 5.0

    seg_climb = WORLD.obstacles_in_path(cx, cy, cz, cx, clearance_y, cz, samples=20)
    seg_cruise = WORLD.obstacles_in_path(
        cx, clearance_y, cz, target_x, clearance_y, target_z, samples=40,
    )
    seg_descend = WORLD.obstacles_in_path(
        target_x, clearance_y, target_z, target_x, target_y, target_z, samples=20,
    )

    if not seg_climb and not seg_cruise and not seg_descend:
        waypoints = [
            {"x": cx, "y": clearance_y, "z": cz,
             "reason": f"climb to clear obstacle (h={max_obstacle_h}m)"},
            {"x": target_x, "y": clearance_y, "z": target_z,
             "reason": "cruise above obstacles"},
            {"x": target_x, "y": target_y, "z": target_z,
             "reason": "descend to scan altitude"},
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
                f"(max h={max_obstacle_h}m). Scan alt={target_y}m."
            ),
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    # ── Strategy 2: go around ─────────────────────────────────────────────
    dx = target_x - cx
    dz = target_z - cz
    length = math.sqrt(dx * dx + dz * dz)
    if length < 1e-6:
        return {
            "asset_id": asset_id,
            "error": "No clear route found",
            "obstacles": [
                {"id": b.id, "cx": b.cx, "cz": b.cz, "h": b.h}
                for b in obstacles
            ],
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    # Perpendicular unit vector in XZ plane
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

        seg1 = WORLD.obstacles_in_path(cx, cy, cz, wp_x, fly_y, wp_z, samples=40)
        seg2 = WORLD.obstacles_in_path(
            wp_x, fly_y, wp_z, target_x, target_y, target_z, samples=40,
        )
        if not seg1 and not seg2:
            waypoints = [
                {"x": wp_x, "y": fly_y, "z": wp_z,
                 "reason": "detour around obstacle"},
                {"x": target_x, "y": target_y, "z": target_z,
                 "reason": "proceed to target"},
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
                    f"Scan alt={target_y}m."
                ),
                **({"target_resolution": target_resolution} if target_resolution else {}),
            }

    # ── Nothing worked ────────────────────────────────────────────────────
    return {
        "asset_id": asset_id,
        "error": "No clear route found",
        "obstacles": [
            {"id": b.id, "cx": b.cx, "cz": b.cz, "h": b.h}
            for b in obstacles
        ],
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
    return service_plan_sweep_pattern(min_x, min_y, max_x, max_y, altitude, spacing)
