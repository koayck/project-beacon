from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.agents.scan_workflow import build_aggregated_scan_report, pick_next_building_for_asset
from backend.runtime import grpc_client


@pytest.mark.asyncio
async def test_pick_next_building_emits_final_summary_when_queue_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _status(_asset_id: str) -> dict:
        return {"x": 0.0, "z": 0.0}

    monkeypatch.setattr(grpc_client, "get_status", _status)

    tool_context = SimpleNamespace(
        state={
            "active_fleet_assets": '["BEACON-01"]',
            "scan_initial_building_by_asset": '{"BEACON-01":{"id":4,"x":-23.0,"z":-28.0,"height":21.0,"bounds":{"min_x":-28.0,"max_x":-18.0,"min_z":-33.0,"max_z":-23.0}}}',
            "scan_pending_buildings": "[]",
            "scan_claimed_initial_by_asset": '{"BEACON-01":true}',
            "scan_done_count_by_asset": '{"BEACON-01":1}',
            "scan_results_list": '["[BEACON-01] Building at (x=-23.0, z=-28.0): 1 survivor(s) across 1 level(s). Waypoints: 8."]',
            "scan_total_buildings": 1,
            "scan_summary_emitted": False,
        },
        actions=SimpleNamespace(escalate=False),
    )

    result = await pick_next_building_for_asset("BEACON-01", tool_context)

    assert result["done"] is True
    assert tool_context.actions.escalate is True
    assert "AREA SCAN COMPLETE" in result["message"]
    assert tool_context.state["scan_summary_emitted"] is True


def test_build_aggregated_scan_report_splits_cross_building_survivor_group() -> None:
    tool_context = SimpleNamespace(
        state={
            "scan_results_list": json.dumps(
                [
                    "[BEACON-01] Building at (x=-15.0, z=-20.0): 4 survivor(s) across 4 level(s). Waypoints: 19.\n"
                    "  - Survivor 0: (-16.5, 3.65, -19.0)\n"
                    "  - Survivor 1: (-14.5, 6.65, -20.5)\n"
                    "  - Survivor 2: (-13.5, 9.65, -21.0)\n"
                    "  - Survivor 7: (-23.0, 12.65, -22.0)"
                ]
            )
        },
        actions=SimpleNamespace(escalate=False),
    )

    result = build_aggregated_scan_report(tool_context)

    assert "Building 1:" not in result["summary"]
    assert "BEACON-01\nBuilding at (x=-15.0, z=-20.0): 4 survivor(s) across 4 level(s). Waypoints: 19." in result["summary"]
    assert "Building at (x=-23.0, z=-22.0): 1 survivor(s)" in result["summary"]
    assert "  - Survivor 7: (-23.0, 12.65, -22.0)" in result["summary"]
