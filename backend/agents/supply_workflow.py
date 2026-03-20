"""Supply Workflow — survivor resolver + fleet assignment + parallel LoopAgent dispatch."""
from __future__ import annotations

import asyncio
import json
import math

from google.adk.agents import Agent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from backend.agents._mcp import make_toolset
from backend.agents._model import GEN_CONFIG, MODEL
from backend.services.core import context as service_context

_SUPPLY_QUEUE_LOCK = asyncio.Lock()
_PARALLEL_BEACON_IDS = ["BEACON-01"]


def _strip_code_fences(raw: str) -> str:
    stripped = raw.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


def _load_json_state(value: object, fallback):
    try:
        if isinstance(value, str):
            return json.loads(_strip_code_fences(value))
        return value if value is not None else fallback
    except (json.JSONDecodeError, TypeError):
        return fallback


def _target_key(target: dict) -> str:
    sid = target.get("id")
    if isinstance(sid, int):
        return f"id:{sid}"
    if isinstance(sid, float) and sid.is_integer():
        return f"id:{int(sid)}"
    if isinstance(sid, str):
        normalized = sid.strip()
        if normalized:
            if normalized.isdigit():
                return f"id:{int(normalized)}"
            return f"id:{normalized.lower()}"
    x = float(target.get("x", 0.0))
    y = float(target.get("y", 0.0))
    z = float(target.get("z", 0.0))
    return f"xyz:{x:.2f},{y:.2f},{z:.2f}"


