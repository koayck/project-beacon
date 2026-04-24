"""Supply Workflow — survivor resolver + fleet assignment + parallel LoopAgent dispatch."""
from __future__ import annotations

import asyncio
import json
import math
from typing import Any

from google.adk.agents import Agent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from backend.agents._mcp import make_toolset
from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.instructions.supply_agent_text import (
    ASSET_SUPPLY_WORKER_INSTRUCTION_TEMPLATE,
    SUPPLY_ASSIGNER_INSTRUCTION,
    SUPPLY_EXECUTOR_INSTRUCTION,
    SUPPLY_REPORT_INSTRUCTION,
    SUPPLY_RESOLVER_INSTRUCTION,
)
from backend.services.core import context as service_context

_SUPPLY_QUEUE_LOCK = asyncio.Lock()
_PARALLEL_BEACON_IDS = ["BEACON-01"]


def _as_dict(value: object) -> dict | None:
    """Return a mapping-like value when possible.

    Args:
        value: Candidate object to validate as mapping-like.

    Returns:
        The original object when it exposes mapping access, otherwise None.
    """
    try:
        value.get  # type: ignore[attr-defined]
    except AttributeError:
        return None
    return value  # type: ignore[return-value]


def _to_float(value: Any) -> float | None:
    """Convert an arbitrary value to float.

    Args:
        value: Value to convert.

    Returns:
        The converted float value, or None when conversion fails.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int_id(value: Any) -> int | None:
    """Convert an arbitrary value to integer.

    Args:
        value: Value to convert.

    Returns:
        The converted integer value, or None when conversion fails.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_json_state(value: object, fallback: Any) -> Any:
    """Decode state value that may be JSON text.

    Args:
        value: Raw state value, possibly JSON-encoded text.
        fallback: Value returned when decoding fails or value is missing.

    Returns:
        Parsed JSON object, passthrough value, or fallback on decode errors.
    """
    try:
        if isinstance(value, str):
            return json.loads(value)
        return value if value is not None else fallback
    except (json.JSONDecodeError, TypeError):
        return fallback


def _target_key(target: dict) -> str:
    """Build a stable key for survivor target deduplication.

    Args:
        target: Survivor target payload containing id and/or coordinates.

    Returns:
        Stable target key using normalized id when possible, otherwise
        coordinate-derived fallback key.
    """
    sid = target.get("id")
    sid_int = _to_int_id(sid)
    sid_float = _to_float(sid)
    if sid_int is not None and sid_float is not None and sid_float.is_integer():
        return f"id:{sid_int}"
    if sid is None:
        normalized = ""
    else:
        try:
            normalized = sid.strip()
        except AttributeError:
            normalized = ""
    if normalized:
        if normalized.isdigit():
            return f"id:{int(normalized)}"
        return f"id:{normalized.lower()}"
    x = float(target.get("x", 0.0))
    y = float(target.get("y", 0.0))
    z = float(target.get("z", 0.0))
    return f"xyz:{x:.2f},{y:.2f},{z:.2f}"


def _dedupe_targets(targets: list[dict]) -> list[dict]:
    """Remove duplicate survivor targets while preserving first-seen order.

    Args:
        targets: Raw survivor target list.

    Returns:
        Deduplicated survivor target list.
    """
    seen: set[str] = set()
    deduped: list[dict] = []
    for target in targets:
        target_dict = _as_dict(target)
        if target_dict is None:
            continue
        key = _target_key(target_dict)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target_dict)
    return deduped


def _filter_unsupplied_targets(targets: list[dict]) -> list[dict]:
    """Filter out targets already marked as supplied.

    Args:
        targets: Survivor target candidates.

    Returns:
        Targets that have not been registered as supplied.
    """
    supplied_keys = service_context.get_supplied_target_keys()
    return [
        target_dict
        for target in targets
        for target_dict in [_as_dict(target)]
        if target_dict is not None and _target_key(target_dict) not in supplied_keys
    ]


