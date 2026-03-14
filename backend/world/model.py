"""
World model — Python mirror of the SARScene.tsx scene data.
Single source of truth for building AABBs, survivor positions,
trees, parks, and flood level used by the vision system and
collision avoidance.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import NamedTuple


# ── Flood ─────────────────────────────────────────────────────────────────────
FLOOD_LEVEL: float = 1.4  # metres above Y=0
BUILDING_PROXIMITY_MARGIN_M: float = 2.0  # edge distance to consider "near" a building

# ── Scene geometry (mirrors SARScene.tsx constants) ───────────────────────────
# Buildings: (cx, cz, w, d, h)  — centre X/Z, width, depth, height
# Target building at (-15, -20) — 4 floors, 12 m tall
# Obstacle at (-7, -10) — solid block on the direct route from base (0,0,0) to target
_RAW_BUILDINGS: list[tuple[float, float, float, float, float]] = [
    (-15, -20, 8, 8, 12),   # target building
    ( -7, -10, 6, 5, 10),   # obstacle on direct route (0,0,0) → (-15,0,-20)
]

# Survivor positions: (x, y, z) — inside target building, floors 2/3/4
# survY(n) = (n-1)*3.0 + 0.65
_RAW_SURVIVORS: list[tuple[float, float, float]] = [
    (-16.5, 3.65, -19.0),   # floor 2
    (-14.5, 6.65, -20.5),   # floor 3
    (-13.5, 9.65, -21.0),   # floor 4
]

_RAW_TREES: list[tuple[float, float]] = []


# ── Dataclasses ───────────────────────────────────────────────────────────────

class Vec3(NamedTuple):
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class Building:
    id: int
    cx: float   # centre X
    cz: float   # centre Z (depth axis)
    w: float    # width  (X extent)
    d: float    # depth  (Z extent)
    h: float    # height (Y extent)

    # AABB min/max corners
    @property
    def min_x(self) -> float: return self.cx - self.w / 2
    @property
    def max_x(self) -> float: return self.cx + self.w / 2
    @property
    def min_z(self) -> float: return self.cz - self.d / 2
    @property
    def max_z(self) -> float: return self.cz + self.d / 2
    @property
    def min_y(self) -> float: return 0.0
    @property
    def max_y(self) -> float: return self.h

    def contains_point(self, x: float, y: float, z: float) -> bool:
        """True if (x,y,z) is strictly inside this building's AABB."""
        return (
            self.min_x <= x <= self.max_x and
            self.min_y <= y <= self.max_y and
            self.min_z <= z <= self.max_z
        )

    def distance_xz(self, x: float, z: float) -> float:
        """2D distance from point to building edge (0 if inside)."""
        dx = max(self.min_x - x, 0.0, x - self.max_x)
        dz = max(self.min_z - z, 0.0, z - self.max_z)
        return math.sqrt(dx * dx + dz * dz)

    def distance_3d(self, x: float, y: float, z: float) -> float:
        """3D distance from point to nearest surface of building AABB."""
        dx = max(self.min_x - x, 0.0, x - self.max_x)
        dy = max(self.min_y - y, 0.0, y - self.max_y)
        dz = max(self.min_z - z, 0.0, z - self.max_z)
        return math.sqrt(dx*dx + dy*dy + dz*dz)


@dataclass(frozen=True)
class Survivor:
    id: int
    x: float
    y: float
    z: float

    @property
    def submerged(self) -> bool:
        return self.y < FLOOD_LEVEL - 0.2

    def distance_to(self, x: float, y: float, z: float) -> float:
        return math.sqrt((self.x-x)**2 + (self.y-y)**2 + (self.z-z)**2)


@dataclass(frozen=True)
class Tree:
    id: int
    x: float
    z: float


# ── World Model singleton ─────────────────────────────────────────────────────

@dataclass
class WorldModel:
    buildings: list[Building] = field(default_factory=list)
    survivors: list[Survivor] = field(default_factory=list)
    trees: list[Tree] = field(default_factory=list)

    def buildings_near(self, x: float, z: float, radius: float) -> list[Building]:
        """All buildings whose edge is within `radius` metres (XZ plane)."""
        return [b for b in self.buildings if b.distance_xz(x, z) <= radius]

    def survivors_near(
        self, x: float, y: float, z: float, radius: float
    ) -> list[Survivor]:
        """All survivors within `radius` metres (3D distance)."""
        return [s for s in self.survivors if s.distance_to(x, y, z) <= radius]

    def is_flooded(self, y: float) -> bool:
        """True if the given Y position is below or at flood level."""
        return y <= FLOOD_LEVEL

    def building_near_xz(
        self, x: float, z: float, margin: float = BUILDING_PROXIMITY_MARGIN_M,
    ) -> Building | None:
        """Return the closest building whose XZ edge is within `margin` metres."""
        candidates = self.buildings_near(x, z, margin)
        if not candidates:
            return None
        return min(candidates, key=lambda b: b.distance_xz(x, z))

    def building_at(self, x: float, y: float, z: float) -> Building | None:
        """Return the building that contains this point, or None."""
        for b in self.buildings:
            if b.contains_point(x, y, z):
                return b
        return None

    def obstacles_in_path(
        self,
        fx: float, fy: float, fz: float,
        tx: float, ty: float, tz: float,
        samples: int = 20,
    ) -> list[Building]:
        """
        Return any buildings whose AABB is intersected by the line segment
        from (fx,fy,fz) → (tx,ty,tz), sampled at `samples` points.
        """
        blocked: list[Building] = []
        blocked_set: set[Building] = set()
        for i in range(1, samples + 1):
            t = i / samples
            sx = fx + (tx - fx) * t
            sy = fy + (ty - fy) * t
            sz = fz + (tz - fz) * t
            for b in self.buildings:
                if b not in blocked_set and b.contains_point(sx, sy, sz):
                    blocked_set.add(b)
                    blocked.append(b)
        return blocked


def _build_world() -> WorldModel:
    buildings = [
        Building(id=i, cx=cx, cz=cz, w=w, d=d, h=h)
        for i, (cx, cz, w, d, h) in enumerate(_RAW_BUILDINGS)
    ]
    survivors = [
        Survivor(id=i, x=x, y=y, z=z)
        for i, (x, y, z) in enumerate(_RAW_SURVIVORS)
    ]
    trees = [
        Tree(id=i, x=x, z=z)
        for i, (x, z) in enumerate(_RAW_TREES)
    ]
    return WorldModel(buildings=buildings, survivors=survivors, trees=trees)


# Module-level singleton — import this everywhere
WORLD: WorldModel = _build_world()
