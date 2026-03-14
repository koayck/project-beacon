"""Unit tests for full-height-above-water building sweep scanning."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import backend.tools.drone_commands as drone_commands
from backend.world.model import FLOOD_LEVEL


@pytest.fixture(autouse=True)
def _mock_client():
    mock = AsyncMock()
    mock.get_status.return_value = {
        "asset_id": "BEACON-01",
        "x": -15.0,
        "y": 17.0,
        "z": -20.0,
        "battery": 88.0,
        "status": "IDLE",
    }
    mock.move_to.return_value = {"success": True, "message": "Moving"}
    mock.scan_area.return_value = {"success": True, "message": "Scanning"}
    mock.get_view.return_value = {
        "asset_id": "BEACON-01",
        "survivors_in_range": 1,
        "summary": "agl=10.0m terrain=airspace",
    }
    drone_commands.set_client(mock)
    yield mock
    drone_commands.set_client(None)  # type: ignore[arg-type]


class TestVerticalSweepPlan:
    def test_plan_building_vertical_sweep_covers_above_water_height(self):
        result = drone_commands.plan_building_vertical_sweep(-18.0, -22.0, level_step=3.0, standoff=2.0)
        assert result["matched_building"] is True
        assert result["building"]["center_x"] == -15.0
        assert result["building"]["center_z"] == -20.0
        assert result["building"]["min_x"] == -19.0
        assert result["building"]["max_x"] == -11.0
        assert all(level > FLOOD_LEVEL for level in result["levels"])
        assert result["levels"][-1] == 12.0
        assert result["waypoint_count"] == len(result["levels"]) * 5

    def test_plan_building_vertical_sweep_returns_error_without_building(self):
        result = drone_commands.plan_building_vertical_sweep(200.0, 200.0)
        assert result["matched_building"] is False
        assert result["error"] == "No nearby building for sweep scan"


class TestVerticalSweepExecution:
    @pytest.mark.asyncio
    async def test_sweep_scan_building_executes_route_and_scan_per_waypoint(self, _mock_client, monkeypatch):
        plan = {
            "matched_building": True,
            "building": {
                "id": 0,
                "min_x": -19.0,
                "max_x": -11.0,
                "min_z": -24.0,
                "max_z": -16.0,
                "center_x": -15.0,
                "center_z": -20.0,
                "height": 12.0,
            },
            "flood_level": 1.4,
            "levels": [2.0],
            "level_count": 1,
            "waypoints": [
                {"x": -21.0, "y": 2.0, "z": -26.0, "level_y": 2.0, "reason": "NW"},
                {"x": -9.0, "y": 2.0, "z": -26.0, "level_y": 2.0, "reason": "NE"},
            ],
            "waypoint_count": 2,
            "summary": "2-waypoint test sweep",
        }

        monkeypatch.setattr(drone_commands, "plan_building_vertical_sweep", lambda *_a, **_k: plan)

        async def _route_ok(*_args, **kwargs):
            return {
                "asset_id": kwargs["asset_id"],
                "waypoints": [
                    {
                        "x": kwargs["target_x"],
                        "y": kwargs["target_y"],
                        "z": kwargs["target_z"],
                        "reason": "direct path clear",
                    }
                ],
            }

        monkeypatch.setattr(drone_commands, "plan_route", _route_ok)
        wait_mock = AsyncMock(return_value={"ok": True, "status": {"status": "IDLE"}})
        monkeypatch.setattr(drone_commands, "_wait_until_waypoint_reached", wait_mock)

        result = await drone_commands.sweep_scan_building("BEACON-01", -15.0, -20.0)
        assert result["success"] is True
        assert result["strategy"] == "vertical_building_sweep"
        assert result["waypoint_count"] == 2
        assert _mock_client.move_to.await_count == 2
        assert _mock_client.scan_area.await_count == 2
        assert wait_mock.await_count == 4

    @pytest.mark.asyncio
    async def test_sweep_scan_building_surfaces_route_blocking_error(self, monkeypatch):
        plan = {
            "matched_building": True,
            "building": {"id": 0, "min_x": -19.0, "max_x": -11.0, "min_z": -24.0, "max_z": -16.0},
            "flood_level": 1.4,
            "levels": [2.0],
            "level_count": 1,
            "waypoints": [{"x": -21.0, "y": 2.0, "z": -26.0, "level_y": 2.0, "reason": "NW"}],
            "waypoint_count": 1,
            "summary": "1-waypoint test sweep",
        }

        monkeypatch.setattr(drone_commands, "plan_building_vertical_sweep", lambda *_a, **_k: plan)

        async def _route_err(*_args, **_kwargs):
            return {"asset_id": "BEACON-01", "error": "No clear route found", "obstacles": [{"id": 1}]}

        monkeypatch.setattr(drone_commands, "plan_route", _route_err)

        result = await drone_commands.sweep_scan_building("BEACON-01", -15.0, -20.0)
        assert result["error"] == "Sweep route blocked"
        assert result["route_error"] == "No clear route found"