async def assign_drones_to_supply_targets(tool_context: ToolContext) -> dict:
    """
    Read state["supply_targets"], assign closest available drones, and persist
    assignment payload into state["supply_assignments"].

    Args:
        tool_context: ADK tool context containing survivor target state.

    Returns:
        Assignment payload persisted to state, including assignments,
        unassigned targets, optional notes, or error details.
    """
    from backend.services.api import assign_fleet_to_buildings

    supply_data = _load_json_state(tool_context.state.get("supply_targets", "{}"), {})
    survivors: list[dict] = _filter_unsupplied_targets(
        _dedupe_targets(supply_data.get("survivors", []))
    )
    asset_id: str = supply_data.get("asset_id", "auto") or "auto"

    if asset_id.upper() not in ("AUTO", "", "UNKNOWN"):
        if not survivors:
            result: dict = {
                "assignments": [],
                "unassigned_targets": [],
                "idle_drones": [],
                "total_assigned": 0,
                "note": "No survivors detected in the selected area. Supply dispatch skipped.",
            }
        else:
            result = {
                "assignments": [{"asset_id": asset_id, "target": survivors[0], "distance_m": 0.0}],
                "unassigned_targets": survivors[1:],
                "idle_drones": [],
                "note": f"Single drone {asset_id} assigned initial survivor target; remaining queued.",
                "total_assigned": 1,
            }
    else:
        assigned = await assign_fleet_to_buildings(survivors)
        if "error" in assigned:
            result = assigned
        else:
            result = {
                "assignments": [
                    {
                        "asset_id": row["asset_id"],
                        "target": row["building"],
                        "distance_m": row.get("distance_m", 0.0),
                    }
                    for row in assigned.get("assignments", [])
                ],
                "unassigned_targets": assigned.get("unassigned_buildings", []),
                "idle_drones": assigned.get("idle_drones", []),
                "total_assigned": assigned.get("total_assigned", 0),
            }
        if "error" not in result and not survivors:
            result["note"] = "No survivors detected in the selected area. Supply dispatch skipped."
        if "error" not in result and result.get("unassigned_targets"):
            result["note"] = (
                "Initial one-target-per-drone assignment complete; remaining survivors "
                "are queued for dynamic pickup by the next available drone."
            )

    _set_supply_execution_enabled("error" not in result and bool(result.get("assignments")))
    tool_context.state["supply_assignments"] = json.dumps(result)
    return result


