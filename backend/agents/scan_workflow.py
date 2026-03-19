"""
Scan Workflow — fleet assignment first, then fleet scan loop until all assigned
buildings are completed, then emit one consolidated final report.

Workflow:
  1) Commander routes mission command to scan_workflow.
  2) Fleet assignment stage resolves target buildings and assigns drones.
  3) Parallel fleet scan stage prepares an interleaved mission queue.
  4) LoopAgent runs pick -> navigate -> sweep-scan repeatedly until done.
  5) Final report agent emits one consolidated operator report.

Structure:
    scan_workflow (SequentialAgent)
    ├── fleet_assignment_stage    # resolver + assignment
    └── fleet_scan_executor_agent # prepare queue + LoopAgent + final reporter

Session state keys:
    scan_buildings        JSON — {"asset_id": str | "auto", "buildings": [{...}], ...}
    fleet_assignments     JSON — {"assignments": [{asset_id, building, ...}], ...}
    buildings_scan_index  int  — next index in queue (managed by pick_next_building)
    scan_results_list     JSON — compact per-building report lines
"""
from __future__ import annotations

import asyncio
import json
import math
import re

from google.adk.agents import Agent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from backend.agents._mcp import FLEET_TOOLS, NAV_TOOLS, THERMAL_TOOLS, make_toolset
from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT

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


# ── Queue FunctionTools ────────────────────────────────────────────────────────

def pick_next_building(tool_context: ToolContext) -> dict:
    """
    Pop the next unscanned building from the session-state queue.

    Increments ``buildings_scan_index`` each call.  When the queue is exhausted
    it sets ``actions.escalate = True`` to exit the LoopAgent.
    """
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

    default_asset_id = scan_data.get("asset_id", "UNKNOWN")
    buildings: list[dict] = scan_data.get("buildings", [])
    index: int = tool_context.state.get("buildings_scan_index", 0)

    if index >= len(buildings):
        tool_context.actions.escalate = True
        return {"done": True, "total_scanned": index, "asset_id": default_asset_id}

    building = buildings[index]
    asset_id = building.get("asset_id", default_asset_id)
    tool_context.state["buildings_scan_index"] = index + 1
    return {
        "done": False,
        "asset_id": asset_id,
        "building": building,
        "index": index,
        "remaining": len(buildings) - index - 1,
    }


def save_scan_result(result: str, tool_context: ToolContext) -> dict:
    """
    Append this building's compact scan result to the accumulated results list.
    Call this after every sweep_scan_building — do NOT print a report to the operator.
    """
    raw = tool_context.state.get("scan_results_list", "[]")
    try:
        results: list[str] = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        results = []
    results.append(result)
    tool_context.state["scan_results_list"] = json.dumps(results)
    return {"saved": True, "total_saved": len(results)}


def get_scan_results(tool_context: ToolContext) -> dict:
    """Return all accumulated per-building scan result strings."""
    raw = tool_context.state.get("scan_results_list", "[]")
    try:
        results: list[str] = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        results = []
    return {"results": results, "total": len(results)}


def _split_scan_result_asset(result_text: str) -> tuple[str | None, str]:
    stripped = result_text.strip()
    match = _RESULT_ASSET_PREFIX_RE.match(stripped)
    if not match:
        return None, stripped
    return match.group("asset"), str(match.group("body") or "").strip()


def _format_split_survivor_sections(result_body: str) -> str:
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
    """Build a deterministic final report from all saved scan results."""
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

    return {
        "success": True,
        "summary": summary,
        "total_buildings_scanned": total_buildings,
        "total_survivors": total_survivors,
        "results": results,
    }


def finalize_scan(tool_context: ToolContext) -> dict:
    """
    Signal that the scan workflow is complete. Used by the final agent to
    cleanly terminate the LoopAgent after all buildings have been scanned.
    """
    tool_context.actions.escalate = True
    return {"done": True}


