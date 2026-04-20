"""Unit tests for 3D A* pathfinding module."""
from __future__ import annotations

from backend.services.navigation.a_star_3d import find_3d_path
from backend.world.model import WORLD


def test_find_3d_path_in_open_space_returns_path() -> None:
    """Pathfinder should return a valid path for obstacle-free open-space segment.

    Args:
        None.
    Returns:
        None.
    """
    path = find_3d_path(
        WORLD,
        (45.0, 10.0, 45.0),
        (55.0, 10.0, 55.0),
        margin=1.0,
        cell_size=1.0,
        max_iterations=50_000,
    )
    assert path is not None
    assert len(path) >= 2
    assert path[0] == (45.0, 10.0, 45.0)
    assert path[-1] == (55.0, 10.0, 55.0)


def test_find_3d_path_avoids_target_building_when_excluded() -> None:
    """Pathfinder should allow approach to excluded building footprint.

    Args:
        None.
    Returns:
        None.
    """
    target_building = WORLD.building_near_xz(-15.0, -20.0)
    assert target_building is not None

    path = find_3d_path(
        WORLD,
        (0.0, 12.0, 0.0),
        (-15.0, 17.0, -20.0),
        margin=1.0,
        exclude_building_id=target_building.id,
        cell_size=1.0,
        max_iterations=120_000,
    )

    assert path is not None
    assert path[-1] == (-15.0, 17.0, -20.0)