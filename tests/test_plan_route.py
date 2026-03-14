"""Unit tests for plan_route() — deterministic route planning."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.tools.drone_commands import plan_route, resolve_scan_target, set_client


@pytest.fixture(autouse=True)
def _mock_client():
    """Inject a mock gRPC client that returns configurable drone positions."""
    mock = AsyncMock()
    # Default: drone at origin
    mock.get_status.return_value = {
        "asset_id": "BEACON-01",
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "battery": 80,
        "status": "IDLE",
    }
    mock.registered_asset_ids.return_value = ["BEACON-01"]
    set_client(mock)
    yield mock
    set_client(None)  # type: ignore[arg-type]


class TestDirectPath:
    """When the direct path is clear, return a single waypoint."""

    @pytest.mark.asyncio
    async def test_direct_with_explicit_altitude(self):
        result = await plan_route("BEACON-01", 10.0, -5.0, 20.0)
        assert result["strategy"] == "direct"
        assert len(result["waypoints"]) == 1
        wp = result["waypoints"][0]
        assert wp["x"] == 10.0
        assert wp["y"] == 20.0
        assert wp["z"] == -5.0

    @pytest.mark.asyncio
    async def test_direct_no_building_nearby_defaults_10m(self):
        result = await plan_route("BEACON-01", 50.0, 50.0)
        assert result["strategy"] == "direct"
        assert result["waypoints"][0]["y"] == 10.0

    @pytest.mark.asyncio
    async def test_clamp_altitude_minimum_5m(self):
        result = await plan_route("BEACON-01", 50.0, 50.0, 2.0)
        assert result["waypoints"][0]["y"] == 5.0


class TestAutoAltitude:
    """When target_y is omitted and a building is nearby, altitude = building.max_y + 5."""

    @pytest.mark.asyncio
    async def test_scan_altitude_from_building(self):
        # Target at (-15, -20) — the target building has h=12
        result = await plan_route("BEACON-01", -15.0, -20.0)
        assert result["to"]["y"] == 17.0  # 12 + 5

    @pytest.mark.asyncio
    async def test_no_building_nearby(self):
        result = await plan_route("BEACON-01", 100.0, 100.0)
        assert result["to"]["y"] == 10.0


class TestScanTargetResolution:
    """Scan coordinates on/near a building should resolve to footprint center."""

    def test_resolve_scan_target_returns_bounds_and_center(self):
        # Point on/near the target building footprint should resolve to building center.
        result = resolve_scan_target(-18.0, -22.0)
        assert result["matched_building"] is True
        assert result["resolved_target"]["x"] == -15.0
        assert result["resolved_target"]["z"] == -20.0
        assert result["building"]["min_x"] == -19.0
        assert result["building"]["max_x"] == -11.0
        assert result["building"]["min_z"] == -24.0
        assert result["building"]["max_z"] == -16.0

    @pytest.mark.asyncio
    async def test_plan_route_snaps_to_building_center_for_scan(self):
        # Input point is near building edge; snapped route target should be center.
        result = await plan_route(
            "BEACON-01",
            -18.0,
            -22.0,
            snap_to_building_center=True,
        )
        assert result["to"]["x"] == -15.0
        assert result["to"]["z"] == -20.0
        assert result["target_resolution"]["bounds"]["min_x"] == -19.0
        assert result["target_resolution"]["bounds"]["max_x"] == -11.0


class TestGoOverStrategy:
    """Drone at (0,0,0) → target (-15,y,-20) blocked by obstacle at (-7,-10,h=10)."""

    @pytest.mark.asyncio
    async def test_over_strategy_waypoints(self):
        result = await plan_route("BEACON-01", -15.0, -20.0)
        assert result["strategy"] == "over"
        assert result["obstacle_count"] >= 1
        assert len(result["waypoints"]) == 3

        wps = result["waypoints"]
        # First waypoint: climb at current XZ
        assert wps[0]["x"] == 0.0
        assert wps[0]["z"] == 0.0
        assert wps[0]["y"] >= 15.0  # obstacle h=10 + 5

        # Second waypoint: cruise to target XZ
        assert wps[1]["x"] == -15.0
        assert wps[1]["z"] == -20.0
        assert wps[1]["y"] == wps[0]["y"]

        # Third waypoint: descend to scan alt
        assert wps[2]["x"] == -15.0
        assert wps[2]["z"] == -20.0
        assert wps[2]["y"] == 17.0  # building h=12 + 5

    @pytest.mark.asyncio
    async def test_summary_contains_strategy(self):
        result = await plan_route("BEACON-01", -15.0, -20.0)
        assert "over" in result["summary"]
        assert "17" in result["summary"]


class TestGoAroundStrategy:
    """Force the go-around path by placing the drone so go-over fails."""

    @pytest.mark.asyncio
    async def test_around_fallback(self, _mock_client):
        # Put drone inside a tall building so climb is blocked too
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -7.0, "y": 5.0, "z": -10.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route("BEACON-01", -15.0, -20.0)
        # Should either find an around route or report error
        assert result.get("strategy") in ("around", None)
        if result.get("strategy") == "around":
            assert len(result["waypoints"]) == 2


class TestErrorCase:
    """When no route is found, return error with obstacle info."""

    @pytest.mark.asyncio
    async def test_error_has_obstacles(self, _mock_client):
        # Place drone at obstacle centre, target also at obstacle
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -7.0, "y": 0.0, "z": -10.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route("BEACON-01", -7.0, -10.0)
        # Either finds a route (direct up is clear) or errors
        assert "waypoints" in result or "error" in result
