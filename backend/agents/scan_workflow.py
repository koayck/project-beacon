"""
Scan Workflow — fleet assignment first, then fleet scan loop until all assigned
buildings are completed, then emit one consolidated final report.

Workflow:
  1) Commander routes mission command to scan_workflow.
    2) Fleet assignment stage assigns drones using pre-resolved scan_buildings.
  3) Parallel fleet scan stage prepares an interleaved mission queue.
  4) LoopAgent runs pick -> navigate -> sweep-scan repeatedly until done.
  5) Final report agent emits one consolidated operator report.

Structure:
    scan_workflow (SequentialAgent)
    ├── fleet_assignment_stage    # assignment from pre-resolved targets
    └── fleet_scan_executor_agent # prepare queue + LoopAgent + final reporter

Session state keys:
    scan_buildings        JSON — {"asset_id": str | "auto", "buildings": [{...}], ...}
    fleet_assignments     JSON — {"assignments": [{asset_id, building, ...}], ...}
    buildings_scan_index  int  — legacy queue index key (retained for compatibility)
    scan_results_list     JSON — compact per-building report lines
"""
from __future__ import annotations

import asyncio
import json
import math
import re
from typing import Any

from google.adk.agents import Agent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from backend.agents._mcp import NAV_TOOLS, THERMAL_TOOLS, make_toolset
from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.instructions.scan_workflow_text import (
    ASSET_SCAN_NAV_INSTRUCTION_TEMPLATE,
    ASSET_SCAN_PICKER_INSTRUCTION_TEMPLATE,
    ASSET_SCAN_THERMAL_INSTRUCTION_TEMPLATE,
    SCAN_FLEET_ASSIGNER_INSTRUCTION,
    SCAN_FLEET_EXECUTOR_INSTRUCTION,
    SCAN_REPORT_INSTRUCTION,
)

_SCAN_QUEUE_LOCK = asyncio.Lock()
_RESULT_ASSET_PREFIX_RE = re.compile(r"^\[(?P<asset>[A-Za-z0-9_-]+)\]\s*(?P<body>.*)$", re.DOTALL)
_RESULT_BUILDING_COORD_RE = re.compile(
    r"^Building at \(x=(?P<x>-?\d+(?:\.\d+)?), z=(?P<z>-?\d+(?:\.\d+)?)\):"
)
_RESULT_SURVIVOR_LINE_RE = re.compile(
    r"^\s*-\s*Survivor\s+(?P<id>\d+):\s+\("
    r"(?P<x>-?\d+(?:\.\d+)?),\s*(?P<y>-?\d+(?:\.\d+)?),\s*(?P<z>-?\d+(?:\.\d+)?)\)"
    r"(?P<tag>.*)$"
)
_CROSS_BUILDING_SURVIVOR_DISTANCE_M = 6.0


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


def _as_list(value: object) -> list | None:
    """Return a list-like value when possible.

    Args:
        value: Candidate object to validate as mutable list-like.

    Returns:
        The original object when it behaves like a mutable list, otherwise None.
    """
    try:
        value.append  # type: ignore[attr-defined]
        value.__iter__  # type: ignore[attr-defined]
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


