from __future__ import annotations

import asyncio

from backend.runtime import grpc_client

# Pre-defined formation offsets (x, y, z) relative to base.
_FORMATIONS: dict[str, list[tuple[float, float, float]]] = {
    "spread": [(0, 0, 10), (10, 0, 10), (-10, 0, 10), (0, 10, 10), (0, -10, 10)],
    "line": [(i * 8, 0, 10) for i in range(5)],
    "triangle": [(0, 0, 10), (6, 6, 10), (-6, 6, 10)],
}


async def move_drone_to(
    asset_id: str, x: float, y: float, z: float, speed: float = 5.0
) -> dict:
    """Move a drone to the given X/Y/Z coordinates at the specified speed."""
    return await grpc_client.move_to(asset_id, x, y, z, speed)


async def return_to_base(asset_id: str) -> dict:
    """Command a drone to return to its home position (0, 0, 0)."""
    return await grpc_client.return_to_base(asset_id)


async def get_drone_status(asset_id: str) -> dict:
    """Get the current position, battery level, and status of a drone."""
    return await grpc_client.get_status(asset_id)


async def scan_area(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """
    Command a drone to scan a circular area centred at (cx, cy, cz).
    Used for thermal imaging and survivor detection.
    """
    return await grpc_client.scan_area(asset_id, cx, cy, cz, radius)


async def thermal_scan(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """SAR-specific alias for area scanning."""
    return await scan_area(asset_id, cx, cy, cz, radius)


def plan_sweep_pattern(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    altitude: float = 10.0,
    spacing: float = 5.0,
) -> dict:
    """
    Compute a lawnmower sweep pattern over a rectangular area.
    Returns a list of (x, y, z) waypoints for systematic coverage.
    """
    waypoints: list[dict] = []
    x = min_x
    direction = 1
    while x <= max_x:
        row = [
            {"x": x, "y": min_y, "z": altitude},
            {"x": x, "y": max_y, "z": altitude},
        ]
        waypoints.extend(row if direction == 1 else list(reversed(row)))
        x += spacing
        direction *= -1
    return {"waypoints": waypoints, "count": len(waypoints)}


async def deploy_swarm(asset_ids: list[str], formation: str = "spread") -> dict:
    """
    Deploy multiple drones in a named formation.
    Supported formations: 'spread', 'line', 'triangle'.
    """
    positions = _FORMATIONS.get(formation, _FORMATIONS["spread"])
    results = await asyncio.gather(
        *[
            grpc_client.move_to(aid, *positions[i % len(positions)])
            for i, aid in enumerate(asset_ids)
        ]
    )
    return {"deployed": asset_ids, "formation": formation, "results": list(results)}


async def recall_swarm(asset_ids: list[str]) -> dict:
    """Command all drones in the list to return to base immediately."""
    results = await asyncio.gather(
        *[grpc_client.return_to_base(aid) for aid in asset_ids]
    )
    return {"recalled": asset_ids, "results": list(results)}
