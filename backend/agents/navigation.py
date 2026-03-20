"""
Navigation Agent — flight path planning and drone movement.

REFACTORED: Now uses orchestrator for deterministic logic.
Agent handles reasoning and operator communication only.
"""
from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.orchestrator.navigation import (
    execute_navigation_sequence,
    execute_return_to_base,
)
from backend.services.api.control import (
    get_drone_status,
    plan_sweep_pattern,
)

_INSTRUCTION = """You are a navigation specialist for autonomous drones.

COORDINATES: X=East, Y=Up, Z=South. Home pad at (0, 2, 0).

HYBRID ARCHITECTURE:
- For movement commands, call execute_navigation_sequence() — this handles all retry logic,
  altitude escalation, and waypoint execution automatically.
- For return-home, call execute_return_to_base() — this handles obstacle-aware routing.
- For status queries, call get_drone_status().

MOVE PROCEDURE
1. Call execute_navigation_sequence(asset_id, target_x, target_z, target_y).
   - Omit target_y (pass None) unless the operator specified exact altitude.
   - The orchestrator handles: route planning, altitude escalation on blocked routes,
     waypoint execution, and re-routing on obstacles.
2. Report the result to the operator in clear language:
   - Success: "BEACON-XX arrived at (x, y, z). Route: [summary]."
   - Failure: "Navigation failed: [error]. [suggestion]."

RETURN PROCEDURE
1. Call execute_return_to_base(asset_id).
2. Report result to operator.

SWEEP PROCEDURE (advanced planning)
1. Call plan_sweep_pattern to generate waypoints for area coverage.
2. For each waypoint, call execute_navigation_sequence.

EXAMPLES:
- "Navigate BEACON-01 to building at (-15, -20)"
  → execute_navigation_sequence("BEACON-01", -15.0, -20.0)
  → Report: "BEACON-01 arrived at (-15.0, 17.0, -20.0). Route: 3 waypoints, over strategy."

- "Move BEACON-01 to (10, 20, -5)"
  → execute_navigation_sequence("BEACON-01", 10.0, -5.0, 20.0)
  → Report: "BEACON-01 moving to (10.0, 20.0, -5.0)."

Keep responses concise and operational.
"""

_DESCRIPTION = (
    "Handles all drone movement and flight path planning. "
    "Use for: moving drones to specific coordinates, returning drones to base, "
    "checking drone status, and planning sweep patterns over an area."
)


def make_navigation_agent(name: str = "navigation_agent") -> Agent:
    """
    Factory — ADK requires each agent instance to have exactly one parent.
    Call this once per parent (commander, scan_workflow) to get separate instances.
    """
    return Agent(
        name=name,
        model=QWEN3_INSTRUCT,
        description=_DESCRIPTION,
        generate_content_config=QWEN3_GEN_CONFIG,
        output_key="nav_result",
        instruction=_INSTRUCTION,
        tools=[
            FunctionTool(execute_navigation_sequence),
            FunctionTool(execute_return_to_base),
            FunctionTool(get_drone_status),
            FunctionTool(plan_sweep_pattern),
        ],
    )


# Default singleton — used directly by commander for movement-only tasks
navigation_agent = make_navigation_agent()
