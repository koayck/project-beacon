"""
Enhanced Commander Agent — Hybrid architecture with strategic planning.

Routes commands through: Command Parser → Mission Planner → Orchestrators
"""
from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import AgentTool

from backend.agents._model import QWEN3_GEN_CONFIG_COMMANDER, QWEN3_INSTRUCT
from backend.agents.command_parser import command_parser
from backend.agents.mission_planner import mission_planner
from backend.agents.recovery import recovery_agent
from backend.agents.navigation import navigation_agent
from backend.agents.scan_workflow import scan_workflow
from backend.agents.supply_workflow import supply_workflow
from backend.agents.schemas import CommandIntent
from backend.instructions.commander_text import COMMANDER_INSTRUCTION


def is_complex_mission(intent: dict) -> bool:
    return CommandIntent.model_validate(intent).is_complex_mission()


enhanced_commander = Agent(
    name="enhanced_commander",
    model=QWEN3_INSTRUCT,
    description="Enhanced commander with strategic planning and adaptive recovery",
    generate_content_config=QWEN3_GEN_CONFIG_COMMANDER,
    instruction=COMMANDER_INSTRUCTION,
    sub_agents=[
        recovery_agent,
        navigation_agent,
        scan_workflow,
        supply_workflow,
    ],
    tools=[
        AgentTool(command_parser),
        is_complex_mission,
        # AgentTool(mission_planner),
    ],
)
