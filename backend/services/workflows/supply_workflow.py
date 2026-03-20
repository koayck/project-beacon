from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def dispatch_supply_to_building(
    asset_id: str,
    building: dict,
    *,
    resolve_scan_target: Callable[[float, float], dict],
    world: object,
    window_scan_standoff_m: float,
    select_window_waypoint: Callable[..., dict | None],
    return_to_base_fn: Callable[[str], Awaitable[dict]],
    plan_route_fn: Callable[..., Awaitable[dict]],
    move_drone_to_fn: Callable[..., Awaitable[dict]],
    wait_until_waypoint_reached_fn: Callable[..., Awaitable[dict]],
    get_status_fn: Callable[[str], Awaitable[dict]],
) -> dict:
    target_x = building.get("x")
    target_y = building.get("y")
    target_z = building.get("z")
    if not isinstance(target_x, (int, float)) or not isinstance(target_z, (int, float)):
        return {
            "asset_id": asset_id,
            "error": "Invalid supply target coordinates.",
            "building": building,
        }

    resolved = resolve_scan_target(float(target_x), float(target_z))
    matched_building = resolved.get("building") if isinstance(resolved, dict) else None
    recommended_window = (
        resolved.get("recommended_window_waypoint")
        if isinstance(resolved, dict)
        else None
    )
    interior_target = False
    window_drop_for_survivor: dict | None = None
    if isinstance(target_y, (int, float)):
        host_building = world.building_at(float(target_x), float(target_y), float(target_z))
        interior_target = host_building is not None
        if host_building is not None:
            candidate_windows = host_building.window_scan_waypoints(standoff=window_scan_standoff_m)
            if candidate_windows:
                window_drop_for_survivor = select_window_waypoint(
                    candidate_windows,
                    ref_x=float(target_x),
                    ref_z=float(target_z),
                    preferred_y=float(target_y),
                )

    if (
        interior_target
        and isinstance(window_drop_for_survivor, dict)
        and isinstance(window_drop_for_survivor.get("x"), (int, float))
        and isinstance(window_drop_for_survivor.get("y"), (int, float))
        and isinstance(window_drop_for_survivor.get("z"), (int, float))
    ):
        drop_x = float(window_drop_for_survivor["x"])
        drop_y = float(window_drop_for_survivor["y"])
        drop_z = float(window_drop_for_survivor["z"])
    elif (
        interior_target
        and isinstance(recommended_window, dict)
        and isinstance(recommended_window.get("x"), (int, float))
        and isinstance(recommended_window.get("y"), (int, float))
        and isinstance(recommended_window.get("z"), (int, float))
    ):
        drop_x = float(recommended_window["x"])
        drop_y = float(recommended_window["y"])
        drop_z = float(recommended_window["z"])
    elif (
        isinstance(target_y, (int, float))
        and isinstance(matched_building, dict)
        and all(
            isinstance(matched_building.get(k), (int, float))
            for k in ("min_x", "max_x", "min_z", "max_z", "height")
        )
    ):
        min_x = float(matched_building["min_x"])
        max_x = float(matched_building["max_x"])
        min_z = float(matched_building["min_z"])
        max_z = float(matched_building["max_z"])
        height = float(matched_building["height"])
        tx = float(target_x)
        tz = float(target_z)

        if tz >= max_z:
            drop_x = min(max(tx, min_x), max_x)
            drop_z = max_z
        elif tz <= min_z:
            drop_x = min(max(tx, min_x), max_x)
            drop_z = min_z
        elif tx >= max_x:
            drop_x = max_x
            drop_z = min(max(tz, min_z), max_z)
        elif tx <= min_x:
            drop_x = min_x
            drop_z = min(max(tz, min_z), max_z)
        else:
            drop_x = tx
            drop_z = tz
        drop_y = max(height + 2.5, float(target_y) + 2.0, 10.0)
    elif isinstance(target_y, (int, float)):
        drop_x = float(target_x)
        drop_y = max(float(target_y) + 2.0, 5.0)
        drop_z = float(target_z)
    else:
        target_height = float(building.get("height", 0.0) or 0.0)
        drop_x = float(target_x)
        drop_y = max(target_height + 5.0, 10.0)
        drop_z = float(target_z)

    to_base = await return_to_base_fn(asset_id)
    if "error" in to_base:
        return {
            "asset_id": asset_id,
            "error": f"Failed to return to base before supply dispatch: {to_base['error']}",
            "building": building,
            "return_result": to_base,
        }

    route = await plan_route_fn(
        asset_id=asset_id,
        target_x=drop_x,
        target_z=drop_z,
        target_y=drop_y,
        snap_to_building_center=False,
    )
    if "error" in route:
        retry_route = await plan_route_fn(
            asset_id=asset_id,
            target_x=drop_x,
            target_z=drop_z,
            target_y=max(drop_y + 5.0, 15.0),
            snap_to_building_center=False,
        )
        if "error" in retry_route:
            return {
                "asset_id": asset_id,
                "error": route["error"],
                "building": building,
                "route": route,
            }
        route = retry_route

    waypoints = route.get("waypoints", [])
    for index, waypoint in enumerate(waypoints, start=1):
        move_result = await move_drone_to_fn(
            asset_id=asset_id,
            x=float(waypoint["x"]),
            y=float(waypoint["y"]),
            z=float(waypoint["z"]),
        )
        if not move_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": move_result.get("message", "Failed while moving on supply route."),
                "building": building,
                "waypoint": waypoint,
                "move_result": move_result,
            }

        wait_result = await wait_until_waypoint_reached_fn(
            asset_id,
            float(waypoint["x"]),
            float(waypoint["y"]),
            float(waypoint["z"]),
            timeout_s=90.0,
            poll_s=0.2,
        )
        if not wait_result.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": wait_result.get("error", "Supply route waypoint not reached."),
                "building": building,
                "waypoint": waypoint,
                "failed_waypoint_index": index,
                "status": wait_result.get("status"),
            }

    final_status = await get_status_fn(asset_id)
    return {
        "success": True,
        "asset_id": asset_id,
        "building": building,
        "drop_point": route.get("to"),
        "waypoint_count": len(waypoints),
        "message": (
            f"SUPPLY SENT - {asset_id} delivered to building "
            f"at (x={float(target_x):.1f}, z={float(target_z):.1f})."
        ),
        "target_type": "survivor" if isinstance(target_y, (int, float)) else "building",
        "matched_building": matched_building,
        "final_status": final_status,
    }