_pick_tool = FunctionTool(func=pick_next_building)
_save_tool = FunctionTool(func=save_scan_result)
_get_tool = FunctionTool(func=get_scan_results)
_build_report_tool = FunctionTool(func=build_aggregated_scan_report)
_finalize_tool = FunctionTool(func=finalize_scan)


# ── Fleet orchestration FunctionTools ─────────────────────────────────────────

async def assign_drones_to_buildings(tool_context: ToolContext) -> dict:
    """
    Read state["scan_buildings"], assign the closest available IDLE drones to
    each building using greedy nearest-first matching, and write the result to
    state["fleet_assignments"].

    When asset_id is an explicit drone ID only the first building is assigned
    initially; remaining buildings stay queued for dynamic pickup.
    When asset_id is "auto" or absent the full fleet is queried for assignments.
    """
    from backend.services.api import assign_fleet_to_buildings

    raw = tool_context.state.get("scan_buildings", "{}")
    try:
        scan_data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        scan_data = {}

    buildings: list[dict] = scan_data.get("buildings", [])
    asset_id: str = scan_data.get("asset_id", "auto") or "auto"

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
    pending: list[dict] = list(data.get("unassigned_buildings", []))
    for row in assignments:
        aid = row.get("asset_id")
        building = row.get("building")
        if not aid or not isinstance(building, dict):
            continue
        if aid not in initial_by_drone:
            initial_by_drone[aid] = building
        else:
            pending.append(building)

    if not initial_by_drone:
        return {"error": "No valid assignments available. Cannot proceed with scan."}

    ordered_aids = sorted(initial_by_drone)
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
    tool_context.state["scan_summary_emitted"] = False
    _set_active_parallel_loops(ordered_aids)
    return {
        "success": True,
        "queued_buildings": len(initial_by_drone) + len(pending),
        "drone_count": len(initial_by_drone),
        "active_assets": ordered_aids,
        "mode": "dynamic_queue_after_initial_assignment",
    }


_assign_drones_tool = FunctionTool(func=assign_drones_to_buildings)
_prepare_fleet_scan_tool = FunctionTool(func=prepare_parallel_fleet_scan)


async def pick_next_building_for_asset(asset_id: str, tool_context: ToolContext) -> dict:
    """Claim next building for this beacon: initial slot first, then closest pending building."""
    raw_assets = tool_context.state.get("active_fleet_assets", "[]")
    raw_initial = tool_context.state.get("scan_initial_building_by_asset", "{}")
    raw_pending = tool_context.state.get("scan_pending_buildings", "[]")
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

    if asset_id not in active_assets:
        tool_context.actions.escalate = True
        return {"done": True, "asset_id": asset_id, "total_scanned": 0}

    drone_x: float | None = None
    drone_z: float | None = None
    from backend.runtime import grpc_client as runtime_grpc_client

    status = await runtime_grpc_client.get_status(asset_id)
    sx = status.get("x")
    sz = status.get("z")
    if isinstance(sx, (int, float)) and isinstance(sz, (int, float)):
        drone_x = float(sx)
        drone_z = float(sz)

    async with _SCAN_QUEUE_LOCK:
        scanned = int(done_count.get(asset_id, 0))
        claimed = bool(claimed_initial.get(asset_id, False))
        building: dict | None = None
        remaining = 0
        if not claimed:
            candidate = initial_by_asset.get(asset_id)
            claimed_initial[asset_id] = True
            if isinstance(candidate, dict):
                building = candidate
                remaining = len(pending)
        if building is None and pending:
            pick_index = 0
            if drone_x is not None and drone_z is not None:
                closest_dist = float("inf")
                for idx, candidate in enumerate(pending):
                    bx = candidate.get("x")
                    bz = candidate.get("z")
                    if not isinstance(bx, (int, float)) or not isinstance(bz, (int, float)):
                        continue
                    dist = math.sqrt((float(bx) - drone_x) ** 2 + (float(bz) - drone_z) ** 2)
                    if dist < closest_dist:
                        closest_dist = dist
                        pick_index = idx
            candidate = pending.pop(pick_index)
            if isinstance(candidate, dict):
                building = candidate
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
                and isinstance(all_results, list)
                and len(all_results) >= total_buildings
            ):
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
    """Append one compact scan result for this beacon and to global report list."""
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


