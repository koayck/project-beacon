from __future__ import annotations

from fastmcp import FastMCP

from backend.services.fleet import discover_fleet, ensure_uplink
from backend.services.drone_control import (
    assign_fleet_to_buildings,
    find_buildings_in_area,
    get_drone_status,
    get_drone_view,
    move_drone_to,
    parallel_fleet_scan,
    plan_route,
    resolve_scan_target,
    return_to_base,
    scan_area,
    sweep_scan_building,
    recall_swarm,
    deploy_swarm,
    plan_sweep_pattern,
)

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
    asset_id: str, x: float, y: float, z: float, speed: float | None = None
) -> dict:
    """Move a specific drone to the provided coordinates."""
    return await move_drone_to(asset_id, x, y, z, speed)


@beacon_mcp.tool(name="get_drone_status")
async def get_drone_status_tool(asset_id: str) -> dict:
    """Return the current status snapshot for one drone."""
    return await get_drone_status(asset_id)


@beacon_mcp.tool(name="scan_area")
async def scan_area_tool(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """Perform a thermal scan around a point in the disaster zone."""
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


@beacon_mcp.tool(name="plan_route")
async def plan_route_tool(
    asset_id: str,
    target_x: float,
    target_z: float,
    target_y: float | None = None,
    snap_to_building_center: bool = False,
) -> dict:
    """
    Pre-compute a collision-free route from the drone's current position to target
    (target_x, target_z). Returns ordered waypoints for the caller to execute via
    move_drone_to. Altitude (target_y) is auto-calculated when omitted.
    """
    return await plan_route(asset_id, target_x, target_z, target_y, snap_to_building_center)


@beacon_mcp.tool(name="resolve_scan_target")
def resolve_scan_target_tool(
    target_x: float,
    target_z: float,
    margin: float = 3.0,
) -> dict:
    """
    Resolve a scan target to the nearest building footprint when the point is on or
    near a building. Returns building bounds and recommended scan altitude.
    """
    return resolve_scan_target(target_x, target_z, margin)


@beacon_mcp.tool(name="get_drone_view")
async def get_drone_view_tool(
    asset_id: str,
    heading_deg: float = 0.0,
    detection_range: float = 20.0,
) -> dict:
    """
    Get what the drone can currently see from its position: nearby buildings,
    visible survivors, terrain type, altitude above ground level, and obstacles ahead.
    """
    return await get_drone_view(asset_id, heading_deg, detection_range)


@beacon_mcp.tool(name="sweep_scan_building")
async def sweep_scan_building_tool(
    asset_id: str,
    target_x: float | None = None,
    target_z: float | None = None,
    scan_radius: float = 12.0,
    level_step: float = 3.0,
    standoff: float = 2.0,
) -> dict:
    """
    Execute a full-height perimeter sweep scan around a building above water level.
    Routes safely to each waypoint, runs scan_area at each point, and returns a
    structured coverage report with survivor counts per level (filtered by scan_radius).
    """
    return await sweep_scan_building(asset_id, target_x, target_z, scan_radius, level_step, standoff)



@beacon_mcp.tool(name="find_buildings_in_area")
def find_buildings_in_area_tool(
    center_x: float,
    center_z: float,
    radius: float = 30.0,
    drone_x: float | None = None,
    drone_z: float | None = None,
) -> dict:
    """
    Return all buildings within radius metres of (center_x, center_z), sorted
    nearest-first. When drone_x/drone_z are provided results are sorted by
    distance from the drone's current position instead of the search centre,
    reducing inter-building transit in multi-building area scans.
    Use before an area scan loop to discover which buildings need to be scanned.
    """
    return find_buildings_in_area(center_x, center_z, radius, drone_x, drone_z)


@beacon_mcp.tool(name="assign_fleet_to_buildings")
async def assign_fleet_to_buildings_tool(buildings: list[dict]) -> dict:
    """
    Assign the closest available IDLE drones to a list of buildings using greedy
    nearest-first matching. Returns assignments (drone→building), unassigned buildings
    (when fewer drones than buildings), and idle drones that were not needed.
    """
    return await assign_fleet_to_buildings(buildings)


@beacon_mcp.tool(name="parallel_fleet_scan")
async def parallel_fleet_scan_tool(
    assignments: list[dict],
    unassigned_buildings: list[dict] | None = None,
) -> dict:
    """
    Execute sweep scans for multiple drone-building assignments concurrently.
    Unassigned buildings are handled sequentially by the first drone after the
    parallel batch completes. Returns a consolidated report with per-building
    survivor counts and a formatted summary.
    """
    return await parallel_fleet_scan(assignments, unassigned_buildings)
