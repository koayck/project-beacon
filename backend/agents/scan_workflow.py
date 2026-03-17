"""
Scan Workflow — navigate then sweep-scan one or more buildings, then emit a
single consolidated final report.

Works for both single-building and multi-building (area) commands:
  - "Scan building at (-15, -20) with BEACON-01"
      → resolver wraps the single building in a 1-item list
      → loop runs once, picker escalates
      → reporter formats 1-building summary

  - "Scan all buildings near (-10, -15) radius 30m with BEACON-01"
      → resolver calls find_buildings_in_area → N-item list
      → loop runs N times, picker escalates when queue is empty
      → reporter formats N-building consolidated summary

Structure:
    scan_workflow (SequentialAgent)
    ├── scan_resolver_agent          # builds state["scan_buildings"] list
    ├── building_scan_loop (LoopAgent, max 20 iterations)
    │   ├── building_picker_agent    # pop next building; escalate when done
    │   ├── navigation_agent_scan    # navigate to current_building
    │   └── thermal_agent_scan       # sweep-scan, silently saves result
    └── scan_report_agent            # reads accumulated results, emits final report

Session state keys:
    scan_buildings        JSON — {"asset_id": str, "buildings": [{id,x,z,height,bounds},…]}
    buildings_scan_index  int  — next index (managed by pick_next_building)
    current_building      str  — navigation target emitted by picker
    nav_result            str  — navigation outcome (read by thermal SCAN GATE)
    scan_results_list     JSON — list of per-building compact result strings (accumulated)
"""
from __future__ import annotations

import json

from google.adk.agents import Agent, LoopAgent, SequentialAgent
from google.adk.tools import FunctionTool
from google.adk.tools.tool_context import ToolContext

from backend.agents._mcp import NAV_TOOLS, THERMAL_TOOLS, make_toolset
from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT


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

    asset_id = scan_data.get("asset_id", "UNKNOWN")
    buildings: list[dict] = scan_data.get("buildings", [])
    index: int = tool_context.state.get("buildings_scan_index", 0)

    if index >= len(buildings):
        tool_context.actions.escalate = True
        return {"done": True, "total_scanned": index, "asset_id": asset_id}

    building = buildings[index]
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


def finalize_scan(tool_context: ToolContext) -> dict:
    """
    Retrieve all accumulated scan results and exit the scan loop.
    Call this ONCE, after saving the LAST building's result (Remaining: 0).
    Sets escalate=True so the LoopAgent terminates.
    """
    raw = tool_context.state.get("scan_results_list", "[]")
    try:
        results: list[str] = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        results = []
    tool_context.actions.escalate = True
    return {"results": results, "total": len(results)}


_pick_tool = FunctionTool(func=pick_next_building)
_save_tool = FunctionTool(func=save_scan_result)
_get_tool = FunctionTool(func=get_scan_results)
_finalize_tool = FunctionTool(func=finalize_scan)


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

COORDINATES: X=East, Y=Up, Z=South. Origin (0,0,0) = home pad.

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
   - YES (last building): Call finalize_scan() — it returns all accumulated results.
     Output the full consolidated report using ONLY the results list from finalize_scan():
     ═══════════════════════════════════════
       AREA SCAN COMPLETE — <N> building(s)
     ═══════════════════════════════════════
     Building 1: <result line>
       <survivor lines if any, indented 2 spaces>
     Building 2: <result line>
       <survivor lines if any, indented 2 spaces>
     ...
     ───────────────────────────────────────
     TOTAL SURVIVORS DETECTED: <sum>   (or "No heat signatures detected across all scanned buildings." if 0)
     ═══════════════════════════════════════
     DO NOT write code. Output the report text directly.
   - NO (more buildings remain): Output only "Result saved for building at (x=<x>, z=<z>)."
