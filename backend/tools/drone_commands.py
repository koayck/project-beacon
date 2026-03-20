from __future__ import annotations

import backend.services.api.control as _dc

# Re-export selected symbols for legacy import paths.
_wait_until_waypoint_reached = _dc._wait_until_waypoint_reached
plan_route = _dc.plan_route
set_client = _dc.set_client


def resolve_scan_target(target_x: float, target_z: float, margin: float = _dc.BUILDING_PROXIMITY_MARGIN_M) -> dict:
    result = _dc.resolve_scan_target(target_x, target_z, margin)
    if not isinstance(result, dict):
        return result
    waypoints = result.get("window_waypoints")
    if isinstance(waypoints, list) and len(waypoints) > 4:
        result = {**result, "window_waypoints": waypoints[:4]}
    return result


def plan_building_vertical_sweep(
    target_x: float,
    target_z: float,
    level_step: float = 3.0,
    standoff: float = 2.0,
    flood_clearance: float = 0.5,
    approach_x: float | None = None,
    approach_z: float | None = None,
) -> dict:
    result = _dc.plan_building_vertical_sweep(
        target_x=target_x,
        target_z=target_z,
        level_step=level_step,
        standoff=standoff,
        flood_clearance=flood_clearance,
        approach_x=approach_x,
        approach_z=approach_z,
    )
    if not isinstance(result, dict) or "building" not in result:
        return result
    building = result.get("building") if isinstance(result.get("building"), dict) else {}
    building_height = float(building.get("height", 0.0) or 0.0)
    levels_raw = result.get("levels") if isinstance(result.get("levels"), list) else []
    levels = [float(level) for level in levels_raw if isinstance(level, (int, float)) and float(level) <= building_height]
    if building_height > 0 and (not levels or abs(levels[-1] - building_height) > 1e-6):
        levels.append(round(building_height, 2))
    return {
        **result,
        "levels": levels,
        "level_count": len(levels),
        "waypoint_count": len(levels) * 5 if levels else result.get("waypoint_count", 0),
    }


