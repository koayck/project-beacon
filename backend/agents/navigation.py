"""
Navigation Agent — flight path planning and drone movement.
"""
from __future__ import annotations

from google.adk.agents import Agent

from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.tools.drone_commands import (
    get_drone_status,
    move_drone_to,
    plan_sweep_pattern,
    return_to_base,
)

navigation_agent = Agent(
    name="navigation_agent",
    model=QWEN3_INSTRUCT,
    description=(
        "Handles all drone movement and flight path planning. "
        "Use for: moving drones to specific coordinates, returning drones to base, "
        "checking drone status, and planning sweep patterns over an area."
    ),
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction="""You are a navigation specialist for autonomous drones.

When given a movement command:
1. Identify the target asset_id (e.g. BEACON-01)
2. Parse the target coordinates (x, y, z) from the request
3. Call move_drone_to with the correct parameters
4. Report the result clearly

When asked to plan a sweep:
1. Parse the area bounds (min_x, min_y, max_x, max_y)
2. Call plan_sweep_pattern to generate waypoints
3. Then move the drone through each waypoint in sequence

Always confirm success or report errors clearly.
Coordinates are in metres. Altitude (z) should be at least 5.0 unless specified.
""",
    tools=[move_drone_to, return_to_base, get_drone_status, plan_sweep_pattern],
)
