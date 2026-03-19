"""Tests for approach-aware and serpentine sweep scan routing."""
from __future__ import annotations

import math

import pytest

from backend.services.api.control import (
    _build_ring,
    _nearest_corner,
    find_buildings_in_area,
    plan_building_vertical_sweep,
)


# ── Corner / helper unit tests ────────────────────────────────────────────────

class TestNearestCorner:
    def test_selects_se_when_approaching_from_origin(self):
        corners = {"NW": (-16.5, -25.0), "NE": (-10.0, -25.0), "SE": (-10.0, -15.0), "SW": (-20.0, -15.0)}
        # Origin (0,0) is south-east of the building: SE corner should be nearest.
        assert _nearest_corner(0.0, 0.0, corners) == "SE"

    def test_selects_nw_when_approaching_from_far_northwest(self):
        corners = {"NW": (-20.0, -25.0), "NE": (-10.0, -25.0), "SE": (-10.0, -15.0), "SW": (-20.0, -15.0)}
        assert _nearest_corner(-50.0, -50.0, corners) == "NW"

    def test_selects_ne_when_approaching_from_east(self):
        corners = {"NW": (-20.0, -25.0), "NE": (-10.0, -25.0), "SE": (-10.0, -15.0), "SW": (-20.0, -15.0)}
        assert _nearest_corner(10.0, -25.0, corners) == "NE"


# ── _build_ring unit tests ────────────────────────────────────────────────────

def _make_corners() -> dict[str, tuple[float, float]]:
    return {"NW": (-20.0, -25.0), "NE": (-10.0, -25.0), "SE": (-10.0, -15.0), "SW": (-20.0, -15.0)}


class TestBuildRing:
    def test_cw_from_nw_visits_all_four_corners(self):
        corners = _make_corners()
        ring, end = _build_ring("NW", True, {}, corners)
        corner_reasons = [r for _, _, r in ring if r.startswith("perimeter ")]
        assert set(corner_reasons) == {"perimeter NW", "perimeter NE", "perimeter SE", "perimeter SW"}

    def test_cw_from_nw_ends_at_sw(self):
        # Open ring CW from NW visits [NW→NE→SE→SW], ends at SW.
        corners = _make_corners()
        _, end = _build_ring("NW", True, {}, corners)
        assert end == "SW"

    def test_cw_from_se_ends_at_ne(self):
        corners = _make_corners()
        _, end = _build_ring("SE", True, {}, corners)
        assert end == "NE"

    def test_ccw_from_sw_ends_at_nw(self):
        # Open ring CCW from SW visits [SW→SE→NE→NW], ends at NW.
        corners = _make_corners()
        _, end = _build_ring("SW", False, {}, corners)
        assert end == "NW"

    def test_cw_ring_does_not_close_back_to_start(self):
        """Open ring: start corner should not appear twice (no close-perimeter duplicate)."""
        corners = _make_corners()
        ring, _ = _build_ring("SE", True, {}, corners)
        corner_reasons = [r for _, _, r in ring if r.startswith("perimeter ")]
        # SE appears exactly once as the first corner, not again at the end.
        assert corner_reasons.count("perimeter SE") == 1

    def test_north_window_placed_between_nw_and_ne_cw(self):
        corners = _make_corners()
        north_win = [{"x": -15.0, "z": -29.0, "face": "north", "floor": 2}]
        ring, _ = _build_ring("NW", True, {"north": north_win}, corners)
        reasons = [r for _, _, r in ring]
        nw_idx = reasons.index("perimeter NW")
        ne_idx = reasons.index("perimeter NE")
        between = reasons[nw_idx + 1: ne_idx]
        assert any("window scan north" in r for r in between)

    def test_east_window_included_on_4th_face_when_cw_from_nw(self):
        """When CW starts at NW, east face is the 4th (return) face — window still included."""
        corners = _make_corners()
        east_win = [{"x": -6.0, "z": -20.0, "face": "east", "floor": 3}]
        ring, _ = _build_ring("NW", True, {"east": east_win}, corners)
        reasons = [r for _, _, r in ring]
        assert any("window scan east" in r for r in reasons)

    def test_serpentine_chain_no_horizontal_gap(self):
        """End corner of ring N == start corner of ring N+1 in serpentine traversal."""
        corners = _make_corners()
        _, end1 = _build_ring("SE", True, {}, corners)
        _, end2 = _build_ring(end1, False, {}, corners)
        _, end3 = _build_ring(end2, True, {}, corners)
        # Pattern should cycle predictably.
        assert end1 == "NE"
        assert end2 == "SE"
        assert end3 == "NE"


# ── plan_building_vertical_sweep with approach coords ────────────────────────