# ── Building picker agent ──────────────────────────────────────────────────────

_PICKER_INSTRUCTION = """You manage the building scan queue.

1. Call pick_next_building().
2. If done=True: output "QUEUE_EMPTY" and stop.
3. If done=False: output EXACTLY this line (fill in values, no extra text):
   SCAN TARGET: Navigate <asset_id> to building at (x=<x>, z=<z>). Height: <height>m. Remaining: <remaining>.
"""

_building_picker_agent = Agent(
    name="building_picker_agent",
    model=QWEN3_INSTRUCT,
    description=(
        "Pops the next building from the scan queue and emits a navigation target, "
        "or exits the loop when all buildings have been scanned."
    ),
    generate_content_config=QWEN3_GEN_CONFIG,
    output_key="current_building",
    instruction=_PICKER_INSTRUCTION,
    tools=[_pick_tool],
)


# ── Navigation agent (scan loop) ───────────────────────────────────────────────

_NAV_INSTRUCTION = """You are a navigation specialist for autonomous drones.

COORDINATES: X=East, Y=Up, Z=South. Home pad at (0, 2, 0).

Your target for this iteration is in state["current_building"]. Parse the asset_id,
x, and z from it (e.g. "Navigate BEACON-01 to building at (x=-15.0, z=-20.0). Height: 12m.").

MOVE PROCEDURE
1. Call resolve_scan_target(target_x, target_z) to snap to the building centre.
2. Set target_y = building.height + 5 (rooftop hover altitude, NOT recommended_scan_y).
3. Call plan_route(asset_id, resolved_x, resolved_z, target_y).
4. If plan_route returns {"error": "No clear route found"}:
   - Call get_drone_status(asset_id) and retry with target_y = max(current_y + 5, 10).
   - Retry once more with target_y = max(current_y + 10, 15) if still failing.
   - Report failure and stop if all retries fail. Do NOT call move_drone_to.
5. If waypoints list is empty, the drone is already at destination — skip move step.
6. For each waypoint in "waypoints", call move_drone_to(asset_id, wp.x, wp.y, wp.z).
7. After the final move: "BEACON-XX arrived at (x, y, z)."
"""

_nav_for_scan = Agent(
    name="navigation_agent_scan",
    model=QWEN3_INSTRUCT,
    description="Navigates the drone to the current scan target building.",
    generate_content_config=QWEN3_GEN_CONFIG,
    output_key="nav_result",
    instruction=_NAV_INSTRUCTION,
    tools=[make_toolset(NAV_TOOLS)],
)


# ── Thermal agent (scan loop — silent accumulation) ────────────────────────────

_SILENT_THERMAL_INSTRUCTION = """You are a thermal imaging specialist for search and rescue drones.

COORDINATES: X=East, Y=Up, Z=South.

SCAN GATE
0. If shared state has nav_result and nav_result contains "error":
   - Call save_scan_result("NAV FAILED for building in current_building: <nav error>").
   - Output "Navigation failed; scan skipped." and stop.
   - Do NOT call scan_area or sweep_scan_building.

SWEEP SCAN PROCEDURE
1. Parse asset_id, x, z from state["current_building"].
   Also note whether state["current_building"] contains "Remaining: 0" — this means it is the LAST building.
2. Call sweep_scan_building(asset_id, target_x=x, target_z=z) — always pass the building coordinates explicitly.
3. Build a compact result string from the tool response:
   - Success: "Building at (x=<x>, z=<z>): <unique_survivor_count> survivor(s) across <level_count> level(s). Waypoints: <waypoint_count>."
     If unique_survivor_count > 0, append a newline and one line per survivor from unique_survivors_detected:
       "  - Survivor <id>: (<x>, <y>, <z>)[SUBMERGED — CRITICAL]" (include SUBMERGED tag only if submerged=true)
     If any submerged survivors: also append " [CRITICAL: <N> submerged]" to the header line.
   - Error:   "Building at (x=<x>, z=<z>): SCAN ERROR — <error>"
4. Call save_scan_result(result=<compact_string>).
5. Check if this is the LAST building ("Remaining: 0" in current_building):
   - YES: Call finalize_scan() to terminate the LoopAgent cleanly.
     Output "SCAN_BATCH_COMPLETE" on its own line.
   - NO: Output only "Result saved for building at (x=<x>, z=<z>)."
"""

