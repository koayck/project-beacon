from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from backend.services.core import context as service_context
from backend.services.supply_stations import select_best_station


_SUPPLY_DISPATCH_GUARD_LOCK = asyncio.Lock()
_SUPPLY_DISPATCH_INFLIGHT_KEYS: set[str] = set()


def _as_dict(value: object) -> dict | None:
    try:
        value.get  # type: ignore[attr-defined]
    except AttributeError:
        return None
    return value  # type: ignore[return-value]


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _supply_target_key(target: dict) -> str:
    target_dict = _as_dict(target)
    sid = target_dict.get("id") if target_dict is not None else None
    sid_int = _to_int(sid)
    sid_float = _to_float(sid)
    if sid_int is not None and sid_float is not None and sid_float.is_integer():
        return f"id:{sid_int}"
    try:
        normalized = sid.strip()
    except AttributeError:
        normalized = ""
    if normalized:
        if normalized.isdigit():
            return f"id:{int(normalized)}"
        return f"id:{normalized.lower()}"

    x = float(target_dict.get("x", 0.0) if target_dict is not None else 0.0)
    y_raw = target_dict.get("y") if target_dict is not None else None
    y = _to_float(y_raw)
    z = float(target_dict.get("z", 0.0) if target_dict is not None else 0.0)
    y_value = y if y is not None else 0.0
    return f"xyz:{x:.2f},{y_value:.2f},{z:.2f}"


async def _go_to_station(
    *,
    asset_id: str,
    station: dict,
    plan_route_fn: Callable[..., Awaitable[dict]],
    move_drone_to_fn: Callable[..., Awaitable[dict]],
    wait_until_waypoint_reached_fn: Callable[..., Awaitable[dict]],
) -> dict:
    """Route the drone to a supply station's (x, z) at pickup altitude.

    Uses the same move-and-wait pattern as the delivery leg, with a single
    high-altitude retry on initial route failure.
    """
    pickup_y = 2.0  # Matches the home-pad landing altitude used by return_workflow.

    route = await plan_route_fn(
        asset_id=asset_id,
        target_x=float(station["x"]),
        target_z=float(station["z"]),
        target_y=pickup_y,
        snap_to_building_center=False,
    )
    if "error" in route:
        retry_route = await plan_route_fn(
            asset_id=asset_id,
            target_x=float(station["x"]),
            target_z=float(station["z"]),
            target_y=max(pickup_y + 5.0, 15.0),
            snap_to_building_center=False,
        )
        if "error" in retry_route:
            return {
                "error": route["error"],
                "pickup_station": station,
                "route": route,
            }
        route = retry_route

    for index, waypoint in enumerate(route.get("waypoints", []), start=1):
        move_result = await move_drone_to_fn(
            asset_id=asset_id,
            x=float(waypoint["x"]),
            y=float(waypoint["y"]),
            z=float(waypoint["z"]),
        )
        if not move_result.get("success", True):
            return {
                "error": move_result.get("message", "Failed while moving on pickup route."),
                "pickup_station": station,
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
                "error": wait_result.get("error", "Pickup waypoint not reached."),
                "pickup_station": station,
                "waypoint": waypoint,
                "failed_waypoint_index": index,
                "status": wait_result.get("status"),
            }

    return {"success": True, "pickup_station": station}


