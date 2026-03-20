from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.agents.scan_workflow import (
    build_aggregated_scan_report,
    pick_next_building_for_asset,
    prepare_parallel_fleet_scan,
)
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


def test_prepare_parallel_fleet_scan_dedupes_duplicate_buildings() -> None:
    tool_context = SimpleNamespace(
        state={
            "fleet_assignments": json.dumps(
                {
                    "assignments": [
                        {
                            "asset_id": "BEACON-01",
                            "building": {"id": 4, "x": -23.0, "z": -28.0, "height": 21.0},
                            "distance_m": 0.0,
                        },
                        {
                            "asset_id": "BEACON-02",
                            "building": {"id": 4, "x": -23.0, "z": -28.0, "height": 21.0},
                            "distance_m": 1.0,
                        },
                    ],
                    "unassigned_buildings": [
                        {"id": 4, "x": -23.0, "z": -28.0, "height": 21.0},
                        {"id": 9, "x": -10.0, "z": -12.0, "height": 18.0},
                        {"id": 9, "x": -10.0, "z": -12.0, "height": 18.0},
                    ],
                }
            )
        },
        actions=SimpleNamespace(escalate=False),
    )

    result = prepare_parallel_fleet_scan(tool_context)

    assert result["success"] is True
    assert result["queued_buildings"] == 2

    initial = json.loads(tool_context.state["scan_initial_building_by_asset"])
    pending = json.loads(tool_context.state["scan_pending_buildings"])

    assert initial["BEACON-01"]["id"] == 4
    assert len(pending) == 1
    assert pending[0]["id"] == 9


@pytest.mark.asyncio
async def test_pick_next_building_concurrent_claims_do_not_reissue_initial(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _status(_asset_id: str) -> dict:
        return {"x": 0.0, "z": 0.0}

    monkeypatch.setattr(grpc_client, "get_status", _status)

    tool_context = SimpleNamespace(
        state={
            "active_fleet_assets": '["BEACON-01","BEACON-04"]',
            "scan_initial_building_by_asset": json.dumps(
                {
                    "BEACON-01": {"id": 3, "x": 12.0, "z": -27.0, "height": 9.0},
                    "BEACON-04": {"id": 4, "x": -28.0, "z": -28.0, "height": 21.0},
                }
            ),
            "scan_pending_buildings": "[]",
            "scan_claimed_initial_by_asset": '{"BEACON-01":false,"BEACON-04":false}',
            "scan_done_count_by_asset": '{"BEACON-01":0,"BEACON-04":0}',
            "scan_results_list": "[]",
            "scan_total_buildings": 2,
            "scan_summary_emitted": False,
        },
        actions=SimpleNamespace(escalate=False),
    )

    first, second = await asyncio.gather(
        pick_next_building_for_asset("BEACON-01", tool_context),
        pick_next_building_for_asset("BEACON-04", tool_context),
    )

    assert first["done"] is False
    assert second["done"] is False

    follow_up = await pick_next_building_for_asset("BEACON-04", tool_context)
    assert follow_up["done"] is True
    assert follow_up["total_scanned"] == 1
