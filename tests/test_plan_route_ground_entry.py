"""Unit tests for plan_route entry_mode='ground_entry'."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.tools.drone_commands import plan_route, set_client


@pytest.fixture(autouse=True)
def _mock_client():
    mock = AsyncMock()
    mock.get_status.return_value = {
        "asset_id": "BEACON-01",
        "x": 0.0, "y": 15.0, "z": 0.0,
        "battery": 80, "status": "IDLE",
    }
    mock.registered_asset_ids.return_value = ["BEACON-01"]
    set_client(mock)
    yield mock
    set_client(None)  # type: ignore[arg-type]


class TestEntryModeGroundEntry:
    """With entry_mode='ground_entry', selection restricts to the lowest floor
    and ranks candidates by horizontal (XZ) distance from the drone."""

    @pytest.mark.asyncio
    async def test_ground_entry_picks_lowest_floor_even_when_drone_is_high(self, _mock_client):
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -5.0, "y": 11.0, "z": -13.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        assert "target_resolution" in result
        tr = result["target_resolution"]
        assert tr.get("entry_mode") == "ground_entry"
        assert "selected_window_waypoint" in tr
        wp = tr["selected_window_waypoint"]
        assert wp["floor"] == 2

    @pytest.mark.asyncio
    async def test_ground_entry_picks_window_nearest_by_xz(self, _mock_client):
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -15.0, "y": 20.0, "z": -10.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        wp = tr["selected_window_waypoint"]
        assert wp["floor"] == 2
        assert wp["face"] == "south"

    @pytest.mark.asyncio
    async def test_ground_entry_ignores_y_distance(self, _mock_client):
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -6.0, "y": 50.0, "z": -20.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        assert tr["selected_window_waypoint"]["floor"] == 2

    @pytest.mark.asyncio
    async def test_ground_entry_excludes_middle_floors(self, _mock_client):
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -15.0, "y": 6.0, "z": -30.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        assert tr["selected_window_waypoint"]["floor"] == 2

    @pytest.mark.asyncio
    async def test_default_mode_preserves_legacy_behavior(self, _mock_client):
        result_default = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
        )
        result_explicit = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="nearest_floor",
        )
        assert result_default["to"] == result_explicit["to"]
        assert result_default.get("strategy") == result_explicit.get("strategy")

    @pytest.mark.asyncio
    async def test_ground_entry_falls_back_when_no_snap(self, _mock_client):
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=False,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        assert "selected_window_waypoint" not in tr

    @pytest.mark.asyncio
    async def test_ground_entry_records_fallback_when_building_has_no_windows(self, _mock_client):
        from backend.world.model import WORLD
        no_window_building = next(
            (b for b in WORLD.buildings if not b.windows),
            None,
        )
        assert no_window_building is not None, (
            "test fixture requires at least one building with no windows"
        )
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": 0.0, "y": 5.0, "z": 0.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01",
            float(no_window_building.cx), float(no_window_building.cz),
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        assert tr.get("entry_mode") == "ground_entry"
        assert tr.get("entry_mode_fallback") is True
        assert "selected_window_waypoint" not in tr
        assert result["to"]["x"] == pytest.approx(float(no_window_building.cx), abs=0.01)
        assert result["to"]["z"] == pytest.approx(float(no_window_building.cz), abs=0.01)