def prepare_parallel_supply_dispatch(tool_context: ToolContext) -> dict:
    """
    Build per-beacon initial survivor assignments plus a shared pending queue.

    Args:
        tool_context: ADK tool context containing supply assignment output.

    Returns:
        Preparation status payload with active assets and queue sizes, or an
        error payload when dispatch setup cannot proceed.
    """
    data = _load_json_state(tool_context.state.get("supply_assignments", "{}"), {})
    if "error" in data:
        _set_active_parallel_supply_loops([])
        return {"error": data["error"], "suggestion": data.get("suggestion", "")}

    assignments: list[dict] = data.get("assignments", [])
    if not assignments:
        supply_targets = _load_json_state(tool_context.state.get("supply_targets", "{}"), {})
        survivors = _dedupe_targets(supply_targets.get("survivors", []))
        _set_active_parallel_supply_loops([])
        if not survivors:
            tool_context.state["supply_no_targets"] = True
            tool_context.state["supply_initial_target_by_asset"] = "{}"
            tool_context.state["supply_pending_targets"] = "[]"
            tool_context.state["supply_claimed_initial_by_asset"] = "{}"
            tool_context.state["supply_done_count_by_asset"] = "{}"
            tool_context.state["supply_results_by_asset"] = "{}"
            tool_context.state["supply_results_list"] = "[]"
            tool_context.state["supply_results_structured"] = "[]"
            tool_context.state["supply_completed_target_keys"] = "[]"
            tool_context.state["supply_inflight_target_keys"] = "[]"
            tool_context.state["active_supply_assets"] = "[]"
            tool_context.state["supply_total_targets"] = 0
            return {
                "success": True,
                "queued_targets": 0,
                "drone_count": 0,
                "active_assets": [],
                "mode": "no_targets",
                "message": "No survivors detected in the selected area. Supply dispatch skipped.",
            }
        return {"error": "No drone assignments available. Cannot proceed with supply dispatch."}

    initial_by_drone: dict[str, dict] = {}
    seen_initial_keys: set[str] = set()
    pending: list[dict] = list(data.get("unassigned_targets", []))
    for row in assignments:
        aid = row.get("asset_id")
        target = _as_dict(row.get("target", row.get("survivor", row.get("building"))))
        if not aid or target is None:
            continue
        key = _target_key(target)
        if key in seen_initial_keys:
            pending.append(target)
            continue
        if aid not in initial_by_drone:
            initial_by_drone[aid] = target
            seen_initial_keys.add(key)
        else:
            pending.append(target)

    if not initial_by_drone:
        _set_active_parallel_supply_loops([])
        return {"error": "No valid assignments available. Cannot proceed with supply dispatch."}

    unique_pending = _dedupe_targets(pending)
    initial_keys = {_target_key(target) for target in initial_by_drone.values()}
    pending = [target for target in unique_pending if _target_key(target) not in initial_keys]

    ordered_aids = sorted(initial_by_drone)
    tool_context.state["supply_initial_target_by_asset"] = json.dumps(initial_by_drone)
    tool_context.state["supply_pending_targets"] = json.dumps(pending)
    tool_context.state["supply_claimed_initial_by_asset"] = json.dumps({aid: False for aid in ordered_aids})
    tool_context.state["supply_done_count_by_asset"] = json.dumps({aid: 0 for aid in ordered_aids})
    tool_context.state["supply_results_by_asset"] = json.dumps({aid: [] for aid in ordered_aids})
    tool_context.state["supply_results_list"] = "[]"
    tool_context.state["supply_results_structured"] = "[]"
    tool_context.state["supply_completed_target_keys"] = "[]"
    tool_context.state["supply_inflight_target_keys"] = "[]"
    tool_context.state["supply_no_targets"] = False
    tool_context.state["active_supply_assets"] = json.dumps(ordered_aids)
    tool_context.state["supply_total_targets"] = len(initial_by_drone) + len(pending)
    _set_active_parallel_supply_loops(ordered_aids)
    return {
        "success": True,
        "queued_targets": len(initial_by_drone) + len(pending),
        "drone_count": len(initial_by_drone),
        "active_assets": ordered_aids,
        "mode": "dynamic_queue_after_initial_assignment",
    }


