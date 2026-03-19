from __future__ import annotations

import asyncio
import math

from backend.services.core import context
from backend.services.core.survivor_registry import get_detected_survivor_ids
from backend.services.navigation.internal.window_ops import select_window_waypoint
from backend.world.model import WINDOW_SCAN_STANDOFF_M

_MIN_ELIGIBLE_BATTERY_PCT = 20


def _distance_xz(x1: float, z1: float, x2: float, z2: float) -> float:
    return math.sqrt((x1 - x2) ** 2 + (z1 - z2) ** 2)


def _is_eligible_idle_drone(status: dict) -> bool:
    return (
        status.get("battery", 0) > _MIN_ELIGIBLE_BATTERY_PCT
        and status.get("status", "") == "IDLE"
    )


def _no_eligible_drones_result(statuses: list[dict | Exception]) -> dict:
    ready_count = len([status for status in statuses if not isinstance(status, Exception)])
    return {
        "error": "No eligible drones available (all busy or low battery).",
        "suggestion": (
            f"{ready_count} drone(s) registered but none are IDLE "
            f"with battery > {_MIN_ELIGIBLE_BATTERY_PCT}%."
        ),
    }


async def select_best_drone(target_x: float, target_z: float) -> dict:
    """Select the best available drone for a mission near (target_x, target_z)."""
    client = context.get_grpc_client()
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
        if not _is_eligible_idle_drone(status):
            continue
        dist = _distance_xz(status["x"], status["z"], target_x, target_z)
        eligible.append({**status, "distance_m": round(dist, 1)})

    if not eligible:
        return _no_eligible_drones_result(statuses)

    return min(eligible, key=lambda drone: drone["distance_m"])


