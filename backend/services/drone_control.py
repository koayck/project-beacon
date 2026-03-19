from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Iterable
from typing import TYPE_CHECKING

from backend.grpc.client import DroneGrpcClient
from backend.runtime import grpc_client
from backend.world.model import (
    BUILDING_PROXIMITY_MARGIN_M,
    FLOOD_LEVEL,
    FLOOR_HEIGHT_M,
    WINDOW_SCAN_STANDOFF_M,
    WORLD,
    Building,
)

_NORMAL_SPEED = 5.0
# _FAST_SPEED = 20.0
_drone_speeds: dict[str, float] = {}
# Match world vision survivor sensor range to avoid sweep summary undercounting.
DEFAULT_SWEEP_SCAN_RADIUS = 5.0
# Half-angle of the drone's forward-facing thermal camera cone (degrees).
# Survivors beyond this angle off the drone's heading are not detected.
THERMAL_HORIZ_FOV_HALF_DEG: float = 60.0
_detected_survivor_ids: set[int] = set()


def _normalize_survivor_id(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return int(raw)
    return None


def register_detected_survivors(rows: Iterable[dict]) -> int:
    """Persist survivor IDs detected during prior scans for later supply gating."""
    before = len(_detected_survivor_ids)
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = _normalize_survivor_id(row.get("id"))
        if sid is None:
            continue
        _detected_survivor_ids.add(sid)
    return len(_detected_survivor_ids) - before


def clear_detected_survivors() -> None:
    """Reset detected-survivor memory (used by tests)."""
    _detected_survivor_ids.clear()

# Pre-defined formation offsets (x, y, z) relative to base.
_FORMATIONS: dict[str, list[tuple[float, float, float]]] = {
    "spread": [(0, 0, 10), (10, 0, 10), (-10, 0, 10), (0, 10, 10), (0, -10, 10)],
    "line": [(i * 8, 0, 10) for i in range(5)],
    "triangle": [(0, 0, 10), (6, 6, 10), (-6, 6, 10)],
}


def _format_sweep_levels(levels: list[float]) -> str:
    return ", ".join(f"{level:g}" for level in levels)


def _format_sweep_findings(survivor_count: int) -> str:
    if survivor_count <= 0:
        return "No heat signatures detected."
    return f"{survivor_count} heat signature(s) detected."


def _build_sweep_scan_report(
    asset_id: str,
    building: dict,
    levels: list[float],
    flood_level: float,
    waypoint_count: int,
    survivor_count: int,
    battery: float,
    sensor_summary: str,
) -> str:
    return (
        f"SWEEP SCAN COMPLETE — {asset_id}\n"
        f"  Building  : X=({building['min_x']:.1f} to {building['max_x']:.1f}), "
        f"Z=({building['min_z']:.1f} to {building['max_z']:.1f})\n"
        f"  Levels    : {_format_sweep_levels(levels)} "
        f"(above flood level {flood_level:.1f}m)\n"
        f"  Waypoints : {waypoint_count}\n"
        f"  Findings  : {_format_sweep_findings(survivor_count)}\n"
        f"  Battery   : {battery:.1f}% remaining\n"
        f"  Sensor    : {sensor_summary}"
    )


def set_drone_speed(asset_id: str, speed: float) -> None:
    _drone_speeds[asset_id] = speed


def get_drone_speed(asset_id: str) -> float:
    return _drone_speeds.get(asset_id, _NORMAL_SPEED)

def set_client(client: DroneGrpcClient | None) -> None:
    global _client
    _client = client


# def grpc_client -> DroneGrpcClient:
#     return _client if _client is not None else grpc_client


def set_drone_speed(asset_id: str, speed: float) -> None:
    _drone_speeds[asset_id] = speed


def get_drone_speed(asset_id: str) -> float:
    return _drone_speeds.get(asset_id, _NORMAL_SPEED)


async def list_all_drones() -> dict:
    """
    Return the current position, battery, and status of all registered drones.
    """
    client = grpc_client
    asset_ids = client.registered_asset_ids()
    if not asset_ids:
        return {"drones": [], "message": "No drones uplinked. Use /uplink to connect a drone."}

    statuses = await asyncio.gather(
        *[client.get_status(aid) for aid in asset_ids],
        return_exceptions=True,
    )
    drones = []
    for aid, status in zip(asset_ids, statuses):
        if isinstance(status, Exception):
            drones.append({"asset_id": aid, "error": str(status)})
        else:
            drones.append(status)
    return {"drones": drones}


async def move_drone_to(
    asset_id: str, x: float, y: float, z: float, speed: float | None = None
) -> dict:
    """Move a drone to the given X/Y/Z coordinates and wait for arrival."""
    move_result = await grpc_client.move_to(
        asset_id,
        x,
        y,
        z,
        speed if speed is not None else get_drone_speed(asset_id),
    )
    if not move_result.get("success", True):
        return move_result

    wait_result = await _wait_until_waypoint_reached(asset_id, x, y, z)
    if not wait_result.get("ok", False):
        return {
            "success": False,
            "message": wait_result.get("error", "Waypoint not reached"),
            "status": wait_result.get("status"),
        }

    return move_result


async def _wait_until_waypoint_reached(
    asset_id: str,
    x: float,
    y: float,
    z: float,
    tolerance: float = 0.6,
    timeout_s: float = 60.0,
    poll_s: float = 0.2,
    blocked_retries: int = 2,
    exclude_building_id: int | None = None,
) -> dict:
    """
    Poll drone status until it reaches a waypoint, is blocked, or times out.

    On BLOCKED, re-plans from the drone's current position to the target waypoint
    up to ``blocked_retries`` times.

    ``exclude_building_id`` is forwarded to ``plan_route`` on re-plan so that the
    building being scanned is not treated as a full obstacle during sweep recovery.
    """
    client = grpc_client
    elapsed = 0.0
    while elapsed <= timeout_s:
        status = await client.get_status(asset_id)

        if status.get("status") == "BLOCKED" and blocked_retries > 0:
            route = await plan_route(
                asset_id, x, z, y,
                exclude_building_id=exclude_building_id,
            )
            if "error" not in route:
                for wp in route["waypoints"]:
                    await client.move_to(
                        asset_id,
                        wp["x"],
                        wp["y"],
                        wp["z"],
                        get_drone_speed(asset_id),
                    )
                    sub = await _wait_until_waypoint_reached(
                        asset_id,
                        wp["x"],
                        wp["y"],
                        wp["z"],
                        tolerance=tolerance,
                        timeout_s=timeout_s,
                        poll_s=poll_s,
                        blocked_retries=0,
                        exclude_building_id=exclude_building_id,
                    )
                    if not sub["ok"]:
                        return sub
                return {"ok": True, "status": await client.get_status(asset_id)}

            return {
                "ok": False,
                "error": "Drone blocked and re-plan failed",
                "status": status,
            }

        if status.get("status") == "BLOCKED":
            return {
                "ok": False,
                "error": "Drone blocked while following return route",
                "status": status,
            }
        if status.get("status") == "ERROR":
            return {
                "ok": False,
                "error": "Drone entered ERROR state while following return route",
                "status": status,
            }

        dx = abs(status["x"] - x)
        dy = abs(status["y"] - y)
        dz = abs(status["z"] - z)
        if dx <= tolerance and dy <= tolerance and dz <= tolerance:
            return {"ok": True, "status": status}

        await asyncio.sleep(poll_s)
        elapsed += poll_s

    timeout_status = await client.get_status(asset_id)
    return {
        "ok": False,
        "error": "Timed out while following return route waypoint",
        "status": timeout_status,
    }


async def return_to_base(asset_id: str) -> dict:
    """
    Return a drone to home with obstacle-aware routing.

    Plans a safe route to home approach, executes each waypoint with status
    polling, then performs a final explicit landing leg to (0,0,0).
    """
    client = grpc_client
    route = await plan_route(asset_id, 0.0, 2.0, 5.0)
    if "error" in route:
        return {
            "asset_id": asset_id,
            "error": "Return route blocked",
            "route_error": route["error"],
            "obstacles": route.get("obstacles", []),
        }

    waypoints = route.get("waypoints", [])
    for wp in waypoints:
        move_result = await client.move_to(
            asset_id,
            wp["x"],
            wp["y"],
            wp["z"],
            get_drone_speed(asset_id),
        )
        if not move_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Failed while executing return route waypoint",
                "waypoint": wp,
                "move_result": move_result,
            }

        wait_result = await _wait_until_waypoint_reached(asset_id, wp["x"], wp["y"], wp["z"])
        if not wait_result.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": wait_result.get("error", "Return route waypoint not reached"),
                "waypoint": wp,
                "status": wait_result.get("status"),
            }

    final_wp = {"x": 0.0, "y": 2.0, "z": 0.0, "reason": "final landing at home pad"}
    final_move_result = await client.move_to(
        asset_id,
        final_wp["x"],
        final_wp["y"],
        final_wp["z"],
        get_drone_speed(asset_id),
    )
    if not final_move_result.get("success", True):
        return {
            "asset_id": asset_id,
            "error": "Failed while executing final home landing leg",
            "waypoint": final_wp,
            "move_result": final_move_result,
        }

    final_wait = await _wait_until_waypoint_reached(
        asset_id,
        final_wp["x"],
        final_wp["y"],
        final_wp["z"],
    )
    if not final_wait.get("ok", False):
        return {
            "asset_id": asset_id,
            "error": final_wait.get("error", "Final home landing leg not reached"),
            "waypoint": final_wp,
            "status": final_wait.get("status"),
        }

    final_status = await client.get_status(asset_id)
    return {
        "success": True,
        "message": "Returned to base",
        "asset_id": asset_id,
        "strategy": "routed_return",
        "waypoint_count": len(waypoints) + 1,
        "route_summary": route.get("summary"),
        "final_status": final_status,
    }


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


