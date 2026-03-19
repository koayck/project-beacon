from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from backend.agents.supply_workflow import (
    _supply_execution_stage,
    _dedupe_targets,
    assign_drones_to_supply_targets,
    build_aggregated_supply_report,
    prepare_parallel_supply_dispatch,
    process_next_supply_target_for_asset,
)
from backend.runtime import grpc_client
from backend.services.api.control import (
    clear_detected_survivors,
    find_survivors_in_area,
    register_detected_survivors,
)


def test_dedupe_targets_normalizes_mixed_id_types() -> None:
    targets = [
        {"id": 7, "x": 20.0, "y": 3.0, "z": -10.0},
        {"id": "7", "x": 21.0, "y": 3.0, "z": -10.0},
        {"id": "S-01", "x": 22.0, "y": 3.0, "z": -10.0},
        {"id": "s-01", "x": 23.0, "y": 3.0, "z": -10.0},
    ]
    deduped = _dedupe_targets(targets)
    assert len(deduped) == 2


def test_prepare_parallel_supply_dispatch_returns_no_targets_message() -> None:
    tool_context = SimpleNamespace(
        state={
            "supply_targets": '{"asset_id":"auto","survivors":[]}',
            "supply_assignments": '{"assignments":[],"unassigned_targets":[],"idle_drones":[],"total_assigned":0}',
        },
        actions=SimpleNamespace(escalate=False),
    )

    result = prepare_parallel_supply_dispatch(tool_context)
    assert result["success"] is True
    assert result["mode"] == "no_targets"
    assert "No survivors detected" in result["message"]
    assert tool_context.state["active_supply_assets"] == "[]"
    assert tool_context.state["supply_total_targets"] == 0

    report = build_aggregated_supply_report(tool_context)
    assert report["summary"] == "No survivors detected in the selected area. Supply dispatch skipped."
    assert report["total_targets"] == 0


def test_find_survivors_in_area_requires_all_detected_before_supply() -> None:
    clear_detected_survivors()
    baseline = find_survivors_in_area(
        center_x=-25.0,
        center_z=-25.0,
        radius=6.0,
        detected_only=False,
        require_all_detected=False,
    )
    assert baseline["total_in_area"] >= 2

    gated_none = find_survivors_in_area(
        center_x=-25.0,
        center_z=-25.0,
        radius=6.0,
        detected_only=True,
        require_all_detected=True,
    )
    assert gated_none["total"] == 0
    assert gated_none["detection_gate_blocked"] is True

    register_detected_survivors([{"id": 6}])
    gated_partial = find_survivors_in_area(
        center_x=-25.0,
        center_z=-25.0,
        radius=6.0,
        detected_only=True,
        require_all_detected=True,
    )
    assert gated_partial["total"] == 0
    assert gated_partial["detection_gate_blocked"] is True

    register_detected_survivors([{"id": 7}])
    gated_all = find_survivors_in_area(
        center_x=-25.0,
        center_z=-25.0,
        radius=6.0,
        detected_only=True,
        require_all_detected=True,
    )
    assert gated_all["detection_gate_blocked"] is False
    assert gated_all["total"] == gated_all["total_in_area"] >= 2
    clear_detected_survivors()


@pytest.mark.asyncio
async def test_assign_drones_disables_execution_stage_when_no_targets() -> None:
    tool_context = SimpleNamespace(
        state={"supply_targets": '{"asset_id":"BEACON-01","survivors":[]}'},
        actions=SimpleNamespace(escalate=False),
    )
    result = await assign_drones_to_supply_targets(tool_context)
    assert result["total_assigned"] == 0
    assert len(_supply_execution_stage.sub_agents) == 0

    restore_context = SimpleNamespace(
        state={
            "supply_targets": (
                '{"asset_id":"BEACON-01","survivors":[{"id":99,"x":20.0,"y":6.65,"z":-16.0}]}'
            )
        },
        actions=SimpleNamespace(escalate=False),
    )
    restored = await assign_drones_to_supply_targets(restore_context)
    assert restored["total_assigned"] == 1
    assert len(_supply_execution_stage.sub_agents) == 3


