"""
Commander Agent — root agent that routes natural language commands
to the Navigation or Thermal sub-agent.
"""
from __future__ import annotations

from google.adk.agents import Agent

from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.agents.navigation import navigation_agent
from backend.agents.thermal import thermal_agent
from backend.tools.swarm_ops import deploy_swarm, recall_swarm

commander = Agent(
    name="commander",
    model=QWEN3_INSTRUCT,
    description="Root agent. Routes drone swarm commands to the correct specialist sub-agent.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction="""You are the Ground Control Station commander for an autonomous drone swarm.

You receive natural language commands and route them to the correct specialist:
- navigation_agent: movement, positioning, waypoints, returning to base, status checks
- thermal_agent: scanning, thermal imaging, survivor detection, heat signatures

For swarm-wide operations (deploy all drones, recall all drones), use deploy_swarm
or recall_swarm directly.

Guidelines:
- Always extract the asset_id from the command (e.g. "BEACON-01", "beacon-01" → "BEACON-01")
- If no specific drone is mentioned, ask the user to specify one or list available drones
- Confirm every action taken with a clear status report
- If an action fails, explain why and suggest alternatives
- Keep responses concise and operational
""",
    sub_agents=[navigation_agent, thermal_agent],
    tools=[deploy_swarm, recall_swarm],
)
