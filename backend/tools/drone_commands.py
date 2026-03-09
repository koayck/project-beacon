"""
Drone command tools — called by ADK agents.
Each function maps 1:1 to a gRPC operation via DroneGrpcClient.
Injected with the client at startup via set_client().
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.grpc.client import DroneGrpcClient

_client: DroneGrpcClient | None = None


def set_client(client: DroneGrpcClient) -> None:
    global _client
    _client = client


def _get_client() -> DroneGrpcClient:
    if _client is None:
        raise RuntimeError("gRPC client not initialised. Call set_client() at startup.")
    return _client


async def move_drone_to(
    asset_id: str, x: float, y: float, z: float, speed: float = 5.0
) -> dict:
    """Move a drone to the given X/Y/Z coordinates at the specified speed."""
    return await _get_client().move_to(asset_id, x, y, z, speed)


async def return_to_base(asset_id: str) -> dict:
    """Command a drone to return to its home position (0, 0, 0)."""
    return await _get_client().return_to_base(asset_id)


async def get_drone_status(asset_id: str) -> dict:
    """Get the current position, battery level, and status of a drone."""
    return await _get_client().get_status(asset_id)


async def scan_area(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict:
    """
    Command a drone to scan a circular area centred at (cx, cy, cz).
    Used for thermal imaging and survivor detection.
    """
    return await _get_client().scan_area(asset_id, cx, cy, cz, radius)


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
