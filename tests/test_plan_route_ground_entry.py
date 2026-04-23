"""Unit tests for plan_route entry_mode='ground_entry'."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.tools.drone_commands import plan_route, set_client


@pytest.fixture(autouse=True)
def _mock_client():
    mock = AsyncMock()
    mock.get_status.return_value = {
        "asset_id": "BEACON-01",
        "x": 0.0, "y": 15.0, "z": 0.0,
        "battery": 80, "status": "IDLE",
    }
    mock.registered_asset_ids.return_value = ["BEACON-01"]
    set_client(mock)
    yield mock
    set_client(None)  # type: ignore[arg-type]


class TestEntryModeGroundEntry:
    """With entry_mode='ground_entry', selection restricts to the lowest floor
    and ranks candidates by horizontal (XZ) distance from the drone."""

    @pytest.mark.asyncio
    async def test_ground_entry_picks_lowest_floor_even_when_drone_is_high(self, _mock_client):
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -5.0, "y": 11.0, "z": -13.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        assert "target_resolution" in result
        tr = result["target_resolution"]
        assert tr.get("entry_mode") == "ground_entry"
        assert "selected_window_waypoint" in tr
        wp = tr["selected_window_waypoint"]
        assert wp["floor"] == 2

    @pytest.mark.asyncio
    async def test_ground_entry_picks_window_nearest_by_xz(self, _mock_client):
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -15.0, "y": 20.0, "z": -10.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        wp = tr["selected_window_waypoint"]
        assert wp["floor"] == 2
        assert wp["face"] == "south"

    @pytest.mark.asyncio
    async def test_ground_entry_ignores_y_distance(self, _mock_client):
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -6.0, "y": 50.0, "z": -20.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        assert tr["selected_window_waypoint"]["floor"] == 2

    @pytest.mark.asyncio
    async def test_ground_entry_excludes_middle_floors(self, _mock_client):
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -15.0, "y": 6.0, "z": -30.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        assert tr["selected_window_waypoint"]["floor"] == 2

    @pytest.mark.asyncio
    async def test_default_mode_preserves_legacy_behavior(self, _mock_client):
        result_default = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
        )
        result_explicit = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="nearest_floor",
        )
        assert result_default["to"] == result_explicit["to"]
        assert result_default.get("strategy") == result_explicit.get("strategy")

    @pytest.mark.asyncio
    async def test_ground_entry_falls_back_when_no_snap(self, _mock_client):
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=False,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        assert "selected_window_waypoint" not in tr

    @pytest.mark.asyncio
    async def test_ground_entry_prefers_xz_over_3d_distance(self, _mock_client, monkeypatch):
        """Regression guard: selection must rank by XZ distance, not 3D.

        East window (sill_y=0.0) and south window (sill_y=2.9) are both on floor 1.
        Because sill heights differ, the waypoints are at different Y elevations
        (east=0.8m, south=3.7m). With the drone at high altitude (y=50) directly
        above the east-face standoff point (x=59, z=50):

        - XZ distance: east=0, south≈12.7  → east wins under XZ
        - 3D distance: east≈49.2, south≈48.0 → south wins under 3D

        The test asserts east is chosen, which only holds when the distance
        function is XZ-only. Reverting to 3D would flip the result.

        The flood filter in route_planner would normally skip the east window
        (y=0.8 below the flood surface); this test disables it via a low
        flood level so the XZ-vs-3D ranking is the only discriminator.
        """
        from backend.services.core import context
        from backend.world.model import Building, WindowAperture

        monkeypatch.setattr(context, "get_flood_level", lambda: -10.0)

        two_face_building = Building(
            id=998,
            cx=50.0, cz=50.0,
            w=10.0, d=10.0, h=12.0,
            windows=(
                # East face: axis_center is a Z coordinate; sill_y=0.0 → waypoint y=0.8
                WindowAperture(face="east", axis_center=50.0, sill_y=0.0, width=2.0, height=1.6),
                # South face: axis_center is an X coordinate; sill_y=2.9 → waypoint y=3.7
                WindowAperture(face="south", axis_center=50.0, sill_y=2.9, width=2.0, height=1.6),
            ),
        )

        class _TwoFaceWorld:
            buildings = (two_face_building,)

            def building_near_xz(self, x, z, margin=2.0):
                return two_face_building

            def obstacles_in_path(self, *_args, **_kwargs):
                return []

            def buildings_near(self, *_args, **_kwargs):
                return [two_face_building]

        monkeypatch.setattr(context, "get_world", lambda: _TwoFaceWorld())

        # East standoff waypoint is at (max_x + 4, 0.8, 50) = (59, 0.8, 50).
        # South standoff waypoint is at (50, 3.7, max_z + 4) = (50, 3.7, 59).
        # Drone placed directly above the east standoff (x=59, z=50) at high altitude.
        # XZ dist: east=0, south≈12.73  → XZ selects east.
        # 3D dist: east≈49.2, south≈48.0 → 3D would select south (regression).
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": 59.0, "y": 50.0, "z": 50.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", 50.0, 50.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        wp = tr["selected_window_waypoint"]
        # Under XZ ranking: east face is selected (distance 0).
        # Under 3D ranking: south face would be selected (smaller 3D distance).
        assert wp["face"] == "east", (
            f"expected east face (XZ-nearest, dist=0), got {wp['face']!r}; "
            "this likely means the distance function reverted to 3D"
        )
        assert wp["floor"] == 1

    @pytest.mark.asyncio
    async def test_ground_entry_skips_unreachable_xz_nearest_when_cleaner_candidate_exists(
        self, _mock_client, monkeypatch
    ):
        """Regression: when the XZ-nearest candidate requires circumnavigating the
        target building through external obstacles, prefer a farther candidate with
        a clear path (human-pilot behavior).

        Drone at (0, 0, 0). Target building center (-25, 20).
          - East window at (-11, 4.2, 22.0): XZ dist ≈ 24.6 — BLOCKED by neighbor.
          - North window at (-28, 4.2, 8.5): XZ dist ≈ 29.3 — clear straight line.

        XZ-only ranking picks east (closer). The fix must detect that the straight
        line to east is blocked and fall through to north instead.
        """
        from backend.services.core import context
        from backend.world.model import Building, WindowAperture

        # The market-hall target building (id=2).
        # north face: min_z=12.5, standoff 4 → waypoint z=8.5
        # east face:  max_x=-15,  standoff 4 → waypoint x=-11
        # floor 1 (sill_y=1.2): waypoint y = 1.2 + 1.0 = 2.2
        target_building = Building(
            id=2,
            cx=-25.0, cz=20.0,
            w=20.0, d=15.0, h=6.0,
            windows=(
                # Floor 1, north face: waypoint (-28, 2.2, 8.5)  XZ dist from (0,0) ≈ 29.3
                WindowAperture(face="north", axis_center=-28.0, sill_y=1.2, width=2.0, height=2.0),
                # Floor 1, east face:  waypoint (-11, 2.2, 22.0) XZ dist from (0,0) ≈ 24.6
                WindowAperture(face="east",  axis_center=22.0,  sill_y=1.2, width=2.0, height=2.0),
            ),
        )

        # A neighbor building that blocks the straight line to the east waypoint.
        blocker = Building(
            id=99,
            cx=-17.0, cz=27.6,
            w=6.0, d=6.0, h=10.0,
        )

        # Standoff = 4.0 (world2 scene value).
        # north waypoint: x = axis_center = -28, z = min_z - 4 = 12.5 - 4 = 8.5
        # east  waypoint: x = max_x + 4   = -15 + 4 = -11, z = axis_center = 22.0
        NORTH_WP_Z = 8.5
        EAST_WP_X  = -11.0

        class _BlockedEastWorld:
            """World where the straight line to the east window hits blocker id=99."""
            buildings = (target_building, blocker)

            def building_near_xz(self, x, z, margin=2.0):
                return target_building

            def buildings_near(self, *_args, **_kwargs):
                return [target_building, blocker]

            def obstacles_in_path(self, fx, fy, fz, tx, ty, tz, samples=20, margin=0.0):
                # Block paths whose destination is near the east waypoint.
                # Clear paths whose destination is near the north waypoint.
                if abs(tx - EAST_WP_X) < 2.0 and abs(tz - 22.0) < 2.0:
                    return [blocker]
                if abs(tz - NORTH_WP_Z) < 2.0:
                    return []
                return []

        monkeypatch.setattr(context, "get_world", lambda: _BlockedEastWorld())

        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": 0.0, "y": 0.0, "z": 0.0,
            "battery": 100, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -25.0, 20.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        wp = tr.get("selected_window_waypoint")
        assert wp is not None, "expected a selected_window_waypoint in target_resolution"
        assert wp["face"] == "north", (
            f"expected north (reachable), got {wp['face']!r} "
            "(likely XZ-nearest east was picked even though it is blocked)"
        )

    @pytest.mark.asyncio
    async def test_ground_entry_picks_reachable_face_when_xz_nearest_requires_circumnavigation(
        self, _mock_client, monkeypatch
    ):
        """Regression: BEACON-04 scenario — XZ-nearest window blocked, farther one clear.

        Drone approaches from the south-east.  Two windows are available on the
        target building.  The east window is XZ-nearer but its LOS is intercepted
        by a wall building; the north window is XZ-farther but has a clear line of
        sight.  The two-stage check must skip east and select north.

        Geometry (drone at (0, 2, −20)):
          - target building: cx=−30, cz=0, w=6, d=6, h=6
              east face max_x=−27, standoff 4 → east_wp = (−23, 2.2, 0)
                  XZ dist from (0,−20) = sqrt(23²+20²) ≈ 30.5  ← NEARER
              north face min_z=−3, standoff 4 → north_wp = (−30, 2.2, −7)
                  XZ dist from (0,−20) = sqrt(30²+13²) ≈ 32.7  ← FARTHER
          - wall_blocker: cx=−19, cz=0, w=2, d=10, h=20
              LOS (0,−20)→(−23,0): passes x=−19 at z≈−3.5 — inside wall ✓ BLOCKED
              LOS (0,−20)→(−30,−7): passes x=−19 at z≈−11.8 — outside wall ✓ CLEAR

        The test verifies that Stage 1 (LOS) correctly rejects east and the
        fallthrough selects north.  Stage 2 (A* check) is a best-effort guard for
        cases where LOS passes but actual routing fails; it is tested indirectly
        here by verifying north_wp passes the bounded A* call without error.
        """
        from backend.services.core import context
        from backend.world.model import Building, WindowAperture

        # STANDOFF_M = 4 in world2; reproduce it explicitly so the test is
        # independent of scene configuration.
        _STANDOFF = 4.0

        # target building: cx=-30, cz=0, w=6, d=6 →
        #   east face max_x=-27 → east_wp x=-27+4=-23, z=axis_center=0
        #   north face min_z=-3 → north_wp z=-3-4=-7, x=axis_center=-30
        target_bld = Building(
            id=70,
            cx=-30.0, cz=0.0,
            w=6.0, d=6.0, h=6.0,
            windows=(
                # East face: waypoint (−23, 2.2, 0)   XZ dist from (0,−20) ≈ 30.5
                WindowAperture(face="east",  axis_center=0.0,   sill_y=1.2, width=2.0, height=2.0),
                # North face: waypoint (−30, 2.2, −7)  XZ dist from (0,−20) ≈ 32.7
                WindowAperture(face="north", axis_center=-30.0, sill_y=1.2, width=2.0, height=2.0),
            ),
        )

        # Wall that intercepts the east LOS but NOT the north LOS.
        # cx=-19, min_x=-20, max_x=-18, min_z=-5, max_z=5
        wall_blocker = Building(id=71, cx=-19.0, cz=0.0, w=2.0, d=10.0, h=20.0)

        class _WallWorld:
            buildings = (target_bld, wall_blocker)

            def building_near_xz(self, x, z, margin=2.0):
                return target_bld

            def buildings_near(self, *_a, **_kw):
                return list(self.buildings)

            def obstacles_in_path(self, fx, fy, fz, tx, ty, tz, samples=20, margin=0.0):
                hit: list = []
                n = max(samples - 1, 1)
                for b in self.buildings:
                    lo_x = b.min_x - margin
                    hi_x = b.max_x + margin
                    lo_z = b.min_z - margin
                    hi_z = b.max_z + margin
                    hi_y = b.max_y + margin
                    for i in range(samples):
                        t = i / n
                        px = fx + t * (tx - fx)
                        py = fy + t * (ty - fy)
                        pz = fz + t * (tz - fz)
                        if lo_x <= px <= hi_x and 0 <= py <= hi_y and lo_z <= pz <= hi_z:
                            hit.append(b)
                            break
                return hit

        monkeypatch.setattr(context, "get_world", lambda: _WallWorld())

        # Drone at (0, 2, −20): south-east of building.
        # east_wp (−23, 2.2, 0): XZ dist ≈ 30.5 — nearer but LOS blocked by wall.
        # north_wp (−30, 2.2, −7): XZ dist ≈ 32.7 — farther but LOS clear.
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": 0.0, "y": 2.0, "z": -20.0,
            "battery": 100, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -30.0, 0.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        wp = tr.get("selected_window_waypoint")
        assert wp is not None, f"expected a selected_window_waypoint, got None. tr={tr}"
        # XZ-nearest candidate (east) must be skipped — LOS blocked by wall_blocker.
        # XZ-farther candidate (north) must be selected — LOS clear.
        assert wp["face"] == "north", (
            f"expected north (clear LOS, farther), got {wp['face']!r}. "
            f"east window should have been rejected: LOS intercepted by wall_blocker."
        )

    @pytest.mark.asyncio
    async def test_ground_entry_records_fallback_when_building_has_no_windows(self, _mock_client):
        from backend.world.model import WORLD
        no_window_building = next(
            (b for b in WORLD.buildings if not b.windows),
            None,
        )
        assert no_window_building is not None, (
            "test fixture requires at least one building with no windows"
        )
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": 0.0, "y": 5.0, "z": 0.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01",
            float(no_window_building.cx), float(no_window_building.cz),
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        assert tr.get("entry_mode") == "ground_entry"
        assert tr.get("entry_mode_fallback") is True
        assert "selected_window_waypoint" not in tr
        assert result["to"]["x"] == pytest.approx(float(no_window_building.cx), abs=0.01)
        assert result["to"]["z"] == pytest.approx(float(no_window_building.cz), abs=0.01)

    @pytest.mark.asyncio
    async def test_ground_entry_filters_windows_on_far_side(self, _mock_client):
        """Regression: drone approaching from one side of the building must NOT
        select a window on the opposite face, even if XZ distance is similar.
        The drone is west of building 3 (residential block); the east-face
        window is on the far side and requires flying around/over the building.
        Only west-face windows should be considered.

        Building 3: cx=20, cz=25, min_x=14, max_x=26.  Drone at x=-20 is west
        of min_x=14, so west face (outward if drone.x < min_x) passes the
        approach-side filter; east face (outward if drone.x > max_x=26) does not
        — drone at x=-20 is not east of 26.
        """
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -20.0, "y": 2.0, "z": 24.0,  # west of building 3 (min_x=14)
            "battery": 100, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", 20.0, 25.0,  # building 3 center
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        wp = tr.get("selected_window_waypoint")
        assert wp is not None, (
            f"expected a selected_window_waypoint in target_resolution; got tr={tr}"
        )
        # Drone is west of building 3: east face is on the far side and must not
        # be selected.  Any other face (south, west) is acceptable since those
        # windows are on the approach-side or adjacent faces.
        assert wp["face"] != "east", (
            f"drone on west side picked east-face window — approach-side filter failed. "
            f"Selected: face={wp['face']}, floor={wp['floor']}"
        )

    @pytest.mark.asyncio
    async def test_ground_entry_excludes_submerged_windows(self, _mock_client, monkeypatch):
        """When the lowest floor's windows sit below the flood surface, ground
        entry must skip them and pick the next floor up — otherwise the drone
        would dive underwater on its approach before the above-water sweep.
        """
        from backend.services.core import context
        from backend.world.model import Building, WindowAperture

        # Flood sits at y=1.4 (default), clearance 0.5 → min entry y = 1.9.
        # Ground-floor sill_y=0.0 → waypoint y=0.8 (SUBMERGED — must be skipped).
        # Second-floor  sill_y=3.0 → waypoint y=3.8 (above flood).
        submerged_ground_building = Building(
            id=997,
            cx=0.0, cz=0.0,
            w=10.0, d=10.0, h=12.0,
            windows=(
                WindowAperture(face="south", axis_center=0.0, sill_y=0.0, width=2.0, height=1.6),
                WindowAperture(face="south", axis_center=0.0, sill_y=3.0, width=2.0, height=1.6),
            ),
        )

        class _FloodWorld:
            buildings = (submerged_ground_building,)

            def building_near_xz(self, x, z, margin=2.0):
                return submerged_ground_building

            def obstacles_in_path(self, *_args, **_kwargs):
                return []

            def buildings_near(self, *_args, **_kwargs):
                return [submerged_ground_building]

        monkeypatch.setattr(context, "get_world", lambda: _FloodWorld())
        monkeypatch.setattr(context, "get_flood_level", lambda: 1.4)

        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": 0.0, "y": 5.0, "z": 20.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", 0.0, 0.0,
            snap_to_building_center=True,
            entry_mode="ground_entry",
        )

        tr = result.get("target_resolution", {})
        wp = tr.get("selected_window_waypoint")
        assert wp is not None, f"expected a selection; target_resolution={tr}"
        assert wp["floor"] == 2, (
            f"expected floor 2 (above-flood lowest), got floor={wp['floor']} "
            f"at y={wp.get('y')}; flood filter not applied?"
        )
        assert float(wp["y"]) >= 1.9, (
            f"selected window y={wp['y']} is at or below flood+clearance (1.9m) — "
            "drone would go underwater"
        )