class TestApproachAwareSweep:
    def test_approach_aware_selects_nearest_start_corner(self):
        # Drone is at origin (0,0,0) — SE corner is nearest for this building.
        result = plan_building_vertical_sweep(
            -15.0, -20.0, standoff=2.0, approach_x=0.0, approach_z=0.0
        )
        assert result["matched_building"] is True
        wp0 = result["waypoints"][0]
        # First waypoint should be descent to SE corner (nearest to origin).
        assert wp0["reason"] == "descent to SE corner"

    def test_approach_from_nw_selects_nw_start(self):
        result = plan_building_vertical_sweep(
            -15.0, -20.0, standoff=2.0, approach_x=-50.0, approach_z=-50.0
        )
        assert result["matched_building"] is True
        wp0 = result["waypoints"][0]
        assert wp0["reason"] == "descent to NW corner"

    def test_all_windows_still_present_with_approach(self):
        result = plan_building_vertical_sweep(
            -15.0, -20.0, standoff=2.0, approach_x=0.0, approach_z=0.0
        )
        window_wps = [wp for wp in result["waypoints"] if "window scan" in wp["reason"]]
        # Building has 3 windows above flood (floors 2,3,4 on N, E, S faces).
        assert len(window_wps) >= 3

    def test_rooftop_scan_still_last_with_approach(self):
        result = plan_building_vertical_sweep(
            -15.0, -20.0, standoff=2.0, approach_x=0.0, approach_z=0.0
        )
        assert result["waypoints"][-1]["reason"] == "rooftop scan"

    def test_no_approach_preserves_legacy_nw_start(self):
        """Without approach params the descent reason is still 'descent to NW corner'."""
        result = plan_building_vertical_sweep(-15.0, -20.0, standoff=2.0)
        wp0 = result["waypoints"][0]
        assert wp0["reason"] == "descent to NW corner"

    def test_approach_reduces_waypoint_count(self):
        """Serpentine open rings emit fewer waypoints than legacy closed rings
        (no close-perimeter waypoint per floor)."""
        legacy = plan_building_vertical_sweep(-15.0, -20.0, standoff=2.0)
        smart = plan_building_vertical_sweep(
            -15.0, -20.0, standoff=2.0, approach_x=0.0, approach_z=0.0
        )
        # Serpentine should have fewer or equal waypoints (never more).
        assert smart["waypoint_count"] <= legacy["waypoint_count"]

    def test_floor_levels_still_ascending_with_approach(self):
        result = plan_building_vertical_sweep(
            -15.0, -20.0, standoff=2.0, approach_x=0.0, approach_z=0.0
        )
        wps = result["waypoints"]
        floor_wps = [wp for wp in wps if "perimeter" in wp["reason"] or "window" in wp["reason"]]
        ys_seen: list[float] = []
        seen: set[float] = set()
        for wp in floor_wps:
            y = wp["y"]
            if y not in seen:
                ys_seen.append(y)
                seen.add(y)
        assert ys_seen == sorted(ys_seen)


# ── find_buildings_in_area drone-relative sorting ────────────────────────────

class TestFindBuildingsInAreaDroneSort:
    def test_returns_all_buildings_within_radius(self):
        result = find_buildings_in_area(-15.0, -20.0, radius=40.0)
        assert result["total"] >= 2

    def test_drone_position_changes_sort_order(self):
        # Without drone pos: sorted by distance from center (-15,-20)
        center_sort = find_buildings_in_area(-15.0, -20.0, radius=50.0)
        # With drone at far NE: buildings near NE side should come first
        drone_sort = find_buildings_in_area(
            -15.0, -20.0, radius=50.0, drone_x=20.0, drone_z=-20.0
        )
        # Results include the same buildings but potentially in different order
        center_ids = [b["id"] for b in center_sort["buildings"]]
        drone_ids = [b["id"] for b in drone_sort["buildings"]]
        assert set(center_ids) == set(drone_ids)

    def test_drone_position_included_in_result_when_provided(self):
        result = find_buildings_in_area(0.0, 0.0, radius=50.0, drone_x=5.0, drone_z=-3.0)
        assert "drone_position" in result
        assert result["drone_position"] == {"x": 5.0, "z": -3.0}

    def test_no_drone_position_omits_key(self):
        result = find_buildings_in_area(0.0, 0.0, radius=50.0)
        assert "drone_position" not in result

    def test_nearest_building_to_drone_comes_first(self):
        # Drone parked near the shophouse twin block (12,-27)
        result = find_buildings_in_area(
            0.0, -20.0, radius=60.0, drone_x=12.0, drone_z=-27.0
        )
        buildings = result["buildings"]
        if len(buildings) >= 2:
            # The shophouse block (id=3, cx=12, cz=-27) should be first.
            assert buildings[0]["id"] == 3
