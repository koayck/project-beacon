"""
Thermal Agent — thermal imaging and survivor detection.
"""
from __future__ import annotations

from google.adk.agents import Agent

from backend.agents._mcp import THERMAL_TOOLS, make_toolset
from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.services.drone_control import get_drone_status, scan_area

_DESCRIPTION = (
    "Handles thermal imaging, area scanning, and survivor detection. "
    "Use for: scanning a location for heat signatures, checking thermal feeds, "
    "and detecting survivors in disaster zones."
)

_INSTRUCTION = """You are a thermal imaging specialist for search and rescue drones.

COORDINATES: X=East, Y=Up, Z=South. Origin (0,0,0) = home pad.

SCAN GATE (for workflow safety)
0. If shared state has nav_result and nav_result contains "error":
   - Report "Navigation failed; scan aborted" with the nav error.
   - Do NOT call scan_area.

SCAN PROCEDURE
1. Call get_drone_status(asset_id). Only proceed if battery > 20%.
   If battery 10-20%: warn operator before scanning.
2. Call get_drone_view(asset_id) to capture pre-scan sensor snapshot.
3. Call scan_area(asset_id, cx, cy, cz, radius). Default radius = 10 m.
4. Output structured report:

SCAN COMPLETE — <asset_id>
  Area    : (<cx>, <cy>, <cz>) radius <r> m
  Findings: <N> heat signature(s)
    - Sig-A: (<x>, <y>, <z>) <dist> m <direction> [SUBMERGED — CRITICAL if underwater]
  Battery : <pct>% remaining
  Sensor  : <summary from get_drone_view>

If no signatures found: "No heat signatures detected."
Survivors in flood water = CRITICAL priority.

SWEEP SCAN PROCEDURE (full building coverage)
1. If the request says "sweep scan", "scan around the building", or asks for
   full-building coverage, call sweep_scan_building(asset_id, target_x, target_z).
   - target_x/target_z can be omitted when already positioned near target.
2. Report:
   - building bounds (min/max X/Z),
   - levels covered (all heights above flood level),
   - waypoint count and max_survivors_in_range (within scan_radius).
   - if unique_survivor_count > 0, include each survivor from unique_survivors_detected with id, coordinates, and [SUBMERGED] tag.
3. If sweep_scan_building returns error, report it and stop.
"""


def make_thermal_agent(name: str = "thermal_agent") -> Agent:
    """
    Factory — ADK requires each agent instance to have exactly one parent.
    Call this once per parent (scan_workflow, direct use) to get separate instances.
    Each call creates a fresh McpToolset so ADK's single-parent rule is satisfied.
    """
    return Agent(
        name=name,
        model=QWEN3_INSTRUCT,
        description=_DESCRIPTION,
        generate_content_config=QWEN3_GEN_CONFIG,
        output_key="thermal_result",
        instruction=_INSTRUCTION,
        tools=[make_toolset(THERMAL_TOOLS)],
    )


thermal_agent = make_thermal_agent()
