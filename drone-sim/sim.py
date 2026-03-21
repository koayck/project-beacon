from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from world import next_position_blocked, get_view


class DroneStatus(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    SCANNING = "SCANNING"
    RETURNING = "RETURNING"
    ERROR = "ERROR"
    BLOCKED = "BLOCKED"


class Vec3(NamedTuple):
    x: float
    y: float
    z: float

    def distance_to(self, other: Vec3) -> float:
        return math.sqrt(
            (self.x - other.x) ** 2
            + (self.y - other.y) ** 2
            + (self.z - other.z) ** 2
        )

    def step_toward(self, target: Vec3, step: float) -> Vec3:
        dist = self.distance_to(target)
        if dist <= step:
            return target
        ratio = step / dist
        return Vec3(
            self.x + (target.x - self.x) * ratio,
            self.y + (target.y - self.y) * ratio,
            self.z + (target.z - self.z) * ratio,
        )


@dataclass(frozen=True)
class DroneSnapshot:
    asset_id: str
    position: Vec3
    battery: float
    status: DroneStatus
    target: Vec3
    speed: float


class DroneSimulator:
    TICK_RATE = 0.1          # seconds per physics tick
    DRAIN_MOVING = 0.005     # battery % per tick when mobile
    DRAIN_IDLE = 0.0         # no drain while idle (preserves battery for missions)
    ARRIVAL_THRESHOLD = 0.05 # units — close enough to count as arrived
    DEFAULT_SPEED = 5.0      # units/sec

    BASE_Y = 0.0

    def __init__(self, asset_id: str, initial_battery: float = 100.0) -> None:
        origin = Vec3(0.0, self.BASE_Y, 0.0)
        self._snapshot = DroneSnapshot(
            asset_id=asset_id,
            position=origin,
            battery=float(initial_battery),
            status=DroneStatus.IDLE,
            target=origin,
            speed=self.DEFAULT_SPEED,
        )
        self._lock = threading.Lock()
        self._running = False
        self._scan_mode = False  # stays True for the entire sweep session
        self._scan_center: Vec3 = origin  # building center being scanned
        self._scan_building_height: float = 0.0  # used to detect rooftop scan

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._running = False

    def get_snapshot(self) -> DroneSnapshot:
        with self._lock:
            return self._snapshot

    def get_scan_center(self) -> Vec3 | None:
        """Return the current scan target (building center), or None if not scanning."""
        with self._lock:
            return self._scan_center if self._scan_mode else None

    def get_scan_building_height(self) -> float | None:
        """Return height of the building being scanned, or None if not scanning."""
        with self._lock:
            return self._scan_building_height if self._scan_mode else None

    def move_to(self, x: float, y: float, z: float, speed: float = 0.0) -> None:
        with self._lock:
            s = self._snapshot
            move_status = DroneStatus.SCANNING if self._scan_mode else DroneStatus.MOVING
            self._snapshot = DroneSnapshot(
                asset_id=s.asset_id,
                position=s.position,
                battery=s.battery,
                status=move_status,
                target=Vec3(x, y, z),
                speed=speed if speed > 0 else self.DEFAULT_SPEED,
            )

    def return_to_base(self) -> None:
        with self._lock:
            s = self._snapshot
            self._scan_mode = False
            self._snapshot = DroneSnapshot(
                asset_id=s.asset_id,
                position=s.position,
                battery=s.battery,
                status=DroneStatus.RETURNING,
                target=Vec3(0.0, self.BASE_Y, 0.0),
                speed=s.speed,
            )

    def scan_area(self, cx: float, cy: float, cz: float) -> None:
        with self._lock:
            s = self._snapshot
            self._scan_mode = True
            self._scan_center = Vec3(cx, cy, cz)
            self._snapshot = DroneSnapshot(
                asset_id=s.asset_id,
                position=s.position,
                battery=s.battery,
                status=DroneStatus.SCANNING,
                target=Vec3(cx, cy, cz),
                speed=s.speed,
            )

    def end_scan_mode(self) -> None:
        """Clear scan session and transition to IDLE."""
        with self._lock:
            s = self._snapshot
            self._scan_mode = False
            self._snapshot = DroneSnapshot(
                asset_id=s.asset_id,
                position=s.position,
                battery=s.battery,
                status=DroneStatus.IDLE,
                target=s.target,
                speed=s.speed,
            )

    # ── Physics ────────────────────────────────────────────────────────────

    def get_enriched_status(self) -> dict:
        """Drone state combined with world-model awareness fields.

        Keeps grpc_server.py as a pure transport adapter — it only needs to
        call this method rather than importing world.get_view() directly.
        """
        s = self.get_snapshot()
        view = get_view(s.position.x, s.position.y, s.position.z)
        return {
            "asset_id": s.asset_id,
            "x": s.position.x,
            "y": s.position.y,
            "z": s.position.z,
            "battery": s.battery,
            "status": s.status.value,
            "nearby_obstacles": view["nearby_obstacles"],
            "nearest_obstacle_dist": view["nearest_obstacle_dist"],
            "survivors_in_range": view["survivors_in_range"],
            "over_flood": view["over_flood"],
            "altitude_agl": view["altitude_agl"],
        }

    def get_view(
        self,
        heading_deg: float = 0.0,
        detection_range: float = 20.0,
        survivor_range: float | None = None,
    ) -> dict:
        """Full sensor view from the drone's current position.

        Keeps grpc_server.py as a pure transport adapter — it delegates view
        computation here rather than importing world.get_view() directly.
        """
        s = self.get_snapshot()
        return get_view(s.position.x, s.position.y, s.position.z,
                        heading_deg=heading_deg, detection_range=detection_range, survivor_range=survivor_range)

    def _loop(self) -> None:
        while self._running:
            with self._lock:
                self._snapshot = self._tick(self._snapshot)
            time.sleep(self.TICK_RATE)

    def _tick(self, s: DroneSnapshot) -> DroneSnapshot:
        if s.battery <= 0.0 and s.status in (
            DroneStatus.MOVING, DroneStatus.SCANNING, DroneStatus.RETURNING,
        ):
            # Battery depleted while in motion — force-land, but allow new
            # commands once battery is reset or if status is already IDLE.
            self._scan_mode = False
            return DroneSnapshot(
                asset_id=s.asset_id,
                position=s.position,
                battery=0.0,
                status=DroneStatus.ERROR,
                target=s.target,
                speed=s.speed,
            )

        mobile = s.status in (
            DroneStatus.MOVING,
            DroneStatus.RETURNING,
            DroneStatus.SCANNING,
        )

        if mobile:
            dist = s.position.distance_to(s.target)
            if dist <= self.ARRIVAL_THRESHOLD:
                # During a scan session stay SCANNING (hovering at waypoint)
                # instead of going IDLE so the FOV cone never flickers off.
                arrive_status = DroneStatus.SCANNING if self._scan_mode else DroneStatus.IDLE
                return DroneSnapshot(
                    asset_id=s.asset_id,
                    position=s.target,
                    battery=max(0.0, s.battery - self.DRAIN_MOVING),
                    status=arrive_status,
                    target=s.target,
                    speed=s.speed,
                )
            new_pos = s.position.step_toward(s.target, s.speed * self.TICK_RATE)

            # ── Collision check — stop before entering a building ─────────
            blocker = next_position_blocked(
                s.position.x, s.position.y, s.position.z,
                new_pos.x, new_pos.y, new_pos.z,
            )
            if blocker is not None:
                return DroneSnapshot(
                    asset_id=s.asset_id,
                    position=s.position,  # stay put
                    battery=max(0.0, s.battery - self.DRAIN_MOVING),
                    status=DroneStatus.BLOCKED,
                    target=s.target,
                    speed=s.speed,
                )

            return DroneSnapshot(
                asset_id=s.asset_id,
                position=new_pos,
                battery=max(0.0, s.battery - self.DRAIN_MOVING),
                status=s.status,
                target=s.target,
                speed=s.speed,
            )

        return DroneSnapshot(
            asset_id=s.asset_id,
            position=s.position,
            battery=max(0.0, s.battery - self.DRAIN_IDLE),
            status=s.status,
            target=s.target,
            speed=s.speed,
        )
