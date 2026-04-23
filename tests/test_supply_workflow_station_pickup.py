"""Tests that dispatch_supply_to_building uses the nearest station for pickup."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

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
async def test_pickup_uses_home_when_no_user_stations():
    kwargs = _make_async_kwargs()
    return_to_base_fn = AsyncMock(return_value={"success": True})

    result = await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 1, "x": 20.0, "z": 20.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        return_to_base_fn=return_to_base_fn,
        plan_route_fn=kwargs["plan_route_fn"],
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    assert result.get("success") is True
    # First plan_route_fn call is the pickup leg, targeting home (0,0).
    pickup_call = kwargs["plan_route_calls"][0]
    assert pickup_call["target_x"] == 0.0
    assert pickup_call["target_z"] == 0.0
    # return_to_base_fn is NOT invoked — pickup now goes through the station planner.
    return_to_base_fn.assert_not_called()


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
        return_to_base_fn=AsyncMock(return_value={"success": True}),
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
async def test_in_flight_dispatch_uses_captured_station_even_after_removal():
    """Station removed mid-flight does not affect an in-flight dispatch."""
    added = supply_stations.add_station(x=18.0, z=18.0)
    kwargs = _make_async_kwargs()

    # Remove the station BEFORE dispatch completes by simulating a removal
    # after select_best_station has captured it. We achieve this by wrapping
    # plan_route_fn so the first call triggers the removal synchronously.
    removal_triggered = False

    async def _plan_route_with_side_effect(**call_kwargs):
        nonlocal removal_triggered
        if not removal_triggered:
            supply_stations.remove_station(added["id"])
            removal_triggered = True
        return await kwargs["plan_route_fn"](**call_kwargs)

    result = await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 4, "x": 20.0, "z": 20.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        return_to_base_fn=AsyncMock(return_value={"success": True}),
        plan_route_fn=_plan_route_with_side_effect,
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    assert result.get("success") is True
    # First call still uses the captured station coords, not home.
    pickup_call = kwargs["plan_route_calls"][0]
    assert pickup_call["target_x"] == 18.0
    assert pickup_call["target_z"] == 18.0


@pytest.mark.asyncio
async def test_pickup_ignores_far_station_when_home_is_closer():
    supply_stations.add_station(x=45.0, z=45.0)
    kwargs = _make_async_kwargs()

    await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 3, "x": 2.0, "z": 2.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        return_to_base_fn=AsyncMock(return_value={"success": True}),
        plan_route_fn=kwargs["plan_route_fn"],
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    pickup_call = kwargs["plan_route_calls"][0]
    assert pickup_call["target_x"] == 0.0
    assert pickup_call["target_z"] == 0.0
