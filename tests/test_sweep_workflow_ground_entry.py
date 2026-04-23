"""Integration-style unit tests for sweep_workflow ground-entry plumbing."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.workflows.sweep_workflow import sweep_scan_building


def _make_sweep_plan_stub() -> MagicMock:
    stub = MagicMock()
    stub.return_value = {
        "matched_building": True,
        "building": {
            "id": 0, "min_x": -19.0, "max_x": -11.0,
            "min_z": -24.0, "max_z": -16.0,
            "center_x": -15.0, "center_z": -20.0, "height": 12.0,
        },
        "flood_level": 1.4,
        "levels": [],
        "level_count": 0,
        "waypoints": [],
        "waypoint_count": 0,
        "rooftop_position": {"x": -15.0, "y": 14.0, "z": -20.0},
        "summary": "",
    }
    return stub


@pytest.mark.asyncio
async def test_sweep_workflow_requests_ground_entry_mode():
    """plan_route must be invoked with entry_mode='ground_entry' and
    snap_to_building_center=True."""
    plan_route_fn = AsyncMock()
    plan_route_fn.return_value = {
        "asset_id": "BEACON-01",
        "from": {"x": 0.0, "y": 15.0, "z": 0.0},
        "to": {"x": -11.0, "y": 4.2, "z": -20.0},
        "waypoints": [
            {"x": -11.0, "y": 4.2, "z": -20.0, "reason": "arrive at target"},
        ],
        "strategy": "direct",
        "summary": "",
        "target_resolution": {
            "building_id": 0,
            "input": {"x": -15.0, "z": -20.0},
            "resolved": {"x": -11.0, "z": -20.0},
            "center": {"x": -15.0, "z": -20.0},
            "bounds": {"min_x": -19.0, "max_x": -11.0, "min_z": -24.0, "max_z": -16.0},
            "selected_window_waypoint": {
                "x": -11.0, "y": 4.2, "z": -20.0, "face": "east", "floor": 2,
            },
            "entry_mode": "ground_entry",
        },
    }

    plan_building_vertical_sweep = _make_sweep_plan_stub()

    get_status = AsyncMock()
    get_status.return_value = {
        "asset_id": "BEACON-01", "x": 0.0, "y": 15.0, "z": 0.0,
        "battery": 80, "status": "IDLE",
    }

    await sweep_scan_building(
        "BEACON-01",
        target_x=-15.0, target_z=-20.0,
        scan_radius=8.0, level_step=3.0, standoff=2.0,
        floor_height_m=3.0, thermal_horiz_fov_half_deg=22.5,
        plan_route_fn=plan_route_fn,
        plan_building_vertical_sweep=plan_building_vertical_sweep,
        wait_until_waypoint_reached=AsyncMock(return_value={"reached": True}),
        get_status=get_status,
        move_to=AsyncMock(return_value={"success": True}),
        scan_area=AsyncMock(return_value={"success": True}),
        get_view=AsyncMock(return_value={"objects": []}),
        end_scan=None,
        get_speed=lambda _: 5.0,
        register_detected_survivors=lambda _: 0,
        build_sweep_scan_report=lambda **_: "",
    )

    found = False
    for call in plan_route_fn.call_args_list:
        kwargs = call.kwargs
        if kwargs.get("entry_mode") == "ground_entry" and kwargs.get("snap_to_building_center") is True:
            found = True
            break
    assert found, (
        f"expected plan_route call with entry_mode='ground_entry'; "
        f"calls={plan_route_fn.call_args_list}"
    )


@pytest.mark.asyncio
async def test_sweep_workflow_does_not_pass_entry_floor_to_sweep_plan():
    """plan_building_vertical_sweep must be called without an entry_floor kwarg."""
    plan_route_fn = AsyncMock()
    plan_route_fn.return_value = {
        "asset_id": "BEACON-01",
        "from": {"x": 0.0, "y": 10.0, "z": 0.0},
        "to": {"x": -15.0, "y": 4.2, "z": -20.0},
        "waypoints": [{"x": -15.0, "y": 4.2, "z": -20.0, "reason": "x"}],
        "strategy": "direct",
        "summary": "",
    }

    plan_building_vertical_sweep = _make_sweep_plan_stub()

    get_status = AsyncMock()
    get_status.return_value = {
        "asset_id": "BEACON-01", "x": 0.0, "y": 10.0, "z": 0.0,
        "battery": 80, "status": "IDLE",
    }

    await sweep_scan_building(
        "BEACON-01",
        target_x=-15.0, target_z=-20.0,
        scan_radius=8.0, level_step=3.0, standoff=2.0,
        floor_height_m=3.0, thermal_horiz_fov_half_deg=22.5,
        plan_route_fn=plan_route_fn,
        plan_building_vertical_sweep=plan_building_vertical_sweep,
        wait_until_waypoint_reached=AsyncMock(return_value={"reached": True}),
        get_status=get_status,
        move_to=AsyncMock(return_value={"success": True}),
        scan_area=AsyncMock(return_value={"success": True}),
        get_view=AsyncMock(return_value={"objects": []}),
        end_scan=None,
        get_speed=lambda _: 5.0,
        register_detected_survivors=lambda _: 0,
        build_sweep_scan_report=lambda **_: "",
    )

    sweep_kwargs = plan_building_vertical_sweep.call_args.kwargs
    assert "entry_floor" not in sweep_kwargs, (
        f"entry_floor should no longer be forwarded; got kwargs={sweep_kwargs}"
    )
