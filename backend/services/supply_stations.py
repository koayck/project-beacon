"""In-memory registry for supply stations and nearest-to-target selection.

Home base at (0,0,0) is a built-in, non-removable station. Additional stations
are placed at runtime via the REST API. Selection minimizes 2D Euclidean
distance from target to station. The first station in list order wins ties,
which means home (always first) wins ties at the origin.
"""
from __future__ import annotations

import math
import threading
from itertools import count
from types import MappingProxyType
from typing import Iterable, Mapping

HOME_STATION_ID = "home"
HOME_STATION: Mapping[str, object] = MappingProxyType(
    {"id": HOME_STATION_ID, "x": 0.0, "z": 0.0}
)

# Placement validity bounds. World2 is a 100×100 grid centered at origin.
# A station must sit on walkable ground inside or on the edge of this square
# (|x| <= WORLD_HALF_SPAN and |z| <= WORLD_HALF_SPAN).
WORLD_HALF_SPAN = 50.0

_lock = threading.Lock()
_id_counter = count(1)
_user_stations: list[dict] = []


def _get_world():
    """Lazy import to avoid circular imports during test fixtures."""
    from backend.services.core import context as service_context
    return service_context.get_world()


def reset() -> None:
    """Clear all user-placed stations. Home remains. For tests / lifespan restart."""
    global _id_counter
    with _lock:
        _user_stations.clear()
        _id_counter = count(1)


def list_stations() -> list[dict]:
    """Return home followed by user-placed stations in insertion order."""
    with _lock:
        return [dict(HOME_STATION)] + [dict(s) for s in _user_stations]


def add_station(*, x: float, z: float) -> dict:
    """Validate and append a user-placed station.

    Raises:
        ValueError: If placement is out of bounds or inside a building.
    """
    if abs(x) > WORLD_HALF_SPAN or abs(z) > WORLD_HALF_SPAN:
        raise ValueError(f"Placement out of bounds: ({x}, {z})")

    world = _get_world()
    with _lock:
        # y=0 samples the ground plane. building_at returns the containing building
        # (AABB hit) or None for open ground.
        if world.building_at(x, 0.0, z) is not None:
            raise ValueError(f"Placement inside building at ({x}, {z})")
        station = {"id": f"station-{next(_id_counter)}", "x": float(x), "z": float(z)}
        _user_stations.append(station)
        return dict(station)


def remove_station(station_id: str) -> bool:
    """Remove a user-placed station. Returns False if not found.

    Raises:
        ValueError: If caller attempts to remove the built-in home station.
    """
    if station_id == HOME_STATION_ID:
        raise ValueError("Home station cannot be removed")
    with _lock:
        for i, station in enumerate(_user_stations):
            if station["id"] == station_id:
                _user_stations.pop(i)
                return True
    return False


def select_best_station(*, target_x: float, target_z: float) -> dict:
    """Return the station minimizing 2D Euclidean distance to (target_x, target_z).

    Home is always in the candidate pool, so the result is never None. Ties go
    to the earliest station in list order (home first, then insertion order).
    """
    candidates: Iterable[dict] = list_stations()
    best = min(
        candidates,
        key=lambda s: math.hypot(s["x"] - target_x, s["z"] - target_z),
    )
    return dict(best)
