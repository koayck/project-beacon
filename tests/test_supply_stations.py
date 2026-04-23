"""Unit tests for the supply station registry and nearest-to-target selector."""
from __future__ import annotations

import pytest

from backend.services import supply_stations


@pytest.fixture(autouse=True)
def _reset_registry():
    supply_stations.reset()
    yield
    supply_stations.reset()


class TestRegistry:
    def test_list_defaults_to_home_only(self):
        stations = supply_stations.list_stations()
        assert len(stations) == 1
        assert stations[0]["id"] == "home"
        assert stations[0]["x"] == 0.0
        assert stations[0]["z"] == 0.0

    def test_add_station_returns_record_with_unique_id(self):
        a = supply_stations.add_station(x=20.0, z=5.0)
        b = supply_stations.add_station(x=-10.0, z=-30.0)
        assert a["x"] == 20.0 and a["z"] == 5.0
        assert b["x"] == -10.0 and b["z"] == -30.0
        assert a["id"] != b["id"]
        assert a["id"] != "home" and b["id"] != "home"

    def test_list_returns_home_plus_added_in_insertion_order(self):
        a = supply_stations.add_station(x=20.0, z=5.0)
        b = supply_stations.add_station(x=-10.0, z=-30.0)
        ids = [s["id"] for s in supply_stations.list_stations()]
        assert ids == ["home", a["id"], b["id"]]

    def test_remove_station_returns_true_when_found(self):
        a = supply_stations.add_station(x=20.0, z=5.0)
        assert supply_stations.remove_station(a["id"]) is True
        assert [s["id"] for s in supply_stations.list_stations()] == ["home"]

    def test_remove_station_returns_false_when_unknown(self):
        assert supply_stations.remove_station("does-not-exist") is False

    def test_remove_home_raises(self):
        with pytest.raises(ValueError):
            supply_stations.remove_station("home")


class TestPlacementValidation:
    def test_add_inside_building_raises(self, monkeypatch):
        class _FakeBuilding:
            pass

        class _FakeWorld:
            def building_at(self, x, y, z):
                # Any (x,z) pair here is treated as inside a building.
                return _FakeBuilding()

        monkeypatch.setattr(supply_stations, "_get_world", lambda: _FakeWorld())
        with pytest.raises(ValueError, match="inside building"):
            supply_stations.add_station(x=-15.0, z=-15.0)

    def test_add_out_of_bounds_raises(self):
        # Default WORLD_HALF_SPAN is 50.0. Anything strictly outside rejects.
        with pytest.raises(ValueError, match="out of bounds"):
            supply_stations.add_station(x=100.0, z=0.0)
        with pytest.raises(ValueError, match="out of bounds"):
            supply_stations.add_station(x=0.0, z=-100.0)


class TestSelectBestStation:
    def test_returns_home_when_no_user_stations(self):
        chosen = supply_stations.select_best_station(target_x=10.0, target_z=10.0)
        assert chosen["id"] == "home"

    def test_picks_station_closest_to_target(self):
        near = supply_stations.add_station(x=30.0, z=30.0)
        supply_stations.add_station(x=-40.0, z=-40.0)
        chosen = supply_stations.select_best_station(target_x=28.0, target_z=29.0)
        assert chosen["id"] == near["id"]

    def test_home_wins_when_target_closer_to_origin(self):
        supply_stations.add_station(x=40.0, z=40.0)
        chosen = supply_stations.select_best_station(target_x=1.0, target_z=1.0)
        assert chosen["id"] == "home"

    def test_deterministic_tiebreak_on_equal_distance(self):
        # Two user stations equidistant from target. Whichever tie-breaking
        # rule we pick must be stable across calls.
        a = supply_stations.add_station(x=10.0, z=0.0)
        b = supply_stations.add_station(x=-10.0, z=0.0)
        first = supply_stations.select_best_station(target_x=0.0, target_z=0.0)
        second = supply_stations.select_best_station(target_x=0.0, target_z=0.0)
        # Home is also equidistant (0), and comes first in the list, so it wins.
        assert first["id"] == "home"
        assert first["id"] == second["id"]
        # Sanity: user stations are in the pool but not chosen here.
        ids = {s["id"] for s in supply_stations.list_stations()}
        assert {a["id"], b["id"]} <= ids
