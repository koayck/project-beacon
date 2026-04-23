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
from backend.agents.recovery import recovery_agent
from backend.agents.navigation import navigation_agent
from backend.agents.scan_workflow import scan_workflow
from backend.agents.supply_workflow import supply_workflow
from backend.instructions.commander_text import COMMANDER_INSTRUCTION
from backend.agents._mcp import make_toolset

commander = Agent(
    name="commander",
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
        AgentTool(scan_resolver_agent),
        make_toolset(["deploy_scout_sweep", "get_explored_sectors"]),
    ],
)
