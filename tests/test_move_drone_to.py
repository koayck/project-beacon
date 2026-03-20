from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import AsyncMock

import pytest

import backend.services.api.control as control


@pytest.fixture(autouse=True)
def _mock_client() -> Iterator[AsyncMock]:
    mock = AsyncMock()
    mock.move_to.return_value = {"success": True, "message": "Moving"}
    mock.get_status.return_value = {
        "asset_id": "BEACON-01",
        "x": 0.0,
        "y": 0.0,
        "z": 0.0,
        "battery": 95.0,
        "status": "IDLE",
    }
    control.set_client(mock)
    yield mock
    control.set_client(None)


@pytest.mark.asyncio
async def test_move_drone_to_waits_until_waypoint_reached(_mock_client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    wait_mock = AsyncMock(
        return_value={
            "ok": True,
            "status": {"asset_id": "BEACON-01", "x": 10.0, "y": 8.0, "z": -5.0, "status": "IDLE"},
        }
    )
    monkeypatch.setattr(control, "_wait_until_waypoint_reached", wait_mock)

    result = await control.move_drone_to("BEACON-01", 10.0, 8.0, -5.0)

    assert result["success"] is True
    assert result["reached"] is True
    assert result["status"]["status"] == "IDLE"
    wait_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_move_drone_to_returns_blocked_error_when_wait_fails(_mock_client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    wait_mock = AsyncMock(
        return_value={
            "ok": False,
            "error": "Drone blocked while following return route",
            "status": {"asset_id": "BEACON-01", "status": "BLOCKED"},
        }
    )
    monkeypatch.setattr(control, "_wait_until_waypoint_reached", wait_mock)

    result = await control.move_drone_to("BEACON-01", 10.0, 8.0, -5.0)

    assert result["success"] is False
    assert "blocked" in result["error"].lower()
    assert result["status"]["status"] == "BLOCKED"


@pytest.mark.asyncio
async def test_move_drone_to_short_circuits_when_dispatch_fails(_mock_client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_client.move_to.return_value = {"success": False, "message": "rejected"}
    wait_mock = AsyncMock(return_value={"ok": True, "status": {"status": "IDLE"}})
    monkeypatch.setattr(control, "_wait_until_waypoint_reached", wait_mock)

    result = await control.move_drone_to("BEACON-01", 1.0, 2.0, 3.0)

    assert result == {"success": False, "message": "rejected"}
    wait_mock.assert_not_awaited()
