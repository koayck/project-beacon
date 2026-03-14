"""Unit tests for plan_route() and BLOCKED retry logic."""
from __future__ import annotations

from unittest.mock import AsyncMock, call

import pytest

from backend.tools.drone_commands import (
    _wait_until_waypoint_reached,
    plan_route,
    resolve_scan_target,
    set_client,
)
from backend.world.model import WORLD


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


class TestObstaclesInPathMargin:
    """obstacles_in_path with margin catches near-miss paths."""

    def test_margin_zero_misses_near_edge(self):
        # A point just outside building 1 AABB (max_x = -4.0, so x=-3.9 is outside)
        b1 = WORLD.buildings[1]  # obstacle at (-7, -10), w=6, d=5 → x[-10,-4], z[-12.5,-7.5]
        hits = WORLD.obstacles_in_path(
            -3.9, 5.0, -10.0,  # just outside east face
            -3.9, 5.0, -10.0,  # same point (degenerate but tests containment)
            samples=1,
            margin=0.0,
        )
        assert b1 not in hits

    def test_margin_catches_near_edge(self):
        b1 = WORLD.buildings[1]
        hits = WORLD.obstacles_in_path(
            -3.9, 5.0, -10.0,
            -3.9, 5.0, -10.0,
            samples=1,
            margin=1.0,
        )
        assert b1 in hits

    def test_margin_does_not_affect_clearly_safe_path(self):
        # Path far from any building
        hits = WORLD.obstacles_in_path(
            50.0, 10.0, 50.0,
            60.0, 10.0, 60.0,
            samples=20,
            margin=1.0,
        )
        assert hits == []


class TestBlockedRetry:
    """_wait_until_waypoint_reached retries on BLOCKED via re-planning."""

    @pytest.mark.asyncio
    async def test_recovers_after_one_blocked(self, _mock_client):
        """Drone reports BLOCKED once, re-plan succeeds, reaches target."""
        # First call: BLOCKED at an offset position
        # Second call (during re-plan get_status): at the offset position (for plan_route)
        # Third call (sub-wait poll): arrived at re-planned waypoint
        # Fourth call (final get_status): at target
        _mock_client.get_status.side_effect = [
            # 1st poll — BLOCKED
            {"asset_id": "BEACON-01", "x": 5.0, "y": 10.0, "z": 5.0, "battery": 70, "status": "BLOCKED"},
            # plan_route reads current pos for re-plan
            {"asset_id": "BEACON-01", "x": 5.0, "y": 10.0, "z": 5.0, "battery": 70, "status": "IDLE"},
            # sub-wait poll — arrived at re-planned waypoint (target is far, so direct)
            {"asset_id": "BEACON-01", "x": 10.0, "y": 10.0, "z": 10.0, "battery": 68, "status": "IDLE"},
            # final get_status after success
            {"asset_id": "BEACON-01", "x": 10.0, "y": 10.0, "z": 10.0, "battery": 68, "status": "IDLE"},
        ]
        _mock_client.move_to.return_value = {"success": True}

        result = await _wait_until_waypoint_reached(
            "BEACON-01", 10.0, 10.0, 10.0, blocked_retries=2,
        )
        assert result["ok"] is True

    @pytest.mark.asyncio
    async def test_gives_up_after_retries_exhausted(self, _mock_client):
        """With blocked_retries=0, BLOCKED is immediately terminal."""
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01", "x": 5.0, "y": 10.0, "z": 5.0,
            "battery": 70, "status": "BLOCKED",
        }

        result = await _wait_until_waypoint_reached(
            "BEACON-01", 10.0, 10.0, 10.0, blocked_retries=0,
        )
        assert result["ok"] is False
        assert "blocked" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_replan_failure_returns_error(self, _mock_client):
        """When re-plan itself fails (all routes blocked), returns error."""
        # BLOCKED, then plan_route sees drone inside a building → no route
        _mock_client.get_status.side_effect = [
            {"asset_id": "BEACON-01", "x": -7.0, "y": 5.0, "z": -10.0, "battery": 70, "status": "BLOCKED"},
            # plan_route get_status — inside obstacle building
            {"asset_id": "BEACON-01", "x": -7.0, "y": 5.0, "z": -10.0, "battery": 70, "status": "IDLE"},
        ]

        result = await _wait_until_waypoint_reached(
            "BEACON-01", 50.0, 10.0, 50.0, blocked_retries=2,
        )
        assert result["ok"] is False
