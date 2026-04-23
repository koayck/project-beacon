"""Tests that dispatch_supply_to_building uses the nearest station for pickup."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from backend.services import supply_stations
from backend.services.workflows.supply_workflow import dispatch_supply_to_building


@pytest.fixture(autouse=True)
def _reset_registry():
    supply_stations.reset()
    yield
    supply_stations.reset()


def _make_world():
    world = MagicMock()
    world.building_at.return_value = None
    return world


def _make_async_kwargs(routes: list[dict] | None = None):
    """Shared kwargs for dispatch_supply_to_building in these tests."""
    # Return a successful 1-waypoint route for every plan_route_fn call.
    # The test inspects which target coordinates each call received.
    plan_route_calls: list[dict] = []

    async def _plan_route_fn(*, asset_id, target_x, target_z, target_y=None, snap_to_building_center=True):
        plan_route_calls.append(
            {"asset_id": asset_id, "target_x": target_x, "target_y": target_y, "target_z": target_z}
        )
        return {
            "waypoints": [{"x": float(target_x), "y": float(target_y or 5.0), "z": float(target_z)}],
            "to": {"x": float(target_x), "y": float(target_y or 5.0), "z": float(target_z)},
        }

    async def _move(*, asset_id, x, y, z):
        return {"success": True}

    async def _wait(*_args, **_kwargs):
        return {"ok": True}

    async def _status(_aid):
        return {"x": 0.0, "y": 2.0, "z": 0.0, "battery": 80.0, "status": "IDLE"}

    return {
        "plan_route_fn": _plan_route_fn,
        "move_drone_to_fn": _move,
        "wait_until_waypoint_reached_fn": _wait,
        "get_status_fn": _status,
        "plan_route_calls": plan_route_calls,
    }


@pytest.mark.asyncio
async def test_dispatch_errors_when_no_user_stations():
    """With home no longer a fallback, dispatch must refuse until the operator
    places at least one supply station."""
    kwargs = _make_async_kwargs()

    result = await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 1, "x": 20.0, "z": 20.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        plan_route_fn=kwargs["plan_route_fn"],
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    assert "error" in result
    assert "No supply stations placed" in result["error"]
    # No route was planned because dispatch short-circuited before pickup.
    assert kwargs["plan_route_calls"] == []


@pytest.mark.asyncio
async def test_pickup_uses_nearest_user_station():
    supply_stations.add_station(x=18.0, z=18.0)
    kwargs = _make_async_kwargs()

    result = await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 2, "x": 20.0, "z": 20.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        plan_route_fn=kwargs["plan_route_fn"],
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    assert result.get("success") is True
    pickup_call = kwargs["plan_route_calls"][0]
    assert pickup_call["target_x"] == 18.0
    assert pickup_call["target_z"] == 18.0


@pytest.mark.asyncio
async def test_station_captured_at_dispatch_start_persists_across_waypoints():
    """Each waypoint on the pickup leg references the station captured at
    dispatch start, not re-queried from the registry. A mid-flight removal
    between waypoints must not redirect later moves.
    """
    station = supply_stations.add_station(x=18.0, z=18.0)

    # Build a multi-waypoint route so there's a window between moves for removal.
    async def _plan_route_fn(*, asset_id, target_x, target_z, target_y=None, snap_to_building_center=True):
        return {
            "waypoints": [
                {"x": float(target_x) - 3.0, "y": 5.0, "z": float(target_z) - 3.0},
                {"x": float(target_x),        "y": 5.0, "z": float(target_z)       },
            ],
            "to": {"x": float(target_x), "y": 5.0, "z": float(target_z)},
        }

    moves: list[dict] = []
    removed = False

    async def _move(*, asset_id, x, y, z):
        nonlocal removed
        moves.append({"x": x, "y": y, "z": z})
        # Remove the station after the first move so later moves must still
        # reference the captured station's coords.
        if not removed:
            supply_stations.remove_station(station["id"])
            removed = True
        return {"success": True}

    async def _wait(*_args, **_kwargs):
        return {"ok": True}

    async def _status(_aid):
        return {"x": 0.0, "y": 2.0, "z": 0.0, "battery": 80.0, "status": "IDLE"}

    result = await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 5, "x": 20.0, "z": 20.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        plan_route_fn=_plan_route_fn,
        move_drone_to_fn=_move,
        wait_until_waypoint_reached_fn=_wait,
        get_status_fn=_status,
    )

    assert result.get("success") is True
    # The pickup leg should have made 2 moves: (15, 15) then (18, 18).
    # Removal happened after the first move. The second move must still use
    # the captured station's coords (18, 18) even though the registry is now empty.
    assert len(moves) >= 2, f"expected at least 2 moves, got {len(moves)}"
    # First two moves are the pickup leg (to (15,15) then (18,18))
    assert moves[0]["x"] == 15.0 and moves[0]["z"] == 15.0, "first pickup move should go to (15,15)"
    assert moves[1]["x"] == 18.0 and moves[1]["z"] == 18.0, "second pickup move should go to (18,18) even after removal"


@pytest.mark.asyncio
async def test_single_far_station_is_still_chosen():
    """With home out of the pool, a lone station wins even if far from target."""
    supply_stations.add_station(x=45.0, z=45.0)
    kwargs = _make_async_kwargs()

    await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 3, "x": 2.0, "z": 2.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        plan_route_fn=kwargs["plan_route_fn"],
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    pickup_call = kwargs["plan_route_calls"][0]
    assert pickup_call["target_x"] == 45.0
    assert pickup_call["target_z"] == 45.0
