from __future__ import annotations

import math
from typing import Any, Literal

from backend.services.core import context
from backend.services.core.survivor_registry import get_detected_survivor_ids
from backend.services.navigation.a_star_3d import find_3d_path
from backend.services.navigation.internal.window_ops import select_window_waypoint
from backend.world.model import WINDOW_SCAN_STANDOFF_M

_EXCLUDED_BUILDING_CLEARANCE_M = 0.6


def _segment_sample_count(
    from_x: float,
    from_y: float,
    from_z: float,
    to_x: float,
    to_y: float,
    to_z: float,
    base_samples: int,
) -> int:
    """Choose a segment sample count that scales with 3D segment length.

    Args:
        from_x: Segment start X coordinate.
        from_y: Segment start Y coordinate.
        from_z: Segment start Z coordinate.
        to_x: Segment end X coordinate.
        to_y: Segment end Y coordinate.
        to_z: Segment end Z coordinate.
        base_samples: Minimum sampling resolution requested by caller.

    Returns:
        Sampling count large enough to avoid missing thin corner intersections.
    """
    distance = math.sqrt(
        (to_x - from_x) ** 2
        + (to_y - from_y) ** 2
        + (to_z - from_z) ** 2
    )
    return max(base_samples, int(math.ceil(distance * 6.0)))