"""

_thermal_for_scan = Agent(
    name="thermal_agent_scan",
    model=QWEN3_INSTRUCT,
    description="Sweep-scans the current building and silently accumulates the result. Generates the final report after the last building.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_SILENT_THERMAL_INSTRUCTION,
    tools=[make_toolset(THERMAL_TOOLS), _save_tool, _finalize_tool],
)


# ── LoopAgent ──────────────────────────────────────────────────────────────────

_building_scan_loop = LoopAgent(
    name="building_scan_loop",
    description=(
        "Iterates over every building in the scan queue: "
        "pick → navigate → sweep-scan → repeat until queue is empty."
    ),
    max_iterations=20,
    sub_agents=[
        _building_picker_agent,
        _nav_for_scan,
        _thermal_for_scan,
    ],
)


# ── Final report agent ─────────────────────────────────────────────────────────

_REPORT_INSTRUCTION = """You produce the final consolidated scan report.

1. Call get_scan_results() to retrieve all accumulated building results.
2. Output ONLY the formatted report below — no code, no explanation, no markdown fences.

═══════════════════════════════════════
  AREA SCAN COMPLETE — <N> building(s)
═══════════════════════════════════════
Building 1: <result line>
  <survivor lines if any, indented 2 spaces>
Building 2: <result line>
  <survivor lines if any, indented 2 spaces>
...
───────────────────────────────────────
TOTAL SURVIVORS DETECTED: <sum of all survivors found>
<if any CRITICAL submerged cases, list them here>
═══════════════════════════════════════

If total survivors = 0: replace the TOTAL line with "No heat signatures detected across all scanned buildings."
DO NOT write or execute any code. Output the report text directly.
"""

_scan_report_agent = Agent(
    name="scan_report_agent",
    model=QWEN3_INSTRUCT,
    description="Reads accumulated scan results and emits a single consolidated final report.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_REPORT_INSTRUCTION,
    tools=[_get_tool],
)


# ── Resolver agent ─────────────────────────────────────────────────────────────

_RESOLVER_INSTRUCTION = """You build the list of buildings to scan.

COORDINATES: X=East, Y=Up, Z=South.

MULTI-BUILDING EXPLICIT — command lists two or more buildings with coordinates:
  (e.g. "scan building A at (20, -20) and building B at (12, -27)")
  1. For EACH building coordinate, call resolve_scan_target(target_x, target_z).
  2. Collect every matched_building result into the buildings list.
  3. asset_id = the asset_id from the command (or infer it).

SINGLE BUILDING — command targets one specific building or coordinate:
  1. Call resolve_scan_target(target_x, target_z).
  2. If matched_building=true, wrap the resolved building in a 1-item list.
  3. If matched_building=false, use the provided coordinates as a 1-item list
     with id=-1, height=0, bounds={min_x:x, max_x:x, min_z:z, max_z:z}.

AREA SCAN — command mentions area / zone / radius / "all buildings" with no explicit list:
  1. Call get_drone_status(asset_id) to get the drone's current position.
  2. Call find_buildings_in_area(center_x, center_z, radius,
       drone_x=<drone.x>, drone_z=<drone.z>).
     Default radius = 30.0 m unless the operator specifies one.
     Passing drone_x/drone_z sorts buildings nearest to the drone first,
     minimising inter-building transit time.

In all cases, output ONLY valid JSON — no markdown, no extra text:
  {"asset_id": "<asset_id>", "buildings": [<building objects>]}

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
    tools=[make_toolset(["resolve_scan_target", "find_buildings_in_area", "get_drone_status"])],
)


# ── Top-level SequentialAgent ──────────────────────────────────────────────────

scan_workflow = SequentialAgent(
    name="scan_workflow",
    description=(
        "Navigate a drone to a target location (one building or all buildings in an area) "
        "then sweep-scan each building for heat signatures, and emit a single consolidated "
        "final report. "
        "Use for ANY scan/thermal/survivor-detection command — single building or area scan."
    ),
    sub_agents=[_scan_resolver_agent, _building_scan_loop],
)
