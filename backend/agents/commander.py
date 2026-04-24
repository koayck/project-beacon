"""
Enhanced Commander Agent — Hybrid architecture with strategic planning.

Routes commands through: Command Parser → Mission Planner → Orchestrators
"""
from __future__ import annotations

from google.adk.agents import Agent
from google.adk.tools import AgentTool

from backend.agents._model import QWEN3_GEN_CONFIG_COMMANDER, QWEN3_INSTRUCT
from backend.agents.command_parser import command_parser
from backend.agents.scan_resolver import scan_resolver_agent
from backend.agents.supply_resolver import supply_resolver_agent
from backend.agents.recovery import recovery_agent
from backend.agents.navigation import navigation_agent
from backend.agents.scan_agent import scan_agent
from backend.agents.supply_agent import supply_agent
# CommandIntent import was used by the now-disabled is_complex_mission tool
# (see comment block below). Re-enable the import if the function is restored.
# from backend.agents.schemas import CommandIntent
from backend.instructions.commander_text import COMMANDER_INSTRUCTION
from backend.agents._mcp import make_toolset


# Kept for reference only — deliberately NOT registered as a tool. The planner
# refactor (commit e723081) removed the complexity check from the routing
# flow; execution goes straight to the specialist agent via mission_type. Do
# not re-register — doing so brings back the hallucination-prone "Simple vs.
# Complex" reasoning path that the refactor was removing.
#
# def is_complex_mission(intent: dict) -> bool:
#     return CommandIntent.model_validate(intent).is_complex_mission()


commander = Agent(
    name="commander",
    model=QWEN3_INSTRUCT,
    description="Enhanced commander with strategic planning and adaptive recovery",
    generate_content_config=QWEN3_GEN_CONFIG_COMMANDER,
    instruction=COMMANDER_INSTRUCTION,
    sub_agents=[
        recovery_agent,
        navigation_agent,
        scan_agent,
        supply_agent,
    ],
    tools=[
        AgentTool(command_parser),
        AgentTool(scan_resolver_agent),
        AgentTool(supply_resolver_agent),
        make_toolset(["deploy_scout_sweep", "get_explored_sectors"]),
    ],
)
