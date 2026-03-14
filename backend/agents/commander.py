"""Commander agent backed by MCP tools for fleet discovery and control."""
from __future__ import annotations

import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StreamableHTTPConnectionParams,
)
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

from backend.agents._model import QWEN3_GEN_CONFIG, QWEN3_INSTRUCT

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
    description="Ground control commander that discovers and directs the rescue fleet through MCP.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction="""You are the Ground Control Station commander for an autonomous rescue swarm.

For every new mission:
1. Call discover_fleet first to identify active drones, battery levels, and current positions.
2. Explain your operational reasoning in brief, visible steps before executing tools.
3. Prefer the closest healthy drone for scans and movement.
4. If a preferred drone is unavailable, choose another active drone and say why.
5. If battery is low, return or avoid assigning that drone to distant work.

Tool use rules:
- Do not assume drone IDs exist until discover_fleet confirms them.
- Use establish_uplink if a discovered drone is not yet uplinked.
- Use get_drone_status before risky or long-distance actions when battery is relevant.
- Use thermal_scan or scan_area for survivor and heat-signature missions.
- Use deploy_swarm and recall_swarm for multi-drone operations.

Response style:
- Start with a short plan summary.
- Then execute the required tools.
- End with a concise operational status report.
""",
    tools=[beacon_mcp_toolset],
)
