"""Compatibility wrappers over the shared drone control service layer."""
from __future__ import annotations

from backend.services.drone_control import (
    get_drone_status as service_get_drone_status,
    move_drone_to as service_move_drone_to,
    plan_sweep_pattern as service_plan_sweep_pattern,
    return_to_base as service_return_to_base,
    scan_area as service_scan_area,
)


async def move_drone_to(
    asset_id: str, x: float, y: float, z: float, speed: float = 5.0
) -> dict:
    """Move a drone to the given X/Y/Z coordinates at the specified speed."""
    return await service_move_drone_to(asset_id, x, y, z, speed)


async def return_to_base(asset_id: str) -> dict:
    """Command a drone to return to its home position (0, 0, 0)."""
    return await service_return_to_base(asset_id)


async def get_drone_status(asset_id: str) -> dict:
    """Get the current position, battery level, and status of a drone."""
    return await service_get_drone_status(asset_id)


async def scan_area(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """
    Command a drone to scan a circular area centred at (cx, cy, cz).
    Used for thermal imaging and survivor detection.
    """
    return await service_scan_area(asset_id, cx, cy, cz, radius)


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
    return service_plan_sweep_pattern(min_x, min_y, max_x, max_y, altitude, spacing)