async def parallel_fleet_supply(
    assignments: list[dict],
    *,
    dispatch_supply_to_building_fn: Callable[[str, dict], Awaitable[dict]],
    unassigned_buildings: list[dict] | None = None,
    unassigned_targets: list[dict] | None = None,
) -> dict:
    if not assignments:
        return {"error": "No assignments provided.", "results": [], "total_supplied": 0}

    async def _dispatch_one(asset_id: str, target: dict) -> dict:
        result = await dispatch_supply_to_building_fn(asset_id, target)
        return {"asset_id": asset_id, "target": target, "supply_result": result}

    rows = []
    for assignment in assignments:
        target = assignment.get("target", assignment.get("survivor", assignment.get("building")))
        if isinstance(target, dict):
            rows.append({"asset_id": assignment["asset_id"], "target": target})

    batch = await asyncio.gather(
        *[_dispatch_one(row["asset_id"], row["target"]) for row in rows],
        return_exceptions=True,
    )

    all_results: list[dict] = []
    for i, result in enumerate(batch):
        if isinstance(result, Exception):
            all_results.append(
                {
                    "asset_id": assignments[i]["asset_id"],
                    "target": rows[i]["target"],
                    "supply_result": {"error": str(result)},
                }
            )
        else:
            all_results.append(result)

    pending_targets = (
        list(unassigned_targets)
        if unassigned_targets is not None
        else list(unassigned_buildings or [])
    )
    if pending_targets:
        fallback_aid = assignments[0]["asset_id"]
        for target in pending_targets:
            result = await dispatch_supply_to_building_fn(fallback_aid, target)
            all_results.append(
                {
                    "asset_id": fallback_aid,
                    "target": target,
                    "supply_result": result,
                }
            )

    total_supplied = 0
    target_summaries: list[str] = []
    for result in all_results:
        supply = result["supply_result"]
        target = result["target"]
        if "error" in supply:
            target_summaries.append(
                f"Target at (x={target['x']}, z={target['z']}) [{result['asset_id']}]: "
                f"SUPPLY ERROR - {supply['error']}"
            )
            continue
        total_supplied += 1
        target_summaries.append(
            f"Target at (x={target['x']:.1f}, z={target['z']:.1f}) [{result['asset_id']}]: "
            f"SUPPLY SENT. Waypoints: {supply.get('waypoint_count', '?')}."
        )

    total_targets = len(all_results)
    divider = "=" * 39
    thin_divider = "-" * 39
    total_line = (
        "No supplies dispatched."
        if total_supplied == 0
        else f"TOTAL SUPPLY DISPATCHED: {total_supplied}"
    )
    summary = (
        f"{divider}\n"
        f"  AREA SUPPLY DISPATCH COMPLETE - {total_targets} target(s)\n"
        f"{divider}\n"
        + "\n".join(target_summaries)
        + f"\n{thin_divider}\n{total_line}\n{divider}"
    )

    return {
        "success": True,
        "results": all_results,
        "total_buildings_targeted": total_targets,
        "total_supplied": total_supplied,
        "summary": summary,
    }
