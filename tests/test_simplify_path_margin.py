"""Unit tests for _simplify_path margin hardening.

Verifies that path simplification uses a stricter margin than planning
(planning_margin + cell_size/2) to prevent diagonal corner-cuts.
"""
from __future__ import annotations

from backend.services.navigation.a_star_3d import _simplify_path


class _FakeBuilding:
    def __init__(self, bid: int) -> None:
        self.id = bid


class _CorridorWorld:
    """Mock world with a single wall at x=5 that blocks only when margin>=1.25.

    This simulates the geometric reality of a straight diagonal between two
    voxels that are each 1.0m from a wall: the midpoint dips closer to the
    wall than the endpoints.
    """

    def obstacles_in_path(
        self,
        x0: float, y0: float, z0: float,
        x1: float, y1: float, z1: float,
        *, samples: int, margin: float,
    ) -> list:
        # Any segment that crosses x=5 at a Y-slice within the obstacle's
        # height is blocked when margin is strict enough.
        crosses_wall = (x0 - 5.0) * (x1 - 5.0) <= 0.0
        if not crosses_wall:
            return []
        # The fake wall has "virtual padding" such that margin<1.25 sees the
        # segment as clear, margin>=1.25 sees it as blocked (simulating how
        # a diagonal cut gets closer to a corner than voxel-to-wall distance).
        if margin >= 1.25:
            return [_FakeBuilding(1)]
        return []


def test_simplify_path_retains_waypoint_when_diagonal_would_graze_wall() -> None:
    """Planning margin 1.0 says segment is clear; simplify margin 1.5 sees graze.

    Given three waypoints where a direct start->end segment would be deemed
    clear at planning margin but not at simplify margin, the simplifier must
    retain the middle waypoint.
    """
    world = _CorridorWorld()
    points = [(0.0, 5.0, 0.0), (5.0, 5.0, 5.0), (10.0, 5.0, 10.0)]

    result = _simplify_path(
        world, points, margin=1.0, exclude_building_id=None, cell_size=1.0,
    )

    # cell_size/2 = 0.5, so simplify margin = 1.5 > 1.25 -> blocked -> keep middle
    assert len(result) == 3
    assert result[0] == (0.0, 5.0, 0.0)
    assert result[-1] == (10.0, 5.0, 10.0)


def test_simplify_path_still_collapses_when_fully_clear() -> None:
    """When no wall is near, simplify collapses intermediate waypoints."""
    class _EmptyWorld:
        def obstacles_in_path(self, *args, **kwargs) -> list:
            return []

    points = [(0.0, 5.0, 0.0), (5.0, 5.0, 5.0), (10.0, 5.0, 10.0)]
    result = _simplify_path(
        _EmptyWorld(), points, margin=1.0, exclude_building_id=None, cell_size=1.0,
    )
    assert result == [(0.0, 5.0, 0.0), (10.0, 5.0, 10.0)]
