from __future__ import annotations

from backend.world.model import Building, WORLD


def _safe_standoff_per_face(
    building: Building,
    desired: float,
    min_standoff: float = 1.0,
    clearance: float = 0.5,
) -> dict[str, float]:
    """Compute the max safe standoff per face given neighbouring buildings."""
    face_standoffs: dict[str, float] = {}
    for face in ("north", "south", "east", "west"):
        best = desired
        for nb in WORLD.buildings:
            if nb.id == building.id:
                continue
            if face == "north":
                if nb.max_x <= building.min_x or nb.min_x >= building.max_x:
                    continue
                if nb.max_z <= building.min_z and nb.max_z > building.min_z - desired:
                    best = min(best, building.min_z - nb.max_z - clearance)
            elif face == "south":
                if nb.max_x <= building.min_x or nb.min_x >= building.max_x:
                    continue
                if nb.min_z >= building.max_z and nb.min_z < building.max_z + desired:
                    best = min(best, nb.min_z - building.max_z - clearance)
            elif face == "west":
                if nb.max_z <= building.min_z or nb.min_z >= building.max_z:
                    continue
                if nb.max_x <= building.min_x and nb.max_x > building.min_x - desired:
                    best = min(best, building.min_x - nb.max_x - clearance)
            elif face == "east":
                if nb.max_z <= building.min_z or nb.min_z >= building.max_z:
                    continue
                if nb.min_x >= building.max_x and nb.min_x < building.max_x + desired:
                    best = min(best, nb.min_x - building.max_x - clearance)
        face_standoffs[face] = max(best, min_standoff)
    return face_standoffs


def _route_sweep_segment(
    from_x: float,
    from_y: float,
    from_z: float,
    to_x: float,
    to_y: float,
    to_z: float,
    exclude_id: int,
    clear_y: float,
    margin: float = 1.0,
) -> list[dict]:
    """Return intermediate transit waypoints needed to route around blocked sweep legs.

    Only *external* buildings (id != exclude_id) trigger a climb-over.  The
    building-under-sweep is intentionally excluded: with the ring start corner
    now derived from the entry window face (sweep_planner.py), intra-floor ring
    segments stay on the same face at standoff distance and never cross the
    target building's footprint.  Re-including the target building here is
    therefore unnecessary and caused false-positive rooftop-altitude climbs.

    The detour altitude is ``blocker.max_y + 3`` — NOT forced up to the full
    rooftop sweep altitude.
    """
    blockers = [
        b for b in WORLD.obstacles_in_path(
            from_x,
            from_y,
            from_z,
            to_x,
            to_y,
            to_z,
            samples=30,
            margin=margin,
        )
        if b.id != exclude_id
    ]
    if not blockers:
        return []

    over_y = round(max(b.max_y for b in blockers) + 3.0, 2)
    return [
        {
            "x": round(from_x, 2),
            "y": over_y,
            "z": round(from_z, 2),
            "reason": "climb over adjacent building",
            "transit": True,
        },
        {
            "x": round(to_x, 2),
            "y": over_y,
            "z": round(to_z, 2),
            "reason": "cruise over adjacent building",
            "transit": True,
        },
    ]
