"""In-memory registry for operator-placed supply stations and nearest-to-target
selection.

The home pad at (0,0,0) is NOT a supply pickup point; it is only used for
drone storage/recall. Supply dispatches must route through an operator-placed
station — if none exists, dispatch fails with a clear error so the operator
knows to place one first.
"""
from __future__ import annotations

import math
import threading
from itertools import count

# Fallback placement bound if the active world model is unavailable. The
# authoritative value comes from WorldModel.half_span (populated from each
# world's scene.world_half_span_m). All current worlds are 100×100 centered
# at origin, giving half_span = 50.0.
_FALLBACK_HALF_SPAN = 50.0

# Defensive cap on user-placed stations per backend process. Prevents runaway
# growth from a buggy or malicious client POSTing in a tight loop. Real
# operational use never approaches this limit; callers hit it with 429.
MAX_USER_STATIONS = 50

_lock = threading.Lock()
_id_counter = count(1)
_user_stations: list[dict] = []


def _get_world():
    """Lazy import to avoid circular imports during test fixtures."""
    from backend.services.core import context as service_context
    return service_context.get_world()


def _world_half_span() -> float:
    """Return the current world's placement half-span in metres."""
    try:
        return float(_get_world().half_span)
    except (AttributeError, TypeError):
        return _FALLBACK_HALF_SPAN


def reset() -> None:
    """Clear all user-placed stations. For tests / lifespan restart."""
    global _id_counter
    with _lock:
        _user_stations.clear()
        _id_counter = count(1)


def list_stations() -> list[dict]:
    """Return all operator-placed stations in insertion order (no home)."""
    with _lock:
        return [dict(s) for s in _user_stations]


class StationLimitReached(Exception):
    """Raised when the per-process cap on user-placed stations is hit."""


def add_station(*, x: float, z: float) -> dict:
    """Validate and append a user-placed station.

    Raises:
        ValueError: If placement is out of bounds or inside a building.
        StationLimitReached: If the user-placed station count would exceed
            MAX_USER_STATIONS.
    """
    half_span = _world_half_span()
    if abs(x) > half_span or abs(z) > half_span:
        raise ValueError(f"Placement out of bounds: ({x}, {z})")

    world = _get_world()
    with _lock:
        if len(_user_stations) >= MAX_USER_STATIONS:
            raise StationLimitReached(
                f"Station limit reached ({MAX_USER_STATIONS}); remove an existing station first."
            )
        # y=0 samples the ground plane. building_at returns the containing building
        # (AABB hit) or None for open ground.
        if world.building_at(x, 0.0, z) is not None:
            raise ValueError(f"Placement inside building at ({x}, {z})")
        station = {"id": f"station-{next(_id_counter)}", "x": float(x), "z": float(z)}
        _user_stations.append(station)
        return dict(station)


def remove_station(station_id: str) -> bool:
    """Remove a user-placed station. Returns False if not found."""
    with _lock:
        for i, station in enumerate(_user_stations):
            if station["id"] == station_id:
                _user_stations.pop(i)
                return True
    return False


def select_best_station(*, target_x: float, target_z: float) -> dict | None:
    """Return the user-placed station nearest to (target_x, target_z).

    Returns None when no stations have been placed. Callers must handle this
    case — home is no longer a fallback pickup point. Ties go to the earliest
    station in insertion order.
    """
    with _lock:
        candidates = list(_user_stations)
    if not candidates:
        return None
    best = min(
        candidates,
        key=lambda s: math.hypot(s["x"] - target_x, s["z"] - target_z),
    )
    return dict(best)