def _dedupe_targets(targets: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        key = _target_key(target)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(target)
    return deduped


def _filter_unsupplied_targets(targets: list[dict]) -> list[dict]:
    supplied_keys = service_context.get_supplied_target_keys()
    return [
        target
        for target in targets
        if isinstance(target, dict) and _target_key(target) not in supplied_keys
    ]


async def assign_drones_to_supply_targets(tool_context: ToolContext) -> dict:
    """
    Read state["supply_targets"], assign closest available drones, and persist
    assignment payload into state["supply_assignments"].
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
        target = row.get("target", row.get("survivor", row.get("building")))
        if not aid or not isinstance(target, dict):
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
            candidate = initial_by_asset.get(asset_id)
            if isinstance(candidate, dict):
                candidate_key = _target_key(candidate)
                if candidate_key not in completed_keys and candidate_key not in inflight_keys:
                    target = candidate
                    target_key = candidate_key
                    inflight_keys.add(candidate_key)
                    remaining = len(pending)
        if target is None and pending:
            filtered_pending: list[dict] = []
            for candidate in pending:
                if not isinstance(candidate, dict):
                    continue
                if _target_key(candidate) in completed_keys:
                    continue
                filtered_pending.append(candidate)
            pending = filtered_pending
            pick_index: int | None = None
            closest_dist = float("inf")
            for idx, candidate in enumerate(pending):
                tx = candidate.get("x")
                tz = candidate.get("z")
                if not isinstance(tx, (int, float)) or not isinstance(tz, (int, float)):
                    continue
                candidate_key = _target_key(candidate)
                if candidate_key in completed_keys or candidate_key in inflight_keys:
                    continue
                dist = math.sqrt((float(tx) - drone_x) ** 2 + (float(tz) - drone_z) ** 2)
                if dist < closest_dist:
                    closest_dist = dist
                    pick_index = idx
            if pick_index is not None:
                candidate = pending.pop(pick_index)
                if isinstance(candidate, dict):
                    target = candidate
                    target_key = _target_key(candidate)
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
    """Build one deterministic final report from all saved supply results."""
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
        if not isinstance(row, dict):
            continue
        asset_id = str(row.get("asset_id", "UNKNOWN"))
        message = str(row.get("message", "")).strip()
        if bool(row.get("success")):
            total_supplied += 1
        elif bool(row.get("skipped")):
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
    return asset_id.lower().replace("-", "_")


def _make_asset_supply_loop(asset_id: str) -> LoopAgent:
    suffix = _asset_suffix(asset_id)

    async def _process_asset_supply(tool_context: ToolContext) -> dict:
        return await process_next_supply_target_for_asset(asset_id, tool_context)

    _process_asset_supply.__name__ = f"process_next_supply_target_{suffix}"
    process_tool = FunctionTool(func=_process_asset_supply)

    worker_instruction = f"""You execute the per-drone supply dispatch loop for {asset_id}.

1. Call {_process_asset_supply.__name__}().
2. If done=true: output "QUEUE_EMPTY" and stop.
3. If done=false:
   - If success=true: output message exactly from result["message"].
   - If success=false: output message exactly from result["message"] and continue.
"""

    worker_agent = Agent(
        name=f"supply_worker_agent_{suffix}",
        model=MODEL,
        description=f"Dispatches queued supply targets for {asset_id}.",
        generate_content_config=GEN_CONFIG,
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
    _fleet_parallel_supply_loops.sub_agents = [
        _get_or_create_asset_supply_loop(asset_id)
        for asset_id in asset_ids
    ]


_SUPPLY_RESOLVER_INSTRUCTION = """You build the list of survivors to receive supplies.

COORDINATES: X=East, Y=Up, Z=South.

MULTI-POINT EXPLICIT — command lists two or more coordinates:
  1. For EACH coordinate, call
     find_survivors_in_area(center_x, center_z, radius=4.0, detected_only=true, require_all_detected=true).
  2. Add returned survivors to one combined list (deduplicate by survivor id).
  3. asset_id = the asset_id from the command; if none is mentioned use "auto".

SINGLE TARGET — command targets one specific coordinate/building:
  1. Call find_survivors_in_area(center_x, center_z, radius=8.0, detected_only=true, require_all_detected=true).
  2. Use returned survivors as the list (nearest-first).
  3. asset_id = the asset_id from the command; if none is mentioned use "auto".

AREA TARGET — command mentions area / zone / radius / "all buildings":
  1. If bounds are provided (from x1,z1 to x2,z2), derive center and radius:
     center_x = (x1+x2)/2, center_z = (z1+z2)/2, radius = max(|x2-x1|, |z2-z1|)/2.
  2. Call find_survivors_in_area(
       center_x, center_z, radius, detected_only=true, require_all_detected=true
     ).
      Default radius = 30.0 m unless specified.
  3. asset_id = "auto" unless a specific drone is explicitly requested.

If the tool response indicates survivors=[] (or detection_gate_blocked=true),
output survivors as [] so supply dispatch is skipped.

ASSET ID RULE: Use "auto" whenever no specific drone is named in the command.
Only use a real asset_id (e.g. "BEACON-01") when explicitly named.

Output ONLY valid JSON — no markdown, no extra text:
  {"asset_id": "<asset_id or auto>", "survivors": [<survivor objects>]}

Each survivor object must have: id, x, y, z.
"""

_supply_resolver_agent = Agent(
    name="supply_resolver_agent",
    model=MODEL,
    description="Resolves supply targets as a survivor list.",
    generate_content_config=GEN_CONFIG,
    output_key="supply_targets",
    instruction=_SUPPLY_RESOLVER_INSTRUCTION,
    tools=[make_toolset(["find_survivors_in_area"])],
)


_SUPPLY_ASSIGNER_INSTRUCTION = """You assign available drones to survivor targets.

1. Call assign_drones_to_supply_targets().
2. If result contains "error": output the error and stop.
3. If total_assigned is 0 and unassigned_targets is empty: output exactly
   "No survivors detected in the selected area. Supply dispatch skipped." and stop.
4. Otherwise output a concise assignment summary:
   Fleet assigned: <total_assigned> drone(s) dispatched.
   <asset_id> → Survivor target at (x=<x>, z=<z>) [<distance_m>m]
   If unassigned_targets exists: "<N> target(s) queued for dynamic pickup."
"""

_supply_assigner_agent = Agent(
    name="supply_assigner_agent",
    model=MODEL,
    description="Assigns closest available IDLE drones to survivor targets.",
    generate_content_config=GEN_CONFIG,
    instruction=_SUPPLY_ASSIGNER_INSTRUCTION,
    tools=[_assign_supply_tool],
)


_SUPPLY_EXECUTOR_INSTRUCTION = """You execute supply dispatch for all assigned drones.

1. Call prepare_parallel_supply_dispatch().
2. If result contains "error": output the error and stop.
3. If result["mode"] == "no_targets", output result["message"] and stop.
4. If success=true, confirm one LoopAgent per BEACON will run in parallel, then continue.
"""

_supply_prep_agent = Agent(
    name="supply_prep_agent",
    model=MODEL,
    description="Prepares a parallel survivor dispatch queue for LoopAgent execution.",
    generate_content_config=GEN_CONFIG,
    instruction=_SUPPLY_EXECUTOR_INSTRUCTION,
    tools=[_prepare_supply_tool],
)


_SUPPLY_REPORT_INSTRUCTION = """You produce the final consolidated supply report.

1. Call build_aggregated_supply_report().
2. If success=true, output result["summary"] verbatim.
3. Do NOT add markdown or extra explanation.
"""

_supply_report_agent = Agent(
    name="supply_report_agent",
    model=MODEL,
    description="Reads accumulated supply results and emits one consolidated final report.",
    generate_content_config=GEN_CONFIG,
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
    if enabled:
        _supply_execution_stage.sub_agents = [
            _supply_prep_agent,
            _fleet_parallel_supply_loops,
            _supply_report_agent,
        ]
    else:
        _supply_execution_stage.sub_agents = []


supply_workflow = SequentialAgent(
    name="supply_workflow",
    description=(
        "Dispatch emergency supplies to one or more survivors and emit one final report. "
        "Automatically assigns the closest available drones in parallel and keeps "
        "dispatching until all survivor targets in the selected area are processed."
    ),
    sub_agents=[_supply_assignment_stage, _supply_execution_stage],
)
