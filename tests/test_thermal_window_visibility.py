"""Thermal visibility tests: indoor survivors must be visible through windows only."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import backend.world.model as backend_world_model
from backend.world.vision import SURVIVOR_RANGE, get_view as backend_get_view


def _load_sim_world_module():
    sim_world_path = Path(__file__).resolve().parent.parent / "drone-sim" / "world.py"
    spec = importlib.util.spec_from_file_location("drone_sim_world_windows", sim_world_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load drone-sim/world.py for visibility parity tests.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SIM_WORLD = _load_sim_world_module()


def _backend_survivor_ids(x: float, y: float, z: float) -> list[int]:
    view = backend_get_view(x, y, z)
    return [s.id for s in view.survivors_visible]


def _sim_survivor_ids(x: float, y: float, z: float) -> list[int]:
    view = SIM_WORLD.get_view(x, y, z)
    return [obj["object_id"] for obj in view["objects"] if obj["object_type"] == "survivor"]


def test_backend_and_sim_use_same_survivor_range():
    assert SURVIVOR_RANGE == 12.0
    assert SIM_WORLD.SURVIVOR_RANGE == SURVIVOR_RANGE


def test_through_wall_is_not_detected():
    # East of target building, aligned to opaque wall segment away from floor-3 east window.
    x, y, z = -7.0, 6.65, -23.0
    backend_ids = _backend_survivor_ids(x, y, z)
    sim_ids = _sim_survivor_ids(x, y, z)
    assert backend_ids == []
    assert sim_ids == []


def test_through_window_is_detected():
    # East of target building, aligned to the floor-3 east facade window aperture.
    x, y, z = -7.0, 6.65, -20.5
    backend_ids = _backend_survivor_ids(x, y, z)
    sim_ids = _sim_survivor_ids(x, y, z)
    assert 1 in backend_ids
    assert 1 in sim_ids


def test_floor_slab_blocks_cross_floor_visibility():
    # Looking through the east facade from high altitude should not see lower-floor
    # survivors because intermediate floor slabs block the line of sight.
    x, y, z = -7.0, 10.0, -20.5
    backend_ids = _backend_survivor_ids(x, y, z)
    sim_ids = _sim_survivor_ids(x, y, z)
    assert backend_ids == []
    assert sim_ids == []


def test_inside_same_building_without_window_los_is_not_detected():
    # Strict LOS: being inside the same building does not bypass window gating.
    x, y, z = -15.0, 6.65, -20.0
    backend_ids = _backend_survivor_ids(x, y, z)
    sim_ids = _sim_survivor_ids(x, y, z)
    assert backend_ids == []
    assert sim_ids == []


def test_outdoor_survivor_range_requires_los_and_matches_sim():
    backend_extra = backend_world_model.Survivor(id=999, x=-10.5, y=5.0, z=-10.0)
    sim_extra = SIM_WORLD.SimSurvivor(id=999, x=-10.5, y=5.0, z=-10.0)
    backend_world_model.WORLD.survivors.append(backend_extra)
    SIM_WORLD.SURVIVORS.append(sim_extra)
    try:
        blocked_backend = _backend_survivor_ids(-2.0, 5.0, -2.0)   # obstacle building blocks LOS
        clear_backend = _backend_survivor_ids(-12.0, 5.0, -2.0)    # clear LOS, still in range
        blocked_sim = _sim_survivor_ids(-2.0, 5.0, -2.0)
        clear_sim = _sim_survivor_ids(-12.0, 5.0, -2.0)

        assert 999 not in blocked_backend
        assert 999 in clear_backend
        assert 999 not in blocked_sim
        assert 999 in clear_sim
        assert sorted(blocked_backend) == sorted(blocked_sim)
        assert sorted(clear_backend) == sorted(clear_sim)
    finally:
        backend_world_model.WORLD.survivors.pop()
        SIM_WORLD.SURVIVORS.pop()


@pytest.mark.parametrize(
    ("x", "y", "z"),
    [
        (-7.0, 6.65, -23.0),   # opaque east wall
        (-7.0, 6.65, -20.5),   # east window (floor 3)
        (-7.0, 10.0, -20.5),   # cross-floor line blocked by slab
        (-15.0, 6.65, -20.0),  # interior
        (-15.0, 12.0, -28.0),  # outside range / no LOS
    ],
)
def test_backend_and_sim_survivor_visibility_parity(x: float, y: float, z: float):
    assert sorted(_backend_survivor_ids(x, y, z)) == sorted(_sim_survivor_ids(x, y, z))
