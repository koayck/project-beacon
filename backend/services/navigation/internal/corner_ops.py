from __future__ import annotations

import math

from backend.world.model import WORLD

# Clockwise corner order (NW=0, NE=1, SE=2, SW=3).
_CORNERS_CW: list[str] = ["NW", "NE", "SE", "SW"]

# Face traversed going CW from each corner to the next CW corner.
_CW_FACE: dict[str, str] = {
    "NW": "north",  # NW -> NE
    "NE": "east",   # NE -> SE
    "SE": "south",  # SE -> SW
    "SW": "west",   # SW -> NW
}


def _push_xz_clear(
    x: float,
    z: float,
    exclude_id: int,
    clearance: float = 0.5,
    max_iters: int = 5,
    prefer_z: bool = False,
) -> tuple[float, float]:
    """Push (x, z) outside any building it overlaps (except the excluded building)."""
    for _ in range(max_iters):
        pushed = False
        for b in WORLD.buildings:
            if b.id == exclude_id:
                continue
            if b.min_x <= x <= b.max_x and b.min_z <= z <= b.max_z:
                dist_e = b.max_x - x
                dist_w = x - b.min_x
                dist_s = b.max_z - z
                dist_n = z - b.min_z
                m = min(dist_e, dist_w, dist_s, dist_n)
                if prefer_z:
                    if m == dist_s:
                        z = b.max_z + clearance
                    elif m == dist_n:
                        z = b.min_z - clearance
                    elif m == dist_e:
                        x = b.max_x + clearance
                    else:
                        x = b.min_x - clearance
                else:
                    if m == dist_e:
                        x = b.max_x + clearance
                    elif m == dist_w:
                        x = b.min_x - clearance
                    elif m == dist_s:
                        z = b.max_z + clearance
                    else:
                        z = b.min_z - clearance
                pushed = True
                break
        if not pushed:
            break
    return round(x, 2), round(z, 2)


def _nearest_corner(
    x: float,
    z: float,
    corners: dict[str, tuple[float, float]],
) -> str:
    """Return the corner label (NW/NE/SE/SW) nearest to (x, z)."""
    return min(
        corners,
        key=lambda c: math.sqrt((corners[c][0] - x) ** 2 + (corners[c][1] - z) ** 2),
    )


def _window_sort_reverse(face: str, clockwise: bool) -> tuple[str, bool]:
    """Return ``(sort_field, reverse)`` for window waypoints on *face*."""
    if face == "north":
        return ("x", not clockwise)
    if face == "east":
        return ("z", not clockwise)
    if face == "south":
        return ("x", clockwise)
    return ("z", clockwise)


def _build_ring(
    start: str,
    clockwise: bool,
    level_windows: dict[str, list[dict]],
    corners: dict[str, tuple[float, float]],
    nw_pushed_east: bool = False,
    west_stop_z: float | None = None,
    p_min_x: float = 0.0,
) -> tuple[list[tuple[float, float, str]], str]:
    """Build an open perimeter ring starting at *start* corner."""
    idx = _CORNERS_CW.index(start)
    step = 1 if clockwise else -1
    order = [_CORNERS_CW[(idx + step * i) % 4] for i in range(4)]

    ring: list[tuple[float, float, str]] = []

    for i, corner in enumerate(order):
        cx, cz = corners[corner]
        ring.append((cx, cz, f"perimeter {corner}"))

        if i == 3:
            return_face = _CW_FACE[order[-1]] if clockwise else _CW_FACE[order[0]]
            sf, rev = _window_sort_reverse(return_face, clockwise)
            for ww in sorted(level_windows.get(return_face, []), key=lambda w: w[sf], reverse=rev):
                ring.append((ww["x"], ww["z"], f"window scan {return_face} floor {ww['floor']}"))
            break

        next_corner = order[i + 1]
        face = _CW_FACE[corner] if clockwise else _CW_FACE[next_corner]

        sf, rev = _window_sort_reverse(face, clockwise)
        for ww in sorted(level_windows.get(face, []), key=lambda w: w[sf], reverse=rev):
            ring.append((ww["x"], ww["z"], f"window scan {face} floor {ww['floor']}"))

        if face == "west" and clockwise and nw_pushed_east:
            nw_x, nw_z = corners["NW"]
            if west_stop_z is not None and west_stop_z > nw_z + 0.01:
                ring.append((p_min_x, west_stop_z, "west face stop (adjacent building)"))

    return ring, order[-1]


def _west_face_stop_z(
    west_x: float,
    to_z: float,
    exclude_id: int,
    clearance: float = 0.5,
) -> float:
    """Southernmost safe z when flying north along x=west_x toward to_z."""
    stop_z = to_z
    for b in WORLD.buildings:
        if b.id == exclude_id:
            continue
        if b.min_x <= west_x <= b.max_x and b.max_z > to_z:
            stop_z = max(stop_z, b.max_z + clearance)
    return round(stop_z, 2)
