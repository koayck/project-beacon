"""Commander agent backed by MCP tools for fleet discovery and control."""
from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT
from backend.agents.navigation import navigation_agent
from backend.agents.thermal import thermal_agent
from backend.tools.swarm_ops import deploy_swarm, recall_swarm


_MCP_URL = os.environ.get("BEACON_MCP_URL", "http://127.0.0.1:8000/mcp/")

beacon_mcp_toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url=_MCP_URL,
        timeout=10.0,
        sse_read_timeout=60.0,
    ),
)

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
    # tools=[beacon_mcp_toolset],
)
