"""Tests that sweep plan starts window-first with perimeter rings + windows."""
from __future__ import annotations

from backend.services.api.control import plan_building_vertical_sweep
from backend.world.vision import get_view as backend_get_view


class TestSweepPlanWindowAndRooftop:
    def test_window_first_waypoint_is_first(self):
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        assert result["matched_building"] is True
        wp0 = result["waypoints"][0]
        assert wp0["reason"].startswith("window scan")
        rooftop = result["rooftop_position"]
        assert wp0["y"] < rooftop["y"]

    def test_sweep_ends_at_last_floor_not_rooftop(self):
        """Rooftop scan was removed — sweep ends at the last floor's perimeter."""
        result = plan_building_vertical_sweep(-15.0, -20.0, level_step=3.0, standoff=2.0)
        last_wp = result["waypoints"][-1]
        assert last_wp["reason"] != "rooftop scan", (
            f"expected sweep to end on a floor waypoint, not 'rooftop scan'; got: {last_wp}"
        )
        # Last waypoint should be at a floor level (below rooftop_y)
        rooftop_y = result["rooftop_position"]["y"]
        assert last_wp["y"] < rooftop_y, (
            f"expected last waypoint below rooftop y={rooftop_y}, got y={last_wp['y']}"
        )

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
        nw_indices = [i for i, r in enumerate(reasons) if r == "perimeter NW"]
        ne_indices = [i for i, r in enumerate(reasons) if r == "perimeter NE"]

        found_north_between = False
        for nw_idx in nw_indices:
            ne_after = [idx for idx in ne_indices if idx > nw_idx]
            if not ne_after:
                continue
            ne_idx = ne_after[0]
            between = reasons[nw_idx + 1:ne_idx]
            if any("window scan north" in r for r in between):
                found_north_between = True
                break

        assert found_north_between

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