async def process_next_supply_target_for_asset(asset_id: str, tool_context: ToolContext) -> dict:
    """
    Claim one survivor target for this beacon, dispatch supply, and persist result.
    Loop terminates when no targets remain.

    Args:
        asset_id: Drone asset identifier for this loop instance.
        tool_context: ADK tool context containing shared dispatch state.

    Returns:
        A payload describing completion status, selected target (when any),
        dispatch outcome, and remaining queued work metadata.
    """
    from backend.runtime import grpc_client as runtime_grpc_client
    from backend.services.api.control import dispatch_supply_to_building

    active_assets = _load_json_state(tool_context.state.get("active_supply_assets", "[]"), [])
    if asset_id not in active_assets:
        tool_context.actions.escalate = True
        return {"done": True, "asset_id": asset_id, "total_dispatched": 0}

    status = await runtime_grpc_client.get_status(asset_id)
    drone_x = float(status.get("x", 0.0))
    drone_z = float(status.get("z", 0.0))

    target: dict | None = None
    target_key: str | None = None
    remaining = 0
    dispatched = 0

    async with _SUPPLY_QUEUE_LOCK:
        initial_by_asset = _load_json_state(tool_context.state.get("supply_initial_target_by_asset", "{}"), {})
        pending = _filter_unsupplied_targets(
            _load_json_state(tool_context.state.get("supply_pending_targets", "[]"), [])
        )
        claimed_initial = _load_json_state(tool_context.state.get("supply_claimed_initial_by_asset", "{}"), {})
        done_count = _load_json_state(tool_context.state.get("supply_done_count_by_asset", "{}"), {})
        completed_keys = set(_load_json_state(tool_context.state.get("supply_completed_target_keys", "[]"), []))
        inflight_keys = set(_load_json_state(tool_context.state.get("supply_inflight_target_keys", "[]"), []))

        dispatched = int(done_count.get(asset_id, 0))
        if not bool(claimed_initial.get(asset_id, False)):
            claimed_initial[asset_id] = True
            candidate = _as_dict(initial_by_asset.get(asset_id))
            if candidate is not None:
                candidate_key = _target_key(candidate)
                if candidate_key not in completed_keys and candidate_key not in inflight_keys:
                    target = candidate
                    target_key = candidate_key
                    inflight_keys.add(candidate_key)
                    remaining = len(pending)
        if target is None and pending:
            filtered_pending: list[dict] = []
            for candidate in pending:
                candidate_dict = _as_dict(candidate)
                if candidate_dict is None:
                    continue
                if _target_key(candidate_dict) in completed_keys:
                    continue
                filtered_pending.append(candidate_dict)
            pending = filtered_pending
            pick_index: int | None = None
            closest_dist = float("inf")
            for idx, candidate in enumerate(pending):
                tx = _to_float(candidate.get("x"))
                tz = _to_float(candidate.get("z"))
                if tx is None or tz is None:
                    continue
                candidate_key = _target_key(candidate)
                if candidate_key in completed_keys or candidate_key in inflight_keys:
                    continue
                dist = math.sqrt((tx - drone_x) ** 2 + (tz - drone_z) ** 2)
                if dist < closest_dist:
                    closest_dist = dist
                    pick_index = idx
            if pick_index is not None:
                candidate = pending.pop(pick_index)
                candidate_dict = _as_dict(candidate)
                if candidate_dict is not None:
                    target = candidate_dict
                    target_key = _target_key(candidate_dict)
                    inflight_keys.add(target_key)
                    remaining = len(pending)
        if target is None:
            tool_context.state["supply_claimed_initial_by_asset"] = json.dumps(claimed_initial)
            tool_context.state["supply_pending_targets"] = json.dumps(pending)
            tool_context.state["supply_inflight_target_keys"] = json.dumps(sorted(inflight_keys))
            tool_context.actions.escalate = True
            return {"done": True, "asset_id": asset_id, "total_dispatched": dispatched}

        tool_context.state["supply_claimed_initial_by_asset"] = json.dumps(claimed_initial)
        tool_context.state["supply_pending_targets"] = json.dumps(pending)
        tool_context.state["supply_inflight_target_keys"] = json.dumps(sorted(inflight_keys))

    supply_result = await dispatch_supply_to_building(asset_id=asset_id, building=target)
    skipped = bool(supply_result.get("skipped", False))
    success = "error" not in supply_result and not skipped
    if skipped:
        line = (
            f"Target at (x={float(target['x']):.1f}, z={float(target['z']):.1f}) "
            f"[{asset_id}]: SUPPLY SKIPPED — already delivered."
        )
    elif success:
        line = (
            f"Target at (x={float(target['x']):.1f}, z={float(target['z']):.1f}) "
            f"[{asset_id}]: SUPPLY SENT. Waypoints: {supply_result.get('waypoint_count', '?')}."
        )
    else:
        line = (
            f"Target at (x={float(target['x']):.1f}, z={float(target['z']):.1f}) "
            f"[{asset_id}]: SUPPLY ERROR — {supply_result.get('error', 'Unknown error')}"
        )

    async with _SUPPLY_QUEUE_LOCK:
        done_count = _load_json_state(tool_context.state.get("supply_done_count_by_asset", "{}"), {})
        done_count[asset_id] = int(done_count.get(asset_id, 0)) + 1
        result_map = _load_json_state(tool_context.state.get("supply_results_by_asset", "{}"), {})
        all_results = _load_json_state(tool_context.state.get("supply_results_list", "[]"), [])
        structured_results = _load_json_state(tool_context.state.get("supply_results_structured", "[]"), [])
        completed_keys = set(_load_json_state(tool_context.state.get("supply_completed_target_keys", "[]"), []))
        inflight_keys = set(_load_json_state(tool_context.state.get("supply_inflight_target_keys", "[]"), []))
        prefixed = f"[{asset_id}] {line}"
        bucket = result_map.get(asset_id, [])
        bucket.append(prefixed)
        result_map[asset_id] = bucket
        all_results.append(prefixed)
        structured_results.append(
            {
                "asset_id": asset_id,
                "target": target,
                "success": success,
                "skipped": skipped,
                "message": line,
                "supply_result": supply_result,
            }
        )
        inflight_keys.discard(target_key or _target_key(target))
        if success or skipped:
            completed_keys.add(_target_key(target))
            service_context.register_supplied_target(target)
        tool_context.state["supply_done_count_by_asset"] = json.dumps(done_count)
        tool_context.state["supply_results_by_asset"] = json.dumps(result_map)
        tool_context.state["supply_results_list"] = json.dumps(all_results)
        tool_context.state["supply_results_structured"] = json.dumps(structured_results)
        tool_context.state["supply_completed_target_keys"] = json.dumps(sorted(completed_keys))
        tool_context.state["supply_inflight_target_keys"] = json.dumps(sorted(inflight_keys))

    return {
        "done": False,
        "asset_id": asset_id,
        "target": target,
        "remaining": remaining,
        "success": success,
        "message": line,
        "results": [{"asset_id": asset_id, "target": target, "supply_result": supply_result}],
    }