_thermal_for_scan = Agent(
    name="thermal_agent_scan",
    model=QWEN3_INSTRUCT,
    description="Sweep-scans the current building and silently accumulates the result. Generates the final report after the last building.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_SILENT_THERMAL_INSTRUCTION,
    tools=[make_toolset(THERMAL_TOOLS), _save_tool],
)


# ── LoopAgent ──────────────────────────────────────────────────────────────────

_building_scan_loop = LoopAgent(
    name="building_scan_loop",
    description=(
        "Iterates over every building in the scan queue: "
        "pick → navigate → sweep-scan → repeat until queue is empty."
    ),
    max_iterations=100,
    sub_agents=[
        _building_picker_agent,
        _nav_for_scan,
        _thermal_for_scan,
    ],
)


# ── Parallel fleet LoopAgents (one per beacon) ────────────────────────────────

_PARALLEL_BEACON_IDS = ["BEACON-01"]


def _asset_suffix(asset_id: str) -> str:
    return asset_id.lower().replace("-", "_")


def _make_asset_scan_loop(asset_id: str) -> LoopAgent:
    suffix = _asset_suffix(asset_id)
    current_key = f"current_building_{suffix}"
    nav_key = f"nav_result_{suffix}"

    async def _pick_asset_building(tool_context: ToolContext) -> dict:
        return await pick_next_building_for_asset(asset_id, tool_context)

    _pick_asset_building.__name__ = f"pick_next_building_{suffix}"
    pick_tool = FunctionTool(func=_pick_asset_building)

    def _save_asset_result(result: str, tool_context: ToolContext) -> dict:
        return save_scan_result_for_asset(asset_id, result, tool_context)

    _save_asset_result.__name__ = f"save_scan_result_{suffix}"
    save_tool = FunctionTool(func=_save_asset_result)

    picker_instruction = f"""You manage the building scan queue for {asset_id}.

1. Call {_pick_asset_building.__name__}().
2. If done=True: output "QUEUE_EMPTY" and stop.
3. If done=False: output EXACTLY this line (fill values, no extra text):
   SCAN TARGET: Navigate <asset_id> to building at (x=<x>, z=<z>). Height: <height>m. Remaining: <remaining>.
"""

    nav_instruction = f"""You are a navigation specialist for autonomous drones.

COORDINATES: X=East, Y=Up, Z=South. Home pad at (0, 2, 0).

Your target for this iteration is in state["{current_key}"]. Parse the asset_id,
x, and z from it (e.g. "Navigate BEACON-01 to building at (x=-15.0, z=-20.0). Height: 12m.").

MOVE PROCEDURE
1. Call resolve_scan_target(target_x, target_z) to snap to the building centre.
2. Set target_y = building.height + 5 (rooftop hover altitude, NOT recommended_scan_y).
3. Call plan_route(asset_id, resolved_x, resolved_z, target_y).
4. If plan_route returns {{\"error\": \"No clear route found\"}}:
   - Call get_drone_status(asset_id) and retry with target_y = max(current_y + 5, 10).
   - Retry once more with target_y = max(current_y + 10, 15) if still failing.
   - Report failure and stop if all retries fail. Do NOT call move_drone_to.
5. If waypoints list is empty, the drone is already at destination — skip move step.
6. For each waypoint in "waypoints", call move_drone_to(asset_id, wp.x, wp.y, wp.z).
7. After the final move: "BEACON-XX arrived at (x, y, z)."
"""

    thermal_instruction = f"""You are a thermal imaging specialist for search and rescue drones.

COORDINATES: X=East, Y=Up, Z=South.

SCAN GATE
0. If shared state has {nav_key} and {nav_key} contains "error":
   - Call {_save_asset_result.__name__}("NAV FAILED for building in {current_key}: <nav error>").
   - Output "Navigation failed; scan skipped." and stop.
   - Do NOT call scan_area or sweep_scan_building.

SWEEP SCAN PROCEDURE
1. Parse asset_id, x, z from state["{current_key}"].
   Also note whether state["{current_key}"] contains "Remaining: 0" — this means no queued building remains after this one.
2. Call sweep_scan_building(asset_id, target_x=x, target_z=z) — always pass building coordinates explicitly.
3. Build a compact result string from the tool response:
   - Success: "Building at (x=<x>, z=<z>): <unique_survivor_count> survivor(s) across <level_count> level(s). Waypoints: <waypoint_count>."
     If unique_survivor_count > 0, append survivor lines:
       "  - Survivor <id>: (<x>, <y>, <z>)[SUBMERGED — CRITICAL]".
   - Error:   "Building at (x=<x>, z=<z>): SCAN ERROR — <error>"
4. Call {_save_asset_result.__name__}(result=<compact_string>).
5. Output only: "Result saved for building at (x=<x>, z=<z>)."
"""

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
        tools=[make_toolset(NAV_TOOLS)],
    )

    thermal_agent = Agent(
        name=f"thermal_agent_scan_{suffix}",
        model=QWEN3_INSTRUCT,
        description=f"Sweep-scans current building for {asset_id} and saves compact results.",
        generate_content_config=QWEN3_GEN_CONFIG,
        instruction=thermal_instruction,
        tools=[make_toolset(THERMAL_TOOLS), save_tool],
    )

    return LoopAgent(
        name=f"building_scan_loop_{suffix}",
        description=f"Loop scan pipeline for {asset_id}: pick -> navigate -> scan until done.",
        max_iterations=100,
        sub_agents=[picker_agent, nav_agent, thermal_agent],
    )


