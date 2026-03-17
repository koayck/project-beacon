"""
World model — loaded from shared/world.json.
Single source of truth for building AABBs, survivor positions,
window apertures, trees, parks, and flood level used by the vision system and
collision avoidance.
"""
from __future__ import annotations

import json as _json
import math
import pathlib as _pathlib
from dataclasses import dataclass, field
from typing import Literal, NamedTuple

# ── Load shared/world.json once at import time ────────────────────────────────
_WORLD_JSON = _json.loads(
    (_pathlib.Path(__file__).parents[2] / "shared" / "world.json").read_text()
)
_S = _WORLD_JSON["scene"]

FLOOD_LEVEL: float                 = _S["flood_level_m"]
BUILDING_PROXIMITY_MARGIN_M: float = _S["building_proximity_margin_m"]
FLOOR_HEIGHT_M: float              = _S["floor_height_m"]
FLOOR_SLAB_THICKNESS_M: float      = _S["floor_slab_thickness_m"]
WINDOW_SCAN_STANDOFF_M: float      = _S["window_scan_standoff_m"]


# ── Dataclasses ───────────────────────────────────────────────────────────────

class Vec3(NamedTuple):
    x: float
    y: float
    z: float


WindowFace = Literal["north", "south", "west", "east"]


@dataclass(frozen=True)
class WindowAperture:
    """
    Vertical rectangular aperture on one building facade.

    For north/south windows, `axis_center` is an X coordinate.
    For west/east windows, `axis_center` is a Z coordinate.
    """
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
class Building:
    id: int
    cx: float   # centre X
    cz: float   # centre Z (depth axis)
    w: float    # width  (X extent)
    d: float    # depth  (Z extent)
    h: float    # height (Y extent)
    windows: tuple[WindowAperture, ...] = ()

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

    def _segment_intersects_window(
        self,
        window: WindowAperture,
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
        """True if segment from source to target crosses any facade window aperture."""
        return any(
            self._segment_intersects_window(window, from_x, from_y, from_z, to_x, to_y, to_z)
            for window in self.windows
        )

    def contains_floor_slab_point(
        self,
        x: float,
        y: float,
        z: float,
        floor_height: float = FLOOR_HEIGHT_M,
        slab_thickness: float = FLOOR_SLAB_THICKNESS_M,
        epsilon: float = 1e-6,
    ) -> bool:
        """True when point lies inside any horizontal slab volume for this building."""
        if not self.contains_point(x, y, z):
            return False

        half = slab_thickness / 2
        level = self.min_y
        while level <= self.max_y + epsilon:
            if level - half - epsilon <= y <= level + half + epsilon:
                return True
            level += floor_height

        # Ensure roof slab exists even when height is not an exact floor multiple.
        return self.max_y - half - epsilon <= y <= self.max_y + half + epsilon

    def window_scan_waypoints(self, standoff: float = WINDOW_SCAN_STANDOFF_M) -> list[dict]:
        """
        Return external waypoints centered in front of each window aperture.

        Waypoints are outside the facade by `standoff` metres and at the
        vertical center of each window to maximize direct indoor visibility.
        """
        waypoints: list[dict] = []
        for window in self.windows:
            y = window.sill_y + window.height / 2
            floor = int(window.sill_y // FLOOR_HEIGHT_M) + 1
            if window.face == "north":
                x = window.axis_center
                z = self.min_z - standoff
            elif window.face == "south":
                x = window.axis_center
                z = self.max_z + standoff
            elif window.face == "west":
                x = self.min_x - standoff
                z = window.axis_center
            else:
                x = self.max_x + standoff
                z = window.axis_center

            waypoints.append(
                {
                    "x": round(x, 2),
                    "y": round(y, 2),
                    "z": round(z, 2),
                    "face": window.face,
                    "floor": floor,
                }
            )
        return waypoints


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
        margin: float = 0.0,
    ) -> list[Building]:
        """
        Return any buildings whose AABB is intersected by the line segment
        from (fx,fy,fz) → (tx,ty,tz), sampled at `samples` points.

        When *margin* > 0 each building's AABB is inflated by that amount
        on all sides (XZ) and top (Y) before the containment check, catching
        paths that graze within *margin* metres of a building surface.
        """
        blocked: list[Building] = []
        blocked_set: set[Building] = set()
        for i in range(1, samples + 1):
            t = i / samples
            sx = fx + (tx - fx) * t
            sy = fy + (ty - fy) * t
            sz = fz + (tz - fz) * t
            for b in self.buildings:
                if b in blocked_set:
                    continue
                if margin > 0.0:
                    inside = (
                        b.min_x - margin <= sx <= b.max_x + margin
                        and b.min_y <= sy <= b.max_y + margin
                        and b.min_z - margin <= sz <= b.max_z + margin
                    )
                else:
                    inside = b.contains_point(sx, sy, sz)
                if inside:
                    blocked_set.add(b)
                    blocked.append(b)
        return blocked


def _build_world() -> WorldModel:
    buildings: list[Building] = []
    for b in _WORLD_JSON["buildings"]:
        cx, cz = float(b["cx"]), float(b["cz"])
        windows: list[WindowAperture] = []
        for w in b["windows"]:
            face: WindowFace = w["face"]
            sill_y = (w["floor"] - 1) * FLOOR_HEIGHT_M + w["sill"]
            axis_center = cx + w["offset"] if face in ("north", "south") else cz + w["offset"]
            windows.append(WindowAperture(
                face=face,
                axis_center=axis_center,
                sill_y=sill_y,
                width=w["width"],
                height=w["height"],
            ))
        buildings.append(Building(
            id=b["id"],
            cx=cx, cz=cz,
            w=float(b["w"]), d=float(b["d"]), h=float(b["h"]),
            windows=tuple(windows),
        ))

    survivors = [
        Survivor(id=i, x=float(s["x"]), y=float(s["y"]), z=float(s["z"]))
        for i, s in enumerate(_WORLD_JSON["survivors"])
    ]
    trees = [
        Tree(id=i, x=float(t["x"]), z=float(t["z"]))
        for i, t in enumerate(_WORLD_JSON.get("trees", []))
    ]
    return WorldModel(buildings=buildings, survivors=survivors, trees=trees)


# Module-level singleton — import this everywhere
WORLD: WorldModel = _build_world()