async def plan_route(
    asset_id: str,
    target_x: float,
    target_z: float,
    target_y: float | None = None,
    snap_to_building_center: bool = False,
    exclude_building_id: int | None = None,
) -> dict:
    """
    Pre-compute a collision-free route from the drone's current position.

    ``exclude_building_id`` removes a specific building from obstacle checks -
    used when the destination IS the target building (e.g. rooftop approach).
    """
    world = context.get_world()
    client = context.get_grpc_client()
    status = await client.get_status(asset_id)
    cx, cy, cz = status["x"], status["y"], status["z"]

    requested_x = target_x
    requested_z = target_z
    nearby = world.building_near_xz(target_x, target_z)
    available_window_waypoints: list[dict] = []
    selected_window_waypoint: dict | None = None
    if nearby is not None and nearby.windows:
        available_window_waypoints = nearby.window_scan_waypoints(standoff=WINDOW_SCAN_STANDOFF_M)

    if snap_to_building_center and nearby is not None:
        target_x = nearby.cx
        target_z = nearby.cz
        selected_window_waypoint = select_window_waypoint(
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

    def _filter(buildings: list) -> list:
        if exclude_building_id is None:
            return buildings
        return [building for building in buildings if building.id != exclude_building_id]

    obstacles = _filter(world.obstacles_in_path(cx, cy, cz, target_x, target_y, target_z, samples=40, margin=1.0))
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

    max_obstacle_h = max(building.max_y for building in obstacles)
    clearance_y = max_obstacle_h + 5.0

    seg_climb = _filter(world.obstacles_in_path(cx, cy, cz, cx, clearance_y, cz, samples=20, margin=1.0))
    seg_cruise = _filter(
        world.obstacles_in_path(
            cx,
            clearance_y,
            cz,
            target_x,
            clearance_y,
            target_z,
            samples=40,
            margin=1.0,
        )
    )
    seg_descend = _filter(
        world.obstacles_in_path(
            target_x,
            clearance_y,
            target_z,
            target_x,
            target_y,
            target_z,
            samples=20,
            margin=1.0,
        )
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
            "from": {"x": cx, "y": cy, "z": cz},
            "to": {"x": target_x, "y": target_y, "z": target_z},
            "waypoints": [],
            "obstacle_count": 0,
            "strategy": "already_at_destination",
            "summary": f"Already at destination (x={target_x}, z={target_z}). No navigation needed.",
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    perp_x = -dz / length
    perp_z = dx / length
    mid_x = (cx + target_x) / 2
    mid_z = (cz + target_z) / 2
    max_half_w = max(max(building.w, building.d) / 2 for building in obstacles)
    offset_dist = max_half_w + 5.0
    fly_y = max(target_y, clearance_y)

    for sign in (1.0, -1.0):
        wp_x = mid_x + sign * perp_x * offset_dist
        wp_z = mid_z + sign * perp_z * offset_dist
        seg1 = _filter(world.obstacles_in_path(cx, cy, cz, wp_x, fly_y, wp_z, samples=40, margin=1.0))
        seg2 = _filter(
            world.obstacles_in_path(
                wp_x,
                fly_y,
                wp_z,
                target_x,
                target_y,
                target_z,
                samples=40,
                margin=1.0,
            )
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
        "obstacles": [{"id": building.id, "cx": building.cx, "cz": building.cz, "h": building.h} for building in obstacles],
        **({"target_resolution": target_resolution} if target_resolution else {}),
    }


def find_buildings_in_area(
    center_x: float,
    center_z: float,
    radius: float = 30.0,
    drone_x: float | None = None,
    drone_z: float | None = None,
) -> dict:
    """
    Return all buildings whose nearest edge is within `radius` metres of
    (center_x, center_z).
    """
    world = context.get_world()
    buildings = world.buildings_near(center_x, center_z, radius)
    sort_x = drone_x if drone_x is not None else center_x
    sort_z = drone_z if drone_z is not None else center_z
    buildings_sorted = sorted(buildings, key=lambda building: building.distance_xz(sort_x, sort_z))
    return {
        "buildings": [
            {
                "id": building.id,
                "x": building.cx,
                "z": building.cz,
                "height": building.h,
                "bounds": {
                    "min_x": building.min_x,
                    "max_x": building.max_x,
                    "min_z": building.min_z,
                    "max_z": building.max_z,
                },
            }
            for building in buildings_sorted
        ],
        "total": len(buildings_sorted),
        "center": {"x": center_x, "z": center_z},
        "radius": radius,
        **({"drone_position": {"x": drone_x, "z": drone_z}} if drone_x is not None else {}),
    }


def find_survivors_in_area(
    center_x: float,
    center_z: float,
    radius: float = 30.0,
    detected_only: bool = False,
    require_all_detected: bool = False,
) -> dict:
    """
    Return all survivors within radius metres of (center_x, center_z) in XZ.
    """
    world = context.get_world()
    detected_ids = get_detected_survivor_ids()

    rows: list[tuple[float, object]] = []
    for survivor in world.survivors:
        dist = math.sqrt((survivor.x - center_x) ** 2 + (survivor.z - center_z) ** 2)
        if dist <= radius:
            rows.append((dist, survivor))
    rows.sort(key=lambda row: row[0])

    detected_rows = [
        (distance, survivor)
        for distance, survivor in rows
        if survivor.id in detected_ids
    ]
    all_detected = len(detected_rows) == len(rows)
    blocked_by_detection_gate = bool(
        detected_only and require_all_detected and rows and not all_detected
    )

    selected_rows = rows
    if detected_only:
        selected_rows = detected_rows
    if blocked_by_detection_gate:
        selected_rows = []

    return {
        "survivors": [
            {
                "id": survivor.id,
                "x": survivor.x,
                "y": survivor.y,
                "z": survivor.z,
                "submerged": survivor.submerged,
                "distance_m": round(distance, 2),
            }
            for distance, survivor in selected_rows
        ],
        "total": len(selected_rows),
        "total_in_area": len(rows),
        "detected_total": len(detected_rows),
        "all_detected": all_detected,
        "detection_gate_blocked": blocked_by_detection_gate,
        "center": {"x": center_x, "z": center_z},
        "radius": radius,
        "detected_only": detected_only,
        "require_all_detected": require_all_detected,
        **(
            {"message": "Not all survivors in the selected area have been detected yet."}
            if blocked_by_detection_gate
            else {}
        ),
    }


def plan_sweep_pattern(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    altitude: float = 10.0,
    spacing: float = 5.0,
) -> dict:
    """Compute a lawnmower sweep pattern over a rectangular area."""
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
