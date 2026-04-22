from __future__ import annotations

import math

from backend.services.navigation.internal.corner_ops import (
    _build_ring,
    _nearest_corner,
    _push_xz_clear,
    _west_face_stop_z,
)
from backend.services.navigation.internal.safety_ops import (
    _route_sweep_segment,
    _safe_standoff_per_face,
)
from backend.world.model import (
    BUILDING_PROXIMITY_MARGIN_M,
    FLOOD_LEVEL,
    WORLD,
)


def plan_building_vertical_sweep(
    target_x: float,
    target_z: float,
    level_step: float = 3.0,
    standoff: float = 2.0,
    flood_clearance: float = 0.5,
    approach_x: float | None = None,
    approach_z: float | None = None,
) -> dict:
    """Plan a perimeter sweep around a building across all heights above water level.

    The sweep always enters at a lowest-floor window closest to
    ``(approach_x, approach_z)`` and iterates floors ascending, ending at
    the last floor's perimeter. No rooftop scan waypoint is emitted.
    """
    building = WORLD.building_near_xz(target_x, target_z, margin=BUILDING_PROXIMITY_MARGIN_M)
    if building is None:
        return {
            "matched_building": False,
            "error": "No nearby building for sweep scan",
            "input": {"x": target_x, "z": target_z},
        }

    safe_standoff = max(standoff, 0.5)
    start_y = max(FLOOD_LEVEL + max(flood_clearance, 0.0), 0.5)
    top_y = building.max_y
    if start_y > top_y:
        return {
            "matched_building": True,
            "error": "Building has no scanable height above water level",
            "building": {
                "id": building.id,
                "min_x": building.min_x,
                "max_x": building.max_x,
                "min_z": building.min_z,
                "max_z": building.max_z,
                "center_x": building.cx,
                "center_z": building.cz,
                "height": building.h,
            },
            "flood_level": FLOOD_LEVEL,
        }

    face_standoffs = _safe_standoff_per_face(building, safe_standoff)

    all_window_wps: list[dict] = []
    for window in building.windows:
        y = round(window.sill_y + window.height / 2, 2)
        floor = int(window.sill_y // 3.0) + 1
        so = face_standoffs[window.face]
        if window.face == "north":
            x, z = window.axis_center, building.min_z - so
        elif window.face == "south":
            x, z = window.axis_center, building.max_z + so
        elif window.face == "west":
            x, z = building.min_x - so, window.axis_center
        else:
            x, z = building.max_x + so, window.axis_center
        all_window_wps.append(
            {
                "x": round(x, 2),
                "y": y,
                "z": round(z, 2),
                "face": window.face,
                "floor": floor,
            }
        )
    above_flood = [w for w in all_window_wps if w["y"] >= start_y]

    floor_levels = sorted({round(w["y"], 2) for w in above_flood})

    perimeter_margin = 1.0
    p_min_x = building.min_x - perimeter_margin
    p_max_x = building.max_x + perimeter_margin
    p_min_z = building.min_z - perimeter_margin
    p_max_z = building.max_z + perimeter_margin

    _CORNER_CLEARANCE = 1.5
    nw_x, nw_z = _push_xz_clear(p_min_x, p_min_z, building.id, clearance=_CORNER_CLEARANCE)
    ne_x, ne_z = _push_xz_clear(p_max_x, p_min_z, building.id, clearance=_CORNER_CLEARANCE, prefer_z=True)
    se_x, se_z = _push_xz_clear(p_max_x, p_max_z, building.id, clearance=_CORNER_CLEARANCE, prefer_z=True)
    sw_x, sw_z = _push_xz_clear(p_min_x, p_max_z, building.id, clearance=_CORNER_CLEARANCE)

    _nw_pushed_east = nw_x > p_min_x + 0.01
    west_stop_z = _west_face_stop_z(p_min_x, p_min_z, building.id) if _nw_pushed_east else p_min_z

    rooftop_y = round(top_y + safe_standoff, 2)

    corners: dict[str, tuple[float, float]] = {
        "NW": (nw_x, nw_z),
        "NE": (ne_x, ne_z),
        "SE": (se_x, se_z),
        "SW": (sw_x, sw_z),
    }

    _serpentine = approach_x is not None and approach_z is not None
    if _serpentine:
        _start_corner = _nearest_corner(approach_x, approach_z, corners)  # type: ignore[arg-type]
    else:
        _start_corner = "NW"

    waypoints: list[dict] = []
    levels: list[float] = []

    entry_window: dict | None = None
    if floor_levels:
        first_level_y = floor_levels[0]
        first_level_windows = [w for w in above_flood if round(w["y"], 2) == first_level_y]
        if approach_x is not None and approach_z is not None:
            ref_x, ref_z = approach_x, approach_z
        else:
            ref_x, ref_z = corners[_start_corner]

        if first_level_windows:
            entry_window = min(
                first_level_windows,
                key=lambda w: math.sqrt((float(w["x"]) - ref_x) ** 2 + (float(w["z"]) - ref_z) ** 2),
            )
            waypoints.append(
                {
                    "x": float(entry_window["x"]),
                    "y": float(entry_window["y"]),
                    "z": float(entry_window["z"]),
                    "level_y": float(entry_window["y"]),
                    "reason": f"window scan {entry_window['face']} floor {entry_window['floor']}",
                }
            )
        else:
            sc_x, sc_z = corners[_start_corner]
            waypoints.append(
                {
                    "x": sc_x,
                    "y": first_level_y,
                    "z": sc_z,
                    "level_y": first_level_y,
                    "reason": f"approach to {_start_corner} corner",
                }
            )

    _current_corner = _start_corner
    _cw = True
    _last_rx: float = waypoints[-1]["x"] if waypoints else corners[_start_corner][0]
    _last_rz: float = waypoints[-1]["z"] if waypoints else corners[_start_corner][1]

    for level_y in floor_levels:
        levels.append(level_y)
        level_wps = [w for w in above_flood if round(w["y"], 2) == level_y]
        level_windows: dict[str, list[dict]] = {}
        for w in level_wps:
            level_windows.setdefault(w["face"], []).append(w)

        if _serpentine:
            ring_items, end_corner = _build_ring(
                start=_current_corner,
                clockwise=_cw,
                level_windows=level_windows,
                corners=corners,
                nw_pushed_east=_nw_pushed_east,
                west_stop_z=west_stop_z if _nw_pushed_east else None,
                p_min_x=p_min_x,
            )
            if entry_window is not None and abs(level_y - float(entry_window["y"])) < 1e-3:
                ring_items = [
                    item
                    for item in ring_items
                    if not (
                        item[2] == f"window scan {entry_window['face']} floor {entry_window['floor']}"
                        and abs(item[0] - float(entry_window["x"])) < 1e-3
                        and abs(item[1] - float(entry_window["z"])) < 1e-3
                    )
                ]
            if level_y == floor_levels[0] and waypoints:
                prev_rx, prev_rz = _last_rx, _last_rz
            else:
                prev_rx, prev_rz = corners[_current_corner]

            if ring_items:
                first_rx, first_rz, _ = ring_items[0]
                # Exclude the building under sweep: the inter-floor diagonal
                # from the last window waypoint to the first corner of the next
                # ring often crosses the building's own AABB, causing a false
                # obstacle detection that triggered a rooftop-altitude climb.
                # Real external blockers still trigger a clearance climb, but
                # we drop the `max(..., rooftop_y)` floor so the drone only
                # climbs as high as actually needed.
                inter_blockers = [
                    b for b in WORLD.obstacles_in_path(
                        _last_rx,
                        level_y,
                        _last_rz,
                        first_rx,
                        level_y,
                        first_rz,
                        samples=30,
                        margin=0.0,
                    )
                    if b.id != building.id
                ]
                if inter_blockers:
                    over_y = round(max(b.max_y for b in inter_blockers) + 3.0, 2)
                    waypoints.append(
                        {
                            "x": round(_last_rx, 2),
                            "y": over_y,
                            "z": round(_last_rz, 2),
                            "level_y": over_y,
                            "reason": "inter-floor climb",
                            "transit": True,
                        }
                    )
                    waypoints.append(
                        {
                            "x": round(first_rx, 2),
                            "y": over_y,
                            "z": round(first_rz, 2),
                            "level_y": over_y,
                            "reason": "inter-floor cruise",
                            "transit": True,
                        }
                    )

            for rx, rz, reason in ring_items:
                for extra in _route_sweep_segment(prev_rx, level_y, prev_rz, rx, level_y, rz, building.id, rooftop_y):
                    waypoints.append({**extra, "level_y": rooftop_y})
                waypoints.append(
                    {
                        "x": round(rx, 2),
                        "y": level_y,
                        "z": round(rz, 2),
                        "level_y": level_y,
                        "reason": reason,
                    }
                )
                prev_rx, prev_rz = rx, rz
            _current_corner = end_corner
            _last_rx, _last_rz = prev_rx, prev_rz
            _cw = not _cw

        else:
            ring: list[tuple[float, float, str]] = [(nw_x, nw_z, "perimeter NW")]
            for ww in level_windows.get("north", []):
                ring.append((ww["x"], ww["z"], f"window scan north floor {ww['floor']}"))
            ring.append((ne_x, ne_z, "perimeter NE"))
            for ww in level_windows.get("east", []):
                ring.append((ww["x"], ww["z"], f"window scan east floor {ww['floor']}"))
            ring.append((se_x, se_z, "perimeter SE"))
            for ww in level_windows.get("south", []):
                ring.append((ww["x"], ww["z"], f"window scan south floor {ww['floor']}"))
            ring.append((sw_x, sw_z, "perimeter SW"))
            for ww in level_windows.get("west", []):
                ring.append((ww["x"], ww["z"], f"window scan west floor {ww['floor']}"))
            if _nw_pushed_east and west_stop_z > p_min_z + 0.01:
                ring.append((p_min_x, west_stop_z, "west face stop (adjacent building)"))
            ring.append((nw_x, nw_z, "close perimeter"))

            if entry_window is not None and abs(level_y - float(entry_window["y"])) < 1e-3:
                ring = [
                    item
                    for item in ring
                    if not (
                        item[2] == f"window scan {entry_window['face']} floor {entry_window['floor']}"
                        and abs(item[0] - float(entry_window["x"])) < 1e-3
                        and abs(item[1] - float(entry_window["z"])) < 1e-3
                    )
                ]

            if level_y == floor_levels[0] and waypoints:
                prev_rx, prev_rz = _last_rx, _last_rz
            else:
                prev_rx, prev_rz = nw_x, nw_z
            for rx, rz, reason in ring:
                for extra in _route_sweep_segment(prev_rx, level_y, prev_rz, rx, level_y, rz, building.id, rooftop_y):
                    waypoints.append({**extra, "level_y": rooftop_y})
                waypoints.append(
                    {
                        "x": round(rx, 2),
                        "y": level_y,
                        "z": round(rz, 2),
                        "level_y": level_y,
                        "reason": reason,
                    }
                )
                prev_rx, prev_rz = rx, rz


    return {
        "matched_building": True,
        "input": {"x": target_x, "z": target_z},
        "building": {
            "id": building.id,
            "min_x": building.min_x,
            "max_x": building.max_x,
            "min_z": building.min_z,
            "max_z": building.max_z,
            "center_x": building.cx,
            "center_z": building.cz,
            "height": building.h,
        },
        "flood_level": FLOOD_LEVEL,
        "levels": levels,
        "level_count": len(levels),
        "waypoints": waypoints,
        "waypoint_count": len(waypoints),
        "rooftop_position": {"x": building.cx, "y": rooftop_y, "z": building.cz},
        "summary": (
            f"Vertical perimeter sweep for building {building.id}: "
            f"{len(levels)} level(s), {len(waypoints)} waypoint(s)."
            if not levels
            else f"Vertical perimeter sweep for building {building.id}: "
                 f"{len(levels)} level(s), {len(waypoints)} waypoint(s), "
                 f"covering y={levels[0]:.1f}..{levels[-1]:.1f} above flood={FLOOD_LEVEL:.1f}."
        ),
    }
