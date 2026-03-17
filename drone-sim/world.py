"""
Minimal world model for the drone sim container.
Mirrors backend/world/model.py — kept in sync via the shared proto/world_data.
Only building AABBs are needed for collision avoidance and vision.
Survivor positions and facade windows are included so thermal detections can
respect wall occlusion.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

FLOOD_LEVEL: float = 1.4
SURVIVOR_RANGE: float = 12.0
FLOOR_HEIGHT: float = 3.0
FLOOR_SLAB_THICKNESS: float = 0.2

# (cx, cz, w, d, h)
# Target building at (-15, -20) — 4 floors, 12 m tall
# Obstacle at (-7, -10) — solid block blocking the direct route from base (0,0,0) to target
_RAW_BUILDINGS = [
    (-15, -20, 8, 8, 12),   # target building
    ( -7, -10, 6, 5, 10),   # obstacle on direct route (0,0,0) → (-15,0,-20)
    ( 20, -20, 6, 6,  9),   # balcony building (3 floors, exterior balcony on south face)
    ( 12, -27, 10, 8, 9),   # twin shophouse block (3 floors, windows on south face)
    (-23, -28, 10, 10, 21), # NW tower (7 floors), SE corner overlaps NW corner of target
]

# (x, y, z) — inside the target building, one per floor (floors 2, 3, 4)
# survY(n) = (n-1)*3.0 + 0.65  →  3.65, 6.65, 9.65
_RAW_SURVIVORS = [
    (-16.5,  3.65, -19.0),  # floor 2 — target building
    (-14.5,  6.65, -20.5),  # floor 3 — target building
    (-13.5,  9.65, -21.0),  # floor 4 — target building
    ( 20.0,  6.65, -16.0),  # floor 3 — balcony building, on exterior balcony (outside AABB)
    (  9.5,  3.65, -27.0),  # floor 2 — shophouse A, visible through south window
    ( 14.5,  6.65, -27.0),  # floor 3 — shophouse B, visible through south window
    (-19.0,  3.65, -27.5),  # floor 2 — NW tower, inside near east window
    (-23.0, 12.65, -22.0),  # floor 5 — NW tower, on south balcony (outside AABB)
]


@dataclass(frozen=True)
class SimBuilding:
    id: int
    cx: float; cz: float
    w: float;  d: float; h: float
    windows: tuple["SimWindowAperture", ...] = ()

    @property
    def min_x(self): return self.cx - self.w/2
    @property
    def max_x(self): return self.cx + self.w/2
    @property
    def min_z(self): return self.cz - self.d/2
    @property
    def max_z(self): return self.cz + self.d/2

    def contains(self, x, y, z) -> bool:
        return self.min_x <= x <= self.max_x and 0 <= y <= self.h and self.min_z <= z <= self.max_z

    def dist_xz(self, x, z) -> float:
        dx = max(self.min_x - x, 0.0, x - self.max_x)
        dz = max(self.min_z - z, 0.0, z - self.max_z)
        return math.sqrt(dx*dx + dz*dz)

    def dist_3d(self, x, y, z) -> float:
        dx = max(self.min_x - x, 0.0, x - self.max_x)
        dy = max(0.0 - y, 0.0, y - self.h)
        dz = max(self.min_z - z, 0.0, z - self.max_z)
        return math.sqrt(dx*dx + dy*dy + dz*dz)

    def _segment_intersects_window(
        self,
        window: "SimWindowAperture",
        from_x: float,
        from_y: float,
        from_z: float,
        to_x: float,
        to_y: float,
        to_z: float,
        epsilon: float = 1e-6,
    ) -> bool:
        dx = to_x - from_x
        dy = to_y - from_y
        dz = to_z - from_z

        if window.face in ("north", "south"):
            if abs(dz) <= epsilon:
                return False
            plane_z = self.min_z if window.face == "north" else self.max_z
            t = (plane_z - from_z) / dz
            if t <= epsilon or t >= 1.0 - epsilon:
                return False
            hit_x = from_x + dx * t
            hit_y = from_y + dy * t
            return (
                window.min_axis - epsilon <= hit_x <= window.max_axis + epsilon
                and window.min_y - epsilon <= hit_y <= window.max_y + epsilon
            )

        if abs(dx) <= epsilon:
            return False
        plane_x = self.min_x if window.face == "west" else self.max_x
        t = (plane_x - from_x) / dx
        if t <= epsilon or t >= 1.0 - epsilon:
            return False
        hit_z = from_z + dz * t
        hit_y = from_y + dy * t
        return (
            window.min_axis - epsilon <= hit_z <= window.max_axis + epsilon
            and window.min_y - epsilon <= hit_y <= window.max_y + epsilon
        )

    def has_window_line_of_sight(
        self,
        from_x: float,
        from_y: float,
        from_z: float,
        to_x: float,
        to_y: float,
        to_z: float,
    ) -> bool:
        return any(
            self._segment_intersects_window(window, from_x, from_y, from_z, to_x, to_y, to_z)
            for window in self.windows
        )

    def contains_floor_slab_point(
        self,
        x: float,
        y: float,
        z: float,
        floor_height: float = FLOOR_HEIGHT,
        slab_thickness: float = FLOOR_SLAB_THICKNESS,
        epsilon: float = 1e-6,
    ) -> bool:
        if not self.contains(x, y, z):
            return False

        half = slab_thickness / 2
        level = 0.0
        while level <= self.h + epsilon:
            if level - half - epsilon <= y <= level + half + epsilon:
                return True
            level += floor_height

        return self.h - half - epsilon <= y <= self.h + half + epsilon


WindowFace = Literal["north", "south", "west", "east"]


@dataclass(frozen=True)
class SimWindowAperture:
    face: WindowFace
    axis_center: float
    sill_y: float
    width: float
    height: float

    @property
    def min_y(self) -> float:
        return self.sill_y

    @property
    def max_y(self) -> float:
        return self.sill_y + self.height

    @property
    def min_axis(self) -> float:
        return self.axis_center - self.width / 2

    @property
    def max_axis(self) -> float:
        return self.axis_center + self.width / 2


@dataclass(frozen=True)
class SimSurvivor:
    id: int
    x: float; y: float; z: float

    @property
    def submerged(self): return self.y < FLOOD_LEVEL - 0.2

    def dist(self, x, y, z) -> float:
        return math.sqrt((self.x-x)**2+(self.y-y)**2+(self.z-z)**2)


def _target_windows(cx: float, cz: float) -> tuple[SimWindowAperture, ...]:
    windows: list[SimWindowAperture] = []
    layout: tuple[tuple[int, WindowFace, float], ...] = (
        (1, "west", 0.0),
        (2, "north", -1.5),
        (3, "east", -0.5),
        (4, "south", 1.5),
    )
    window_width = 2.0
    window_height = 1.6
    for floor, face, offset in layout:
        sill_y = (floor - 1) * 3.0 + 0.4
        axis_center = cx + offset if face in ("north", "south") else cz + offset
        windows.append(
            SimWindowAperture(
                face=face,
                axis_center=axis_center,
                sill_y=sill_y,
                width=window_width,
                height=window_height,
            )
        )
    return tuple(windows)


def _shophouse_windows(cx: float, cz: float) -> tuple[SimWindowAperture, ...]:
    windows: list[SimWindowAperture] = []
    layout: tuple[tuple[int, WindowFace, float], ...] = (
        (2, "south", -2.5),
        (2, "south",  2.5),
        (3, "south", -2.5),
        (3, "south",  2.5),
    )
    window_width = 1.6
    window_height = 1.4
    for floor, face, offset in layout:
        sill_y = (floor - 1) * 3.0 + 0.5
        axis_center = cx + offset if face in ("north", "south") else cz + offset
        windows.append(
            SimWindowAperture(
                face=face,
                axis_center=axis_center,
                sill_y=sill_y,
                width=window_width,
                height=window_height,
            )
        )
    return tuple(windows)


def _nw_tower_windows(cx: float, cz: float) -> tuple[SimWindowAperture, ...]:
    windows: list[SimWindowAperture] = []
    layout: tuple[tuple[int, WindowFace, float], ...] = (
        (2, "east",  0.5),
        (4, "south", -1.5),
        (6, "north",  2.0),
        (7, "west",  -1.0),
    )
    window_width = 1.8
    window_height = 1.6
    for floor, face, offset in layout:
        sill_y = (floor - 1) * 3.0 + 0.4
        axis_center = cx + offset if face in ("north", "south") else cz + offset
        windows.append(
            SimWindowAperture(
                face=face,
                axis_center=axis_center,
                sill_y=sill_y,
                width=window_width,
                height=window_height,
            )
        )
    return tuple(windows)


BUILDINGS = [
    SimBuilding(
        i, cx, cz, w, d, h,
        _target_windows(cx, cz) if i == 0
        else _shophouse_windows(cx, cz) if i == 3
        else _nw_tower_windows(cx, cz) if i == 4
        else ()
    )
    for i, (cx, cz, w, d, h) in enumerate(_RAW_BUILDINGS)
]
SURVIVORS = [SimSurvivor(i, *r) for i, r in enumerate(_RAW_SURVIVORS)]


def _compass(dx: float, dz: float) -> str:
    a = math.degrees(math.atan2(dx, -dz)) % 360
    return ["N","NE","E","SE","S","SW","W","NW"][round(a/45) % 8]


def get_view(x: float, y: float, z: float,
             heading_deg: float = 0.0,
             detection_range: float = 20.0) -> dict:
    """Return a view dict matching ViewResponse fields."""
    import json

    nearby_b = [b for b in BUILDINGS if b.dist_xz(x, z) <= detection_range]

    def _building_at(px: float, py: float, pz: float) -> SimBuilding | None:
        for b in BUILDINGS:
            if b.contains(px, py, pz):
                return b
        return None

    def _line_of_sight_clear(
        to_x: float,
        to_y: float,
        to_z: float,
        ignore_building_ids: set[int] | None = None,
    ) -> bool:
        ignored = ignore_building_ids or set()
        samples = 30
        for i in range(1, samples + 1):
            t = i / samples
            sx = x + (to_x - x) * t
            sy = y + (to_y - y) * t
            sz = z + (to_z - z) * t
            for b in BUILDINGS:
                if not b.contains(sx, sy, sz):
                    continue
                if b.id in ignored:
                    if b.contains_floor_slab_point(sx, sy, sz):
                        return False
                    continue
                return False
        return True

    def _survivor_visible(s: SimSurvivor) -> bool:
        survivor_building = _building_at(s.x, s.y, s.z)
        if survivor_building is None:
            return _line_of_sight_clear(s.x, s.y, s.z)
        if not survivor_building.has_window_line_of_sight(x, y, z, s.x, s.y, s.z):
            return False
        return _line_of_sight_clear(
            s.x,
            s.y,
            s.z,
            ignore_building_ids={survivor_building.id},
        )

    nearby_s: list[SimSurvivor] = []
    for s in SURVIVORS:
        if not _survivor_visible(s):
            continue
        if s.dist(x, y, z) <= SURVIVOR_RANGE:
            nearby_s.append(s)

    nearest_b_dist = min((b.dist_xz(x, z) for b in nearby_b), default=float("inf"))

    # Obstacle ahead
    rad = math.radians(heading_deg)
    lx = x + math.sin(rad) * 10.0
    lz = z - math.cos(rad) * 10.0
    obstacle_ahead = False
    for i in range(1, 11):
        t = i / 10
        sx, sy, sz = x + (lx-x)*t, y, z + (lz-z)*t
        if any(b.contains(sx, sy, sz) for b in BUILDINGS):
            obstacle_ahead = True
            break

    # Terrain
    ground_y = 0.0
    in_building = any(b.contains(x, y, z) for b in BUILDINGS)
    if not in_building:
        for b in BUILDINGS:
            if b.min_x <= x <= b.max_x and b.min_z <= z <= b.max_z and b.h <= y:
                ground_y = max(ground_y, b.h)
    agl = max(y - ground_y, 0.0) if not in_building else 0.0
    if in_building:
        terrain = "in_building"
    elif ground_y > 0:
        terrain = "building_roof"
    elif y <= FLOOD_LEVEL and ground_y == 0:
        terrain = "flooded"
    elif y < 0.5:
        terrain = "ground"
    else:
        terrain = "airspace"

    over_flood = y <= FLOOD_LEVEL

    # Build VisibleObject list
    objects = []
    for b in sorted(nearby_b, key=lambda b: b.dist_xz(x, z)):
        objects.append({
            "object_type": "building",
            "object_id": b.id,
            "x": b.cx, "y": b.h/2, "z": b.cz,
            "distance": round(b.dist_xz(x, z), 1),
            "direction": _compass(b.cx - x, b.cz - z),
            "detail": json.dumps({"w": b.w, "d": b.d, "h": b.h}),
        })
    for s in sorted(nearby_s, key=lambda s: s.dist(x, y, z)):
        objects.append({
            "object_type": "survivor",
            "object_id": s.id,
            "x": s.x, "y": s.y, "z": s.z,
            "distance": round(s.dist(x, y, z), 1),
            "direction": _compass(s.x - x, s.z - z),
            "detail": json.dumps({"submerged": s.submerged}),
        })

    # Summary string
    parts = [f"agl={agl:.1f}m terrain={terrain}"]
    if over_flood: parts.append("OVER_FLOOD")
    if obstacle_ahead: parts.append(f"OBSTACLE_AHEAD")
    if nearby_b: parts.append(f"buildings={len(nearby_b)}")
    if nearby_s:
        surv_str = "; ".join(
            f"surv@({s.x:.0f},{s.y:.0f},{s.z:.0f}) {s.dist(x,y,z):.1f}m {_compass(s.x-x,s.z-z)}"
            + (" [SUBMERGED]" if s.submerged else "")
            for s in nearby_s
        )
        parts.append("SURVIVORS: " + surv_str)
    summary = " | ".join(parts)

    return {
        "objects": objects,
        "terrain": terrain,
        "altitude_agl": round(agl, 2),
        "obstacle_ahead": obstacle_ahead,
        "nearest_obstacle_dist": round(nearest_b_dist, 1) if nearest_b_dist != float("inf") else 999.0,
        "nearby_obstacles": len(nearby_b),
        "survivors_in_range": len(nearby_s),
        "over_flood": over_flood,
        "summary": summary,
    }


def _segment_intersects_building(
    x: float, y: float, z: float,
    nx: float, ny: float, nz: float,
    b: SimBuilding,
) -> bool:
    """Return True if the line segment (x,y,z)→(nx,ny,nz) intersects building *b*.

    Uses the slab method for ray-AABB intersection, clamped to t ∈ [0, 1].
    """
    dx = nx - x
    dy = ny - y
    dz = nz - z

    tmin = 0.0
    tmax = 1.0

    for lo, hi, orig, d in (
        (b.min_x, b.max_x, x, dx),
        (0.0,     b.h,     y, dy),
        (b.min_z, b.max_z, z, dz),
    ):
        if abs(d) < 1e-12:
            # Segment is parallel to this slab — miss if origin is outside.
            if orig < lo or orig > hi:
                return False
        else:
            t1 = (lo - orig) / d
            t2 = (hi - orig) / d
            if t1 > t2:
                t1, t2 = t2, t1
            tmin = max(tmin, t1)
            tmax = min(tmax, t2)
            if tmin > tmax:
                return False

    return True


def next_position_blocked(x: float, y: float, z: float,
                           nx: float, ny: float, nz: float) -> SimBuilding | None:
    """Return the first building whose AABB is crossed by the movement segment."""
    for b in BUILDINGS:
        # Skip buildings the drone is currently inside to avoid trapping it.
        if b.contains(x, y, z):
            continue
        if _segment_intersects_building(x, y, z, nx, ny, nz, b):
            return b
    return None


def building_center_near(x: float, z: float) -> SimBuilding | None:
    """Return the nearest building to (x, z), or None if BUILDINGS is empty."""
    if not BUILDINGS:
        return None
    return min(BUILDINGS, key=lambda b: b.dist_xz(x, z))
