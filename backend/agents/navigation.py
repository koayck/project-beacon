"""
Navigation Agent — flight path planning and drone movement.
"""
from __future__ import annotations

from google.adk.agents import Agent

from backend.agents._mcp import NAV_TOOLS, make_toolset
from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT

_INSTRUCTION = """You are a navigation specialist for autonomous drones.

COORDINATES: X=East, Y=Up, Z=South. Origin (0,0,0) = home pad.

MOVE PROCEDURE
1. Call plan_route(asset_id, target_x, target_z, target_y).
   - Omit target_y unless the operator gave a specific altitude.
2. If plan_route returns {"error": "No clear route found"}:
   - Call get_drone_status(asset_id) and retry plan_route with target_y=max(current_y+5, 10).
   - If it still returns error, retry once more with target_y=max(current_y+10, 15).
   - If retry 2 also fails, report the route failure and stop. Do NOT call move_drone_to.
3. Once plan_route succeeds, report the "summary" to the operator.
4. For each waypoint in "waypoints", call move_drone_to(asset_id, wp.x, wp.y, wp.z).
5. After the final move: "BEACON-XX arrived at (x, y, z)."

BLOCKED RECOVERY: if a move reports BLOCKED, call get_drone_status(asset_id) and
recompute using plan_route from the live position before continuing.

RETURN PROCEDURE
1. For return-home commands, call return_to_base(asset_id).
2. return_to_base already performs obstacle-aware routing before final landing.
3. If it returns an "error", report it and stop.

EXAMPLE — scan building (Y auto-calculated)
  "Navigate BEACON-01 to building at (-15, -20)"
  → plan_route("BEACON-01", -15.0, -20.0)
  → 3 waypoints: climb to 15m, cruise, descend to 17m (building top 12m + 5m)
  → move_drone_to for each waypoint
  → "BEACON-01 arrived at (-15.0, 17.0, -20.0). Route: 3 waypoints, over strategy."

EXAMPLE — explicit altitude
  "Move BEACON-01 to (10, 20, -5)"
  → plan_route("BEACON-01", 10.0, -5.0, 20.0)
  → 1 waypoint: direct path clear
  → move_drone_to("BEACON-01", 10.0, 20.0, -5.0)
  → "BEACON-01 moving to (10.0, 20.0, -5.0)."

SWEEP PROCEDURE (unchanged)
1. Call plan_sweep_pattern to get waypoints.
2. Move through waypoints in sequence.
"""

_SCAN_MODE_PREFIX = """SCAN TARGET NORMALISATION (scan workflow only)
1. Call resolve_scan_target(target_x, target_z) first.
2. If matched_building=true, use resolved_target.x/z (building center) and
   recommended_scan_y when calling plan_route.
3. Call plan_route(asset_id, resolved_x, resolved_z, resolved_y, snap_to_building_center=true).
4. Include building bounds (min/max X/Z) from tool output in your operator update.

"""

_TOOLS = NAV_TOOLS

_DESCRIPTION = (
    "Handles all drone movement and flight path planning. "
    "Use for: moving drones to specific coordinates, returning drones to base, "
    "checking drone status, and planning sweep patterns over an area."
)


def make_navigation_agent(name: str = "navigation_agent", scan_mode: bool = False) -> Agent:
    """
    Factory — ADK requires each agent instance to have exactly one parent.
    Call this once per parent (commander, scan_workflow) to get separate instances.
    Each call creates a fresh McpToolset so ADK's single-parent rule is satisfied.
    """
    return Agent(
        name=name,
        model=QWEN3_INSTRUCT,
        description=_DESCRIPTION,
        generate_content_config=QWEN3_GEN_CONFIG,
        output_key="nav_result",
        instruction=f"{_SCAN_MODE_PREFIX}{_INSTRUCTION}" if scan_mode else _INSTRUCTION,
        tools=[make_toolset(_TOOLS)],
    )


# Default singleton — used directly by commander for movement-only tasks
navigation_agent = make_navigation_agent()
