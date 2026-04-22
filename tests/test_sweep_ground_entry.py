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

    def test_sweep_emits_no_rooftop_waypoint(self):
        """Regression guard: the final rooftop scan waypoint was removed.

        After the ground-entry refactor, the sweep ends at the last floor's
        perimeter. No waypoint should have reason 'rooftop scan' or
        'ascent to rooftop altitude', and none should be a 'rooftop NW/NE/SE/SW scan'.
        """
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-10.0, approach_z=-5.0,
        )
        forbidden_reasons = {
            "rooftop scan",
            "ascent to rooftop altitude",
            "rooftop NW scan",
            "rooftop NE scan",
            "rooftop SE scan",
            "rooftop SW scan",
        }
        offenders = [
            w for w in plan["waypoints"]
            if w.get("reason") in forbidden_reasons
        ]
        assert not offenders, (
            f"expected no rooftop-scan waypoints, found: {offenders}"
        )

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

    def test_sweep_never_climbs_to_rooftop_altitude(self):
        """Regression guard: no waypoint should be forced up to rooftop altitude.

        The inter-floor transit used to climb to max(blocker+3, rooftop_y), which
        made the drone fly to roof height between floors and looked like a rooftop
        scan.  Fix 2 removed the ``max(..., rooftop_y)`` floor so detours only
        climb as high as the actual blocker requires (``blocker.max_y + 3``).

        Fix 2a restored the target building as an obstacle for *intra-floor* ring
        segments (e.g. south window → NW corner can cross the footprint).  Those
        detours legitimately climb to ``building_height + 3`` to clear the roof —
        that is NOT a rooftop cruise, just enough vertical clearance to cross once.
        The guard is therefore relaxed to ``<= building_height + 3.0``.

        The critical regression to prevent is climbs forced to rooftop altitude
        when the obstacle is only the building's own standoff zone (false positive).
        That is caught by the fact that the detour altitude matches ``max_y + 3``
        rather than the full rooftop sweep altitude.
        """
        plan = plan_building_vertical_sweep(
            target_x=20.0, target_z=25.0,  # building 3: h=18, multi-floor
            level_step=3.0, standoff=2.0,
            approach_x=0.0, approach_z=0.0,
        )
        assert plan["matched_building"] is True, "expected building 3 to match"
        building_height = plan["building"]["height"]
        for w in plan["waypoints"]:
            # Intra-floor detours that cross the building footprint climb to
            # building_height + 3.  Any climb beyond that indicates the old
            # rooftop-altitude forcing bug has returned.
            assert w["y"] <= building_height + 3.0, (
                f"waypoint altitude ({w['y']}) exceeds building_height+3 "
                f"({building_height + 3.0}), suggesting a rooftop-altitude "
                f"forcing regression: {w}"
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