_asset_scan_loop_cache: dict[str, LoopAgent] = {}


def _get_or_create_asset_scan_loop(asset_id: str) -> LoopAgent:
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
    """Configure parallel loop count from current fleet assignment result."""
    if not asset_ids:
        asset_ids = ["BEACON-01"]
    _fleet_parallel_scan_loops.sub_agents = [
        _get_or_create_asset_scan_loop(asset_id)
        for asset_id in asset_ids
    ]


# ── Final report agent ─────────────────────────────────────────────────────────

_REPORT_INSTRUCTION = """You MUST produce the final consolidated scan report. This is mandatory.

1. Call build_aggregated_scan_report() — you MUST call this tool.
2. Output the value of result["summary"] verbatim. Do NOT skip this step.
3. Do NOT add extra text, markdown, or explanation — just the summary string.
"""

_scan_report_agent = Agent(
    name="scan_report_agent",
    model=QWEN3_INSTRUCT,
    description="Reads accumulated scan results and emits a single consolidated final report.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_REPORT_INSTRUCTION,
    tools=[_build_report_tool],
)


# ── Fleet agents ──────────────────────────────────────────────────────────────

_FLEET_TOOL_NAMES = tuple(FLEET_TOOLS)

_FLEET_ASSIGNER_INSTRUCTION = """You assign available drones to buildings for a fleet scan.

1. Call assign_drones_to_buildings().
   The tool reads the scan queue and assigns only ONE initial building per drone.
2. If the result contains "error": output the error message clearly and stop.
3. Otherwise output a brief assignment summary — one line per assignment:
   Fleet assigned: <total_assigned> drone(s) dispatched.
   <asset_id> → Building at (x=<x>, z=<z>) [<distance_m>m]
   (repeat for each assignment)
   If unassigned_buildings is non-empty: "<N> building(s) queued for dynamic pickup."
"""