async def dispatch_supply_to_building(
    asset_id: str,
    building: dict,
    *,
    resolve_scan_target: Callable[[float, float], dict],
    world: object,
    window_scan_standoff_m: float,
    select_window_waypoint: Callable[..., dict | None],
    plan_route_fn: Callable[..., Awaitable[dict]],
    move_drone_to_fn: Callable[..., Awaitable[dict]],
    wait_until_waypoint_reached_fn: Callable[..., Awaitable[dict]],
    get_status_fn: Callable[[str], Awaitable[dict]],
) -> dict:
    """Dispatch a supply payload to `building` via the nearest supply station.

    Pickup routing goes through the station registry via `_go_to_station`;
    there is no longer an unconditional return to (0,0,0) before dispatch.
    """
    target_key = _supply_target_key(building)
    async with _SUPPLY_DISPATCH_GUARD_LOCK:
        supplied_keys = service_context.get_supplied_target_keys()
        if target_key in supplied_keys or target_key in _SUPPLY_DISPATCH_INFLIGHT_KEYS:
            return {
                "success": True,
                "skipped": True,
                "asset_id": asset_id,
                "building": building,
                "target_key": target_key,
                "message": "Supply already delivered to this target. Skipping duplicate dispatch.",
            }
        _SUPPLY_DISPATCH_INFLIGHT_KEYS.add(target_key)

    try:
        target_x = building.get("x")
        target_y = building.get("y")
        target_z = building.get("z")
        target_x_f = _to_float(target_x)
        target_z_f = _to_float(target_z)
        if target_x_f is None or target_z_f is None:
            return {
                "asset_id": asset_id,
                "error": "Invalid supply target coordinates.",
                "building": building,
            }

        resolved = resolve_scan_target(target_x_f, target_z_f)
        resolved_dict = _as_dict(resolved)
        matched_building = resolved_dict.get("building") if resolved_dict is not None else None
        recommended_window = (
            resolved_dict.get("recommended_window_waypoint")
            if resolved_dict is not None
            else None
        )
        interior_target = False
        window_drop_for_survivor: dict | None = None
        target_y_f = _to_float(target_y)
        if target_y_f is not None:
            host_building = world.building_at(target_x_f, target_y_f, target_z_f)
            interior_target = host_building is not None
            if host_building is not None:
                candidate_windows = host_building.window_scan_waypoints(standoff=window_scan_standoff_m)
                if candidate_windows:
                    window_drop_for_survivor = select_window_waypoint(
                        candidate_windows,
                        ref_x=target_x_f,
                        ref_z=target_z_f,
                        preferred_y=target_y_f,
                    )

        window_drop_dict = _as_dict(window_drop_for_survivor)
        recommended_window_dict = _as_dict(recommended_window)
        matched_building_dict = _as_dict(matched_building)
        window_x = _to_float(window_drop_dict.get("x")) if window_drop_dict is not None else None
        window_y = _to_float(window_drop_dict.get("y")) if window_drop_dict is not None else None
        window_z = _to_float(window_drop_dict.get("z")) if window_drop_dict is not None else None
        recommended_x = _to_float(recommended_window_dict.get("x")) if recommended_window_dict is not None else None
        recommended_y = _to_float(recommended_window_dict.get("y")) if recommended_window_dict is not None else None
        recommended_z = _to_float(recommended_window_dict.get("z")) if recommended_window_dict is not None else None

        if (
            interior_target
            and window_x is not None
            and window_y is not None
            and window_z is not None
        ):
            drop_x = window_x
            drop_y = window_y
            drop_z = window_z
        elif (
            interior_target
            and recommended_x is not None
            and recommended_y is not None
            and recommended_z is not None
        ):
            drop_x = recommended_x
            drop_y = recommended_y
            drop_z = recommended_z
        elif (
            target_y_f is not None
            and matched_building_dict is not None
        ):
            min_x = _to_float(matched_building_dict.get("min_x"))
            max_x = _to_float(matched_building_dict.get("max_x"))
            min_z = _to_float(matched_building_dict.get("min_z"))
            max_z = _to_float(matched_building_dict.get("max_z"))
            height = _to_float(matched_building_dict.get("height"))
            if None in (min_x, max_x, min_z, max_z, height):
                matched_building_dict = None
            else:
                tx = target_x_f
                tz = target_z_f

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
                drop_y = max(height + 2.5, target_y_f + 2.0, 10.0)
        elif target_y_f is not None:
            drop_x = target_x_f
            drop_y = max(target_y_f + 2.0, 5.0)
            drop_z = target_z_f
        else:
            target_height = float(building.get("height", 0.0) or 0.0)
            drop_x = target_x_f
            drop_y = max(target_height + 5.0, 10.0)
            drop_z = target_z_f

        station = select_best_station(target_x=drop_x, target_z=drop_z)
        pickup_result = await _go_to_station(
            asset_id=asset_id,
            station=station,
            plan_route_fn=plan_route_fn,
            move_drone_to_fn=move_drone_to_fn,
            wait_until_waypoint_reached_fn=wait_until_waypoint_reached_fn,
        )
        if "error" in pickup_result:
            return {
                "asset_id": asset_id,
                "error": f"Failed to reach supply station before dispatch: {pickup_result['error']}",
                "building": building,
                "pickup_station": station,
                "pickup_result": pickup_result,
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
                    "pickup_station": station,
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
                    "pickup_station": station,
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
                    "pickup_station": station,
                    "building": building,
                    "waypoint": waypoint,
                    "failed_waypoint_index": index,
                    "status": wait_result.get("status"),
                }

        final_status = await get_status_fn(asset_id)
        service_context.register_supplied_target(building)
        return {
            "success": True,
            "asset_id": asset_id,
            "building": building,
            "drop_point": route.get("to"),
            "waypoint_count": len(waypoints),
            "message": (
                f"SUPPLY SENT - {asset_id} delivered to building "
                f"at (x={target_x_f:.1f}, z={target_z_f:.1f})."
            ),
            "target_type": "survivor" if target_y_f is not None else "building",
            "matched_building": matched_building,
            "target_key": target_key,
            "final_status": final_status,
            "pickup_station": station,
        }
    finally:
        async with _SUPPLY_DISPATCH_GUARD_LOCK:
            _SUPPLY_DISPATCH_INFLIGHT_KEYS.discard(target_key)


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
        target_dict = _as_dict(target)
        if target_dict is not None:
            rows.append({"asset_id": assignment["asset_id"], "target": target_dict})

    batch = await asyncio.gather(
        *[_dispatch_one(row["asset_id"], row["target"]) for row in rows],
        return_exceptions=True,
    )

    all_results: list[dict] = []
    for i, result in enumerate(batch):
        if isinstance(result, BaseException):
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

    _schedule_supply_mission_recall(assignments, all_results)

    return {
        "success": True,
        "results": all_results,
        "total_buildings_targeted": total_targets,
        "total_supplied": total_supplied,
        "summary": summary,
    }


