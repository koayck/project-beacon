from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.services.workflows.sweep_workflow import sweep_scan_building


@pytest.mark.asyncio
async def test_rooftop_recovery_replan_excludes_target_building() -> None:
    preplan = {
        "matched_building": True,
        "building": {
            "id": 1,
            "min_x": 22.5,
            "max_x": 37.5,
            "min_z": -31.0,
            "max_z": -19.0,
            "center_x": 30.0,
            "center_z": -25.0,
            "height": 24.0,
        },
        "flood_level": 1.4,
        "levels": [5.0],
        "level_count": 1,
        "rooftop_position": {"x": 30.0, "y": 29.0, "z": -25.0},
        "waypoints": [{"x": 22.5, "y": 5.0, "z": -31.0, "reason": "perimeter NW"}],
        "waypoint_count": 1,
    }

    def _plan_building_vertical_sweep(*, approach_x: float | None = None, **_kwargs: object) -> dict:
        if approach_x is None:
            return preplan
        # Keep the second planning stage minimal so the test isolates rooftop recovery wiring.
        return {
            **preplan,
            "waypoints": [],
            "waypoint_count": 0,
        }

    async def _plan_route_fn(**kwargs: object) -> dict:
        return {
            "asset_id": kwargs["asset_id"],
            "waypoints": [
                {
                    "x": kwargs["target_x"],
                    "y": kwargs.get("target_y", 10.0),
                    "z": kwargs["target_z"],
                    "reason": "direct path clear",
                }
            ],
        }

    wait_mock = AsyncMock(return_value={"ok": True, "status": {"status": "IDLE"}})
    get_status_mock = AsyncMock(
        side_effect=[
            {"asset_id": "BEACON-01", "x": 0.0, "y": 10.0, "z": 0.0, "battery": 91.0, "status": "IDLE"},
            {"asset_id": "BEACON-01", "x": 0.0, "y": 10.0, "z": 0.0, "battery": 91.0, "status": "IDLE"},
            {"asset_id": "BEACON-01", "x": 30.0, "y": 29.0, "z": -25.0, "battery": 89.0, "status": "IDLE"},
        ]
    )

    result = await sweep_scan_building(
        "BEACON-01",
        target_x=30.0,
        target_z=-25.0,
        scan_radius=8.0,
        level_step=3.0,
        standoff=2.0,
        floor_height_m=3.0,
        thermal_horiz_fov_half_deg=60.0,
        plan_route_fn=_plan_route_fn,
        plan_building_vertical_sweep=_plan_building_vertical_sweep,
        wait_until_waypoint_reached=wait_mock,
        get_status=get_status_mock,
        move_to=AsyncMock(return_value={"success": True}),
        scan_area=AsyncMock(return_value={"success": True}),
        get_view=AsyncMock(return_value={"summary": "", "objects": []}),
        end_scan=None,
        get_speed=lambda _asset_id: 5.0,
        register_detected_survivors=lambda _rows: 0,
        build_sweep_scan_report=lambda **_kwargs: "ok",
    )

    assert result["success"] is True
    assert wait_mock.await_count >= 1
    assert wait_mock.await_args_list[0].kwargs.get("exclude_building_id") == 1


@pytest.mark.asyncio
async def test_sweep_error_text_uses_scan_route_context() -> None:
    preplan = {
        "matched_building": True,
        "building": {
            "id": 1,
            "min_x": 22.5,
            "max_x": 37.5,
            "min_z": -31.0,
            "max_z": -19.0,
            "center_x": 30.0,
            "center_z": -25.0,
            "height": 24.0,
        },
        "flood_level": 1.4,
        "levels": [5.0],
        "level_count": 1,
        "rooftop_position": {"x": 30.0, "y": 29.0, "z": -25.0},
        "waypoints": [],
        "waypoint_count": 0,
    }

    async def _plan_route_fn(**kwargs: object) -> dict:
        return {
            "asset_id": kwargs["asset_id"],
            "waypoints": [
                {
                    "x": kwargs["target_x"],
                    "y": kwargs.get("target_y", 10.0),
                    "z": kwargs["target_z"],
                    "reason": "direct path clear",
                }
            ],
        }

    result = await sweep_scan_building(
        "BEACON-01",
        target_x=30.0,
        target_z=-25.0,
        scan_radius=8.0,
        level_step=3.0,
        standoff=2.0,
        floor_height_m=3.0,
        thermal_horiz_fov_half_deg=60.0,
        plan_route_fn=_plan_route_fn,
        plan_building_vertical_sweep=lambda **_kwargs: preplan,
        wait_until_waypoint_reached=AsyncMock(
            return_value={
                "ok": False,
                "error": "Drone blocked while following return route",
                "status": {"status": "BLOCKED"},
            }
        ),
        get_status=AsyncMock(return_value={"asset_id": "BEACON-01", "x": 0.0, "y": 10.0, "z": 0.0, "battery": 91.0, "status": "IDLE"}),
        move_to=AsyncMock(return_value={"success": True}),
        scan_area=AsyncMock(return_value={"success": True}),
        get_view=AsyncMock(return_value={"summary": "", "objects": []}),
        end_scan=None,
        get_speed=lambda _asset_id: 5.0,
        register_detected_survivors=lambda _rows: 0,
        build_sweep_scan_report=lambda **_kwargs: "ok",
    )

    assert result["error"] == "Drone blocked while following scan route"