_fleet_assigner_agent = Agent(
    name="fleet_assigner_agent",
    model=QWEN3_INSTRUCT,
    description="Assigns the closest available IDLE drones to buildings using proximity-based greedy matching.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_FLEET_ASSIGNER_INSTRUCTION,
    tools=[_assign_drones_tool],
)


_FLEET_EXECUTOR_INSTRUCTION = """You execute the fleet scan missions for all assigned drone-building pairs.

1. Call prepare_parallel_fleet_scan().
2. If the result contains "error": output the error message to the operator and stop.
3. If success, confirm that one LoopAgent per BEACON will run in parallel, then continue.
"""

_fleet_scan_prep_agent = Agent(
    name="fleet_scan_prep_agent",
    model=QWEN3_INSTRUCT,
    description="Prepares a parallel fleet mission queue for LoopAgent execution.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_FLEET_EXECUTOR_INSTRUCTION,
    tools=[_prepare_fleet_scan_tool],
)


# ── Resolver agent ─────────────────────────────────────────────────────────────

_RESOLVER_INSTRUCTION = """You build the list of buildings to scan.

COORDINATES: X=East, Y=Up, Z=South.

MULTI-BUILDING EXPLICIT — command lists two or more buildings with coordinates:
  (e.g. "scan building A at (20, -20) and building B at (12, -27)")
  1. For EACH building coordinate, call resolve_scan_target(target_x, target_z).
  2. Collect every matched_building result into the buildings list.
  3. asset_id = the asset_id from the command; if none is mentioned use "auto".

SINGLE BUILDING — command targets one specific building or coordinate:
  1. Call resolve_scan_target(target_x, target_z).
  2. If matched_building=true, wrap the resolved building in a 1-item list.
  3. If matched_building=false, use the provided coordinates as a 1-item list
      with id=-1, height=0, bounds={min_x:x, max_x:x, min_z:z, max_z:z}.
  4. asset_id = the asset_id from the command; if none is mentioned use "auto".

AREA SCAN — command mentions area / zone / radius / "all buildings" with no explicit list:
  1. Call find_buildings_in_area(center_x, center_z, radius).
     Default radius = 30.0 m unless the operator specifies one.
  2. asset_id = "auto" (fleet assignment will pick the best drones).

ASSET ID RULE: Use "auto" whenever no specific drone is named in the command.
Only use a real asset_id (e.g. "BEACON-01") when the operator explicitly names it.

In all cases, output ONLY valid JSON — no markdown, no extra text:
  {"asset_id": "<asset_id or auto>", "buildings": [<building objects>]}

Each building object must have: id, x, z, height, bounds{min_x,max_x,min_z,max_z}.
"""

_scan_resolver_agent = Agent(
    name="scan_resolver_agent",
    model=QWEN3_INSTRUCT,
    description=(
        "Resolves the scan target — a single building or all buildings in an area — "
        "and stores the list for the scan loop."
    ),
    generate_content_config=QWEN3_GEN_CONFIG,
    output_key="scan_buildings",
    instruction=_RESOLVER_INSTRUCTION,
    tools=[make_toolset(["resolve_scan_target", "find_buildings_in_area"])],
)

# ── Fleet assignment stage ─────────────────────────────────────────────────────

_fleet_assignment_stage = SequentialAgent(
    name="fleet_assignment_stage",
    description="Resolve scan targets first, then perform fleet assignment.",
    sub_agents=[_scan_resolver_agent, _fleet_assigner_agent],
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