async def sweep_scan_building(
    asset_id: str,
    target_x: float | None = None,
    target_z: float | None = None,
    scan_radius: float = _dc.DEFAULT_SWEEP_SCAN_RADIUS,
    level_step: float = 3.0,
    standoff: float = 2.0,
) -> dict:
    """Compatibility wrapper that keeps monkeypatch behavior used by tests."""
    preplan = plan_building_vertical_sweep(
        target_x if target_x is not None else 0.0,
        target_z if target_z is not None else 0.0,
        level_step=level_step,
        standoff=standoff,
    )
    if not isinstance(preplan, dict):
        return {"asset_id": asset_id, "error": "Invalid sweep plan response"}
    if not preplan.get("matched_building", False):
        return {
            "asset_id": asset_id,
            "error": preplan.get("error", "No building found for sweep scan"),
            "input": preplan.get("input", {"x": target_x, "z": target_z}),
        }
    if "error" in preplan:
        return {
            "asset_id": asset_id,
            "error": preplan["error"],
            "building": preplan.get("building"),
            "flood_level": preplan.get("flood_level"),
        }

    client = _dc.grpc_client
    waypoint_reports: list[dict] = []

    for index, wp in enumerate(preplan.get("waypoints", []), start=1):
        route = await plan_route(
            asset_id=asset_id,
            target_x=float(wp["x"]),
            target_z=float(wp["z"]),
            target_y=float(wp["y"]),
            snap_to_building_center=False,
            exclude_building_id=preplan.get("building", {}).get("id"),
        )
        if isinstance(route, dict) and "error" in route:
            return {
                "asset_id": asset_id,
                "error": "Sweep route blocked",
                "route_error": route["error"],
                "route_obstacles": route.get("obstacles", []),
                "completed_waypoints": index - 1,
            }

        route_waypoints = route.get("waypoints", []) if isinstance(route, dict) else []
        for move_wp in route_waypoints:
            move_result = await client.move_to(
                asset_id,
                float(move_wp["x"]),
                float(move_wp["y"]),
                float(move_wp["z"]),
            )
            if not move_result.get("success", True):
                return {
                    "asset_id": asset_id,
                    "error": "Failed while moving to sweep waypoint",
                    "failed_waypoint": wp,
                    "move_result": move_result,
                    "completed_waypoints": index - 1,
                }

            wait_result = await _wait_until_waypoint_reached(
                asset_id,
                float(move_wp["x"]),
                float(move_wp["y"]),
                float(move_wp["z"]),
                exclude_building_id=preplan.get("building", {}).get("id"),
            )
            if not wait_result.get("ok", False):
                return {
                    "asset_id": asset_id,
                    "error": wait_result.get("error", "Sweep waypoint not reached"),
                    "failed_waypoint": wp,
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
            exclude_building_id=preplan.get("building", {}).get("id"),
        )
        if not scan_wait.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": scan_wait.get("error", "Scan hold not reached"),
                "failed_scan_waypoint": wp,
                "status": scan_wait.get("status"),
                "completed_waypoints": index - 1,
            }

        view = await client.get_view(asset_id)
        detected = [
            {
                "id": obj.get("object_id"),
                "x": obj.get("x"),
                "y": obj.get("y"),
                "z": obj.get("z"),
                "distance": obj.get("distance"),
                "direction": obj.get("direction"),
            }
            for obj in view.get("objects", [])
            if obj.get("object_type") == "survivor"
        ]
        in_radius = [
            row for row in detected
            if isinstance(row.get("distance"), (int, float)) and float(row["distance"]) <= scan_radius
        ]
        waypoint_reports.append(
            {
                "index": index,
                "x": wp["x"],
                "y": wp["y"],
                "z": wp["z"],
                "level_y": wp.get("level_y", wp["y"]),
                "survivors_in_range": len(in_radius),
                "survivors_within_scan_radius": len(in_radius),
                "detected_survivors": in_radius,
                "detected_survivors_within_scan_radius": in_radius,
                "sensor_summary": view.get("summary", ""),
            }
        )

    by_id: dict[int, dict] = {}
    for report in waypoint_reports:
        for det in report.get("detected_survivors", []):
            sid = det.get("id")
            if not isinstance(sid, int):
                continue
            by_id[sid] = {
                "id": sid,
                "x": det.get("x"),
                "y": det.get("y"),
                "z": det.get("z"),
                "direction": det.get("direction"),
            }

    unique = sorted(by_id.values(), key=lambda row: int(row["id"]))
    final_status = await client.get_status(asset_id)
    message = _dc._build_sweep_scan_report(
        asset_id=asset_id,
        building=preplan.get("building", {}),
        levels=preplan.get("levels", []),
        flood_level=float(preplan.get("flood_level", 0.0) or 0.0),
        waypoint_count=int(preplan.get("waypoint_count", len(preplan.get("waypoints", []))) or 0),
        survivor_count=len(unique),
        battery=float(final_status.get("battery", 0.0)),
        sensor_summary=str(waypoint_reports[-1].get("sensor_summary", "") if waypoint_reports else ""),
    )
    return {
        "success": True,
        "asset_id": asset_id,
        "strategy": "vertical_building_sweep",
        "building": preplan.get("building"),
        "flood_level": preplan.get("flood_level"),
        "levels": preplan.get("levels", []),
        "level_count": preplan.get("level_count", 0),
        "waypoint_count": preplan.get("waypoint_count", len(preplan.get("waypoints", []))),
        "scan_reports": waypoint_reports,
        "max_survivors_in_range": max((r["survivors_in_range"] for r in waypoint_reports), default=0),
        "reported_survivor_count": len(unique),
        "total_survivor_detections": sum(len(r.get("detected_survivors", [])) for r in waypoint_reports),
        "unique_survivors_detected": unique,
        "unique_survivor_count": len(unique),
        "summary": message,
        "message": message,
    }


async def return_to_base(asset_id: str) -> dict:
    """Compatibility wrapper preserving monkeypatch-friendly return routing behavior."""
    client = _dc.grpc_client
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
            float(wp["x"]),
            float(wp["y"]),
            float(wp["z"]),
            _dc.get_drone_speed(asset_id),
        )
        if not move_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Failed while executing return route waypoint",
                "waypoint": wp,
                "move_result": move_result,
            }

        wait_result = await _wait_until_waypoint_reached(
            asset_id,
            float(wp["x"]),
            float(wp["y"]),
            float(wp["z"]),
        )
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
        _dc.get_drone_speed(asset_id),
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


__all__ = [
    "_wait_until_waypoint_reached",
    "plan_route",
    "return_to_base",
    "resolve_scan_target",
    "plan_building_vertical_sweep",
    "set_client",
    "sweep_scan_building",
]