async def get_drone_view(
    asset_id: str,
    heading_deg: float = 0.0,
    detection_range: float = 20.0,
) -> dict:
    """
    Get what the drone can currently see from its position.
    Returns nearby buildings, visible survivors, terrain type, altitude above
    ground level, and whether an obstacle is ahead.
    """
    return await grpc_client.get_view(asset_id, heading_deg, detection_range)


def _select_window_waypoint(
    waypoints: list[dict],
    ref_x: float,
    ref_z: float,
    preferred_y: float | None = None,
) -> dict | None:
    if not waypoints:
        return None

    def _score(wp: dict) -> tuple[float, float]:
        y_delta = abs(float(wp["y"]) - preferred_y) if preferred_y is not None else 0.0
        x_delta = float(wp["x"]) - ref_x
        z_delta = float(wp["z"]) - ref_z
        xz_dist = math.sqrt(x_delta * x_delta + z_delta * z_delta)
        return (y_delta, xz_dist)

    return min(waypoints, key=_score)


def resolve_scan_target(
    target_x: float,
    target_z: float,
    margin: float = BUILDING_PROXIMITY_MARGIN_M,
) -> dict:
    """
    Resolve a scan target to a building footprint when the point is on/near one.

    Returns the resolved scan center and building bounds so agents can explain
    why a target was normalised.
    """
    building = WORLD.building_near_xz(target_x, target_z, margin=margin)
    if building is None:
        return {
            "matched_building": False,
            "input": {"x": target_x, "z": target_z},
            "resolved_target": {"x": target_x, "z": target_z},
            "summary": "No nearby building footprint; using provided coordinates.",
        }

    window_waypoints = building.window_scan_waypoints(standoff=WINDOW_SCAN_STANDOFF_M)
    preferred_y = building.h / 2 if window_waypoints else None
    recommended_window = _select_window_waypoint(
        window_waypoints,
        ref_x=target_x,
        ref_z=target_z,
        preferred_y=preferred_y,
    )
    recommended_scan_y = (
        float(recommended_window["y"])
        if recommended_window is not None
        else building.max_y + 5.0
    )

    summary = (
        f"Matched building {building.id}; footprint "
        f"x[{building.min_x:.1f},{building.max_x:.1f}] "
        f"z[{building.min_z:.1f},{building.max_z:.1f}] "
        f"→ center ({building.cx:.1f}, {building.cz:.1f})."
    )
    if recommended_window is not None:
        summary += (
            " Recommended window approach "
            f"{recommended_window['face']} floor {recommended_window['floor']} "
            f"at ({recommended_window['x']:.1f}, {recommended_window['y']:.1f}, {recommended_window['z']:.1f})."
        )

    return {
        "matched_building": True,
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
        "input": {"x": target_x, "z": target_z},
        "resolved_target": {"x": building.cx, "z": building.cz},
        "recommended_scan_y": recommended_scan_y,
        "window_waypoints": window_waypoints,
        "recommended_window_waypoint": recommended_window,
        "summary": summary,
    }


def _push_xz_clear(
    x: float,
    z: float,
    exclude_id: int,
    clearance: float = 0.5,
    max_iters: int = 5,
    prefer_z: bool = False,
) -> tuple[float, float]:
    """Push (x, z) outside any building it overlaps (except the excluded building).

    On each iteration finds the first blocking building and exits via the
    nearest face + clearance.  Repeats until no overlap or max_iters reached.

    ``prefer_z=True`` breaks ties in favour of the z-axis exit direction.
    Use this for corners on the +X face (NE, SE) so the push goes along the
    face rather than across it — e.g. the SE corner of a building whose
    east neighbour is equally close in X and Z: pushing north (z) keeps the
    corner on the east face; pushing west (x) would skip the east face scan.
    """
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


# ── Perimeter ring helpers ─────────────────────────────────────────────────────

# Clockwise corner order (NW=0, NE=1, SE=2, SW=3).
_CORNERS_CW: list[str] = ["NW", "NE", "SE", "SW"]

# Face traversed going CW from each corner to the next CW corner.
_CW_FACE: dict[str, str] = {
    "NW": "north",  # NW → NE
    "NE": "east",   # NE → SE
    "SE": "south",  # SE → SW
    "SW": "west",   # SW → NW
}


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
    """Return ``(sort_field, reverse)`` for window waypoints on *face*.

    Sorting by this key produces waypoints in traversal order for the given
    direction so the drone sweeps smoothly along the face.
    """
    # CW: north=X-asc, east=Z-asc, south=X-desc, west=Z-desc.
    # CCW: reverse of the above on each face.
    if face == "north":
        return ("x", not clockwise)
    if face == "east":
        return ("z", not clockwise)
    if face == "south":
        return ("x", clockwise)
    # west
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
    """Build an open perimeter ring starting at *start* corner.

    Visits all four corners (covering three face segments in the traversal
    direction), then appends any window waypoints from the fourth "return"
    face so no windows are missed.  The ring does **not** close back to
    *start*.

    Returns ``(ring_items, end_corner)`` where *ring_items* is a list of
    ``(x, z, reason)`` tuples and *end_corner* is the last corner visited.
    """
    idx = _CORNERS_CW.index(start)
    step = 1 if clockwise else -1
    order = [_CORNERS_CW[(idx + step * i) % 4] for i in range(4)]

    ring: list[tuple[float, float, str]] = []

    for i, corner in enumerate(order):
        cx, cz = corners[corner]
        ring.append((cx, cz, f"perimeter {corner}"))

        if i == 3:
            # Append windows for the 4th (return) face so no window is skipped.
            return_face = _CW_FACE[order[-1]] if clockwise else _CW_FACE[order[0]]
            sf, rev = _window_sort_reverse(return_face, clockwise)
            for ww in sorted(level_windows.get(return_face, []), key=lambda w: w[sf], reverse=rev):
                ring.append((ww["x"], ww["z"], f"window scan {return_face} floor {ww['floor']}"))
            break

        next_corner = order[i + 1]
        face = _CW_FACE[corner] if clockwise else _CW_FACE[next_corner]

        # Window waypoints for this face in traversal order.
        sf, rev = _window_sort_reverse(face, clockwise)
        for ww in sorted(level_windows.get(face, []), key=lambda w: w[sf], reverse=rev):
            ring.append((ww["x"], ww["z"], f"window scan {face} floor {ww['floor']}"))

        # West-face-stop: insert only when flying north along the west face
        # CW (SW→NW) and NW was pushed east — guards against clipping the
        # blocking neighbour's corner before reaching the pushed NW position.
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
    """Southernmost safe z when flying north along x=west_x toward to_z.

    Returns to_z when the path is unobstructed; otherwise the z just south of
    the first blocking building's south face.
    """
    stop_z = to_z
    for b in WORLD.buildings:
        if b.id == exclude_id:
            continue
        if b.min_x <= west_x <= b.max_x and b.max_z > to_z:
            stop_z = max(stop_z, b.max_z + clearance)
    return round(stop_z, 2)


def _safe_standoff_per_face(
    building: "Building",
    desired: float,
    min_standoff: float = 1.0,
    clearance: float = 0.5,
) -> dict[str, float]:
    """Compute the max safe standoff per face given neighbouring buildings.

    For each face direction, find the nearest building whose footprint
    overlaps in the perpendicular axis and cap the standoff so the
    waypoint doesn't land inside it (with `clearance` margin).
    """
    from backend.world.model import WORLD

    face_standoffs: dict[str, float] = {}
    for face in ("north", "south", "east", "west"):
        best = desired
        for nb in WORLD.buildings:
            if nb.id == building.id:
                continue
            if face == "north":
                # Window waypoint goes to z = building.min_z - standoff.
                # Neighbour blocks if its z-range straddles that position
                # and it overlaps in X.
                if nb.max_x <= building.min_x or nb.min_x >= building.max_x:
                    continue  # no X overlap
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
    """
    Return intermediate transit waypoints needed to route around any building
    that blocks the direct sweep segment from→to.

    Neighbor buildings are checked with ``margin`` (default 1 m).  The scanned
    building itself (``exclude_id``) is checked separately with margin=0 so that
    diagonal corner-to-corner paths that clip through its own volume are also
    re-routed, while window-approach positions legitimately on the face are not
    falsely blocked.

    If the direct path is clear, returns an empty list.
    Otherwise returns two waypoints (climb + cruise at ``clear_y``) marked
    ``transit=True`` so ``sweep_scan_building`` skips scanning at those positions.
    The caller is responsible for appending the actual destination at ``to_y``.
    """
    # Neighbouring buildings — use full margin so we stay comfortably clear.
    blockers = [
        b for b in WORLD.obstacles_in_path(
            from_x, from_y, from_z,
            to_x, to_y, to_z,
            samples=30, margin=margin,
        )
        if b.id != exclude_id
    ]
    # Scanned building itself — margin=0 catches paths that actually intersect
    # the solid volume (e.g. diagonal SE→SW cuts) without flagging face approaches.
    blockers.extend(
        b for b in WORLD.obstacles_in_path(
            from_x, from_y, from_z,
            to_x, to_y, to_z,
            samples=30, margin=0.0,
        )
        if b.id == exclude_id
    )
    if not blockers:
        return []

    over_y = round(max(b.max_y for b in blockers) + 3.0, 2)
    over_y = max(over_y, round(clear_y, 2))
    return [
        {
            "x": round(from_x, 2), "y": over_y, "z": round(from_z, 2),
            "reason": "climb over adjacent building", "transit": True,
        },
        {
            "x": round(to_x, 2), "y": over_y, "z": round(to_z, 2),
            "reason": "cruise over adjacent building", "transit": True,
        },
    ]


