"""Unit tests for obstacle-aware return_to_base()."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import backend.tools.drone_commands as drone_commands


@pytest.fixture(autouse=True)
def _mock_client():
    mock = AsyncMock()
    mock.get_status.return_value = {
        "asset_id": "BEACON-01",
        "x": -15.0,
        "y": 17.0,
        "z": -20.0,
        "battery": 80.0,
        "status": "IDLE",
    }
    mock.move_to.return_value = {"success": True, "message": "Moving"}
    mock.return_to_base.return_value = {"success": True, "message": "Returning to base"}
    drone_commands.set_client(mock)
    yield mock
    drone_commands.set_client(None)  # type: ignore[arg-type]


class TestReturnToBaseRouting:
    @pytest.mark.asyncio
    async def test_return_executes_waypoints_then_final_return(self, _mock_client, monkeypatch):
        async def _route_ok(*_args, **_kwargs):
            return {
                "asset_id": "BEACON-01",
                "waypoints": [{"x": 0.0, "y": 5.0, "z": 0.0, "reason": "home approach"}],
                "summary": "1 waypoint home approach",
            }

        monkeypatch.setattr("backend.services.api.control.plan_route", _route_ok)
        wait_mock = AsyncMock(
            side_effect=[
                {"ok": True, "status": {"status": "IDLE"}},
                {"ok": True, "status": {"status": "IDLE"}},
            ]
        )
        monkeypatch.setattr("backend.services.api.control._wait_until_waypoint_reached", wait_mock)
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": 0.0,
            "y": 0.0,
            "z": 0.0,
            "battery": 79.8,
            "status": "IDLE",
        }

        result = await drone_commands.return_to_base("BEACON-01")
        assert result["success"] is True
        assert result["strategy"] == "routed_return"
        assert result["waypoint_count"] == 2  # home approach + final landing
        assert _mock_client.move_to.await_count == 2
        first_move = _mock_client.move_to.await_args_list[0].args
        second_move = _mock_client.move_to.await_args_list[1].args
        assert first_move == ("BEACON-01", 0.0, 5.0, 0.0, 5.0)
        # Home pad sits at y=2 (see CLAUDE.md); the final landing leg targets that.
        assert second_move == ("BEACON-01", 0.0, 2.0, 0.0, 5.0)
        _mock_client.return_to_base.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_return_surfaces_route_error(self, _mock_client, monkeypatch):
        async def _route_error(*_args, **_kwargs):
            return {"asset_id": "BEACON-01", "error": "No clear route found", "obstacles": [{"id": 1}]}

        monkeypatch.setattr("backend.services.api.control.plan_route", _route_error)

        result = await drone_commands.return_to_base("BEACON-01")
        assert result["error"] == "Return route blocked"
        _mock_client.move_to.assert_not_awaited()
        _mock_client.return_to_base.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_return_stops_on_waypoint_failure(self, _mock_client, monkeypatch):
        async def _route_ok(*_args, **_kwargs):
            return {
                "asset_id": "BEACON-01",
                "waypoints": [{"x": 0.0, "y": 5.0, "z": 0.0, "reason": "home approach"}],
                "summary": "1 waypoint home approach",
            }

        monkeypatch.setattr("backend.services.api.control.plan_route", _route_ok)
        _mock_client.move_to.return_value = {"success": False, "message": "blocked"}

        result = await drone_commands.return_to_base("BEACON-01")
        assert result["error"] == "Failed while executing return route waypoint"
        _mock_client.return_to_base.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_return_stops_when_blocked_during_waypoint_follow(self, _mock_client, monkeypatch):
        async def _route_ok(*_args, **_kwargs):
            return {
                "asset_id": "BEACON-01",
                "waypoints": [{"x": 0.0, "y": 5.0, "z": 0.0, "reason": "home approach"}],
                "summary": "1 waypoint home approach",
            }

        monkeypatch.setattr("backend.services.api.control.plan_route", _route_ok)
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -5.0,
            "y": 5.0,
            "z": -5.0,
            "battery": 79.0,
            "status": "BLOCKED",
        }

        result = await drone_commands.return_to_base("BEACON-01")
        assert result["error"] == "Drone blocked while following return route"
        _mock_client.return_to_base.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_return_stops_when_final_landing_leg_fails(self, _mock_client, monkeypatch):
        async def _route_ok(*_args, **_kwargs):
            return {
                "asset_id": "BEACON-01",
                "waypoints": [{"x": 0.0, "y": 5.0, "z": 0.0, "reason": "home approach"}],
                "summary": "1 waypoint home approach",
            }

        monkeypatch.setattr("backend.services.api.control.plan_route", _route_ok)
        wait_mock = AsyncMock(
            side_effect=[
                {"ok": True, "status": {"status": "IDLE"}},
                {"ok": False, "error": "Drone blocked while descending at home", "status": {"status": "BLOCKED"}},
            ]
        )
        monkeypatch.setattr("backend.services.api.control._wait_until_waypoint_reached", wait_mock)

        result = await drone_commands.return_to_base("BEACON-01")
        assert result["error"] == "Drone blocked while descending at home"
        assert _mock_client.move_to.await_count == 2
        _mock_client.return_to_base.assert_not_awaited()