def build_aggregated_supply_report(tool_context: ToolContext) -> dict:
    """Build one deterministic final report from saved supply results.

    Args:
        tool_context: ADK tool context containing accumulated supply results.

    Returns:
        Final summary payload with totals, failures/skips, and raw result rows.
    """
    if bool(tool_context.state.get("supply_no_targets", False)):
        summary = "No survivors detected in the selected area. Supply dispatch skipped."
        return {
            "success": True,
            "summary": summary,
            "total_targets": 0,
            "total_supplied": 0,
            "failed_targets": 0,
            "results": [],
        }

    rows = _load_json_state(tool_context.state.get("supply_results_structured", "[]"), [])
    total_targets = int(tool_context.state.get("supply_total_targets", 0) or 0)
    if total_targets <= 0:
        total_targets = len(rows)

    total_supplied = 0
    failed = 0
    skipped_targets = 0
    grouped_lines: dict[str, list[str]] = {}
    for row in rows:
        row_dict = _as_dict(row)
        if row_dict is None:
            continue
        asset_id = str(row_dict.get("asset_id", "UNKNOWN"))
        message = str(row_dict.get("message", "")).strip()
        if bool(row_dict.get("success")):
            total_supplied += 1
        elif bool(row_dict.get("skipped")):
            skipped_targets += 1
        else:
            failed += 1
        grouped_lines.setdefault(asset_id, []).append(message)

    lines: list[str] = []
    for asset_id, sections in grouped_lines.items():
        if lines:
            lines.append("")
        lines.append(asset_id)
        lines.extend(sections)

    div = "═" * 39
    thin = "─" * 39
    total_line = (
        "No supplies dispatched."
        if total_supplied == 0
        else f"TOTAL SUPPLY DISPATCHED: {total_supplied}"
    )
    failure_line = f"FAILED TARGETS: {failed}" if failed > 0 else "FAILED TARGETS: 0"
    skipped_line = (
        f"SKIPPED TARGETS: {skipped_targets}"
        if skipped_targets > 0
        else "SKIPPED TARGETS: 0"
    )
    summary = (
        f"{div}\n"
        f"  AREA SUPPLY DISPATCH COMPLETE — {total_targets} survivor(s)\n"
        f"{div}\n"
        + ("\n".join(lines) if lines else "No supply dispatch results recorded.")
        + f"\n{thin}\n{total_line}\n{failure_line}\n{skipped_line}\n{div}"
    )
    return {
        "success": True,
        "summary": summary,
        "total_targets": total_targets,
        "total_supplied": total_supplied,
        "failed_targets": failed,
        "skipped_targets": skipped_targets,
        "results": rows,
    }


