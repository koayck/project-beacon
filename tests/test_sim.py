"""Unit tests for the drone state machine."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "drone-sim"))

from sim import DroneSimulator, DroneStatus, Vec3


def test_initial_state():
    sim = DroneSimulator("TEST-01")
    s = sim.get_snapshot()
    assert s.asset_id == "TEST-01"
    assert s.position == Vec3(0.0, 0.0, 0.0)
    assert s.battery == 100.0
    assert s.status == DroneStatus.IDLE


def test_move_to_sets_moving_status():
    sim = DroneSimulator("TEST-01")
    sim.move_to(10.0, 5.0, 2.0)
    s = sim.get_snapshot()
    assert s.status == DroneStatus.MOVING
    assert s.target == Vec3(10.0, 5.0, 2.0)


def test_return_to_base_sets_returning():
    sim = DroneSimulator("TEST-01")
    sim.move_to(5.0, 5.0, 5.0)
    sim.return_to_base()
    s = sim.get_snapshot()
    assert s.status == DroneStatus.RETURNING
    assert s.target == Vec3(0.0, 0.0, 0.0)


def test_scan_area_sets_scanning():
    sim = DroneSimulator("TEST-01")
    sim.scan_area(3.0, 2.0, 1.0)
    s = sim.get_snapshot()
    assert s.status == DroneStatus.SCANNING
    assert s.target == Vec3(3.0, 2.0, 1.0)


def test_drone_moves_toward_target():
    sim = DroneSimulator("TEST-01")
    sim.move_to(100.0, 0.0, 0.0, speed=50.0)
    sim.start()
    time.sleep(0.3)  # 3 physics ticks at 0.1s each, speed=50 → ~15 units
    sim.stop()
    s = sim.get_snapshot()
    assert s.position.x > 0.0, "Drone should have moved toward target"


def test_drone_arrives_and_becomes_idle():
    sim = DroneSimulator("TEST-01")
    sim.move_to(0.1, 0.0, 0.0, speed=10.0)  # very close target
    sim.start()
    time.sleep(0.5)
    sim.stop()
    s = sim.get_snapshot()
    assert s.status == DroneStatus.IDLE


def test_battery_drains_while_moving():
    sim = DroneSimulator("TEST-01")
    sim.move_to(1000.0, 0.0, 0.0)
    sim.start()
    time.sleep(0.5)
    sim.stop()
    s = sim.get_snapshot()
    assert s.battery < 100.0


def test_vec3_distance():
    a = Vec3(0.0, 0.0, 0.0)
    b = Vec3(3.0, 4.0, 0.0)
    assert abs(a.distance_to(b) - 5.0) < 1e-6


def test_vec3_step_toward_arrives():
    a = Vec3(0.0, 0.0, 0.0)
    b = Vec3(1.0, 0.0, 0.0)
    result = a.step_toward(b, step=10.0)
    assert result == b  # large step arrives at target
