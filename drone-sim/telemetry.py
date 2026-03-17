from __future__ import annotations

import json
import math
import os
import socket
import threading
import time

from sim import DroneSimulator
from world import get_view, building_center_near

UDP_PORT = int(os.environ.get("TELEMETRY_PORT", "5005"))
# Docker Desktop on Windows/macOS is unreliable for UDP broadcast from
# containers to the host. Prefer an explicit host target when available.
TELEMETRY_HOST = os.environ.get(
    "TELEMETRY_HOST",
    os.environ.get("BROADCAST_HOST", "255.255.255.255"),
)
INTERVAL = 0.1  # seconds between heartbeats (match sim tick rate)


def _heading_toward(pos, target) -> float:
    """Return heading in degrees (0=North/-Z, 90=East/+X) from pos toward target."""
    dx = target.x - pos.x
    dz = target.z - pos.z
    if abs(dx) < 1e-6 and abs(dz) < 1e-6:
        return 0.0
    return math.degrees(math.atan2(dx, -dz)) % 360


def _heading_toward_xz(from_x: float, from_z: float, to_x: float, to_z: float) -> float:
    """Return heading in degrees (0=North/-Z, 90=East/+X)."""
    dx = to_x - from_x
    dz = to_z - from_z
    if abs(dx) < 1e-6 and abs(dz) < 1e-6:
        return 0.0
    return math.degrees(math.atan2(dx, -dz)) % 360


def _scan_tilt_deg(drone_y: float, building_height: float) -> float:
    """
    Return camera tilt in degrees (0=horizontal, -90=straight down).
    Tilts downward when the drone is at or above the building rooftop.
    """
    if building_height <= 0:
        return 0.0
    # Fraction of how far above the building the drone is.
    # At rooftop level (drone_y ~= building_height + standoff) → -90°.
    # At mid-building height → 0°.
    above = drone_y - building_height
    if above <= 0:
        return 0.0
    # Smooth transition: 0° at roof, -90° at 3m above
    tilt = max(-90.0, -90.0 * min(1.0, above / 3.0))
    return round(tilt, 1)


def _broadcast_loop(simulator: DroneSimulator) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if TELEMETRY_HOST.endswith(".255") or TELEMETRY_HOST == "255.255.255.255":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    while True:
        s = simulator.get_snapshot()
        scan_center = simulator.get_scan_center()
        view = get_view(s.position.x, s.position.y, s.position.z)

        # Heading: when scanning, face the nearest building's center (not the
        # scan waypoint), so the FOV cone always points into the building.
        # For the rooftop phase the cone tilts downward via scan_tilt_deg.
        if scan_center is not None:
            bld = building_center_near(scan_center.x, scan_center.z)
            if bld is not None:
                heading_target_x, heading_target_z = bld.cx, bld.cz
                scan_tilt = _scan_tilt_deg(s.position.y, bld.h)
            else:
                heading_target_x, heading_target_z = scan_center.x, scan_center.z
                scan_tilt = 0.0
        else:
            heading_target_x, heading_target_z = s.target.x, s.target.z
            scan_tilt = 0.0

        heading = round(_heading_toward_xz(
            s.position.x, s.position.z,
            heading_target_x, heading_target_z,
        ), 1)

        payload = json.dumps({
            "asset_id": s.asset_id,
            "x": round(s.position.x, 3),
            "y": round(s.position.y, 3),
            "z": round(s.position.z, 3),
            "battery": round(s.battery, 2),
            "status": s.status.value,
            "timestamp_ms": int(time.time() * 1000),
            # Lightweight awareness fields
            "nearby_obstacles": view["nearby_obstacles"],
            "nearest_obstacle_dist": view["nearest_obstacle_dist"],
            "survivors_in_range": view["survivors_in_range"],
            "over_flood": view["over_flood"],
            "altitude_agl": view["altitude_agl"],
            "heading_deg": heading,
            "scan_tilt_deg": scan_tilt,
        }).encode()

        try:
            sock.sendto(payload, (TELEMETRY_HOST, UDP_PORT))
        except OSError as exc:
            print(f"[telemetry] broadcast error: {exc}")

        time.sleep(INTERVAL)


def start_telemetry(simulator: DroneSimulator) -> threading.Thread:
    t = threading.Thread(target=_broadcast_loop, args=(simulator,), daemon=True)
    t.start()
    print(f"[telemetry] broadcasting to {TELEMETRY_HOST}:{UDP_PORT}")
    return t