_assign_supply_tool = FunctionTool(func=assign_drones_to_supply_targets)
_prepare_supply_tool = FunctionTool(func=prepare_parallel_supply_dispatch)
_build_supply_report_tool = FunctionTool(func=build_aggregated_supply_report)


def _asset_suffix(asset_id: str) -> str:
    """Normalize an asset id into a safe generated-name suffix.

    Args:
        asset_id: Drone asset identifier.

    Returns:
        Lowercased, hyphen-normalized suffix string safe for agent/tool names.
    """
    return asset_id.lower().replace("-", "_")


def _make_asset_supply_loop(asset_id: str) -> LoopAgent:
    """Create a per-asset supply LoopAgent pipeline.

    Args:
        asset_id: Drone asset identifier used to bind generated tools/agents.

    Returns:
        Configured LoopAgent that repeatedly dispatches queued targets for the
        provided asset.
    """
    suffix = _asset_suffix(asset_id)

    async def _process_asset_supply(tool_context: ToolContext) -> dict:
        """Dispatch the next queued supply target for this asset.

        Args:
            tool_context: ADK tool context containing mutable dispatch state.

        Returns:
            Per-iteration dispatch result payload for this asset.
        """
        return await process_next_supply_target_for_asset(asset_id, tool_context)

    _process_asset_supply.__name__ = f"process_next_supply_target_{suffix}"
    process_tool = FunctionTool(func=_process_asset_supply)

    worker_instruction = ASSET_SUPPLY_WORKER_INSTRUCTION_TEMPLATE.format(
        asset_id=asset_id,
        process_function_name=_process_asset_supply.__name__,
    )

    worker_agent = Agent(
        name=f"supply_worker_agent_{suffix}",
        model=QWEN3_INSTRUCT,
        description=f"Dispatches queued supply targets for {asset_id}.",
        generate_content_config=QWEN3_GEN_CONFIG,
        instruction=worker_instruction,
        tools=[process_tool],
    )

    return LoopAgent(
        name=f"supply_dispatch_loop_{suffix}",
        description=f"Loop supply pipeline for {asset_id}: pick -> dispatch -> repeat.",
        max_iterations=200,
        sub_agents=[worker_agent],
    )


_asset_supply_loop_cache: dict[str, LoopAgent] = {}


def _get_or_create_asset_supply_loop(asset_id: str) -> LoopAgent:
    """Fetch a cached per-asset supply loop or create one.

    Args:
        asset_id: Drone asset identifier.

    Returns:
        Cached or newly created LoopAgent instance for the asset.
    """
    loop = _asset_supply_loop_cache.get(asset_id)
    if loop is None:
        loop = _make_asset_supply_loop(asset_id)
        _asset_supply_loop_cache[asset_id] = loop
    return loop


