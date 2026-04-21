"""Unit tests for plan_route entry_mode='extreme_floor'."""
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


class TestEntryModeExtremeFloor:
    """With entry_mode='extreme_floor', selection restricts to lowest/highest floors only."""

    @pytest.mark.asyncio
    async def test_extreme_floor_picks_from_top_when_drone_is_high(self, _mock_client):
        # Drone placed adjacent to the east facade at roof altitude.
        # Building id=0: highest floor=4, east-face window at (-6, 10.2, -14).
        # Drone is close to that window in 3D, making it the closest extreme-floor candidate.
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -5.0, "y": 11.0, "z": -13.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="extreme_floor",
        )
        assert "target_resolution" in result
        tr = result["target_resolution"]
        assert tr.get("entry_mode") == "extreme_floor"
        assert tr.get("entry_floor_kind") == "highest"
        assert "selected_window_waypoint" in tr
        wp = tr["selected_window_waypoint"]
        assert wp["floor"] == 4
        assert wp["y"] == pytest.approx(10.2, abs=0.01)

    @pytest.mark.asyncio
    async def test_extreme_floor_picks_from_bottom_when_drone_is_low(self, _mock_client):
        # Drone placed near the south facade at low altitude.
        # Building id=0: lowest floor=2, south-face windows at y=4.2.
        # Drone is close to a floor-2 south window, making it the closest extreme-floor candidate.
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -17.0, "y": 4.0, "z": -2.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="extreme_floor",
        )
        tr = result.get("target_resolution", {})
        assert tr.get("entry_floor_kind") == "lowest"
        assert tr["selected_window_waypoint"]["floor"] == 2
        assert tr["selected_window_waypoint"]["y"] == pytest.approx(4.2, abs=0.01)

    @pytest.mark.asyncio
    async def test_extreme_floor_excludes_middle_floor_candidates(self, _mock_client):
        # Drone placed so the legacy (nearest_floor) logic would pick floor 3
        # (y=7.2 is closest to the default preferred_y = h/2 = 6). extreme_floor
        # must instead return floor 2 (lowest) or 4 (highest) — never floor 3.
        # Building id=0 has floors 2, 3, 4 with h=12 so h/2=6 is nearest floor 3.
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -15.0, "y": 6.0, "z": -30.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="extreme_floor",
        )
        tr = result.get("target_resolution", {})
        floor = tr["selected_window_waypoint"]["floor"]
        assert floor in (2, 4), f"expected extreme floor (2 or 4), got {floor}"

    @pytest.mark.asyncio
    async def test_default_mode_preserves_legacy_behavior(self, _mock_client):
        # Without entry_mode, selection uses preferred_y (building center by default)
        # and ref_x/ref_z = requested coords. Must produce identical shape as today.
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
    async def test_extreme_floor_falls_back_when_no_snap(self, _mock_client):
        # entry_mode is a no-op when snap_to_building_center=False.
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=False,
            entry_mode="extreme_floor",
        )
        tr = result.get("target_resolution", {})
        # No window selected because no snap requested.
        assert "selected_window_waypoint" not in tr
        assert tr.get("entry_floor_kind") is None or "entry_floor_kind" not in tr

    @pytest.mark.asyncio
    async def test_extreme_floor_single_floor_windows_resolves_to_lowest(self, _mock_client, monkeypatch):
        # Edge case: a building with windows on only one floor (lowest == highest).
        # The tie-break must resolve to entry_floor_kind='lowest'.
        from backend.services.core import context
        from backend.world.model import Building, WindowAperture

        single_floor_building = Building(
            id=999,
            cx=40.0, cz=40.0,
            w=8.0, d=8.0, h=12.0,
            windows=(
                WindowAperture(face="south", axis_center=40.0,
                               sill_y=3.4, width=2.0, height=1.6),
            ),
        )

        class _SingleFloorWorld:
            buildings = (single_floor_building,)

            def building_near_xz(self, x, z, margin=2.0):
                return single_floor_building

            def obstacles_in_path(self, *_args, **_kwargs):
                return []

            def buildings_near(self, *_args, **_kwargs):
                return [single_floor_building]

        monkeypatch.setattr(context, "get_world", lambda: _SingleFloorWorld())

        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": 20.0, "y": 8.0, "z": 40.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", 40.0, 40.0,
            snap_to_building_center=True,
            entry_mode="extreme_floor",
        )
        tr = result.get("target_resolution", {})
        assert tr.get("entry_mode") == "extreme_floor"
        assert tr.get("entry_floor_kind") == "lowest"
        assert tr["selected_window_waypoint"]["floor"] == 2

    @pytest.mark.asyncio
    async def test_extreme_floor_records_fallback_when_building_has_no_windows(self, _mock_client):
        # Building id=6 (utility_block) in world2.json has no windows. With snap_to_building_center=True
        # and entry_mode='extreme_floor', target snaps to building center and
        # entry_mode_fallback=True is recorded.
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": 0.0, "y": 5.0, "z": 0.0,
            "battery": 80, "status": "IDLE",
        }
        # Find a no-windows building in world2.json and target it. If building id=6
        # has no windows, use its coordinates. Otherwise pick any building with
        # an empty windows list from WORLD.buildings.
        from backend.world.model import WORLD
        no_window_building = next(
            (b for b in WORLD.buildings if not b.windows),
            None,
        )
        assert no_window_building is not None, (
            "test fixture requires at least one building with no windows"
        )
        result = await plan_route(
            "BEACON-01",
            float(no_window_building.cx), float(no_window_building.cz),
            snap_to_building_center=True,
            entry_mode="extreme_floor",
        )
        tr = result.get("target_resolution", {})
        assert tr.get("entry_mode") == "extreme_floor"
        assert tr.get("entry_mode_fallback") is True
        assert "selected_window_waypoint" not in tr
        # Target should have snapped to building center (no window waypoint).
        assert result["to"]["x"] == pytest.approx(float(no_window_building.cx), abs=0.01)
        assert result["to"]["z"] == pytest.approx(float(no_window_building.cz), abs=0.01)
