"""
Virtual camera / sensor system.
Given a drone position, computes what the drone can "see" — buildings,
survivors, terrain type, altitude above ground, and obstacle-ahead status.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from backend.world.model import WORLD, Building, Survivor

# Default sensor parameters
DEFAULT_RANGE: float = 20.0   # metres
DEFAULT_FOV: float   = 90.0   # degrees (downward-facing cone full angle)
SURVIVOR_RANGE: float = 12.0  # survivors are harder to spot, shorter range
OBSTACLE_LOOKAHEAD: float = 10.0  # metres ahead to check for obstacles

TerrainType = Literal["ground", "flooded", "building_roof", "in_building", "airspace"]


def _bearing_label(dx: float, dz: float) -> str:
    """Return a compass label (N/NE/E/…) for a 2D delta vector."""
    angle = math.degrees(math.atan2(dx, -dz)) % 360  # 0=North, 90=East
    labels = ["N","NE","E","SE","S","SW","W","NW"]
    idx = round(angle / 45) % 8
    return labels[idx]


@dataclass
class VisibleBuilding:
    id: int
    cx: float
    cz: float
    width: float
    depth: float
    height: float
    distance: float      # metres to nearest edge
    direction: str       # compass label from drone


@dataclass
class VisibleSurvivor:
    id: int
    x: float
    y: float
    z: float
    distance: float
    direction: str
    submerged: bool


@dataclass
class ViewResult:
    """Everything a drone can observe from its current position."""
    buildings_visible: list[VisibleBuilding]
    survivors_visible: list[VisibleSurvivor]
    terrain: TerrainType
    altitude_agl: float          # altitude above ground (or building roof)
    obstacle_ahead: bool         # anything blocking within OBSTACLE_LOOKAHEAD
    nearest_obstacle_dist: float # metres, inf if clear
    nearby_obstacles: int        # count of buildings within range
    survivors_in_range: int      # count of visible survivors
    over_flood: bool             # is this position over flood water

    def to_dict(self) -> dict:
        return {
            "buildings_visible": [
                {
                    "id": b.id,
                    "cx": round(b.cx, 1),
                    "cz": round(b.cz, 1),
                    "width": b.width,
                    "depth": b.depth,
                    "height": b.height,
                    "distance": round(b.distance, 1),
                    "direction": b.direction,
                }
                for b in self.buildings_visible
            ],
            "survivors_visible": [
                {
                    "id": s.id,
                    "x": round(s.x, 1),
                    "y": round(s.y, 1),
                    "z": round(s.z, 1),
                    "distance": round(s.distance, 1),
                    "direction": s.direction,
                    "submerged": s.submerged,
                }
                for s in self.survivors_visible
            ],
            "terrain": self.terrain,
            "altitude_agl": round(self.altitude_agl, 2),
            "obstacle_ahead": self.obstacle_ahead,
            "nearest_obstacle_dist": round(self.nearest_obstacle_dist, 1)
                if self.nearest_obstacle_dist != float("inf") else None,
            "nearby_obstacles": self.nearby_obstacles,
            "survivors_in_range": self.survivors_in_range,
            "over_flood": self.over_flood,
        }

    def to_summary(self) -> str:
        """Human-readable one-line summary for LLM context."""
        parts: list[str] = []
        parts.append(f"altitude_agl={self.altitude_agl:.1f}m")
        parts.append(f"terrain={self.terrain}")
        if self.over_flood:
            parts.append("OVER_FLOOD")
        if self.obstacle_ahead:
            parts.append(f"OBSTACLE_AHEAD({self.nearest_obstacle_dist:.1f}m)")
        if self.nearby_obstacles:
            parts.append(f"buildings_nearby={self.nearby_obstacles}")
        if self.survivors_in_range:
            surv_strs = [
                f"survivor@({s.x:.0f},{s.y:.0f},{s.z:.0f}) {s.distance:.1f}m {s.direction}"
                + (" [SUBMERGED]" if s.submerged else "")
                for s in self.survivors_visible
            ]
            parts.append("SURVIVORS: " + "; ".join(surv_strs))
        return " | ".join(parts)


def _terrain_at(x: float, y: float, z: float) -> tuple[TerrainType, float]:
    """
    Returns (terrain_type, altitude_above_ground).
    altitude_agl is y minus the highest building below, or y for open ground.
    """
    # Check if drone is inside a building
    b_inside = WORLD.building_at(x, y, z)
    if b_inside:
        return "in_building", 0.0

    # Find highest building surface directly below (same XZ, lower Y)
    ground_y = 0.0
    for b in WORLD.buildings:
        if b.min_x <= x <= b.max_x and b.min_z <= z <= b.max_z:
            if b.max_y <= y:  # building roof is below drone
                ground_y = max(ground_y, b.max_y)

    agl = y - ground_y

    if ground_y > 0:
        terrain: TerrainType = "building_roof"
    elif WORLD.is_flooded(y) and ground_y == 0.0:
        terrain = "flooded"
    else:
        terrain = "ground" if y < 0.5 else "airspace"

    return terrain, max(agl, 0.0)


def _line_of_sight_clear(
    from_x: float,
    from_y: float,
    from_z: float,
    to_x: float,
    to_y: float,
    to_z: float,
    ignore_building_ids: set[int] | None = None,
) -> bool:
    """
    True if no geometry blocks the segment from source to target.

    Buildings listed in `ignore_building_ids` are excluded from blockage checks
    except for their floor slabs, which remain blocking.
    """
    ignored = ignore_building_ids or set()
    samples = 30
    for i in range(1, samples + 1):
        t = i / samples
        sx = from_x + (to_x - from_x) * t
        sy = from_y + (to_y - from_y) * t
        sz = from_z + (to_z - from_z) * t

        for b in WORLD.buildings:
            if not b.contains_point(sx, sy, sz):
                continue
            if b.id in ignored:
                if b.contains_floor_slab_point(sx, sy, sz):
                    return False
                continue
            return False
    return True


def _survivor_visible(
    drone_x: float,
    drone_y: float,
    drone_z: float,
    survivor: Survivor,
) -> bool:
    """
    Thermal visibility policy:
    - Outdoor survivors require direct line of sight.
    - Indoor survivors require a valid window aperture intersection
      plus unobstructed line of sight.
    """
    survivor_building = WORLD.building_at(survivor.x, survivor.y, survivor.z)

    if survivor_building is None:
        return _line_of_sight_clear(
            drone_x, drone_y, drone_z, survivor.x, survivor.y, survivor.z
        )

    if not survivor_building.has_window_line_of_sight(
        drone_x,
        drone_y,
        drone_z,
        survivor.x,
        survivor.y,
        survivor.z,
    ):
        return False

    return _line_of_sight_clear(
        drone_x,
        drone_y,
        drone_z,
        survivor.x,
        survivor.y,
        survivor.z,
        ignore_building_ids={survivor_building.id},
    )


def get_view(
    x: float,
    y: float,
    z: float,
    heading_deg: float = 0.0,
    fov_deg: float = DEFAULT_FOV,
    detection_range: float = DEFAULT_RANGE,
) -> ViewResult:
    """
    Compute everything visible from position (x, y, z).

    heading_deg: direction the drone faces (0 = North/−Z, 90 = East/+X).
                 Used for the obstacle-ahead check.
    fov_deg:     full-cone half-angle for the downward-facing camera.
    detection_range: maximum metres for building detection.
    """
    # ── Buildings ──────────────────────────────────────────────────────────
    nearby = WORLD.buildings_near(x, z, detection_range)
    visible_buildings: list[VisibleBuilding] = []
    nearest_obstacle_dist = float("inf")

    for b in nearby:
        dist = b.distance_xz(x, z)
        if dist < nearest_obstacle_dist:
            nearest_obstacle_dist = dist
        dx = b.cx - x
        dz = b.cz - z
        visible_buildings.append(VisibleBuilding(
            id=b.id,
            cx=b.cx, cz=b.cz,
            width=b.w, depth=b.d, height=b.h,
            distance=round(dist, 2),
            direction=_bearing_label(dx, dz),
        ))

    # Sort closest first
    visible_buildings.sort(key=lambda b: b.distance)

    # ── Obstacle ahead (along heading vector) ─────────────────────────────
    rad = math.radians(heading_deg)
    fwd_x = math.sin(rad) * OBSTACLE_LOOKAHEAD
    fwd_z = -math.cos(rad) * OBSTACLE_LOOKAHEAD
    obstacles_ahead = WORLD.obstacles_in_path(
        x, y, z,
        x + fwd_x, y, z + fwd_z,
        samples=10,
    )
    obstacle_ahead = len(obstacles_ahead) > 0

    # ── Survivors ─────────────────────────────────────────────────────────
    visible_survivors: list[VisibleSurvivor] = []
    for s in WORLD.survivors:
        if not _survivor_visible(x, y, z, s):
            continue
        dist = s.distance_to(x, y, z)
        if dist > SURVIVOR_RANGE:
            continue
        dx = s.x - x
        dz = s.z - z
        visible_survivors.append(VisibleSurvivor(
            id=s.id,
            x=s.x, y=s.y, z=s.z,
            distance=round(dist, 2),
            direction=_bearing_label(dx, dz),
            submerged=s.submerged,
        ))
    visible_survivors.sort(key=lambda s: s.distance)

    # ── Terrain & AGL ─────────────────────────────────────────────────────
    terrain, agl = _terrain_at(x, y, z)
    over_flood = WORLD.is_flooded(y)

    return ViewResult(
        buildings_visible=visible_buildings,
        survivors_visible=visible_survivors,
        terrain=terrain,
        altitude_agl=agl,
        obstacle_ahead=obstacle_ahead,
        nearest_obstacle_dist=nearest_obstacle_dist,
        nearby_obstacles=len(visible_buildings),
        survivors_in_range=len(visible_survivors),
        over_flood=over_flood,
    )
