from __future__ import annotations

from fastmcp import FastMCP

from backend.services.drone_control import (
    deploy_swarm,
    get_drone_status,
    move_drone_to,
    plan_sweep_pattern,
    recall_swarm,
    return_to_base,
    scan_area,
    thermal_scan,
)
from backend.services.fleet import discover_fleet, ensure_uplink

beacon_mcp = FastMCP(
    name="Project Beacon MCP",
    instructions=(
        "MCP tools for an offline search-and-rescue drone fleet. "
        "Call discover_fleet first for every new mission to identify active drones, "
        "their battery levels, and their current positions before issuing movement "
        "or scan commands."
    ),
)


@beacon_mcp.tool(name="discover_fleet")
async def discover_active_fleet(
    auto_uplink: bool = True,
    include_registered: bool = True,
) -> dict:
    """
    Discover drones currently active on the network.
    Returns a fleet list with battery, status, position, and uplink state.
    """
    return await discover_fleet(
        auto_uplink=auto_uplink,
        include_registered=include_registered,
    )


@beacon_mcp.tool(name="establish_uplink")
async def establish_uplink(asset_id: str) -> dict:
    """Register a discovered drone with the commander so control tools can use it."""
    return await ensure_uplink(asset_id)


@beacon_mcp.tool(name="move_drone_to")
async def move_drone_to_tool(
    asset_id: str, x: float, y: float, z: float, speed: float = 5.0
) -> dict:
    """Move a specific drone to the provided coordinates."""
    return await move_drone_to(asset_id, x, y, z, speed)


@beacon_mcp.tool(name="get_drone_status")
async def get_drone_status_tool(asset_id: str) -> dict:
    """Return the current status snapshot for one drone."""
    return await get_drone_status(asset_id)


@beacon_mcp.tool(name="thermal_scan")
async def thermal_scan_tool(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """Perform a thermal scan around a point in the disaster zone."""
    return await thermal_scan(asset_id, cx, cy, cz, radius)


@beacon_mcp.tool(name="scan_area")
async def scan_area_tool(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """Alias for thermal scans with the existing scan_area naming."""
    return await scan_area(asset_id, cx, cy, cz, radius)


@beacon_mcp.tool(name="return_to_base")
async def return_to_base_tool(asset_id: str) -> dict:
    """Return a single drone to base immediately."""
    return await return_to_base(asset_id)


@beacon_mcp.tool(name="deploy_swarm")
async def deploy_swarm_tool(asset_ids: list[str], formation: str = "spread") -> dict:
    """Deploy multiple drones in a named formation."""
    return await deploy_swarm(asset_ids, formation)


@beacon_mcp.tool(name="recall_swarm")
async def recall_swarm_tool(asset_ids: list[str]) -> dict:
    """Recall all listed drones to base."""
    return await recall_swarm(asset_ids)


@beacon_mcp.tool(name="plan_sweep_pattern")
def plan_sweep_pattern_tool(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    altitude: float = 10.0,
    spacing: float = 5.0,
) -> dict:
    """Generate a lawnmower sweep over a rectangular area."""
    return plan_sweep_pattern(min_x, min_y, max_x, max_y, altitude, spacing)
