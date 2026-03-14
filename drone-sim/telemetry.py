from __future__ import annotations

import json
import os
import socket
import threading
import time

from sim import DroneSimulator
from world import get_view

UDP_PORT = int(os.environ.get("TELEMETRY_PORT", "5005"))
# Docker Desktop on Windows/macOS is unreliable for UDP broadcast from
# containers to the host. Prefer an explicit host target when available.
TELEMETRY_HOST = os.environ.get(
    "TELEMETRY_HOST",
    os.environ.get("BROADCAST_HOST", "255.255.255.255"),
)
INTERVAL = 1.0  # seconds between heartbeats


def _broadcast_loop(simulator: DroneSimulator) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if TELEMETRY_HOST.endswith(".255") or TELEMETRY_HOST == "255.255.255.255":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

    while True:
        s = simulator.get_snapshot()
        view = get_view(s.position.x, s.position.y, s.position.z)
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
