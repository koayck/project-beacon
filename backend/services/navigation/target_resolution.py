from __future__ import annotations

from backend.services.navigation.internal.window_ops import select_window_waypoint
from backend.world.model import (
    BUILDING_PROXIMITY_MARGIN_M,
    WINDOW_SCAN_STANDOFF_M,
    WORLD,
)


def resolve_scan_target(
    target_x: float,
    target_z: float,
    margin: float = BUILDING_PROXIMITY_MARGIN_M,
) -> dict:
    """Resolve a scan target to a building footprint when the point is on/near one."""
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
    recommended_window = select_window_waypoint(
        window_waypoints,
        ref_x=target_x,
        ref_z=target_z,
        preferred_y=preferred_y,
    )
    recommended_scan_y = (
        float(recommended_window["y"]) if recommended_window is not None else building.max_y + 5.0
    )

    summary = (
        f"Matched building {building.id}; footprint "
        f"x[{building.min_x:.1f},{building.max_x:.1f}] "
        f"z[{building.min_z:.1f},{building.max_z:.1f}] "
        f"-> center ({building.cx:.1f}, {building.cz:.1f})."
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