@pytest.mark.asyncio
async def test_process_next_supply_target_reserves_inflight_target(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _status(_asset_id: str) -> dict:
        return {"x": 0.0, "z": 0.0}

    monkeypatch.setattr(grpc_client, "get_status", _status)

    import backend.services.api.control as drone_control

    dispatch_calls: list[tuple[str, int | None]] = []

    async def _dispatch(asset_id: str, building: dict) -> dict:
        dispatch_calls.append((asset_id, building.get("id")))
        await asyncio.sleep(0.01)
        return {"success": True, "waypoint_count": 3}

    monkeypatch.setattr(drone_control, "dispatch_supply_to_building", _dispatch)

    shared_target = {"id": 11, "x": 20.0, "y": 6.0, "z": -16.0}
    tool_context = SimpleNamespace(
        state={
            "active_supply_assets": '["BEACON-01","BEACON-02"]',
            "supply_initial_target_by_asset": json.dumps(
                {"BEACON-01": shared_target, "BEACON-02": shared_target}
            ),
            "supply_pending_targets": "[]",
            "supply_claimed_initial_by_asset": '{"BEACON-01":false,"BEACON-02":false}',
            "supply_done_count_by_asset": '{"BEACON-01":0,"BEACON-02":0}',
            "supply_results_by_asset": '{"BEACON-01":[],"BEACON-02":[]}',
            "supply_results_list": "[]",
            "supply_results_structured": "[]",
            "supply_completed_target_keys": "[]",
            "supply_inflight_target_keys": "[]",
        },
        actions=SimpleNamespace(escalate=False),
    )

    res_a, res_b = await asyncio.gather(
        process_next_supply_target_for_asset("BEACON-01", tool_context),
        process_next_supply_target_for_asset("BEACON-02", tool_context),
    )

    assert len(dispatch_calls) == 1
    assert {res_a["asset_id"], res_b["asset_id"]} == {"BEACON-01", "BEACON-02"}
    assert sum(1 for row in (res_a, res_b) if row.get("done") is True) == 1
    assert json.loads(tool_context.state["supply_completed_target_keys"]) == ["id:11"]


@pytest.mark.asyncio
async def test_process_next_supply_target_stops_when_only_completed_targets_remain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _status(_asset_id: str) -> dict:
        return {"x": 0.0, "z": 0.0}

    monkeypatch.setattr(grpc_client, "get_status", _status)

    import backend.services.api.control as drone_control

    dispatch_calls: list[str] = []

    async def _dispatch(asset_id: str, building: dict) -> dict:
        dispatch_calls.append(asset_id)
        return {"success": True, "waypoint_count": 3}

    monkeypatch.setattr(drone_control, "dispatch_supply_to_building", _dispatch)

    completed_target = {"id": 22, "x": 24.0, "y": 3.0, "z": -14.0}
    tool_context = SimpleNamespace(
        state={
            "active_supply_assets": '["BEACON-01"]',
            "supply_initial_target_by_asset": '{"BEACON-01":{"id":22,"x":24.0,"y":3.0,"z":-14.0}}',
            "supply_pending_targets": json.dumps([completed_target]),
            "supply_claimed_initial_by_asset": '{"BEACON-01":true}',
            "supply_done_count_by_asset": '{"BEACON-01":1}',
            "supply_results_by_asset": '{"BEACON-01":[]}',
            "supply_results_list": "[]",
            "supply_results_structured": "[]",
            "supply_completed_target_keys": '["id:22"]',
            "supply_inflight_target_keys": "[]",
        },
        actions=SimpleNamespace(escalate=False),
    )

    result = await process_next_supply_target_for_asset("BEACON-01", tool_context)

    assert result["done"] is True
    assert result["total_dispatched"] == 1
    assert dispatch_calls == []
    assert tool_context.actions.escalate is True