def _schedule_supply_mission_recall(
    assignments: list[dict],
    all_results: list[dict],
) -> None:
    """Schedule return-to-base for every drone that executed a supply dispatch.

    Runs after the area-supply summary is built so the response time is not
    affected; the grace-then-recall coroutine inside mission_recall handles
    operator-chained follow-up commands.
    """
    seen: set[str] = set()
    asset_ids: list[str] = []
    for row in assignments:
        aid = row.get("asset_id")
        if isinstance(aid, str) and aid and aid not in seen:
            seen.add(aid)
            asset_ids.append(aid)
    for row in all_results:
        aid = row.get("asset_id")
        if isinstance(aid, str) and aid and aid not in seen:
            seen.add(aid)
            asset_ids.append(aid)
    if not asset_ids:
        return

    try:
        from backend.runtime import grpc_client as runtime_grpc_client
        from backend.runtime import ws_broadcaster
        from backend.services.api import return_to_base
        from backend.services.mission_recall import schedule_mission_complete_recall
    except Exception:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger(__name__).exception(
            "Failed to import mission_recall dependencies; skipping post-supply recall",
        )
        return

    schedule_mission_complete_recall(
        asset_ids,
        get_status=runtime_grpc_client.get_status,
        return_to_base_fn=return_to_base,
        publish_event=ws_broadcaster.broadcast,
        trigger_reason="supply_mission_complete",
    )
