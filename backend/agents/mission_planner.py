"""
Mission Planner Agent — Strategic mission planning.

Analyzes mission requirements and fleet status, outputs optimal execution plan.
"""
from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import FunctionTool

from backend.agents._model import QWEN3_GEN_CONFIG_COMMANDER, QWEN3_INSTRUCT
from backend.agents.schemas import (
    CommandIntent,
    MissionPlan,
    MissionStrategy,
    FleetAssignment,
)
from backend.services.api.control import list_all_drones
from backend.instructions.mission_planner_text import MISSION_PLANNER_INSTRUCTION


async def estimate_route_duration(
    from_x: float,
    from_z: float,
    to_x: float,
    to_z: float,
    speed_mps: float = 5.0
) -> dict:
    """Estimate flight duration between two points."""
    import math
    distance = math.sqrt((to_x - from_x)**2 + (to_z - from_z)**2)
    duration_s = distance / speed_mps
    return {
        "distance_m": round(distance, 1),
        "duration_s": round(duration_s, 1),
        "duration_min": round(duration_s / 60, 2)
    }


mission_planner = Agent(
    name="mission_planner",
    model=QWEN3_INSTRUCT,
    generate_content_config=QWEN3_GEN_CONFIG_COMMANDER,
    description="Strategic mission planner for complex multi-drone operations",
    instruction=MISSION_PLANNER_INSTRUCTION,
    output_schema=MissionPlan,
    tools=[
        list_all_drones,
        estimate_route_duration,
    ],
)
