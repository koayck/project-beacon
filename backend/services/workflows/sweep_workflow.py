from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Awaitable, Callable
from typing import Any


def _normalize_scan_route_error(message: object, fallback: str) -> str:
    text = str(message) if message is not None else fallback
    return text.replace("return route", "scan route")


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

async def sweep_scan_building(
    asset_id: str,
    *,
    target_x: float | None,
    target_z: float | None,
    scan_radius: float,
    level_step: float,
    standoff: float,
    floor_height_m: float,
    thermal_horiz_fov_half_deg: float,
    plan_route_fn: Callable[..., Awaitable[dict]],
    plan_building_vertical_sweep: Callable[..., dict],
    wait_until_waypoint_reached: Callable[..., Awaitable[dict]],
    get_status: Callable[[str], Awaitable[dict]],
    move_to: Callable[[str, float, float, float, float], Awaitable[dict]],
    scan_area: Callable[[str, float, float, float, float], Awaitable[dict]],
    get_view: Callable[[str, float, float], Awaitable[dict]],
    end_scan: Callable[[str], Awaitable[dict]] | None,
    get_speed: Callable[[str], float],
    register_detected_survivors: Callable[[list[dict]], int],
    build_sweep_scan_report: Callable[..., str],
) -> dict:
    """
    Execute a full-height-above-water perimeter sweep scan around a building.
    """
    # ── Wait for drone to finish any in-progress movement ──────────────
    _SETTLE_TIMEOUT_S = 120.0
    _SETTLE_POLL_S = 0.3
    _settled = 0.0
    while _settled < _SETTLE_TIMEOUT_S:
        _st = await get_status(asset_id)
        if _st.get("status") != "MOVING":
            break
        await asyncio.sleep(_SETTLE_POLL_S)
        _settled += _SETTLE_POLL_S

    status = await get_status(asset_id)
    if target_x is None:
        target_x = status["x"]
    if target_z is None:
        target_z = status["z"]

    # 1. Pick the entry window via drone-XZ-distance on lowest-floor windows
    #    only, and compute a collision-free route to it. Ground-entry mimics
    #    a human pilot entering a building at the ground floor nearest to
    #    their approach rather than climbing to the roof first.
    entry_route = await plan_route_fn(
        asset_id=asset_id,
        target_x=target_x,
        target_z=target_z,
        snap_to_building_center=True,
        entry_mode="ground_entry",
    )
    if "error" in entry_route:
        return {
            "asset_id": asset_id,
            "error": "Sweep route blocked",
            "route_error": entry_route["error"],
            "route_obstacles": entry_route.get("obstacles", []),
            "completed_waypoints": 0,
        }

    # 2. Build the sweep plan. Both the route planner above and the sweep
    #    planner below use the drone's pre-flight XZ to pick the nearest
    #    lowest-floor entry window, so they typically agree on the entry.
    #    They may diverge only in pathological entry routes where the drone
    #    traverses significant XZ distance before reaching the building —
    #    not observed in current world geometries.
    plan = plan_building_vertical_sweep(
        target_x=target_x,
        target_z=target_z,
        level_step=level_step,
        standoff=standoff,
        approach_x=status.get("x"),
        approach_z=status.get("z"),
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

    building = plan.get("building", {})
    fallback_rooftop = {
        "x": float(building.get("center_x", target_x)),
        "y": float(building.get("height", 0.0)) + float(standoff),
        "z": float(building.get("center_z", target_z)),
    }

    waypoint_reports: list[dict] = []
    rooftop = plan.get("rooftop_position", fallback_rooftop)
    building_cx: float = float(building.get("center_x", target_x))
    building_cz: float = float(building.get("center_z", target_z))
    building_min_x: float = float(building.get("min_x", building_cx))
    building_max_x: float = float(building.get("max_x", building_cx))
    building_min_z: float = float(building.get("min_z", building_cz))
    building_max_z: float = float(building.get("max_z", building_cz))
    building_height: float = float(building.get("height", rooftop["y"]))
    _SURVIVOR_BUILDING_MARGIN = 2.1

    def _belongs_to_target_building(sx: object, sy: object, sz: object) -> bool:
        sx_f = _to_float(sx)
        sy_f = _to_float(sy)
        sz_f = _to_float(sz)
        if sx_f is None or sy_f is None or sz_f is None:
            return False
        return (
            building_min_x - _SURVIVOR_BUILDING_MARGIN <= sx_f <= building_max_x + _SURVIVOR_BUILDING_MARGIN
            and building_min_z - _SURVIVOR_BUILDING_MARGIN <= sz_f <= building_max_z + _SURVIVOR_BUILDING_MARGIN
            and -0.5 <= sy_f <= building_height + floor_height_m
        )

    building_id_raw = building.get("id")
    building_id = int(building_id_raw) if isinstance(building_id_raw, (int, float)) else None

    if plan["waypoints"]:
        # Use the entry route computed pre-sweep to drive the drone to the first
        # sweep waypoint. The sweep's first waypoint equals the entry window we
        # already routed to, so no second route computation is needed.
        transition_route = entry_route
        if "error" in transition_route:
            return {
                "asset_id": asset_id,
                "error": "Sweep route blocked",
                "route_error": transition_route["error"],
                "route_obstacles": transition_route.get("obstacles", []),
                "completed_waypoints": 0,
            }
        for move_wp in transition_route.get("waypoints", []):
            move_result = await move_to(
                asset_id, move_wp["x"], move_wp["y"], move_wp["z"],
                get_speed(asset_id),
            )
            if not move_result.get("success", True):
                return {
                    "asset_id": asset_id,
                    "error": "Failed while routing to first sweep waypoint",
                    "move_result": move_result,
                    "completed_waypoints": 0,
                }
            wait_result = await wait_until_waypoint_reached(
                asset_id, move_wp["x"], move_wp["y"], move_wp["z"],
                exclude_building_id=building_id,
            )
            if not wait_result.get("ok", False):
                return {
                    "asset_id": asset_id,
                    "error": _normalize_scan_route_error(
                        wait_result.get("error"),
                        "Could not reach first sweep waypoint",
                    ),
                    "status": wait_result.get("status"),
                    "completed_waypoints": 0,
                }

    for index, wp in enumerate(plan["waypoints"], start=1):
        move_result = await move_to(
            asset_id, wp["x"], wp["y"], wp["z"],
            get_speed(asset_id),
        )
        if not move_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Failed while moving to sweep waypoint",
                "failed_waypoint": wp,
                "move_result": move_result,
                "completed_waypoints": index - 1,
            }

        wait_result = await wait_until_waypoint_reached(
            asset_id, wp["x"], wp["y"], wp["z"],
            exclude_building_id=building_id,
        )
        if not wait_result.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": _normalize_scan_route_error(
                    wait_result.get("error"),
                    "Sweep waypoint not reached",
                ),
                "failed_waypoint": wp,
                "status": wait_result.get("status"),
                "completed_waypoints": index - 1,
            }

        if wp.get("transit"):
            continue

        scan_result = await scan_area(asset_id, wp["x"], wp["y"], wp["z"], scan_radius)
        if not scan_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Scan tool failed during vertical sweep",
                "failed_scan_waypoint": wp,
                "scan_result": scan_result,
                "completed_waypoints": index - 1,
            }

        scan_wait = await wait_until_waypoint_reached(
            asset_id,
            wp["x"],
            wp["y"],
            wp["z"],
            timeout_s=15.0,
        )
        if not scan_wait.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": _normalize_scan_route_error(
                    scan_wait.get("error"),
                    "Scan hold not reached",
                ),
                "failed_scan_waypoint": wp,
                "status": scan_wait.get("status"),
                "completed_waypoints": index - 1,
            }

        wp_x = float(wp["x"])
        wp_y = float(wp["y"])
        wp_z = float(wp["z"])
        face_dx = building_cx - wp_x
        face_dz = building_cz - wp_z
        heading_toward_building = math.degrees(math.atan2(face_dx, -face_dz)) % 360
        # Keep view range aligned with scan radius so sweep detections and
        # radius-filtered reporting use the same sensing envelope.
        view = await get_view(asset_id, heading_toward_building, float(scan_radius))
        detected_survivors: list[dict] = []
        for obj in view.get("objects", []):
            if obj.get("object_type") != "survivor":
                continue
            if not _belongs_to_target_building(obj.get("x"), obj.get("y"), obj.get("z")):
                continue
            sx, sz = obj.get("x", wp_x), obj.get("z", wp_z)
            surv_dx, surv_dz = sx - wp_x, sz - wp_z
            face_mag = math.sqrt(face_dx**2 + face_dz**2)
            surv_mag = math.sqrt(surv_dx**2 + surv_dz**2)
            if face_mag > 1e-6 and surv_mag > 1e-6:
                cos_a = (face_dx * surv_dx + face_dz * surv_dz) / (face_mag * surv_mag)
                angle_off_axis = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))
                if angle_off_axis > thermal_horiz_fov_half_deg:
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
            if (_to_float(det.get("distance")) is not None)
            and math.isfinite(float(det["distance"]))
            and float(det["distance"]) <= scan_radius
        ]
        view_survivor_count = view.get("survivors_in_range")
        survivors_visible_count = len(detected_survivors)
        view_survivor_count_int = _to_float(view_survivor_count)
        if view_survivor_count_int is not None and view_survivor_count_int.is_integer():
            survivors_visible_count = max(survivors_visible_count, int(view_survivor_count_int))
        survivors_within_radius_count = len(survivors_in_scan_radius)
        waypoint_reports.append(
            {
                "index": index,
                "x": wp["x"],
                "y": wp["y"],
                "z": wp["z"],
                "level_y": wp["level_y"],
                "survivors_in_range": survivors_visible_count,
                "survivors_within_scan_radius": survivors_within_radius_count,
                "detected_survivors": detected_survivors,
                "detected_survivors_within_scan_radius": survivors_in_scan_radius,
                "sensor_summary": view.get("summary", ""),
            }
        )

    max_survivors_seen = max((r["survivors_in_range"] for r in waypoint_reports), default=0)

    survivor_detection_index: dict[int, dict] = {}
    for report in waypoint_reports:
        for det in report.get("detected_survivors", []):
            sid = det.get("id")
            sid_value = _to_float(sid)
            if sid_value is None or not sid_value.is_integer():
                continue
            sid = int(sid_value)
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
            distance_value = _to_float(distance)
            current_min_value = _to_float(current_min)
            if distance_value is not None and (
                current_min_value is None or distance_value < current_min_value
            ):
                entry["closest_distance"] = distance_value
                entry["direction"] = det.get("direction")

    unique_survivors_detected = sorted(
        survivor_detection_index.values(),
        key=lambda row: int(row["id"]),
    )
    register_detected_survivors(unique_survivors_detected)
    reported_survivor_count = max(len(unique_survivors_detected), max_survivors_seen)
    final_status = await get_status(asset_id)
    if callable(end_scan):
        await end_scan(asset_id)
    latest_sensor_summary = waypoint_reports[-1]["sensor_summary"] if waypoint_reports else ""
    message = build_sweep_scan_report(
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
