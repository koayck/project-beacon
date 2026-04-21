"""Unit tests for plan_building_vertical_sweep entry_floor parameter."""
from __future__ import annotations

from backend.services.navigation.sweep_planner import plan_building_vertical_sweep


class TestEntryFloor:
    def test_entry_floor_lowest_iterates_floors_ascending(self):
        """Default behavior: first floor-level waypoint is at the lowest level."""
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
            entry_floor="lowest",
        )
        assert plan["matched_building"] is True
        levels = plan["levels"]
        rooftop_y = plan["rooftop_position"]["y"]
        # The first non-transit waypoint should be at the lowest scanning level.
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        assert non_transit, "expected at least one non-transit waypoint"
        first_level_y = non_transit[0]["level_y"]
        scanning_levels = [l for l in levels if l < rooftop_y]
        assert scanning_levels, "expected at least one scanning level"
        assert first_level_y == min(scanning_levels)

    def test_entry_floor_highest_iterates_floors_descending(self):
        """With entry_floor='highest', first scanning waypoint is at the top floor."""
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
            entry_floor="highest",
        )
        assert plan["matched_building"] is True
        rooftop_y = plan["rooftop_position"]["y"]
        scanning_levels = [l for l in plan["levels"] if l < rooftop_y]
        assert scanning_levels, "expected at least one scanning level"
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        first_level_y = non_transit[0]["level_y"]
        assert first_level_y == max(scanning_levels)

    def test_entry_floor_highest_still_ends_on_rooftop(self):
        """Top-down sweep still ends on the rooftop waypoint."""
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
            entry_floor="highest",
        )
        last_wp = plan["waypoints"][-1]
        assert last_wp["reason"] == "rooftop scan"
        assert last_wp["y"] == plan["rooftop_position"]["y"]

    def test_entry_floor_default_matches_legacy(self):
        """Calling without entry_floor preserves existing behavior."""
        plan_legacy = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
        )
        plan_explicit = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
            entry_floor="lowest",
        )
        assert plan_legacy["waypoint_count"] == plan_explicit["waypoint_count"]
        assert plan_legacy["levels"] == plan_explicit["levels"]
