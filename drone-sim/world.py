"""
Minimal world model for the drone sim container.
Mirrors backend/world/model.py — kept in sync via the shared proto/world_data.
Only building AABBs are needed for collision avoidance and vision.
Survivor positions are also included so the drone can report detections.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

FLOOD_LEVEL: float = 1.4

# (cx, cz, w, d, h)
# Target building at (-15, -20) — 4 floors, 12 m tall
# Obstacle at (-7, -10) — solid block blocking the direct route from base (0,0,0) to target
_RAW_BUILDINGS = [
    (-15, -20, 8, 8, 12),   # target building
    ( -7, -10, 6, 5, 10),   # obstacle on direct route (0,0,0) → (-15,0,-20)
]

# (x, y, z) — inside the target building, one per floor (floors 2, 3, 4)
# survY(n) = (n-1)*3.0 + 0.65  →  3.65, 6.65, 9.65
_RAW_SURVIVORS = [
    (-16.5, 3.65, -19.0),   # floor 2
    (-14.5, 6.65, -20.5),   # floor 3
    (-13.5, 9.65, -21.0),   # floor 4
]


@dataclass(frozen=True)
class SimBuilding:
    id: int
    cx: float; cz: float
    w: float;  d: float; h: float

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


@dataclass(frozen=True)
class SimSurvivor:
    id: int
    x: float; y: float; z: float

    @property
    def submerged(self): return self.y < FLOOD_LEVEL - 0.2

    def dist(self, x, y, z) -> float:
        return math.sqrt((self.x-x)**2+(self.y-y)**2+(self.z-z)**2)


BUILDINGS = [SimBuilding(i, *r) for i, r in enumerate(_RAW_BUILDINGS)]
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
    nearby_s = [s for s in SURVIVORS if s.dist(x, y, z) <= 12.0]

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


def next_position_blocked(x: float, y: float, z: float,
                           nx: float, ny: float, nz: float) -> SimBuilding | None:
    """Return the first building that would be entered when moving from current to next pos."""
    for b in BUILDINGS:
        if b.contains(nx, ny, nz):
            return b
    return None
