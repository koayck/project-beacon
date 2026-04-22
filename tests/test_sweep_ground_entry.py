"""Unit tests for plan_building_vertical_sweep ground-entry behavior.

After the ground-entry refactor, plan_building_vertical_sweep always iterates
floors ascending and enters at a lowest-floor window closest to the drone's
approach coordinates.
"""
from __future__ import annotations

import math

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
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        wp_levels = [w["level_y"] for w in non_transit if w["level_y"] < rooftop_y]
        assert wp_levels == sorted(wp_levels), f"waypoint level_y not ascending: {wp_levels}"

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
        # approach_x=-10 breaks the x=-13 / x=-17 window symmetry: x=-13 is
        # clearly closer to -10 than x=-17 is, so min() and first()[0] diverge
        # whenever the list starts with the x=-17 window.
        approach_x, approach_z = -10.0, -50.0
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=approach_x, approach_z=approach_z,
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

        lowest_window_wps = [
            wp for wp in plan["waypoints"]
            if wp.get("level_y") == lowest_y
            and "window scan" in wp.get("reason", "")
        ]
        assert lowest_window_wps, "expected at least one lowest-floor window scan waypoint"
        min_dist = min(
            math.hypot(wp["x"] - approach_x, wp["z"] - approach_z)
            for wp in lowest_window_wps
        )
        first_dist = math.hypot(first["x"] - approach_x, first["z"] - approach_z)
        assert first_dist == min_dist, (
            f"entry window not nearest to approach: first_dist={first_dist}, min={min_dist}"
        )

    def test_entry_window_not_duplicated_in_ring(self):
        """Regression guard: the entry window must be filtered out of the
        first-floor ring so the drone does not double-visit it."""
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-10.0, approach_z=-5.0,
        )
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        assert non_transit, "expected at least one non-transit waypoint"
        entry = non_transit[0]
        entry_level = entry["level_y"]
        same_floor_matches = [
            w for w in non_transit
            if w["level_y"] == entry_level
            and abs(w["x"] - entry["x"]) < 0.01
            and abs(w["z"] - entry["z"]) < 0.01
        ]
        assert len(same_floor_matches) == 1, (
            f"entry window visited {len(same_floor_matches)} times on entry floor, expected 1: "
            f"matches={same_floor_matches}"
        )