def plan_building_vertical_sweep(
    target_x: float,
    target_z: float,
    level_step: float = 3.0,
    standoff: float = 2.0,
    flood_clearance: float = 0.5,
    approach_x: float | None = None,
    approach_z: float | None = None,
) -> dict:
    """
    Plan a perimeter sweep around a building across all heights above water level.

    Returns waypoints only for the sweep itself (floor rings + rooftop).
    Navigation to/from the building is handled by the caller.

    When *approach_x* / *approach_z* are provided the planner uses an
    approach-aware starting corner (nearest perimeter corner to the drone's
    pre-navigation position) and a serpentine (boustrophedon) open-ring
    traversal so consecutive floor rings chain seamlessly — the end of ring N
    is the start of ring N+1 with no redundant close-ring return leg.

    When omitted the legacy NW-start clockwise closed-ring behaviour is
    preserved for backward compatibility.
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

    # Window-facing waypoints grouped by floor, with per-face dynamic
    # standoff that shrinks when a neighbouring building is too close.
    # When a balcony protrudes from a face, increase the minimum standoff
    # so the drone clears the balcony edge.
    desired_standoff = max(safe_standoff, WINDOW_SCAN_STANDOFF_M)
    face_standoffs = _safe_standoff_per_face(building, desired_standoff)
    for face in ("north", "south", "east", "west"):
        protrusion = building.balcony_protrusion(face)
        if protrusion > 0:
            face_standoffs[face] = max(face_standoffs[face], protrusion + 1.0)

    # Build window waypoints manually using per-face standoffs.
    all_window_wps: list[dict] = []
    for window in building.windows:
        y = round(window.sill_y + window.height / 2, 2)
        floor = int(window.sill_y // 3.0) + 1  # FLOOR_HEIGHT_M = 3.0
        so = face_standoffs[window.face]
        if window.face == "north":
            x, z = window.axis_center, building.min_z - so
        elif window.face == "south":
            x, z = window.axis_center, building.max_z + so
        elif window.face == "west":
            x, z = building.min_x - so, window.axis_center
        else:  # east
            x, z = building.max_x + so, window.axis_center
        all_window_wps.append({
            "x": round(x, 2), "y": y, "z": round(z, 2),
            "face": window.face, "floor": floor,
        })
    above_flood = [w for w in all_window_wps if w["y"] >= start_y]

    # Derive floor levels from window centre heights, ascending.
    floor_levels = sorted({round(w["y"], 2) for w in above_flood})
    # Note: no level_step fallback here — windowless buildings cannot be safely
    # ringed at floor level when adjacent buildings block the perimeter corners.
    # They receive a rooftop-level perimeter flyaround instead (see below).

    # Perimeter corners kept tight (1 m from wall) to avoid colliding
    # with neighbouring buildings.  When a balcony protrudes from a face,
    # push that face's perimeter outward by the balcony depth so the
    # drone path clears the balcony geometry.
    perimeter_margin = 1.0
    p_min_x = building.min_x - perimeter_margin - building.balcony_protrusion("west")
    p_max_x = building.max_x + perimeter_margin + building.balcony_protrusion("east")
    p_min_z = building.min_z - perimeter_margin - building.balcony_protrusion("north")
    p_max_z = building.max_z + perimeter_margin + building.balcony_protrusion("south")

    # Push all four perimeter corners outside any adjacent building.
    # clearance=1.5 > _route_sweep_segment margin (1.0) so the vertical descent
    # back to scan altitude at a pushed corner is also guaranteed to be clear.
    _CORNER_CLEARANCE = 1.5
    nw_x, nw_z = _push_xz_clear(p_min_x, p_min_z, building.id, clearance=_CORNER_CLEARANCE)
    ne_x, ne_z = _push_xz_clear(p_max_x, p_min_z, building.id, clearance=_CORNER_CLEARANCE, prefer_z=True)
    se_x, se_z = _push_xz_clear(p_max_x, p_max_z, building.id, clearance=_CORNER_CLEARANCE, prefer_z=True)
    sw_x, sw_z = _push_xz_clear(p_min_x, p_max_z, building.id, clearance=_CORNER_CLEARANCE)

    # When NW was pushed east, flying the west face straight to the
    # corrected NW would clip through the target building's corner.
    # Compute the last safe z on the west face before the blocking neighbour.
    _nw_pushed_east = nw_x > p_min_x + 0.01
    west_stop_z = _west_face_stop_z(p_min_x, p_min_z, building.id) if _nw_pushed_east else p_min_z

    # Rooftop hover point — above building centre.
    rooftop_y = round(top_y + safe_standoff, 2)

    # Named corners dict used by the serpentine helpers.
    corners: dict[str, tuple[float, float]] = {
        "NW": (nw_x, nw_z),
        "NE": (ne_x, ne_z),
        "SE": (se_x, se_z),
        "SW": (sw_x, sw_z),
    }

    # Serpentine mode: activated when the caller supplies the drone's
    # pre-navigation position so we can pick the nearest starting corner.
    _serpentine = approach_x is not None and approach_z is not None
    if _serpentine:
        # assert approach_x and approach_z are not None — guaranteed by _serpentine check.
        _start_corner = _nearest_corner(approach_x, approach_z, corners)  # type: ignore[arg-type]
    else:
        _start_corner = "NW"

    waypoints: list[dict] = []
    levels: list[float] = []

    # Descent waypoint: from above building centre, move laterally to the
    # start corner at rooftop altitude before descending to the lowest floor.
    # This avoids clipping through the building roof.
    if floor_levels:
        sc_x, sc_z = corners[_start_corner]
        waypoints.append(
            {
                "x": sc_x,
                "y": rooftop_y,
                "z": sc_z,
                "level_y": rooftop_y,
                "reason": f"descent to {_start_corner} corner",
            }
        )

    # Ascending floor rings.
    _current_corner = _start_corner
    _cw = True  # start clockwise; serpentine alternates per floor
    # Track the last emitted (x, z) so inter-floor transitions can be checked
    # for collisions.  Initialised to the start corner; updated after each ring.
    _last_rx: float = corners[_start_corner][0]
    _last_rz: float = corners[_start_corner][1]

    for level_y in floor_levels:
        levels.append(level_y)
        level_wps = [w for w in above_flood if round(w["y"], 2) == level_y]
        # Group by face, preserving insertion order within each face, so multiple
        # windows on the same face at the same floor (e.g. shophouse south x2) are
        # all visited instead of the last one silently overwriting the others.
        level_windows: dict[str, list[dict]] = {}
        for w in level_wps:
            level_windows.setdefault(w["face"], []).append(w)

        if _serpentine:
            # Open-ring serpentine: end of this ring becomes the start of the
            # next, so consecutive floors chain without a redundant close leg.
            ring_items, end_corner = _build_ring(
                start=_current_corner,
                clockwise=_cw,
                level_windows=level_windows,
                corners=corners,
                nw_pushed_east=_nw_pushed_east,
                west_stop_z=west_stop_z if _nw_pushed_east else None,
                p_min_x=p_min_x,
            )
            prev_rx, prev_rz = corners[_current_corner]

            # ── Inter-floor transit check ─────────────────────────────────
            # The previous ring may have ended at a 4th-face window waypoint
            # that lies outside the current ring's start corner.  The direct
            # diagonal from that position to this ring's first waypoint can
            # re-enter the scanned building.  _route_sweep_segment excludes the
            # scanned building from its check, so we add a separate zero-margin
            # check for it here and insert a climb/cruise transit if needed.
            if ring_items:
                first_rx, first_rz, _ = ring_items[0]
                # Check whether the path from the previous floor's last emitted
                # position to the first item of this ring clips any building,
                # including the scanned building (margin=0).
                inter_blockers = WORLD.obstacles_in_path(
                    _last_rx, level_y, _last_rz,
                    first_rx, level_y, first_rz,
                    samples=30, margin=0.0,
                )
                if inter_blockers:
                    over_y = round(max(b.max_y for b in inter_blockers) + 3.0, 2)
                    over_y = max(over_y, round(rooftop_y, 2))
                    waypoints.append({"x": round(_last_rx, 2), "y": over_y, "z": round(_last_rz, 2),
                                      "level_y": rooftop_y, "reason": "inter-floor climb", "transit": True})
                    waypoints.append({"x": round(first_rx, 2), "y": over_y, "z": round(first_rz, 2),
                                      "level_y": rooftop_y, "reason": "inter-floor cruise", "transit": True})

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
            _last_rx, _last_rz = prev_rx, prev_rz  # track last emitted position
            _cw = not _cw  # alternate direction for next floor

        else:
            # Legacy closed-ring behaviour (NW start, clockwise, closes at NW).
            # Ring: NW → [north…] → NE → [east…] → SE → [south…] → SW → [west…] → NW
            # NW corner may be adjusted east to avoid an adjacent building.
            ring: list[tuple[float, float, str]] = [
                (nw_x, nw_z, "perimeter NW"),
            ]
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
            # When NW was pushed east, add a "west-face stop" before closing the ring
            # so the drone hugs the west face safely and then turns NE to reach NW.
            if _nw_pushed_east and west_stop_z > p_min_z + 0.01:
                ring.append((p_min_x, west_stop_z, "west face stop (adjacent building)"))
            ring.append((nw_x, nw_z, "close perimeter"))

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

    # Windowless buildings: rooftop-level perimeter flyaround.
    # Floor-level rings are skipped for buildings without windows because adjacent
    # structures may make the full perimeter unreachable at low altitude (e.g. a
    # shophouse sharing the NW corner physically blocks the west / north-west path).
    # Flying at rooftop altitude clears all neighbours and still gives full
    # scan coverage given the large sensor radius.
    if not floor_levels and top_y > start_y:
        levels.append(rooftop_y)
        prev_rx, prev_rz = nw_x, nw_z
        for rx, rz, label in [
            (nw_x,  nw_z,  "rooftop NW scan"),
            (ne_x,  ne_z,  "rooftop NE scan"),
            (se_x,  se_z,  "rooftop SE scan"),
            (sw_x,  sw_z,  "rooftop SW scan"),
        ]:
            for extra in _route_sweep_segment(prev_rx, rooftop_y, prev_rz, rx, rooftop_y, rz, building.id, rooftop_y):
                waypoints.append({**extra, "level_y": rooftop_y})
            waypoints.append(
                {
                    "x": round(rx, 2),
                    "y": rooftop_y,
                    "z": round(rz, 2),
                    "level_y": rooftop_y,
                    "reason": label,
                }
            )
            prev_rx, prev_rz = rx, rz

    # Ascent waypoint: go up at the last corner before moving to building centre
    # to avoid clipping through the building at intermediate heights.
    if floor_levels:
        ac_x, ac_z = corners[_current_corner]
        waypoints.append(
            {
                "x": ac_x,
                "y": rooftop_y,
                "z": ac_z,
                "level_y": rooftop_y,
                "reason": "ascent to rooftop altitude",
            }
        )

    # Rooftop scan last. Only append level if not already added (windowless perimeter path
    # already appended rooftop_y to levels above).
    if rooftop_y not in levels:
        levels.append(rooftop_y)
    waypoints.append(
        {
            "x": building.cx,
            "y": rooftop_y,
            "z": building.cz,
            "level_y": rooftop_y,
            "reason": "rooftop scan",
        }
    )

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
            f"{len(levels)} level(s), {len(waypoints)} waypoint(s), "
            f"covering y={levels[0]:.1f}..{levels[-1]:.1f} above flood={FLOOD_LEVEL:.1f}."
        ),
    }


async def sweep_scan_building(
    asset_id: str,
    target_x: float | None = None,
    target_z: float | None = None,
    scan_radius: float = DEFAULT_SWEEP_SCAN_RADIUS,
    level_step: float = 3.0,
    standoff: float = 2.0,
) -> dict:
    """
    Execute a full-height-above-water perimeter sweep scan around a building.
    """
    client = grpc_client

    # ── Wait for drone to finish any in-progress movement ──────────────
    # The LLM navigation agent fires move_drone_to commands without
    # waiting for physical arrival.  If we start planning immediately the
    # drone may be mid-flight near an obstacle, causing plan_route to
    # fail.  Wait until the drone settles (IDLE / ARRIVED / ERROR) or
    # until a generous timeout expires.
    _SETTLE_TIMEOUT_S = 120.0
    _SETTLE_POLL_S = 0.3
    _settled = 0.0
    while _settled < _SETTLE_TIMEOUT_S:
        _st = await client.get_status(asset_id)
        if _st.get("status") not in ("MOVING",):
            break
        await asyncio.sleep(_SETTLE_POLL_S)
        _settled += _SETTLE_POLL_S

    # Fetch status so default target can fall back to current drone position.
    status = await client.get_status(asset_id)
    if target_x is None:
        target_x = status["x"]
    if target_z is None:
        target_z = status["z"]

    preplan = plan_building_vertical_sweep(
        target_x=target_x,
        target_z=target_z,
        level_step=level_step,
        standoff=standoff,
    )
    if not preplan.get("matched_building", False):
        return {
            "asset_id": asset_id,
            "error": preplan.get("error", "No building found for sweep scan"),
            "input": preplan.get("input", {"x": target_x, "z": target_z}),
        }
    if "error" in preplan:
        return {
            "asset_id": asset_id,
            "error": preplan["error"],
            "building": preplan.get("building"),
            "flood_level": preplan.get("flood_level"),
        }

    waypoint_reports: list[dict] = []
    rooftop = preplan["rooftop_position"]
    building_cx: float = preplan["building"]["center_x"]
    building_cz: float = preplan["building"]["center_z"]
    building_min_x: float = preplan["building"]["min_x"]
    building_max_x: float = preplan["building"]["max_x"]
    building_min_z: float = preplan["building"]["min_z"]
    building_max_z: float = preplan["building"]["max_z"]
    building_height: float = preplan["building"]["height"]
    # Include shallow exterior balconies while still rejecting neighbouring buildings.
    _SURVIVOR_BUILDING_MARGIN = 2.1

    def _belongs_to_target_building(sx: object, sy: object, sz: object) -> bool:
        if not isinstance(sx, (int, float)) or not isinstance(sy, (int, float)) or not isinstance(sz, (int, float)):
            return False
        return (
            building_min_x - _SURVIVOR_BUILDING_MARGIN <= float(sx) <= building_max_x + _SURVIVOR_BUILDING_MARGIN
            and building_min_z - _SURVIVOR_BUILDING_MARGIN <= float(sz) <= building_max_z + _SURVIVOR_BUILDING_MARGIN
            and -0.5 <= float(sy) <= building_height + FLOOR_HEIGHT_M
        )

    # ── Step 2: Navigate to top of building using plan_route ───────────
    building_id = preplan["building"]["id"]
    route = await plan_route(
        asset_id=asset_id,
        target_x=rooftop["x"],
        target_z=rooftop["z"],
        target_y=rooftop["y"],
        exclude_building_id=building_id,
    )
    if "error" in route:
        return {
            "asset_id": asset_id,
            "error": "Sweep route blocked — cannot reach building rooftop",
            "route_error": route["error"],
            "route_obstacles": route.get("obstacles", []),
            "completed_waypoints": 0,
        }
    for move_wp in route.get("waypoints", []):
        move_result = await client.move_to(
            asset_id, move_wp["x"], move_wp["y"], move_wp["z"],
            get_drone_speed(asset_id),
        )
        if not move_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Failed while navigating to building rooftop",
                "move_result": move_result,
                "completed_waypoints": 0,
            }
        wait_result = await _wait_until_waypoint_reached(
            asset_id, move_wp["x"], move_wp["y"], move_wp["z"],
        )
        if not wait_result.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": wait_result.get("error", "Could not reach building rooftop"),
                "status": wait_result.get("status"),
                "completed_waypoints": 0,
            }

    # Rebuild the sweep plan from rooftop approach so pathing is consistent
    # regardless of where the drone started before rooftop transit.
    plan = plan_building_vertical_sweep(
        target_x=target_x,
        target_z=target_z,
        level_step=level_step,
        standoff=standoff,
        approach_x=rooftop["x"],
        approach_z=rooftop["z"],
    )
    if not plan.get("matched_building", False):
        return {
            "asset_id": asset_id,
            "error": plan.get("error", "No building found for sweep scan"),
            "input": plan.get("input", {"x": target_x, "z": target_z}),
        }
    if "error" in plan:
        return {
            "asset_id": asset_id,
            "error": plan["error"],
            "building": plan.get("building"),
            "flood_level": plan.get("flood_level"),
        }
    rooftop = plan["rooftop_position"]
    building_cx = plan["building"]["center_x"]
    building_cz = plan["building"]["center_z"]
    building_id = plan["building"]["id"]

    # Ensure the first sweep waypoint is reached via routed movement too; a direct
    # lateral rooftop move can be blocked for tightly-packed buildings (e.g. NW tower).
    if plan["waypoints"]:
        first_wp = plan["waypoints"][0]
        transition_route = await plan_route(
            asset_id=asset_id,
            target_x=first_wp["x"],
            target_z=first_wp["z"],
            target_y=first_wp["y"],
            exclude_building_id=building_id,
        )
        if "error" in transition_route:
            return {
                "asset_id": asset_id,
                "error": "Sweep start blocked — cannot reach first scan waypoint",
                "route_error": transition_route["error"],
                "route_obstacles": transition_route.get("obstacles", []),
                "completed_waypoints": 0,
            }
        for move_wp in transition_route.get("waypoints", []):
            move_result = await client.move_to(
                asset_id, move_wp["x"], move_wp["y"], move_wp["z"],
                get_drone_speed(asset_id),
            )
            if not move_result.get("success", True):
                return {
                    "asset_id": asset_id,
                    "error": "Failed while routing to first sweep waypoint",
                    "move_result": move_result,
                    "completed_waypoints": 0,
                }
            wait_result = await _wait_until_waypoint_reached(
                asset_id, move_wp["x"], move_wp["y"], move_wp["z"],
                exclude_building_id=building_id,
            )
            if not wait_result.get("ok", False):
                return {
                    "asset_id": asset_id,
                    "error": wait_result.get("error", "Could not reach first sweep waypoint"),
                    "status": wait_result.get("status"),
                    "completed_waypoints": 0,
                }

    # ── Steps 3-4: Sweep floor rings + rooftop ────────────────────────
    # Waypoints come from plan_building_vertical_sweep.  Most are perimeter
    # scan points; some are transit waypoints (transit=True) inserted to route
    # over adjacent buildings at shared corners — those are moved through but
    # not scanned.
    for index, wp in enumerate(plan["waypoints"], start=1):
        move_result = await client.move_to(
            asset_id, wp["x"], wp["y"], wp["z"],
            get_drone_speed(asset_id),
        )
        if not move_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Failed while moving to sweep waypoint",
                "failed_waypoint": wp,
                "move_result": move_result,
                "completed_waypoints": index - 1,
            }

        wait_result = await _wait_until_waypoint_reached(
            asset_id, wp["x"], wp["y"], wp["z"],
            exclude_building_id=building_id,
        )
        if not wait_result.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": wait_result.get("error", "Sweep waypoint not reached"),
                "failed_waypoint": wp,
                "status": wait_result.get("status"),
                "completed_waypoints": index - 1,
            }

        if wp.get("transit"):
            continue

        scan_result = await client.scan_area(asset_id, wp["x"], wp["y"], wp["z"], scan_radius)
        if not scan_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": "Scan tool failed during vertical sweep",
                "failed_scan_waypoint": wp,
                "scan_result": scan_result,
                "completed_waypoints": index - 1,
            }

        scan_wait = await _wait_until_waypoint_reached(
            asset_id,
            wp["x"],
            wp["y"],
            wp["z"],
            timeout_s=15.0,
        )
        if not scan_wait.get("ok", False):
            return {
                "asset_id": asset_id,
                "error": scan_wait.get("error", "Sweep scan point did not stabilise"),
                "failed_scan_waypoint": wp,
                "status": scan_wait.get("status"),
                "completed_waypoints": index - 1,
            }

        # Face the building center so the thermal camera FOV is correctly oriented.
        wp_x, wp_z = wp["x"], wp["z"]
        face_dx = building_cx - wp_x
        face_dz = building_cz - wp_z
        heading_toward_building = math.degrees(math.atan2(face_dx, -face_dz)) % 360
        view = await client.get_view(asset_id, heading_deg=heading_toward_building, detection_range=5.0)
        detected_survivors: list[dict] = []
        for obj in view.get("objects", []):
            if obj.get("object_type") != "survivor":
                continue
            if not _belongs_to_target_building(obj.get("x"), obj.get("y"), obj.get("z")):
                continue
            # Horizontal FOV filter: discard survivors outside the camera cone.
            sx, sz = obj.get("x", wp_x), obj.get("z", wp_z)
            surv_dx, surv_dz = sx - wp_x, sz - wp_z
            face_mag = math.sqrt(face_dx**2 + face_dz**2)
            surv_mag = math.sqrt(surv_dx**2 + surv_dz**2)
            if face_mag > 1e-6 and surv_mag > 1e-6:
                cos_a = (face_dx * surv_dx + face_dz * surv_dz) / (face_mag * surv_mag)
                angle_off_axis = math.degrees(math.acos(max(-1.0, min(1.0, cos_a))))
                if angle_off_axis > THERMAL_HORIZ_FOV_HALF_DEG:
                    continue
            detail_raw = obj.get("detail", "")
            detail: dict = {}
            if isinstance(detail_raw, str) and detail_raw:
                try:
                    parsed = json.loads(detail_raw)
                    if isinstance(parsed, dict):
                        detail = parsed
                except json.JSONDecodeError:
                    detail = {}
            detected_survivors.append(
                {
                    "id": obj.get("object_id"),
                    "x": obj.get("x"),
                    "y": obj.get("y"),
                    "z": obj.get("z"),
                    "distance": obj.get("distance"),
                    "direction": obj.get("direction"),
                    "submerged": bool(detail.get("submerged", False)),
                }
            )

        survivors_in_scan_radius = [
            det
            for det in detected_survivors
            if isinstance(det.get("distance"), (int, float))
            and math.isfinite(float(det["distance"]))
            and float(det["distance"]) <= scan_radius
        ]
        view_survivor_count = view.get("survivors_in_range")
        survivors_visible_count = len(detected_survivors)
        if isinstance(view_survivor_count, int):
            survivors_visible_count = max(survivors_visible_count, view_survivor_count)
        survivors_within_radius_count = len(survivors_in_scan_radius)
        waypoint_reports.append(
            {
                "index": index,
                "x": wp["x"],
                "y": wp["y"],
                "z": wp["z"],
                "level_y": wp["level_y"],
                # Keep sweep summary aligned with rendered scan rays / sensor visibility.
                "survivors_in_range": survivors_visible_count,
                "survivors_within_scan_radius": survivors_within_radius_count,
                "detected_survivors": detected_survivors,
                "detected_survivors_within_scan_radius": survivors_in_scan_radius,
                "sensor_summary": view.get("summary", ""),
            }
        )

    # ── Step 5: Return to top of building ─────────────────────────────
    move_result = await client.move_to(
        asset_id, rooftop["x"], rooftop["y"], rooftop["z"],
        get_drone_speed(asset_id),
    )
    if move_result.get("success", True):
        await _wait_until_waypoint_reached(
            asset_id, rooftop["x"], rooftop["y"], rooftop["z"],
        )

    max_survivors_seen = max((r["survivors_in_range"] for r in waypoint_reports), default=0)

    survivor_detection_index: dict[int, dict] = {}
    for report in waypoint_reports:
        for det in report.get("detected_survivors", []):
            sid = det.get("id")
            if not isinstance(sid, int):
                continue
            entry = survivor_detection_index.get(sid)
            if entry is None:
                survivor_detection_index[sid] = {
                    "id": sid,
                    "x": det.get("x"),
                    "y": det.get("y"),
                    "z": det.get("z"),
                    "direction": det.get("direction"),
                    "submerged": bool(det.get("submerged", False)),
                    "first_detected_waypoint": report.get("index"),
                    "detected_waypoint_count": 1,
                    "closest_distance": det.get("distance"),
                }
                continue

            entry["detected_waypoint_count"] = int(entry["detected_waypoint_count"]) + 1
            entry["submerged"] = bool(entry["submerged"]) or bool(det.get("submerged", False))
            distance = det.get("distance")
            current_min = entry.get("closest_distance")
            if isinstance(distance, (int, float)) and (
                not isinstance(current_min, (int, float)) or distance < current_min
            ):
                entry["closest_distance"] = distance
                entry["direction"] = det.get("direction")

    unique_survivors_detected = sorted(
        survivor_detection_index.values(),
        key=lambda row: int(row["id"]),
    )
    register_detected_survivors(unique_survivors_detected)
    # Use whichever signal is stronger: unique survivor IDs or per-waypoint in-range count.
    # This avoids false zeroes in summary when IDs are unavailable but detections exist.
    reported_survivor_count = max(len(unique_survivors_detected), max_survivors_seen)
    final_status = await client.get_status(asset_id)
    end_scan = getattr(client, "end_scan", None)
    if callable(end_scan):
        await end_scan(asset_id)  # clear scan session → drone returns to IDLE
    latest_sensor_summary = waypoint_reports[-1]["sensor_summary"] if waypoint_reports else ""
    message = _build_sweep_scan_report(
        asset_id=asset_id,
        building=plan["building"],
        levels=plan["levels"],
        flood_level=plan["flood_level"],
        waypoint_count=plan["waypoint_count"],
        survivor_count=reported_survivor_count,
        battery=float(final_status.get("battery", 0.0)),
        sensor_summary=str(latest_sensor_summary),
    )

    return {
        "success": True,
        "message": message,
        "asset_id": asset_id,
        "strategy": "vertical_building_sweep",
        "building": plan["building"],
        "flood_level": plan["flood_level"],
        "levels": plan["levels"],
        "level_count": plan["level_count"],
        "waypoint_count": plan["waypoint_count"],
        "scan_reports": waypoint_reports,
        "max_survivors_in_range": max_survivors_seen,
        "reported_survivor_count": reported_survivor_count,
        "total_survivor_detections": sum(
            len(report.get("detected_survivors", [])) for report in waypoint_reports
        ),
        "unique_survivors_detected": unique_survivors_detected,
        "unique_survivor_count": len(unique_survivors_detected),
        "summary": message,
    }


async def select_best_drone(target_x: float, target_z: float) -> dict:
    """
    Select the best available drone for a mission near (target_x, target_z).
    """
    client = grpc_client
    asset_ids = client.registered_asset_ids()
    if not asset_ids:
        return {
            "error": "No drones uplinked.",
            "suggestion": "Use /uplink to connect a drone first.",
        }

    statuses = await asyncio.gather(
        *[client.get_status(aid) for aid in asset_ids],
        return_exceptions=True,
    )

    eligible = []
    for status in statuses:
        if isinstance(status, Exception):
            continue
        if status.get("battery", 0) <= 20:
            continue
        if status.get("status", "") != "IDLE":
            continue
        dist = math.sqrt((status["x"] - target_x) ** 2 + (status["z"] - target_z) ** 2)
        eligible.append({**status, "distance_m": round(dist, 1)})

    if not eligible:
        busy = [s for s in statuses if not isinstance(s, Exception)]
        return {
            "error": "No eligible drones available (all busy or low battery).",
            "suggestion": f"{len(busy)} drone(s) registered but none are IDLE with battery > 20%.",
        }

    return min(eligible, key=lambda d: d["distance_m"])


async def plan_route(
    asset_id: str,
    target_x: float,
    target_z: float,
    target_y: float | None = None,
    snap_to_building_center: bool = False,
    exclude_building_id: int | None = None,
) -> dict:
    """
    Pre-compute a collision-free route from the drone's current position
    to the target (target_x, target_z) with optional altitude target_y.

    ``exclude_building_id`` removes a specific building from obstacle checks —
    used when the destination IS the target building (e.g. rooftop approach) so
    the building doesn't block its own approach route.
    """
    client = grpc_client
    status = await client.get_status(asset_id)
    cx, cy, cz = status["x"], status["y"], status["z"]

    requested_x = target_x
    requested_z = target_z
    nearby = WORLD.building_near_xz(target_x, target_z)
    available_window_waypoints: list[dict] = []
    selected_window_waypoint: dict | None = None
    if nearby is not None and nearby.windows:
        available_window_waypoints = nearby.window_scan_waypoints(standoff=WINDOW_SCAN_STANDOFF_M)

    if snap_to_building_center and nearby is not None:
        target_x = nearby.cx
        target_z = nearby.cz
        selected_window_waypoint = _select_window_waypoint(
            available_window_waypoints,
            ref_x=requested_x,
            ref_z=requested_z,
            preferred_y=target_y if target_y is not None else nearby.h / 2,
        )
        if selected_window_waypoint is not None:
            target_x = float(selected_window_waypoint["x"])
            target_z = float(selected_window_waypoint["z"])

    if target_y is None:
        if selected_window_waypoint is not None:
            target_y = float(selected_window_waypoint["y"])
        elif nearby is not None:
            target_y = nearby.max_y + 5.0
        else:
            target_y = 10.0
    target_y = max(target_y, 5.0)

    target_resolution: dict | None = None
    if nearby is not None:
        target_resolution = {
            "building_id": nearby.id,
            "input": {"x": requested_x, "z": requested_z},
            "resolved": {"x": target_x, "z": target_z},
            "center": {"x": nearby.cx, "z": nearby.cz},
            "bounds": {
                "min_x": nearby.min_x,
                "max_x": nearby.max_x,
                "min_z": nearby.min_z,
                "max_z": nearby.max_z,
            },
        }
        if available_window_waypoints:
            target_resolution["window_waypoints"] = available_window_waypoints
        if selected_window_waypoint is not None:
            target_resolution["selected_window_waypoint"] = selected_window_waypoint

    window_summary_suffix = ""
    if selected_window_waypoint is not None:
        window_summary_suffix = (
            " Window approach "
            f"{selected_window_waypoint['face']} floor {selected_window_waypoint['floor']}."
        )

    def _filter(buildings: list) -> list:
        if exclude_building_id is None:
            return buildings
        return [b for b in buildings if b.id != exclude_building_id]

    obstacles = _filter(WORLD.obstacles_in_path(cx, cy, cz, target_x, target_y, target_z, samples=40, margin=1.0))
    if not obstacles:
        return {
            "asset_id": asset_id,
            "from": {"x": cx, "y": cy, "z": cz},
            "to": {"x": target_x, "y": target_y, "z": target_z},
            "waypoints": [
                {"x": target_x, "y": target_y, "z": target_z, "reason": "direct path clear"},
            ],
            "obstacle_count": 0,
            "strategy": "direct",
            "summary": f"1 waypoint, direct path clear. Scan alt={target_y}m.{window_summary_suffix}",
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    max_obstacle_h = max(b.max_y for b in obstacles)
    clearance_y = max_obstacle_h + 5.0

    seg_climb = _filter(WORLD.obstacles_in_path(cx, cy, cz, cx, clearance_y, cz, samples=20, margin=1.0))
    seg_cruise = _filter(WORLD.obstacles_in_path(
        cx,
        clearance_y,
        cz,
        target_x,
        clearance_y,
        target_z,
        samples=40,
        margin=1.0,
    ))
    seg_descend = _filter(WORLD.obstacles_in_path(
        target_x,
        clearance_y,
        target_z,
        target_x,
        target_y,
        target_z,
        samples=20,
        margin=1.0,
    ))

    if not seg_climb and not seg_cruise and not seg_descend:
        waypoints = [
            {
                "x": cx,
                "y": clearance_y,
                "z": cz,
                "reason": f"climb to clear obstacle (h={max_obstacle_h}m)",
            },
            {"x": target_x, "y": clearance_y, "z": target_z, "reason": "cruise above obstacles"},
            {"x": target_x, "y": target_y, "z": target_z, "reason": "descend to scan altitude"},
        ]
        return {
            "asset_id": asset_id,
            "from": {"x": cx, "y": cy, "z": cz},
            "to": {"x": target_x, "y": target_y, "z": target_z},
            "waypoints": waypoints,
            "obstacle_count": len(obstacles),
            "strategy": "over",
            "summary": (
                f"3 waypoints, clearing {len(obstacles)} obstacle via over "
                f"(max h={max_obstacle_h}m). Scan alt={target_y}m.{window_summary_suffix}"
            ),
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    dx = target_x - cx
    dz = target_z - cz
    length = math.sqrt(dx * dx + dz * dz)
    if length < 1e-6:
        # Drone is already at the target X/Z — no horizontal navigation needed.
        return {
            "asset_id": asset_id,
            "from": {"x": cx, "y": cy, "z": cz},
            "to": {"x": target_x, "y": target_y, "z": target_z},
            "waypoints": [],
            "obstacle_count": 0,
            "strategy": "already_at_destination",
            "summary": f"Already at destination (x={target_x}, z={target_z}). No navigation needed.",
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    perp_x = -dz / length
    perp_z = dx / length
    mid_x = (cx + target_x) / 2
    mid_z = (cz + target_z) / 2
    max_half_w = max(max(b.w, b.d) / 2 for b in obstacles)
    offset_dist = max_half_w + 5.0
    fly_y = max(target_y, clearance_y)

    for sign in (1.0, -1.0):
        wp_x = mid_x + sign * perp_x * offset_dist
        wp_z = mid_z + sign * perp_z * offset_dist

        seg1 = _filter(WORLD.obstacles_in_path(cx, cy, cz, wp_x, fly_y, wp_z, samples=40, margin=1.0))
        seg2 = _filter(WORLD.obstacles_in_path(
            wp_x,
            fly_y,
            wp_z,
            target_x,
            target_y,
            target_z,
            samples=40,
            margin=1.0,
        ))
        if not seg1 and not seg2:
            waypoints = [
                {"x": wp_x, "y": fly_y, "z": wp_z, "reason": "detour around obstacle"},
                {"x": target_x, "y": target_y, "z": target_z, "reason": "proceed to target"},
            ]
            return {
                "asset_id": asset_id,
                "from": {"x": cx, "y": cy, "z": cz},
                "to": {"x": target_x, "y": target_y, "z": target_z},
                "waypoints": waypoints,
                "obstacle_count": len(obstacles),
                "strategy": "around",
                "summary": (
                    f"2 waypoints, clearing {len(obstacles)} obstacle via around. "
                    f"Scan alt={target_y}m.{window_summary_suffix}"
                ),
                **({"target_resolution": target_resolution} if target_resolution else {}),
            }

    return {
        "asset_id": asset_id,
        "error": "No clear route found",
        "obstacles": [{"id": b.id, "cx": b.cx, "cz": b.cz, "h": b.h} for b in obstacles],
        **({"target_resolution": target_resolution} if target_resolution else {}),
    }


def find_buildings_in_area(
    center_x: float,
    center_z: float,
    radius: float = 30.0,
    drone_x: float | None = None,
    drone_z: float | None = None,
) -> dict:
    """
    Return all buildings whose nearest edge is within `radius` metres of
    (center_x, center_z).

    Results are sorted nearest-first relative to the drone's current position
    when *drone_x* / *drone_z* are provided, otherwise relative to the search
    centre.  Drone-relative ordering reduces inter-building transit time for
    multi-building area scans.
    """
    buildings = WORLD.buildings_near(center_x, center_z, radius)
    sort_x = drone_x if drone_x is not None else center_x
    sort_z = drone_z if drone_z is not None else center_z
    buildings_sorted = sorted(buildings, key=lambda b: b.distance_xz(sort_x, sort_z))
    return {
        "buildings": [
            {
                "id": b.id,
                "x": b.cx,
                "z": b.cz,
                "height": b.h,
                "bounds": {
                    "min_x": b.min_x,
                    "max_x": b.max_x,
                    "min_z": b.min_z,
                    "max_z": b.max_z,
                },
            }
            for b in buildings_sorted
        ],
        "total": len(buildings_sorted),
        "center": {"x": center_x, "z": center_z},
        "radius": radius,
        **({"drone_position": {"x": drone_x, "z": drone_z}} if drone_x is not None else {}),
    }


def find_survivors_in_area(
    center_x: float,
    center_z: float,
    radius: float = 30.0,
    detected_only: bool = False,
    require_all_detected: bool = False,
) -> dict:
    """
    Return all survivors within radius metres of (center_x, center_z) in XZ.
    Results are sorted nearest-first from the search centre.
    When detected_only=True, only survivors detected in prior sweep scans are returned.
    When require_all_detected=True, return no survivors unless every survivor in area
    has already been detected.
    """
    rows: list[tuple[float, object]] = []
    for survivor in WORLD.survivors:
        dist = math.sqrt((survivor.x - center_x) ** 2 + (survivor.z - center_z) ** 2)
        if dist <= radius:
            rows.append((dist, survivor))
    rows.sort(key=lambda row: row[0])

    detected_rows = [
        (distance, survivor)
        for distance, survivor in rows
        if survivor.id in _detected_survivor_ids
    ]
    all_detected = len(detected_rows) == len(rows)
    blocked_by_detection_gate = bool(
        detected_only and require_all_detected and rows and not all_detected
    )

    selected_rows = rows
    if detected_only:
        selected_rows = detected_rows
    if blocked_by_detection_gate:
        selected_rows = []

    return {
        "survivors": [
            {
                "id": survivor.id,
                "x": survivor.x,
                "y": survivor.y,
                "z": survivor.z,
                "submerged": survivor.submerged,
                "distance_m": round(distance, 2),
            }
            for distance, survivor in selected_rows
        ],
        "total": len(selected_rows),
        "total_in_area": len(rows),
        "detected_total": len(detected_rows),
        "all_detected": all_detected,
        "detection_gate_blocked": blocked_by_detection_gate,
        "center": {"x": center_x, "z": center_z},
        "radius": radius,
        "detected_only": detected_only,
        "require_all_detected": require_all_detected,
        **(
            {"message": "Not all survivors in the selected area have been detected yet."}
            if blocked_by_detection_gate
            else {}
        ),
    }


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


async def assign_fleet_to_buildings(buildings: list[dict]) -> dict:
    """
    Assign the closest available drones to buildings using greedy nearest-first matching.

    For each building the nearest IDLE drone with battery > 20% is selected.
    Returns assignments (drone→building pairs), any unassigned buildings (more buildings
    than eligible drones), and idle drones that were not needed.
    """
    if not buildings:
        return {"assignments": [], "unassigned_buildings": [], "idle_drones": []}

    client = grpc_client
    asset_ids = client.registered_asset_ids()
    if not asset_ids:
        return {
            "error": "No drones uplinked.",
            "suggestion": "Use /uplink to connect a drone first.",
            "assignments": [],
            "unassigned_buildings": buildings,
        }

    statuses = await asyncio.gather(
        *[client.get_status(aid) for aid in asset_ids],
        return_exceptions=True,
    )

    eligible: list[dict] = []
    for status in statuses:
        if isinstance(status, Exception):
            continue
        if status.get("battery", 0) <= 20:
            continue
        if status.get("status", "") != "IDLE":
            continue
        eligible.append(status)

    if not eligible:
        busy = [s for s in statuses if not isinstance(s, Exception)]
        return {
            "error": "No eligible drones available (all busy or low battery).",
            "suggestion": f"{len(busy)} drone(s) registered but none are IDLE with battery > 20%.",
            "assignments": [],
            "unassigned_buildings": buildings,
        }

    # Greedy nearest-first: repeatedly pick the globally closest (drone, building) pair.
    remaining_drones = list(eligible)
    remaining_buildings = list(buildings)
    assignments: list[dict] = []

    while remaining_buildings and remaining_drones:
        best_drone: dict | None = None
        best_building: dict | None = None
        best_dist = float("inf")
        for drone in remaining_drones:
            for building in remaining_buildings:
                dist = math.sqrt(
                    (drone["x"] - building["x"]) ** 2 + (drone["z"] - building["z"]) ** 2
                )
                if dist < best_dist:
                    best_dist = dist
                    best_drone = drone
                    best_building = building

        if best_drone is None or best_building is None:
            break

        assignments.append(
            {
                "asset_id": best_drone["asset_id"],
                "building": best_building,
                "distance_m": round(best_dist, 1),
            }
        )
        remaining_drones = [d for d in remaining_drones if d["asset_id"] != best_drone["asset_id"]]
        remaining_buildings = [b for b in remaining_buildings if b is not best_building]

    return {
        "assignments": assignments,
        "unassigned_buildings": remaining_buildings,
        "idle_drones": [d["asset_id"] for d in remaining_drones],
        "total_assigned": len(assignments),
    }


async def parallel_fleet_scan(
    assignments: list[dict],
    unassigned_buildings: list[dict] | None = None,
) -> dict:
    """
    Execute sweep scans for all drone-building assignments concurrently.

    After the parallel first batch, any unassigned buildings are scanned
    sequentially by the first assignment's drone (fallback for when fewer
    drones than buildings are available).
    """
    if not assignments:
        return {"error": "No assignments provided.", "results": [], "total_survivors": 0}

    async def _scan_one(asset_id: str, building: dict) -> dict:
        result = await sweep_scan_building(
            asset_id=asset_id,
            target_x=building["x"],
            target_z=building["z"],
        )
        return {"asset_id": asset_id, "building": building, "scan_result": result}

    batch = await asyncio.gather(
        *[_scan_one(a["asset_id"], a["building"]) for a in assignments],
        return_exceptions=True,
    )

    all_results: list[dict] = []
    for i, result in enumerate(batch):
        if isinstance(result, Exception):
            all_results.append(
                {
                    "asset_id": assignments[i]["asset_id"],
                    "building": assignments[i]["building"],
                    "scan_result": {"error": str(result)},
                }
            )
        else:
            all_results.append(result)

    # Sequential fallback: unassigned buildings handled by first assignment's drone.
    if unassigned_buildings:
        fallback_aid = assignments[0]["asset_id"]
        for building in unassigned_buildings:
            result = await sweep_scan_building(
                asset_id=fallback_aid,
                target_x=building["x"],
                target_z=building["z"],
            )
            all_results.append({"asset_id": fallback_aid, "building": building, "scan_result": result})

    # Build consolidated report.
    total_survivors = 0
    building_summaries: list[str] = []
    for result in all_results:
        scan = result["scan_result"]
        building = result["building"]
        if "error" in scan:
            building_summaries.append(
                f"Building at (x={building['x']}, z={building['z']}) [{result['asset_id']}]: "
                f"SCAN ERROR — {scan['error']}"
            )
        else:
            count: int = scan.get("reported_survivor_count", 0)
            levels = scan.get("level_count", "?")
            waypoints = scan.get("waypoint_count", "?")
            total_survivors += count
            line = (
                f"Building at (x={building['x']:.1f}, z={building['z']:.1f}) [{result['asset_id']}]: "
                f"{count} survivor(s) across {levels} level(s). Waypoints: {waypoints}."
            )
            unique_survivors: list[dict] = scan.get("unique_survivors_detected", [])
            if unique_survivors:
                survivor_lines = []
                for survivor in unique_survivors:
                    submerged_tag = " [SUBMERGED — CRITICAL]" if survivor.get("submerged") else ""
                    survivor_lines.append(
                        f"  - Survivor {survivor['id']}: "
                        f"({survivor['x']}, {survivor['y']}, {survivor['z']}){submerged_tag}"
                    )
                if any(survivor.get("submerged") for survivor in unique_survivors):
                    submerged_count = sum(1 for survivor in unique_survivors if survivor.get("submerged"))
                    line += f" [CRITICAL: {submerged_count} submerged]"
                line += "\n" + "\n".join(survivor_lines)
            building_summaries.append(line)

    total_buildings = len(all_results)
    divider = "═" * 39
    thin_divider = "─" * 39
    total_line = (
        "No heat signatures detected across all scanned buildings."
        if total_survivors == 0
        else f"TOTAL SURVIVORS DETECTED: {total_survivors}"
    )
    summary = (
        f"{divider}\n"
        f"  AREA SCAN COMPLETE — {total_buildings} building(s)\n"
        f"{divider}\n"
        + "\n".join(building_summaries)
        + f"\n{thin_divider}\n{total_line}\n{divider}"
    )

    return {
        "success": True,
        "results": all_results,
        "total_buildings_scanned": total_buildings,
        "total_survivors": total_survivors,
        "summary": summary,
    }


async def dispatch_supply_to_building(asset_id: str, building: dict) -> dict:
    """
    Dispatch one drone to deliver supplies for a target survivor/building.

    Flow: return to base for pickup, route to target drop point,
    execute waypoints, then report completion.
    """
    target_x = building.get("x")
    target_y = building.get("y")
    target_z = building.get("z")
    if not isinstance(target_x, (int, float)) or not isinstance(target_z, (int, float)):
        return {
            "asset_id": asset_id,
            "error": "Invalid supply target coordinates.",
            "building": building,
        }

    resolved = resolve_scan_target(float(target_x), float(target_z))
    matched_building = resolved.get("building") if isinstance(resolved, dict) else None
    recommended_window = (
        resolved.get("recommended_window_waypoint")
        if isinstance(resolved, dict)
        else None
    )
    interior_target = False
    window_drop_for_survivor: dict | None = None
    if isinstance(target_y, (int, float)):
        host_building = WORLD.building_at(float(target_x), float(target_y), float(target_z))
        interior_target = host_building is not None
        if host_building is not None:
            candidate_windows = host_building.window_scan_waypoints(standoff=WINDOW_SCAN_STANDOFF_M)
            if candidate_windows:
                window_drop_for_survivor = _select_window_waypoint(
                    candidate_windows,
                    ref_x=float(target_x),
                    ref_z=float(target_z),
                    preferred_y=float(target_y),
                )

    if (
        interior_target
        and isinstance(window_drop_for_survivor, dict)
        and isinstance(window_drop_for_survivor.get("x"), (int, float))
        and isinstance(window_drop_for_survivor.get("y"), (int, float))
        and isinstance(window_drop_for_survivor.get("z"), (int, float))
    ):
        drop_x = float(window_drop_for_survivor["x"])
        drop_y = float(window_drop_for_survivor["y"])
        drop_z = float(window_drop_for_survivor["z"])
    elif (
        interior_target
        and isinstance(recommended_window, dict)
        and isinstance(recommended_window.get("x"), (int, float))
        and isinstance(recommended_window.get("y"), (int, float))
        and isinstance(recommended_window.get("z"), (int, float))
    ):
        drop_x = float(recommended_window["x"])
        drop_y = float(recommended_window["y"])
        drop_z = float(recommended_window["z"])
    elif (
        isinstance(target_y, (int, float))
        and isinstance(matched_building, dict)
        and all(
            isinstance(matched_building.get(k), (int, float))
            for k in ("min_x", "max_x", "min_z", "max_z", "height")
        )
    ):
        # Balcony/exterior-near-building targets: route to a rooftop-edge drop point
        # to avoid no-route failures against inflated obstacle bounds at facade level.
        min_x = float(matched_building["min_x"])
        max_x = float(matched_building["max_x"])
        min_z = float(matched_building["min_z"])
        max_z = float(matched_building["max_z"])
        height = float(matched_building["height"])
        tx = float(target_x)
        tz = float(target_z)

        if tz >= max_z:
            drop_x = min(max(tx, min_x), max_x)
            drop_z = max_z
        elif tz <= min_z:
            drop_x = min(max(tx, min_x), max_x)
            drop_z = min_z
        elif tx >= max_x:
            drop_x = max_x
            drop_z = min(max(tz, min_z), max_z)
        elif tx <= min_x:
            drop_x = min_x
            drop_z = min(max(tz, min_z), max_z)
        else:
            drop_x = tx
            drop_z = tz
        drop_y = max(height + 2.5, float(target_y) + 2.0, 10.0)
    elif isinstance(target_y, (int, float)):
        drop_x = float(target_x)
        drop_y = max(float(target_y) + 2.0, 5.0)
        drop_z = float(target_z)
    else:
        target_height = float(building.get("height", 0.0) or 0.0)
        drop_x = float(target_x)
        drop_y = max(target_height + 5.0, 10.0)
        drop_z = float(target_z)

    to_base = await return_to_base(asset_id)
    if "error" in to_base:
        return {
            "asset_id": asset_id,
            "error": f"Failed to return to base before supply dispatch: {to_base['error']}",
            "building": building,
            "return_result": to_base,
        }

    route = await plan_route(
        asset_id=asset_id,
        target_x=drop_x,
        target_z=drop_z,
        target_y=drop_y,
        snap_to_building_center=False,
    )
    if "error" in route:
        retry_route = await plan_route(
            asset_id=asset_id,
            target_x=drop_x,
            target_z=drop_z,
            target_y=max(drop_y + 5.0, 15.0),
            snap_to_building_center=False,
        )
        if "error" in retry_route:
            return {
                "asset_id": asset_id,
                "error": route["error"],
                "building": building,
                "route": route,
            }
        route = retry_route

    waypoints = route.get("waypoints", [])
    for waypoint in waypoints:
        move_result = await move_drone_to(
            asset_id=asset_id,
            x=float(waypoint["x"]),
            y=float(waypoint["y"]),
            z=float(waypoint["z"]),
        )
        if not move_result.get("success", True):
            return {
                "asset_id": asset_id,
                "error": move_result.get("message", "Failed while moving on supply route."),
                "building": building,
                "waypoint": waypoint,
                "move_result": move_result,
            }

    final_status = await grpc_client.get_status(asset_id)
    return {
        "success": True,
        "asset_id": asset_id,
        "building": building,
        "drop_point": route.get("to"),
        "waypoint_count": len(waypoints),
        "message": (
            f"SUPPLY SENT — {asset_id} delivered to building "
            f"at (x={float(target_x):.1f}, z={float(target_z):.1f})."
        ),
        "target_type": "survivor" if isinstance(target_y, (int, float)) else "building",
        "matched_building": matched_building,
        "final_status": final_status,
    }


async def parallel_fleet_supply(
    assignments: list[dict],
    unassigned_buildings: list[dict] | None = None,
    unassigned_targets: list[dict] | None = None,
) -> dict:
    """
    Execute supply dispatch for all drone-building assignments concurrently.

    After the parallel first batch, any unassigned buildings are handled
    sequentially by the first assignment's drone.
    """
    if not assignments:
        return {"error": "No assignments provided.", "results": [], "total_supplied": 0}

    async def _dispatch_one(asset_id: str, target: dict) -> dict:
        result = await dispatch_supply_to_building(asset_id=asset_id, building=target)
        return {"asset_id": asset_id, "target": target, "supply_result": result}

    rows = []
    for assignment in assignments:
        target = assignment.get("target", assignment.get("survivor", assignment.get("building")))
        if isinstance(target, dict):
            rows.append({"asset_id": assignment["asset_id"], "target": target})

    batch = await asyncio.gather(
        *[_dispatch_one(row["asset_id"], row["target"]) for row in rows],
        return_exceptions=True,
    )

    all_results: list[dict] = []
    for i, result in enumerate(batch):
        if isinstance(result, Exception):
            all_results.append(
                {
                    "asset_id": assignments[i]["asset_id"],
                    "target": rows[i]["target"],
                    "supply_result": {"error": str(result)},
                }
            )
        else:
            all_results.append(result)

    pending_targets = (
        list(unassigned_targets)
        if unassigned_targets is not None
        else list(unassigned_buildings or [])
    )
    if pending_targets:
        fallback_aid = assignments[0]["asset_id"]
        for target in pending_targets:
            result = await dispatch_supply_to_building(asset_id=fallback_aid, building=target)
            all_results.append(
                {
                    "asset_id": fallback_aid,
                    "target": target,
                    "supply_result": result,
                }
            )

    total_supplied = 0
    target_summaries: list[str] = []
    for result in all_results:
        supply = result["supply_result"]
        target = result["target"]
        if "error" in supply:
            target_summaries.append(
                f"Target at (x={target['x']}, z={target['z']}) [{result['asset_id']}]: "
                f"SUPPLY ERROR — {supply['error']}"
            )
            continue
        total_supplied += 1
        target_summaries.append(
            f"Target at (x={target['x']:.1f}, z={target['z']:.1f}) [{result['asset_id']}]: "
            f"SUPPLY SENT. Waypoints: {supply.get('waypoint_count', '?')}."
        )

    total_targets = len(all_results)
    divider = "═" * 39
    thin_divider = "─" * 39
    total_line = (
        "No supplies dispatched."
        if total_supplied == 0
        else f"TOTAL SUPPLY DISPATCHED: {total_supplied}"
    )
    summary = (
        f"{divider}\n"
        f"  AREA SUPPLY DISPATCH COMPLETE — {total_targets} target(s)\n"
        f"{divider}\n"
        + "\n".join(target_summaries)
        + f"\n{thin_divider}\n{total_line}\n{divider}"
    )

    return {
        "success": True,
        "results": all_results,
        "total_buildings_targeted": total_targets,
        "total_supplied": total_supplied,
        "summary": summary,
    }


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
        *[return_to_base(aid) for aid in asset_ids]
    )
    return {"recalled": asset_ids, "results": list(results)}
