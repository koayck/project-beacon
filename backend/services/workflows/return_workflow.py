from __future__ import annotations

from typing import Awaitable, Callable

async def return_to_base(
    asset_id: str,
    *,
    plan_route_fn: Callable[..., Awaitable[dict]],
    move_to: Callable[[str, float, float, float, float], Awaitable[dict]],
    get_status: Callable[[str], Awaitable[dict]],
    get_speed: Callable[[str], float],
    wait_until_waypoint_reached: Callable[..., Awaitable[dict]],
) -> dict:
    """
    Return a drone to home with obstacle-aware routing.

    Plans a safe route to home approach, executes each waypoint with status
    polling, then performs a final explicit landing leg to (0,0,0).
    """
    route = await plan_route_fn(asset_id, 0.0, 2.0, 5.0)
    if "error" in route:
        return {
            "asset_id": asset_id,
            "error": "Return route blocked",
            "route_error": route["error"],
            "obstacles": route.get("obstacles", []),
        }

    waypoints = route.get("waypoints", [])
    for wp in waypoints:
        move_result = await move_to(
            asset_id,
            wp["x"],
            wp["y"],
            wp["z"],
            get_speed(asset_id),
        )
        if not move_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Failed while executing return route waypoint",
                "waypoint": wp,
                "move_result": move_result,
            }

        wait_result = await wait_until_waypoint_reached(asset_id, wp["x"], wp["y"], wp["z"])
        if not wait_result.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": wait_result.get("error", "Return route waypoint not reached"),
                "waypoint": wp,
                "status": wait_result.get("status"),
            }

    final_wp = {"x": 0.0, "y": 2.0, "z": 0.0, "reason": "final landing at home pad"}
    final_move_result = await move_to(
        asset_id,
        final_wp["x"],
        final_wp["y"],
        final_wp["z"],
        get_speed(asset_id),
    )
    if not final_move_result.get("success", True):
        return {
            "asset_id": asset_id,
            "error": "Failed while executing final home landing leg",
            "waypoint": final_wp,
            "move_result": final_move_result,
        }

    final_wait = await wait_until_waypoint_reached(
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

    final_status = await get_status(asset_id)
    return {
        "success": True,
        "message": "Returned to base",
        "asset_id": asset_id,
        "strategy": "routed_return",
        "waypoint_count": len(waypoints) + 1,
        "route_summary": route.get("summary"),
        "final_status": final_status,
    }
