"""Regression tests for sweep summary survivor counting."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

import backend.services.api.control as drone_control


@pytest.mark.asyncio
async def test_sweep_summary_counts_visible_survivor_even_if_outside_scan_radius(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        "waypoints": [{"x": -21.0, "y": 2.0, "z": -26.0, "level_y": 2.0, "reason": "NW"}],
        "waypoint_count": 1,
        "rooftop_position": {"x": -15.0, "y": 14.0, "z": -20.0},
        "summary": "1-waypoint test sweep",
    }
    monkeypatch.setattr(drone_control, "plan_building_vertical_sweep", lambda *_a, **_k: plan)

    async def _route_ok(*_args, **kwargs):
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

    monkeypatch.setattr(drone_control, "plan_route", _route_ok)
    monkeypatch.setattr(
        drone_control,
        "_wait_until_waypoint_reached",
        AsyncMock(return_value={"ok": True, "status": {"status": "IDLE"}}),
    )

    class _Client:
        async def get_status(self, _asset_id: str) -> dict:
            return {
                "asset_id": "BEACON-01",
                "x": -15.0,
                "y": 2.0,
                "z": -20.0,
                "battery": 88.0,
                "status": "IDLE",
            }

        async def move_to(self, *_args, **_kwargs) -> dict:
            return {"success": True, "message": "Moving"}

        async def scan_area(self, *_args, **_kwargs) -> dict:
            return {"success": True, "message": "Scanning"}

        async def get_view(self, *_args, **_kwargs) -> dict:
            # Visible survivor exists, but distance is outside the caller's scan_radius.
            return {
                "asset_id": "BEACON-01",
                "survivors_in_range": 1,
                "summary": "agl=10.0m terrain=airspace",
                "objects": [
                    {
                        "object_type": "survivor",
                        "object_id": 7,
                        "x": -14.5,
                        "y": 6.65,
                        "z": -20.5,
                        "distance": 20.0,
                        "direction": "W",
                        "detail": "{\"submerged\": false}",
                    }
                ],
            }

    monkeypatch.setattr(drone_control, "grpc_client", _Client())

    result = await drone_control.sweep_scan_building(
        "BEACON-01",
        -15.0,
        -20.0,
        scan_radius=8.0,
    )

    assert result["success"] is True
    assert result["max_survivors_in_range"] == 1
    assert result["reported_survivor_count"] == 1
    assert result["scan_reports"][0]["survivors_within_scan_radius"] == 0
    assert len(result["scan_reports"][0]["detected_survivors"]) == 1
    assert "Findings  : 1 heat signature(s) detected." in result["message"]
