"""Unit tests for plan_building_vertical_sweep ground-entry behavior.

After the ground-entry refactor, plan_building_vertical_sweep always iterates
floors ascending and enters at a lowest-floor window closest to the drone's
approach coordinates.
"""
from __future__ import annotations

from backend.services.navigation.sweep_planner import plan_building_vertical_sweep


class TestGroundEntrySweep:
    def test_first_scanning_waypoint_is_on_lowest_floor(self):
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
        )
        assert plan["matched_building"] is True
        levels = plan["levels"]
        rooftop_y = plan["rooftop_position"]["y"]
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        assert non_transit, "expected at least one non-transit waypoint"
        first_level_y = non_transit[0]["level_y"]
        scanning_levels = [l for l in levels if l < rooftop_y]
        assert scanning_levels, "expected at least one scanning level"
        assert first_level_y == min(scanning_levels)

    def test_floors_iterate_ascending(self):
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
        )
        rooftop_y = plan["rooftop_position"]["y"]
        scanning_levels = [l for l in plan["levels"] if l < rooftop_y]
        assert scanning_levels == sorted(scanning_levels), (
            f"expected ascending floor order, got {scanning_levels}"
        )

    def test_sweep_still_ends_on_rooftop(self):
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
        )
        last_wp = plan["waypoints"][-1]
        assert last_wp["reason"] == "rooftop scan"
        assert last_wp["y"] == plan["rooftop_position"]["y"]

    def test_entry_window_is_closest_to_approach_on_lowest_floor(self):
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-50.0,
        )
        rooftop_y = plan["rooftop_position"]["y"]
        scanning_levels = [l for l in plan["levels"] if l < rooftop_y]
        lowest_y = min(scanning_levels)
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        first = non_transit[0]
        assert first["level_y"] == lowest_y
        assert "window scan" in first["reason"], (
            f"expected first waypoint to be a window scan, got {first['reason']}"
        )