def _to_non_negative_int(value: Any) -> int | None:
    """Convert an arbitrary value to a non-negative integer.

    Args:
        value: Value to convert.

    Returns:
        A non-negative integer, or None when conversion fails or value is negative.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number


def _building_dedupe_key(building: dict) -> tuple[str, str] | None:
    """Build a stable deduplication key for a building target.

    Args:
        building: Building payload containing id and/or coordinate fields.

    Returns:
        A tagged key tuple using building id when available, coordinate fallback
        when id is missing, or None when no valid key can be derived.
    """
    building_dict = _as_dict(building)
    if building_dict is None:
        return None

    building_id = _to_non_negative_int(building_dict.get("id"))
    if building_id is not None:
        return ("id", str(building_id))

    x = _to_float(building_dict.get("x"))
    z = _to_float(building_dict.get("z"))
    if x is not None and z is not None:
        # Coordinate fallback for ad-hoc targets where id may be -1 or absent.
        return ("coord", f"{x:.3f},{z:.3f}")

    return None


def _dedupe_buildings(buildings: list[dict]) -> list[dict]:
    """Remove duplicate building targets while preserving first-seen order.

    Args:
        buildings: Raw building target list.

    Returns:
        A deduplicated list preserving the original order of first occurrence.
    """
    seen: set[tuple[str, str]] = set()
    unique: list[dict] = []
    for building in buildings:
        key = _building_dedupe_key(building)
        if key is None:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(building)
    return unique


# ── Queue FunctionTools ────────────────────────────────────────────────────────


def get_shared_state(tool_context: ToolContext) -> dict:
    """Expose current shared loop state.

    Args:
        tool_context: ADK tool context containing current workflow state.

    Returns:
        A payload containing a dictionary snapshot of tool context state.
    """
    return {"state": tool_context.state.to_dict()}


def _split_scan_result_asset(result_text: str) -> tuple[str | None, str]:
    """Split optional asset prefix from a saved scan line.

    Args:
        result_text: Raw saved scan result line.

    Returns:
        A tuple of asset id (or None) and normalized message body.
    """
    stripped = result_text.strip()
    match = _RESULT_ASSET_PREFIX_RE.match(stripped)
    if not match:
        return None, stripped
    return match.group("asset"), str(match.group("body") or "").strip()


def _format_split_survivor_sections(result_body: str) -> str:
    """Reformat survivor lines into building-grouped sections.

    Args:
        result_body: Building-level scan report body.

    Returns:
        Reformatted report text where cross-building survivors are split into
        separate synthetic building sections.
    """
    lines = [line.rstrip() for line in result_body.splitlines() if line.strip()]
    if not lines:
        return result_body.strip()

    header = lines[0]
    header_match = _RESULT_BUILDING_COORD_RE.match(header)
    if not header_match:
        return "\n".join(lines)

    center_x = float(header_match.group("x"))
    center_z = float(header_match.group("z"))
    survivor_rows: list[tuple[str, float, float]] = []
    passthrough_rows: list[str] = []
    for line in lines[1:]:
        survivor_match = _RESULT_SURVIVOR_LINE_RE.match(line)
        if survivor_match:
            survivor_rows.append(
                (line, float(survivor_match.group("x")), float(survivor_match.group("z")))
            )
        else:
            passthrough_rows.append(line)

    if not survivor_rows:
        return "\n".join(lines)

    primary_rows: list[str] = []
    cross_building_groups: dict[tuple[float, float], list[str]] = {}
    for line, survivor_x, survivor_z in survivor_rows:
        distance = math.hypot(survivor_x - center_x, survivor_z - center_z)
        if distance <= _CROSS_BUILDING_SURVIVOR_DISTANCE_M:
            primary_rows.append(line)
            continue
        key = (round(survivor_x, 1), round(survivor_z, 1))
        cross_building_groups.setdefault(key, []).append(line)

    if not cross_building_groups or not primary_rows:
        return "\n".join(lines)

    rendered = [header, *primary_rows, *passthrough_rows]
    for (building_x, building_z), group in sorted(cross_building_groups.items()):
        rendered.append("")
        rendered.append(
            f"Building at (x={building_x:.1f}, z={building_z:.1f}): {len(group)} survivor(s)"
        )
        rendered.extend(group)
    return "\n".join(rendered)


def build_aggregated_scan_report(tool_context: ToolContext) -> dict:
    """Build a deterministic final scan report from accumulated results.

    Args:
        tool_context: ADK tool context containing scan result state.

    Returns:
        A payload containing summary text, aggregate totals, and raw result rows.
    """
    raw = tool_context.state.get("scan_results_list", "[]")
    try:
        results: list[str] = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        results = []

    survivor_re = re.compile(r":\s*(\d+)\s+survivor\(s\)")
    total_survivors = 0
    grouped_lines: dict[str, list[str]] = {}
    ungrouped_lines: list[str] = []

    for idx, item in enumerate(results, start=1):
        text = str(item)
        asset_id, body = _split_scan_result_asset(text)
        first_line = body.splitlines()[0] if body else ""
        match = survivor_re.search(first_line)
        if match:
            total_survivors += int(match.group(1))
        if asset_id is None:
            ungrouped_lines.append(f"Building {idx}: {body}")
            continue
        grouped_lines.setdefault(asset_id, []).append(_format_split_survivor_sections(body))

    lines: list[str] = []
    for asset_id, sections in grouped_lines.items():
        if lines:
            lines.append("")
        lines.append(asset_id)
        for section_index, section in enumerate(sections):
            if section_index > 0:
                lines.append("")
            lines.append(section)

    if ungrouped_lines:
        if lines:
            lines.append("")
        lines.extend(ungrouped_lines)

    total_buildings = len(results)
    div = "═" * 39
    thin = "─" * 39
    total_line = (
        "No heat signatures detected across all scanned buildings."
        if total_survivors == 0
        else f"TOTAL SURVIVORS DETECTED: {total_survivors}"
    )
    summary = (
        f"{div}\n"
        f"  AREA SCAN COMPLETE — {total_buildings} building(s)\n"
        f"{div}\n"
        + ("\n".join(lines) if lines else "No building scan results recorded.")
        + f"\n{thin}\n{total_line}\n{div}"
    )

    _trigger_mission_complete_recall(tool_context)

    return {
        "success": True,
        "summary": summary,
        "total_buildings_scanned": total_buildings,
        "total_survivors": total_survivors,
        "results": results,
    }


def _trigger_mission_complete_recall(tool_context: ToolContext) -> None:
    """Schedule post-mission recall for every drone that participated.

    Idempotent via the ``mission_recall_scheduled`` state flag — build_aggregated
    _scan_report may be reached through multiple paths (loop-exit + reporter
    agent), but the recall tasks must only spawn once per mission.
    """
    if tool_context.state.get("mission_recall_scheduled"):
        return

    raw_assets = tool_context.state.get("active_fleet_assets", "[]")
    try:
        asset_ids = (
            json.loads(raw_assets) if isinstance(raw_assets, str) else raw_assets
        )
    except (json.JSONDecodeError, TypeError):
        asset_ids = []
    if not isinstance(asset_ids, list) or not asset_ids:
        return

    try:
        from backend.runtime import grpc_client as runtime_grpc_client
        from backend.runtime import ws_broadcaster
        from backend.services.api import return_to_base
        from backend.services.mission_recall import schedule_mission_complete_recall
    except Exception:  # noqa: BLE001
        import logging as _logging
        _logging.getLogger(__name__).exception(
            "Failed to import mission_recall dependencies; skipping post-mission recall",
        )
        return

    schedule_mission_complete_recall(
        asset_ids,
        get_status=runtime_grpc_client.get_status,
        return_to_base_fn=return_to_base,
        publish_event=ws_broadcaster.broadcast,
        trigger_reason="scan_mission_complete",
    )
    tool_context.state["mission_recall_scheduled"] = True


_build_report_tool = FunctionTool(func=build_aggregated_scan_report)


# ── Fleet orchestration FunctionTools ─────────────────────────────────────────

async def assign_drones_to_buildings(tool_context: ToolContext) -> dict:
    """
    Read state["scan_buildings"], assign the closest available IDLE drones to
    each building using greedy nearest-first matching, and write the result to
    state["fleet_assignments"].

    When asset_id is an explicit drone ID only the first building is assigned
    initially; remaining buildings stay queued for dynamic pickup.
    When asset_id is "auto" or absent the full fleet is queried for assignments.

    Args:
        tool_context: ADK tool context containing resolved scan targets.

    Returns:
        Fleet assignment payload persisted to state, including assignments,
        unassigned buildings, and optional notes/errors.
    """
    from backend.services.api import assign_fleet_to_buildings

    raw = tool_context.state.get("scan_buildings", "{}")
    if isinstance(raw, str):
        # Strip markdown code fences the LLM occasionally emits
        stripped = raw.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[-1]
            stripped = stripped.rsplit("```", 1)[0]
            raw = stripped.strip()
    try:
        scan_data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        scan_data = {}

    buildings_raw: list[dict] = scan_data.get("buildings", [])
    buildings = _dedupe_buildings(buildings_raw)
    scan_data["buildings"] = buildings
    tool_context.state["scan_buildings"] = json.dumps(scan_data)
    asset_id: str = scan_data.get("asset_id", "auto") or "auto"

    if asset_id.upper() == "BEACON-SCOUT":
        asset_id = "auto"
        scan_data["asset_id"] = asset_id
        tool_context.state["scan_buildings"] = json.dumps(scan_data)

    if asset_id.upper() not in ("AUTO", "", "UNKNOWN"):
        # Explicit single-drone: assign only first building now; keep the rest queued.
        if not buildings:
            result: dict = {"assignments": [], "unassigned_buildings": [], "idle_drones": []}
        else:
            result = {
                "assignments": [{"asset_id": asset_id, "building": buildings[0], "distance_m": 0.0}],
                "unassigned_buildings": buildings[1:],
                "idle_drones": [],
                "note": f"Single drone {asset_id} assigned initial building; remaining queued dynamically.",
                "total_assigned": 1,
            }
    else:
        result = await assign_fleet_to_buildings(buildings)
        if "error" not in result and result.get("unassigned_buildings"):
            result["note"] = (
                "Initial one-building-per-drone assignment complete; remaining "
                "buildings are queued for dynamic pickup by whichever drone finishes first."
            )

    tool_context.state["fleet_assignments"] = json.dumps(result)
    return result


def prepare_parallel_fleet_scan(tool_context: ToolContext) -> dict:
    """
    Build per-beacon initial assignments plus shared pending queue.

    Args:
        tool_context: ADK tool context containing fleet assignment output.

    Returns:
        Preparation status payload with active assets and queue sizes, or an
        error payload when preparation cannot proceed.
    """
    raw = tool_context.state.get("fleet_assignments", "{}")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        data = {}

    if "error" in data:
        return {"error": data["error"], "suggestion": data.get("suggestion", "")}

    assignments: list[dict] = data.get("assignments", [])
    if not assignments:
        return {"error": "No drone assignments available. Cannot proceed with scan."}

    initial_by_drone: dict[str, dict] = {}
    assigned_keys: set[tuple[str, str]] = set()
    pending_raw: list[dict] = list(data.get("unassigned_buildings", []))
    for row in assignments:
        aid = row.get("asset_id")
        building = _as_dict(row.get("building"))
        if not aid or building is None:
            continue
        key = _building_dedupe_key(building)
        if aid not in initial_by_drone and key is not None and key not in assigned_keys:
            initial_by_drone[aid] = building
            assigned_keys.add(key)
        else:
            pending_raw.append(building)

    used_keys = {
        key
        for key in (_building_dedupe_key(building) for building in initial_by_drone.values())
        if key is not None
    }
    pending: list[dict] = []
    for building in _dedupe_buildings(pending_raw):
        key = _building_dedupe_key(building)
        if key is None or key in used_keys:
            continue
        used_keys.add(key)
        pending.append(building)

    if not initial_by_drone:
        return {"error": "No valid assignments available. Cannot proceed with scan."}

    ordered_aids = sorted(initial_by_drone)
    queue_enabled = len(pending) > 0
    done_count_by_asset = {aid: 0 for aid in ordered_aids}
    claimed_initial_by_asset = {aid: False for aid in ordered_aids}
    tool_context.state["buildings_scan_index"] = 0
    tool_context.state["scan_results_list"] = "[]"
    tool_context.state["scan_initial_building_by_asset"] = json.dumps(initial_by_drone)
    tool_context.state["scan_pending_buildings"] = json.dumps(pending)
    tool_context.state["scan_claimed_initial_by_asset"] = json.dumps(claimed_initial_by_asset)
    tool_context.state["scan_done_count_by_asset"] = json.dumps(done_count_by_asset)
    tool_context.state["scan_results_by_asset"] = json.dumps({aid: [] for aid in ordered_aids})
    tool_context.state["active_fleet_assets"] = json.dumps(ordered_aids)
    tool_context.state["scan_total_buildings"] = len(initial_by_drone) + len(pending)
    tool_context.state["scan_queue_enabled"] = queue_enabled
    tool_context.state["scan_summary_emitted"] = False
    _set_active_parallel_loops(ordered_aids)
    return {
        "success": True,
        "queued_buildings": len(initial_by_drone) + len(pending),
        "drone_count": len(initial_by_drone),
        "active_assets": ordered_aids,
        "mode": (
            "dynamic_queue_after_initial_assignment"
            if queue_enabled
            else "initial_assignment_only_no_queue"
        ),
    }


_assign_drones_tool = FunctionTool(func=assign_drones_to_buildings)
_prepare_fleet_scan_tool = FunctionTool(func=prepare_parallel_fleet_scan)


async def pick_next_building_for_asset(asset_id: str, tool_context: ToolContext) -> dict:
    """Claim the next building for a specific asset.

    Args:
        asset_id: Drone asset identifier for this loop instance.
        tool_context: ADK tool context containing shared queue state.

    Returns:
        A payload with done status and either the claimed building or completion
        metadata when no work remains.
    """
    raw_assets = tool_context.state.get("active_fleet_assets", "[]")
    raw_initial = tool_context.state.get("scan_initial_building_by_asset", "{}")
    raw_pending = tool_context.state.get("scan_pending_buildings", "[]")
    queue_enabled_raw = tool_context.state.get("scan_queue_enabled", True)
    raw_claimed = tool_context.state.get("scan_claimed_initial_by_asset", "{}")
    raw_done_count = tool_context.state.get("scan_done_count_by_asset", "{}")
    try:
        active_assets = json.loads(raw_assets) if isinstance(raw_assets, str) else raw_assets
    except (json.JSONDecodeError, TypeError):
        active_assets = []
    try:
        initial_by_asset = json.loads(raw_initial) if isinstance(raw_initial, str) else raw_initial
    except (json.JSONDecodeError, TypeError):
        initial_by_asset = {}
    try:
        pending = json.loads(raw_pending) if isinstance(raw_pending, str) else raw_pending
    except (json.JSONDecodeError, TypeError):
        pending = []
    try:
        claimed_initial = json.loads(raw_claimed) if isinstance(raw_claimed, str) else raw_claimed
    except (json.JSONDecodeError, TypeError):
        claimed_initial = {}
    try:
        done_count = json.loads(raw_done_count) if isinstance(raw_done_count, str) else raw_done_count
    except (json.JSONDecodeError, TypeError):
        done_count = {}

    if isinstance(queue_enabled_raw, str):
        queue_enabled = queue_enabled_raw.strip().lower() not in {"false", "0", "no", "off"}
    else:
        queue_enabled = bool(queue_enabled_raw)

    # Fast-path: when queueing is disabled, each asset has at most one initial
    # assignment and should not attempt any further queue claims.
    if not queue_enabled and bool(claimed_initial.get(asset_id, False)):
        scanned = int(done_count.get(asset_id, 0))
        tool_context.actions.escalate = True
        raw_results = tool_context.state.get("scan_results_list", "[]")
        try:
            all_results = json.loads(raw_results) if isinstance(raw_results, str) else raw_results
        except (json.JSONDecodeError, TypeError):
            all_results = []
        total_buildings = int(tool_context.state.get("scan_total_buildings", 0) or 0)
        summary_emitted = bool(tool_context.state.get("scan_summary_emitted", False))
        if (
            not summary_emitted
            and total_buildings > 0
        ):
            all_results_list = _as_list(all_results)
            if all_results_list is None or len(all_results_list) < total_buildings:
                return {"done": True, "asset_id": asset_id, "total_scanned": scanned}
            report = build_aggregated_scan_report(tool_context)
            tool_context.state["scan_summary_emitted"] = True
            return {
                "done": True,
                "asset_id": asset_id,
                "total_scanned": scanned,
                "message": report.get("summary", "Scan complete."),
            }
        return {"done": True, "asset_id": asset_id, "total_scanned": scanned}

    # Gracefully handle state not yet propagated from prep agent.
    # If active_assets is empty but we have an initial building, proceed anyway.
    has_initial = _as_dict(initial_by_asset.get(asset_id)) is not None
    if asset_id not in active_assets and not has_initial and not pending:
        tool_context.actions.escalate = True
        return {"done": True, "asset_id": asset_id, "total_scanned": 0}

    drone_x: float | None = None
    drone_z: float | None = None
    from backend.runtime import grpc_client as runtime_grpc_client

    status = await runtime_grpc_client.get_status(asset_id)
    sx = _to_float(status.get("x"))
    sz = _to_float(status.get("z"))
    if sx is not None and sz is not None:
        drone_x = sx
        drone_z = sz

    async with _SCAN_QUEUE_LOCK:
        # Re-read mutable shared queue state under lock to avoid stale reads
        # when the picker tool is invoked multiple times concurrently.
        fresh_pending_raw = tool_context.state.get("scan_pending_buildings", "[]")
        fresh_claimed_raw = tool_context.state.get("scan_claimed_initial_by_asset", "{}")
        fresh_done_count_raw = tool_context.state.get("scan_done_count_by_asset", "{}")
        try:
            pending = json.loads(fresh_pending_raw) if isinstance(fresh_pending_raw, str) else fresh_pending_raw
        except (json.JSONDecodeError, TypeError):
            pending = []
        try:
            claimed_initial = json.loads(fresh_claimed_raw) if isinstance(fresh_claimed_raw, str) else fresh_claimed_raw
        except (json.JSONDecodeError, TypeError):
            claimed_initial = {}
        try:
            done_count = json.loads(fresh_done_count_raw) if isinstance(fresh_done_count_raw, str) else fresh_done_count_raw
        except (json.JSONDecodeError, TypeError):
            done_count = {}

        scanned = int(done_count.get(asset_id, 0))
        claimed = bool(claimed_initial.get(asset_id, False))

        # Re-check no-queue completion after refresh so stale pre-lock reads cannot
        # re-claim the initial building.
        if not queue_enabled and claimed:
            tool_context.actions.escalate = True
            raw_results = tool_context.state.get("scan_results_list", "[]")
            try:
                all_results = json.loads(raw_results) if isinstance(raw_results, str) else raw_results
            except (json.JSONDecodeError, TypeError):
                all_results = []
            total_buildings = int(tool_context.state.get("scan_total_buildings", 0) or 0)
            summary_emitted = bool(tool_context.state.get("scan_summary_emitted", False))
            if (
                not summary_emitted
                and total_buildings > 0
            ):
                all_results_list = _as_list(all_results)
                if all_results_list is None or len(all_results_list) < total_buildings:
                    return {"done": True, "asset_id": asset_id, "total_scanned": scanned}
                report = build_aggregated_scan_report(tool_context)
                tool_context.state["scan_summary_emitted"] = True
                return {
                    "done": True,
                    "asset_id": asset_id,
                    "total_scanned": scanned,
                    "message": report.get("summary", "Scan complete."),
                }
            return {"done": True, "asset_id": asset_id, "total_scanned": scanned}

        building: dict | None = None
        remaining = 0
        if not claimed:
            candidate = _as_dict(initial_by_asset.get(asset_id))
            claimed_initial[asset_id] = True
            if candidate is not None:
                building = candidate
                remaining = len(pending)
        if building is None and pending:
            pick_index = 0
            if drone_x is not None and drone_z is not None:
                closest_dist = float("inf")
                for idx, candidate in enumerate(pending):
                    candidate_dict = _as_dict(candidate)
                    if candidate_dict is None:
                        continue
                    bx = _to_float(candidate_dict.get("x"))
                    bz = _to_float(candidate_dict.get("z"))
                    if bx is None or bz is None:
                        continue
                    dist = math.sqrt((bx - drone_x) ** 2 + (bz - drone_z) ** 2)
                    if dist < closest_dist:
                        closest_dist = dist
                        pick_index = idx
            candidate = pending.pop(pick_index)
            candidate_dict = _as_dict(candidate)
            if candidate_dict is not None:
                building = candidate_dict
                remaining = len(pending)

        if building is None:
            # Safety: if this drone hasn't scanned anything yet but had an initial
            # assignment, the state may not have propagated. Re-read the initial
            # assignment one more time before giving up.
            if scanned == 0 and not claimed:
                fresh_initial_raw = tool_context.state.get("scan_initial_building_by_asset", "{}")
                try:
                    fresh_initial = json.loads(fresh_initial_raw) if isinstance(fresh_initial_raw, str) else fresh_initial_raw
                except (json.JSONDecodeError, TypeError):
                    fresh_initial = {}
                retry_candidate = _as_dict(fresh_initial.get(asset_id))
                if retry_candidate is not None:
                    claimed_initial[asset_id] = True
                    building = retry_candidate
                    remaining = len(pending)

            if building is None:
                tool_context.state["scan_claimed_initial_by_asset"] = json.dumps(claimed_initial)
                tool_context.state["scan_pending_buildings"] = json.dumps(pending)
                tool_context.actions.escalate = True
                raw_results = tool_context.state.get("scan_results_list", "[]")
                try:
                    all_results = json.loads(raw_results) if isinstance(raw_results, str) else raw_results
                except (json.JSONDecodeError, TypeError):
                    all_results = []
                total_buildings = int(tool_context.state.get("scan_total_buildings", 0) or 0)
                summary_emitted = bool(tool_context.state.get("scan_summary_emitted", False))
                if (
                    not summary_emitted
                    and total_buildings > 0
                ):
                    all_results_list = _as_list(all_results)
                    if all_results_list is None or len(all_results_list) < total_buildings:
                        return {"done": True, "asset_id": asset_id, "total_scanned": scanned}
                    report = build_aggregated_scan_report(tool_context)
                    tool_context.state["scan_summary_emitted"] = True
                    return {
                        "done": True,
                        "asset_id": asset_id,
                        "total_scanned": scanned,
                        "message": report.get("summary", "Scan complete."),
                    }
                return {"done": True, "asset_id": asset_id, "total_scanned": scanned}

        next_scanned = scanned + 1
        done_count[asset_id] = next_scanned
        tool_context.state["scan_claimed_initial_by_asset"] = json.dumps(claimed_initial)
        tool_context.state["scan_pending_buildings"] = json.dumps(pending)
        tool_context.state["scan_done_count_by_asset"] = json.dumps(done_count)
        return {
            "done": False,
            "asset_id": asset_id,
            "building": building,
            "index": next_scanned - 1,
            "remaining": remaining,
        }


def save_scan_result_for_asset(asset_id: str, result: str, tool_context: ToolContext) -> dict:
    """Save a per-asset scan result and append it to the global list.

    Args:
        asset_id: Drone asset identifier that produced the result.
        result: Compact building scan result text.
        tool_context: ADK tool context containing mutable workflow state.

    Returns:
        A status payload with per-asset saved result count.
    """
    raw_map = tool_context.state.get("scan_results_by_asset", "{}")
    raw_all = tool_context.state.get("scan_results_list", "[]")
    try:
        result_map = json.loads(raw_map) if isinstance(raw_map, str) else raw_map
    except (json.JSONDecodeError, TypeError):
        result_map = {}
    try:
        all_results = json.loads(raw_all) if isinstance(raw_all, str) else raw_all
    except (json.JSONDecodeError, TypeError):
        all_results = []

    prefixed = f"[{asset_id}] {result}"
    bucket = result_map.get(asset_id, [])
    bucket.append(prefixed)
    result_map[asset_id] = bucket
    all_results.append(prefixed)

    tool_context.state["scan_results_by_asset"] = json.dumps(result_map)
    tool_context.state["scan_results_list"] = json.dumps(all_results)
    return {"saved": True, "asset_id": asset_id, "total_saved_for_asset": len(bucket)}


# ── Parallel fleet LoopAgents (one per beacon) ────────────────────────────────

_PARALLEL_BEACON_IDS = ["BEACON-01"]
_SCAN_LOOP_NAV_TOOLS = [tool for tool in NAV_TOOLS if tool != "resolve_scan_target"]


def _asset_suffix(asset_id: str) -> str:
    """Normalize an asset id into a safe generated-name suffix.

    Args:
        asset_id: Drone asset identifier.

    Returns:
        Lowercased, hyphen-normalized suffix string safe for agent/tool names.
    """
    return asset_id.lower().replace("-", "_")


def _make_asset_scan_loop(asset_id: str) -> LoopAgent:
    """Create a per-asset scan LoopAgent pipeline.

    Args:
        asset_id: Drone asset identifier used to bind generated tools/agents.

    Returns:
        Configured LoopAgent that repeatedly picks, navigates, and scans for
        the provided asset.
    """
    suffix = _asset_suffix(asset_id)
    current_key = f"current_building_{suffix}"
    nav_key = f"nav_result_{suffix}"

    async def _pick_asset_building(tool_context: ToolContext) -> dict:
        """Select the next building assigned to this asset.

        Args:
            tool_context: ADK tool context containing shared queue state.

        Returns:
            A per-asset building selection payload from shared queue state.
        """
        return await pick_next_building_for_asset(asset_id, tool_context)

    _pick_asset_building.__name__ = f"pick_next_building_{suffix}"
    pick_tool = FunctionTool(func=_pick_asset_building)

    def _save_asset_result(result: str, tool_context: ToolContext) -> dict:
        """Persist one per-building scan result for this asset.

        Args:
            result: Compact building scan result text.
            tool_context: ADK tool context containing mutable state.

        Returns:
            Save status payload for this asset.
        """
        return save_scan_result_for_asset(asset_id, result, tool_context)

    _save_asset_result.__name__ = f"save_scan_result_{suffix}"
    save_tool = FunctionTool(func=_save_asset_result)

    picker_instruction = ASSET_SCAN_PICKER_INSTRUCTION_TEMPLATE.format(
        asset_id=asset_id,
        pick_function_name=_pick_asset_building.__name__,
    )

    nav_instruction = ASSET_SCAN_NAV_INSTRUCTION_TEMPLATE.format(current_key=current_key)

    thermal_instruction = ASSET_SCAN_THERMAL_INSTRUCTION_TEMPLATE.format(
        nav_key=nav_key,
        current_key=current_key,
        save_function_name=_save_asset_result.__name__,
    )

    picker_agent = Agent(
        name=f"building_picker_agent_{suffix}",
        model=QWEN3_INSTRUCT,
        description=f"Picks next building for {asset_id}.",
        generate_content_config=QWEN3_GEN_CONFIG,
        output_key=current_key,
        instruction=picker_instruction,
        tools=[pick_tool],
    )

    nav_agent = Agent(
        name=f"navigation_agent_scan_{suffix}",
        model=QWEN3_INSTRUCT,
        description=f"Navigates {asset_id} to current scan target.",
        generate_content_config=QWEN3_GEN_CONFIG,
        output_key=nav_key,
        instruction=nav_instruction,
        tools=[make_toolset(_SCAN_LOOP_NAV_TOOLS)],
    )

    thermal_agent = Agent(
        name=f"thermal_agent_scan_{suffix}",
        model=QWEN3_INSTRUCT,
        description=f"Sweep-scans current building for {asset_id} and saves compact results.",
        generate_content_config=QWEN3_GEN_CONFIG,
        instruction=thermal_instruction,
        tools=[make_toolset(THERMAL_TOOLS), save_tool, get_shared_state],
    )

    return LoopAgent(
        name=f"building_scan_loop_{suffix}",
        description=f"Loop scan pipeline for {asset_id}: pick -> navigate -> scan until done.",
        max_iterations=100,
        sub_agents=[picker_agent, nav_agent, thermal_agent],
    )


_asset_scan_loop_cache: dict[str, LoopAgent] = {}


def _get_or_create_asset_scan_loop(asset_id: str) -> LoopAgent:
    """Fetch a cached per-asset scan loop or create one.

    Args:
        asset_id: Drone asset identifier.

    Returns:
        Cached or newly created LoopAgent instance for the asset.
    """
    loop = _asset_scan_loop_cache.get(asset_id)
    if loop is None:
        loop = _make_asset_scan_loop(asset_id)
        _asset_scan_loop_cache[asset_id] = loop
    return loop


_fleet_parallel_scan_loops = ParallelAgent(
    name="fleet_parallel_scan_loops",
    description="Runs one LoopAgent per BEACON in parallel for true multi-drone execution.",
    sub_agents=[_get_or_create_asset_scan_loop(asset_id) for asset_id in _PARALLEL_BEACON_IDS],
)


def _set_active_parallel_loops(asset_ids: list[str]) -> None:
    """Configure active parallel scan loops from assigned assets.

    Args:
        asset_ids: Asset identifiers that should run parallel scan loops.

    Returns:
        None. Updates parallel agent sub-agent configuration in place.
    """
    if not asset_ids:
        return
    _fleet_parallel_scan_loops.sub_agents = [
        _get_or_create_asset_scan_loop(asset_id)
        for asset_id in asset_ids
    ]


# ── Final report agent ─────────────────────────────────────────────────────────

_REPORT_INSTRUCTION = SCAN_REPORT_INSTRUCTION

_scan_report_agent = Agent(
    name="scan_report_agent",
    model=QWEN3_INSTRUCT,
    description="Reads accumulated scan results and emits a single consolidated final report.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_REPORT_INSTRUCTION,
    tools=[_build_report_tool],
)


# ── Fleet agents ──────────────────────────────────────────────────────────────

_FLEET_ASSIGNER_INSTRUCTION = SCAN_FLEET_ASSIGNER_INSTRUCTION

_fleet_assigner_agent = Agent(
    name="fleet_assigner_agent",
    model=QWEN3_INSTRUCT,
    description=(
        "Assigns drones to buildings with optimization: highest battery first when all are at base, "
        "otherwise proximity-based greedy matching."
    ),
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_FLEET_ASSIGNER_INSTRUCTION,
    tools=[_assign_drones_tool],
)


_FLEET_EXECUTOR_INSTRUCTION = SCAN_FLEET_EXECUTOR_INSTRUCTION

_fleet_scan_prep_agent = Agent(
    name="fleet_scan_prep_agent",
    model=QWEN3_INSTRUCT,
    description="Prepares a parallel fleet mission queue for LoopAgent execution.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_FLEET_EXECUTOR_INSTRUCTION,
    tools=[_prepare_fleet_scan_tool],
)


# ── Fleet assignment stage ─────────────────────────────────────────────────────

_fleet_assignment_stage = SequentialAgent(
    name="fleet_assignment_stage",
    description="Perform fleet assignment using pre-resolved scan targets.",
    sub_agents=[_fleet_assigner_agent],
)


# ── Fleet scan execution stage ─────────────────────────────────────────────────

_fleet_scan_executor_agent = SequentialAgent(
    name="fleet_scan_executor_agent",
    description=(
        "Run parallel fleet scan via one LoopAgent per BEACON "
        "(pick -> navigate -> scan) until all buildings are processed."
    ),
    sub_agents=[_fleet_scan_prep_agent, _fleet_parallel_scan_loops, _scan_report_agent],
)


# ── Top-level SequentialAgent ──────────────────────────────────────────────────

scan_workflow = SequentialAgent(
    name="scan_workflow",
    description=(
        "Navigate a drone fleet to scan one or more buildings for heat signatures "
        "and emit a single consolidated final report. "
        "Automatically assigns the closest available drones in parallel when multiple "
        "buildings are targeted. "
        "Use for ANY scan/thermal/survivor-detection command — single building or area scan."
    ),
    sub_agents=[_fleet_assignment_stage, _fleet_scan_executor_agent],
)