_fleet_parallel_supply_loops = ParallelAgent(
    name="fleet_parallel_supply_loops",
    description="Runs one supply LoopAgent per BEACON in parallel for true multi-drone dispatch.",
    sub_agents=[_get_or_create_asset_supply_loop(asset_id) for asset_id in _PARALLEL_BEACON_IDS],
)


def _set_active_parallel_supply_loops(asset_ids: list[str]) -> None:
    """Configure active parallel supply loops from assigned assets.

    Args:
        asset_ids: Asset identifiers that should run parallel supply loops.

    Returns:
        None. Updates parallel agent sub-agent configuration in place.
    """
    _fleet_parallel_supply_loops.sub_agents = [
        _get_or_create_asset_supply_loop(asset_id)
        for asset_id in asset_ids
    ]


_SUPPLY_RESOLVER_INSTRUCTION = SUPPLY_RESOLVER_INSTRUCTION

_supply_resolver_agent = Agent(
    name="supply_resolver_agent",
    model=QWEN3_INSTRUCT,
    description="Resolves supply targets as a survivor list.",
    generate_content_config=QWEN3_GEN_CONFIG,
    output_key="supply_targets",
    instruction=_SUPPLY_RESOLVER_INSTRUCTION,
    tools=[make_toolset(["find_survivors_in_area"])],
)


_SUPPLY_ASSIGNER_INSTRUCTION = SUPPLY_ASSIGNER_INSTRUCTION

_supply_assigner_agent = Agent(
    name="supply_assigner_agent",
    model=QWEN3_INSTRUCT,
    description="Assigns closest available IDLE drones to survivor targets.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_SUPPLY_ASSIGNER_INSTRUCTION,
    tools=[_assign_supply_tool],
)


_SUPPLY_EXECUTOR_INSTRUCTION = SUPPLY_EXECUTOR_INSTRUCTION

_supply_prep_agent = Agent(
    name="supply_prep_agent",
    model=QWEN3_INSTRUCT,
    description="Prepares a parallel survivor dispatch queue for LoopAgent execution.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_SUPPLY_EXECUTOR_INSTRUCTION,
    tools=[_prepare_supply_tool],
)


_SUPPLY_REPORT_INSTRUCTION = SUPPLY_REPORT_INSTRUCTION

_supply_report_agent = Agent(
    name="supply_report_agent",
    model=QWEN3_INSTRUCT,
    description="Reads accumulated supply results and emits one consolidated final report.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_SUPPLY_REPORT_INSTRUCTION,
    tools=[_build_supply_report_tool],
)


_supply_assignment_stage = SequentialAgent(
    name="supply_assignment_stage",
    description="Resolve survivor targets first, then perform fleet assignment.",
    sub_agents=[_supply_resolver_agent, _supply_assigner_agent],
)

_supply_execution_stage = SequentialAgent(
    name="supply_execution_stage",
    description=(
        "Run parallel survivor supply dispatch via one LoopAgent per BEACON "
        "(pick -> dispatch) until all targets are processed."
    ),
    sub_agents=[_supply_prep_agent, _fleet_parallel_supply_loops, _supply_report_agent],
)


def _set_supply_execution_enabled(enabled: bool) -> None:
    """Enable or disable supply execution stage sub-agents.

    Args:
        enabled: True to enable execution stage pipeline; False to disable it.

    Returns:
        None. Mutates execution stage sub-agent list in place.
    """
    if enabled:
        _supply_execution_stage.sub_agents = [
            _supply_prep_agent,
            _fleet_parallel_supply_loops,
            _supply_report_agent,
        ]
    else:
        _supply_execution_stage.sub_agents = []


supply_agent = SequentialAgent(
    name="supply_agent",
    description=(
        "Dispatch emergency supplies to one or more survivors and emit one final report. "
        "Automatically assigns the closest available drones in parallel and keeps "
        "dispatching until all survivor targets in the selected area are processed."
    ),
    sub_agents=[_supply_assignment_stage, _supply_execution_stage],
)
