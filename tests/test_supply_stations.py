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
    def test_list_defaults_to_empty(self):
        # Home is NOT a supply station; the registry starts empty.
        assert supply_stations.list_stations() == []

    def test_add_station_returns_record_with_unique_id(self):
        a = supply_stations.add_station(x=20.0, z=5.0)
        b = supply_stations.add_station(x=-10.0, z=-30.0)
        assert a["x"] == 20.0 and a["z"] == 5.0
        assert b["x"] == -10.0 and b["z"] == -30.0
        assert a["id"] != b["id"]

    def test_list_returns_user_stations_in_insertion_order(self):
        a = supply_stations.add_station(x=20.0, z=5.0)
        b = supply_stations.add_station(x=-10.0, z=-30.0)
        ids = [s["id"] for s in supply_stations.list_stations()]
        assert ids == [a["id"], b["id"]]

    def test_remove_station_returns_true_when_found(self):
        a = supply_stations.add_station(x=20.0, z=5.0)
        assert supply_stations.remove_station(a["id"]) is True
        assert supply_stations.list_stations() == []

    def test_remove_station_returns_false_when_unknown(self):
        assert supply_stations.remove_station("does-not-exist") is False

    def test_remove_home_id_returns_false(self):
        # Home is not in the registry at all; DELETE falls through to 'not found'.
        assert supply_stations.remove_station("home") is False


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
        # Default half_span (from WorldModel) is 50.0. Anything strictly outside rejects.
        with pytest.raises(ValueError, match="out of bounds"):
            supply_stations.add_station(x=100.0, z=0.0)
        with pytest.raises(ValueError, match="out of bounds"):
            supply_stations.add_station(x=0.0, z=-100.0)

    def test_add_beyond_station_limit_raises(self, monkeypatch):
        """Registry caps user-placed stations at MAX_USER_STATIONS."""
        monkeypatch.setattr(supply_stations, "MAX_USER_STATIONS", 2)
        supply_stations.add_station(x=1.0, z=1.0)
        supply_stations.add_station(x=2.0, z=2.0)
        with pytest.raises(supply_stations.StationLimitReached, match="limit"):
            supply_stations.add_station(x=3.0, z=3.0)

    def test_add_bounds_respect_world_half_span(self, monkeypatch):
        """The registry pulls half_span from the active world, not a constant."""

        class _ShrunkenWorld:
            half_span = 10.0

            def building_at(self, x, y, z):
                return None

        monkeypatch.setattr(supply_stations, "_get_world", lambda: _ShrunkenWorld())
        # Still valid within the shrunken world.
        supply_stations.add_station(x=9.0, z=9.0)
        # Rejected because the smaller world bound applies even though 40 < 50.
        with pytest.raises(ValueError, match="out of bounds"):
            supply_stations.add_station(x=40.0, z=0.0)


class TestSelectBestStation:
    def test_returns_none_when_no_user_stations(self):
        # Home is no longer a fallback — dispatch must have stations placed.
        assert supply_stations.select_best_station(target_x=10.0, target_z=10.0) is None

    def test_picks_station_closest_to_target(self):
        near = supply_stations.add_station(x=30.0, z=30.0)
        supply_stations.add_station(x=-40.0, z=-40.0)
        chosen = supply_stations.select_best_station(target_x=28.0, target_z=29.0)
        assert chosen is not None
        assert chosen["id"] == near["id"]

    def test_single_station_wins_regardless_of_distance(self):
        """With home out of the pool, a lone station is always chosen —
        even if it's far from the target."""
        lone = supply_stations.add_station(x=40.0, z=40.0)
        chosen = supply_stations.select_best_station(target_x=1.0, target_z=1.0)
        assert chosen is not None
        assert chosen["id"] == lone["id"]

    def test_deterministic_tiebreak_on_equal_distance(self):
        """Two stations equidistant from the target: insertion order wins."""
        a = supply_stations.add_station(x=10.0, z=0.0)
        supply_stations.add_station(x=-10.0, z=0.0)
        first = supply_stations.select_best_station(target_x=0.0, target_z=0.0)
        second = supply_stations.select_best_station(target_x=0.0, target_z=0.0)
        assert first is not None and second is not None
        assert first["id"] == a["id"]  # first-inserted wins
        assert first["id"] == second["id"]  # stable across calls
