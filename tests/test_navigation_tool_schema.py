"""Unit tests for ADK-safe navigation tool schema."""
from __future__ import annotations

import pytest

from backend.orchestrator.navigation import (
    NavigationResult,
    Point3D,
    execute_navigation_sequence_tool,
)


@pytest.mark.asyncio
async def test_execute_navigation_sequence_tool_returns_json_serializable_schema(monkeypatch):
    """Ensure tool wrapper returns only primitive/JSON-safe values.

    Args:
        monkeypatch: pytest fixture used to replace orchestrator internals.

    Returns:
        None. Assertions verify output schema.
    """

    async def _fake_execute_navigation_sequence(*_args, **_kwargs):
        return NavigationResult(
            success=True,
            final_position=Point3D(x=10.0, y=15.0, z=-5.0),
            waypoints_completed=3,
            route_summary="3 waypoints",
            error=None,
        )

    monkeypatch.setattr(
        "backend.orchestrator.navigation.execute_navigation_sequence",
        _fake_execute_navigation_sequence,
    )

    result = await execute_navigation_sequence_tool(
        asset_id="BEACON-01",
        target_x=10.0,
        target_z=-5.0,
    )

    assert result == {
        "success": True,
        "final_position": {"x": 10.0, "y": 15.0, "z": -5.0},
        "waypoints_completed": 3,
        "route_summary": "3 waypoints",
        "error": None,
    }
