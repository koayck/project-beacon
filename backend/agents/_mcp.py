"""Shared MCP toolset factory for ADK agents."""
from __future__ import annotations

import os

from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPConnectionParams
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset

_MCP_URL = os.environ.get("BEACON_MCP_URL", "http://127.0.0.1:8000/mcp/")

# Tool name groups — used by agents to declare which MCP tools they need.
NAV_TOOLS = [
    "plan_route",
    "move_drone_to",
    "return_to_base",
    "get_drone_status",
    "plan_sweep_pattern",
    "resolve_scan_target",
]

THERMAL_TOOLS = [
    "scan_area",
    "sweep_scan_building",
    "get_drone_status",
    "get_drone_view",
]

SWARM_TOOLS = [
    "deploy_swarm",
    "recall_swarm",
    "discover_fleet",
    "deploy_scout_sweep",
    "get_explored_sectors",
]

FLEET_TOOLS = [
    "assign_fleet_to_buildings",
    "parallel_fleet_scan",
    "discover_fleet",
]


def make_toolset(tool_filter: list[str] | None = None) -> McpToolset:
    """
    Return a new McpToolset instance pointing at the Beacon MCP server.
    Each agent must have its own instance — ADK enforces single-parent ownership.
    """
    return McpToolset(
        connection_params=StreamableHTTPConnectionParams(
            url=_MCP_URL,
            timeout=10.0,
            # Long enough to cover a full scout sweep (~90s at 15 m/s across
            # the 5x5 grid) plus RTB, with a comfortable margin for slower
            # runs.
            sse_read_timeout=360.0,
        ),
        tool_filter=tool_filter,
    )
