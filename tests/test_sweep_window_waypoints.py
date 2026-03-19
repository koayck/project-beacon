"""Tests that sweep plan uses rooftop-first approach with perimeter rings + windows."""
from __future__ import annotations

from backend.services.api.control import plan_building_vertical_sweep
from backend.world.vision import get_view as backend_get_view


class TestSweepPlanWindowAndRooftop:
    def test_descent_waypoint_is_first(self):
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        assert result["matched_building"] is True
        wp0 = result["waypoints"][0]
        assert wp0["reason"] == "descent to NW corner"
        rooftop = result["rooftop_position"]
        assert wp0["y"] == rooftop["y"]

    def test_rooftop_scan_is_last_waypoint(self):
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        assert result["waypoints"][-1]["reason"] == "rooftop scan"
        assert result["waypoints"][-1]["y"] > result["building"]["height"]

    def test_window_waypoints_present_in_plan(self):
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        window_wps = [wp for wp in result["waypoints"] if "window scan" in wp["reason"]]
        assert len(window_wps) >= 3, (
            f"Expected at least 3 window waypoints (one per above-flood window), "
            f"got {len(window_wps)}: {window_wps}"
        )

    def test_window_waypoints_have_correct_faces(self):
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        window_wps = [wp for wp in result["waypoints"] if "window scan" in wp["reason"]]
        faces_found = {wp["reason"].split()[2] for wp in window_wps}
        assert "north" in faces_found
        assert "east" in faces_found
        assert "south" in faces_found

    def test_perimeter_corners_present_in_ring(self):
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        corner_wps = [wp for wp in result["waypoints"] if "perimeter" in wp["reason"]]
        assert len(corner_wps) > 0

    def test_floor_levels_ascending(self):
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        wps = result["waypoints"]
        # Skip descent waypoint, get floor ring waypoints (exclude rooftop)
        floor_wps = [wp for wp in wps if "perimeter" in wp["reason"] or "window" in wp["reason"]]
        floor_ys = []
        seen = set()
        for wp in floor_wps:
            y = wp["y"]
            if y not in seen:
                floor_ys.append(y)
                seen.add(y)
        assert floor_ys == sorted(floor_ys)

    def test_window_inserted_into_perimeter_ring(self):
        """Window waypoints should appear between perimeter corners, not after all corners."""
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        wps = result["waypoints"]
        reasons = [wp["reason"] for wp in wps]
        # Find the first NW → NE span (on any floor)
        nw_idx = next(i for i, r in enumerate(reasons) if r == "perimeter NW")
        ne_idx = next(i for i, r in enumerate(reasons[nw_idx:], start=nw_idx) if r == "perimeter NE")
        between = reasons[nw_idx + 1:ne_idx]
        # The north window should be between NW and NE on the floor that has it
        assert any("window scan north" in r for r in between)

    def test_rooftop_position_returned(self):
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        rooftop = result["rooftop_position"]
        assert "x" in rooftop and "y" in rooftop and "z" in rooftop
        assert rooftop["y"] > result["building"]["height"]


class TestSweepWindowWaypointsDetectSurvivors:
    def test_backend_vision_detects_survivors_from_window_waypoints(self):
        """Window waypoints should have line-of-sight to indoor survivors."""
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        window_wps = [wp for wp in result["waypoints"] if "window scan" in wp["reason"]]
        detected_ids: set[int] = set()
        for wp in window_wps:
            view = backend_get_view(wp["x"], wp["y"], wp["z"])
            for s in view.survivors_visible:
                detected_ids.add(s.id)
        assert len(detected_ids) == 3, (
            f"Expected all 3 unique survivors detected, got IDs {detected_ids}"
        )