async def plan_route(
    asset_id: str,
    target_x: float,
    target_z: float,
    target_y: float | None = None,
    snap_to_building_center: bool = False,
    exclude_building_id: int | None = None,
    entry_mode: Literal["nearest_floor", "ground_entry"] = "nearest_floor",
) -> dict:
    """
    Pre-compute a collision-free route from the drone's current position.

    ``exclude_building_id`` removes a specific building from obstacle checks -
    used when the destination IS the target building (e.g. rooftop approach).

    ``entry_mode`` controls window-waypoint selection when ``snap_to_building_center``
    is True and the target building has windows:
      - ``"nearest_floor"`` (default): pick the window closest in Y to ``target_y``
        (building center by default), with XZ distance as tiebreaker. Preserves
        historical behavior.
      - ``"ground_entry"``: restrict candidates to the lowest-floor windows only,
        and pick the one minimizing horizontal (XZ) distance from the drone's
        current position. This mimics a human pilot entering a building at the
        ground floor nearest their approach, rather than climbing to the roof
        first. When the restricted set is empty (e.g. building has no windows),
        fall back to ``nearest_floor`` behavior with ``entry_mode_fallback=True``
        recorded.

    Args:
        asset_id: Drone identifier.
        target_x: Target X coordinate.
        target_z: Target Z coordinate.
        target_y: Optional target altitude.
        snap_to_building_center: Whether to snap target onto building center/window waypoint.
        exclude_building_id: Optional building id to ignore as obstacle.
        entry_mode: Window-waypoint selection policy (see above).
    Returns:
        Structured route payload with strategy, waypoints, and optional error.
    """
    world = context.get_world()
    client = context.get_grpc_client()
    status = await client.get_status(asset_id)
    cx, cy, cz = status["x"], status["y"], status["z"]

    requested_x = target_x
    requested_z = target_z
    nearby = world.building_near_xz(target_x, target_z)
    available_window_waypoints: list[dict] = []
    selected_window_waypoint: dict | None = None
    if nearby is not None and nearby.windows:
        available_window_waypoints = nearby.window_scan_waypoints(standoff=WINDOW_SCAN_STANDOFF_M)

    entry_mode_fallback = False
    if snap_to_building_center and nearby is not None:
        target_x = nearby.cx
        target_z = nearby.cz

        if entry_mode == "ground_entry" and available_window_waypoints:
            floors = {int(wp["floor"]) for wp in available_window_waypoints}
            lowest_floor = min(floors)
            ground_candidates: list[dict] = [
                wp for wp in available_window_waypoints
                if int(wp["floor"]) == lowest_floor
            ]
            assert ground_candidates, (
                "ground_entry candidate set is empty despite non-empty "
                "available_window_waypoints — this is a logic error"
            )

            def _drone_dist_xz(wp: dict) -> float:
                dx = float(wp["x"]) - cx
                dz = float(wp["z"]) - cz
                return math.sqrt(dx * dx + dz * dz)

            selected_window_waypoint = min(ground_candidates, key=_drone_dist_xz)

        if selected_window_waypoint is None:
            if entry_mode == "ground_entry":
                entry_mode_fallback = True
            selected_window_waypoint = select_window_waypoint(
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

    # If the requested target XZ falls inside a building's footprint and the
    # requested altitude would place the drone inside or on the rooftop, lift
    # target_y above the roof. Otherwise A*'s goal snapping lands the drone on
    # the roof surface where any obstacle perturbation leaves it BLOCKED.
    footprint_building = world.building_near_xz(target_x, target_z, margin=0.0)
    if footprint_building is not None and target_y <= footprint_building.max_y + 0.5:
        target_y = footprint_building.max_y + 5.0

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

    if target_resolution is not None:
        if entry_mode == "ground_entry":
            target_resolution["entry_mode"] = "ground_entry"
            if entry_mode_fallback:
                target_resolution["entry_mode_fallback"] = True

    window_summary_suffix = ""
    if selected_window_waypoint is not None:
        window_summary_suffix = (
            " Window approach "
            f"{selected_window_waypoint['face']} floor {selected_window_waypoint['floor']}."
        )

    def _filter(buildings: list) -> list:
        """Drop the optional excluded building from obstacle collections.

        Args:
            buildings: Candidate obstacle list from world collision checks.

        Returns:
            Filtered obstacle list with excluded building removed when configured.
        """
        if exclude_building_id is None:
            return buildings
        return [building for building in buildings if building.id != exclude_building_id]

    def _segment_hits_excluded_geometry(
        from_x: float,
        from_y: float,
        from_z: float,
        to_x: float,
        to_y: float,
        to_z: float,
        *,
        samples: int,
    ) -> bool:
        """Check whether a segment intersects hard geometry of excluded building.

        Args:
            from_x: Segment start X coordinate.
            from_y: Segment start Y coordinate.
            from_z: Segment start Z coordinate.
            to_x: Segment end X coordinate.
            to_y: Segment end Y coordinate.
            to_z: Segment end Z coordinate.
            samples: Sampling resolution for obstacle checks.

        Returns:
            True when the excluded building is intersected with margin=0.0,
            otherwise False.
        """
        if exclude_building_id is None:
            return False
        segment_samples = _segment_sample_count(
            from_x,
            from_y,
            from_z,
            to_x,
            to_y,
            to_z,
            base_samples=samples,
        )
        return any(
            building.id == exclude_building_id
            for building in world.obstacles_in_path(
                from_x,
                from_y,
                from_z,
                to_x,
                to_y,
                to_z,
                samples=segment_samples,
                margin=0.0,
            )
        )

    def _segment_blockers(
        from_x: float,
        from_y: float,
        from_z: float,
        to_x: float,
        to_y: float,
        to_z: float,
        *,
        samples: int,
        margin: float,
    ) -> list:
        """Return blockers for a segment including hard excluded-building intersections.

        Args:
            from_x: Segment start X coordinate.
            from_y: Segment start Y coordinate.
            from_z: Segment start Z coordinate.
            to_x: Segment end X coordinate.
            to_y: Segment end Y coordinate.
            to_z: Segment end Z coordinate.
            samples: Sampling resolution for obstacle checks.
            margin: Inflated-margin obstacle distance used for regular planning.

        Returns:
            List of blocking buildings. Includes filtered margin blockers and,
            when applicable, the excluded building if segment intersects its
            hard geometry.
        """
        segment_samples = _segment_sample_count(
            from_x,
            from_y,
            from_z,
            to_x,
            to_y,
            to_z,
            base_samples=samples,
        )

        margin_hits = _filter(
            world.obstacles_in_path(
                from_x,
                from_y,
                from_z,
                to_x,
                to_y,
                to_z,
                samples=segment_samples,
                margin=margin,
            )
        )
        if exclude_building_id is None:
            return margin_hits

        excluded_hard_hits = [
            building
            for building in world.obstacles_in_path(
                from_x,
                from_y,
                from_z,
                to_x,
                to_y,
                to_z,
                samples=segment_samples,
                margin=0.0,
            )
            if building.id == exclude_building_id
        ]

        excluded_clearance_hits = [
            building
            for building in world.obstacles_in_path(
                from_x,
                from_y,
                from_z,
                to_x,
                to_y,
                to_z,
                samples=segment_samples,
                margin=_EXCLUDED_BUILDING_CLEARANCE_M,
            )
            if building.id == exclude_building_id
        ]

        excluded_hits = excluded_hard_hits + [
            building
            for building in excluded_clearance_hits
            if all(building.id != existing.id for existing in excluded_hard_hits)
        ]
        if not excluded_hits:
            return margin_hits
        if any(building.id == exclude_building_id for building in margin_hits):
            return margin_hits
        return [*margin_hits, *excluded_hits]

    obstacles = _segment_blockers(
        cx,
        cy,
        cz,
        target_x,
        target_y,
        target_z,
        samples=40,
        margin=1.0,
    )
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

    dx = target_x - cx
    dz = target_z - cz
    length = math.sqrt(dx * dx + dz * dz)
    if length < 1e-6:
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

    max_obstacle_h = max(building.max_y for building in obstacles)
    clearance_y = max_obstacle_h + 5.0

    a_star_path = find_3d_path(
        world,
        (float(cx), float(cy), float(cz)),
        (float(target_x), float(target_y), float(target_z)),
        margin=1.0,
        exclude_building_id=exclude_building_id,
        cell_size=1.0,
        max_altitude=max(clearance_y + 10.0, target_y + 15.0),
        max_iterations=120_000,
    )
    if a_star_path is not None and len(a_star_path) >= 2:
        # Keep excluded building traversable for close-to-facade goals, but never
        # allow routes that physically cross through its hard geometry.
        invalid_excluded_crossing = False
        if exclude_building_id is not None:
            for (fx, fy, fz), (tx, ty, tz) in zip(a_star_path[:-1], a_star_path[1:]):
                if _segment_hits_excluded_geometry(
                    float(fx),
                    float(fy),
                    float(fz),
                    float(tx),
                    float(ty),
                    float(tz),
                    samples=10,
                ):
                    invalid_excluded_crossing = True
                    break

        if invalid_excluded_crossing:
            a_star_path = None

    if a_star_path is not None and len(a_star_path) >= 2:
        a_star_waypoints = []
        for idx, (wx, wy, wz) in enumerate(a_star_path[1:]):
            reason = "3d a* transit waypoint"
            if idx == len(a_star_path[1:]) - 1:
                reason = "arrive at target"
            a_star_waypoints.append(
                {
                    "x": round(float(wx), 2),
                    "y": round(float(wy), 2),
                    "z": round(float(wz), 2),
                    "reason": reason,
                }
            )

        return {
            "asset_id": asset_id,
            "from": {"x": cx, "y": cy, "z": cz},
            "to": {"x": target_x, "y": target_y, "z": target_z},
            "waypoints": a_star_waypoints,
            "obstacle_count": len(obstacles),
            "strategy": "a_star_3d",
            "summary": (
                f"{len(a_star_waypoints)} waypoint(s), clearing {len(obstacles)} obstacle(s) via 3D A*. "
                f"Scan alt={target_y}m.{window_summary_suffix}"
            ),
            **({"target_resolution": target_resolution} if target_resolution else {}),
        }

    seg_climb = _segment_blockers(
        cx,
        cy,
        cz,
        cx,
        clearance_y,
        cz,
        samples=20,
        margin=1.0,
    )
    seg_cruise = _segment_blockers(
        cx,
        clearance_y,
        cz,
        target_x,
        clearance_y,
        target_z,
        samples=40,
        margin=1.0,
    )
    seg_descend = _segment_blockers(
        target_x,
        clearance_y,
        target_z,
        target_x,
        target_y,
        target_z,
        samples=20,
        margin=1.0,
    )

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

    perp_x = -dz / length
    perp_z = dx / length
    mid_x = (cx + target_x) / 2
    mid_z = (cz + target_z) / 2
    max_half_w = max(max(building.w, building.d) / 2 for building in obstacles)
    offset_dist = max_half_w + 5.0
    fly_y = max(target_y, clearance_y)

    for sign in (1.0, -1.0):
        wp_x = mid_x + sign * perp_x * offset_dist
        wp_z = mid_z + sign * perp_z * offset_dist
        seg1 = _segment_blockers(
            cx,
            cy,
            cz,
            wp_x,
            fly_y,
            wp_z,
            samples=40,
            margin=1.0,
        )
        seg2 = _segment_blockers(
            wp_x,
            fly_y,
            wp_z,
            target_x,
            target_y,
            target_z,
            samples=40,
            margin=1.0,
        )
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
        "obstacles": [{"id": building.id, "cx": building.cx, "cz": building.cz, "h": building.h} for building in obstacles],
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
    """
    world = context.get_world()
    buildings = world.buildings_near(center_x, center_z, radius)
    sort_x = drone_x if drone_x is not None else center_x
    sort_z = drone_z if drone_z is not None else center_z
    buildings_sorted = sorted(buildings, key=lambda building: building.distance_xz(sort_x, sort_z))
    return {
        "buildings": [
            {
                "id": building.id,
                "x": building.cx,
                "z": building.cz,
                "height": building.h,
                "bounds": {
                    "min_x": building.min_x,
                    "max_x": building.max_x,
                    "min_z": building.min_z,
                    "max_z": building.max_z,
                },
            }
            for building in buildings_sorted
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
    """
    world = context.get_world()
    detected_ids = get_detected_survivor_ids()

    rows: list[tuple[float, Any]] = []
    for survivor in world.survivors:
        sx = float(getattr(survivor, "x", 0.0))
        sz = float(getattr(survivor, "z", 0.0))
        dist = math.sqrt((sx - center_x) ** 2 + (sz - center_z) ** 2)
        if dist <= radius:
            rows.append((dist, survivor))
    rows.sort(key=lambda row: row[0])

    detected_rows = [
        (distance, survivor)
        for distance, survivor in rows
        if int(getattr(survivor, "id", -1)) in detected_ids
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
                "id": int(getattr(survivor, "id", -1)),
                "x": float(getattr(survivor, "x", 0.0)),
                "y": float(getattr(survivor, "y", 0.0)),
                "z": float(getattr(survivor, "z", 0.0)),
                "submerged": bool(getattr(survivor, "submerged", False)),
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
    """Compute a lawnmower sweep pattern over a rectangular area."""
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
