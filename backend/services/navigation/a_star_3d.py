from __future__ import annotations

import heapq
import math
from dataclasses import dataclass


@dataclass
class Grid3D:
    """Voxel grid representation for 3D route planning.

    Args:
        min_x: Minimum X bound in world coordinates.
        max_x: Maximum X bound in world coordinates.
        min_y: Minimum Y bound in world coordinates.
        max_y: Maximum Y bound in world coordinates.
        min_z: Minimum Z bound in world coordinates.
        max_z: Maximum Z bound in world coordinates.
        cell_size: Side length for each cubic voxel.
    Returns:
        None.
    """

    min_x: float
    max_x: float
    min_y: float
    max_y: float
    min_z: float
    max_z: float
    cell_size: float

    def __post_init__(self) -> None:
        """Initialize grid dimensions.

        Args:
            None.
        Returns:
            None.
        """
        self.width = int(math.ceil((self.max_x - self.min_x) / self.cell_size)) + 1
        self.height = int(math.ceil((self.max_y - self.min_y) / self.cell_size)) + 1
        self.depth = int(math.ceil((self.max_z - self.min_z) / self.cell_size)) + 1

    def world_to_grid(self, x: float, y: float, z: float) -> tuple[int, int, int]:
        """Convert world-space coordinates to voxel indices.

        Args:
            x: World-space X coordinate.
            y: World-space Y coordinate.
            z: World-space Z coordinate.
        Returns:
            A tuple ``(gx, gy, gz)`` representing grid indices.
        """
        gx = int(round((x - self.min_x) / self.cell_size))
        gy = int(round((y - self.min_y) / self.cell_size))
        gz = int(round((z - self.min_z) / self.cell_size))
        return gx, gy, gz

    def grid_to_world(self, gx: int, gy: int, gz: int) -> tuple[float, float, float]:
        """Convert voxel indices back to world-space coordinates.

        Args:
            gx: Grid X index.
            gy: Grid Y index.
            gz: Grid Z index.
        Returns:
            A tuple ``(x, y, z)`` at the center of the voxel cell.
        """
        x = self.min_x + gx * self.cell_size
        y = self.min_y + gy * self.cell_size
        z = self.min_z + gz * self.cell_size
        return x, y, z

    def in_bounds(self, gx: int, gy: int, gz: int) -> bool:
        """Check whether a voxel index is inside the grid.

        Args:
            gx: Grid X index.
            gy: Grid Y index.
            gz: Grid Z index.
        Returns:
            ``True`` if the voxel lies within the grid bounds, else ``False``.
        """
        return 0 <= gx < self.width and 0 <= gy < self.height and 0 <= gz < self.depth


def _distance_3d(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """Compute Euclidean distance between two 3D integer grid coordinates.

    Args:
        a: First grid coordinate.
        b: Second grid coordinate.
    Returns:
        Euclidean distance value.
    """
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _segment_clear(world: object, start: tuple[float, float, float], end: tuple[float, float, float], margin: float, exclude_building_id: int | None) -> bool:
    """Check whether a 3D segment intersects any blocked building.

    Args:
        world: World model instance providing ``obstacles_in_path``.
        start: Segment start ``(x, y, z)``.
        end: Segment end ``(x, y, z)``.
        margin: Obstacle safety margin in metres.
        exclude_building_id: Optional building id to ignore.
    Returns:
        ``True`` when the segment is obstacle-free, otherwise ``False``.
    """
    samples = max(12, int(_distance_3d((int(start[0]), int(start[1]), int(start[2])), (int(end[0]), int(end[1]), int(end[2]))) * 2))
    blockers = world.obstacles_in_path(
        start[0],
        start[1],
        start[2],
        end[0],
        end[1],
        end[2],
        samples=samples,
        margin=margin,
    )
    if exclude_building_id is None:
        return not blockers
    return not [building for building in blockers if getattr(building, "id", None) != exclude_building_id]


def _find_nearest_walkable(
    world: object,
    grid: Grid3D,
    origin: tuple[int, int, int],
    margin: float,
    exclude_building_id: int | None,
    search_radius: int = 4,
) -> tuple[int, int, int] | None:
    """Find the nearest walkable voxel around an origin voxel.

    Args:
        world: World model instance providing ``obstacles_in_path``.
        grid: Active planning grid.
        origin: Starting voxel index.
        margin: Obstacle safety margin.
        exclude_building_id: Optional building id to ignore.
        search_radius: Maximum voxel radius to probe.
    Returns:
        A walkable voxel index or ``None`` if none is found.
    """
    if not grid.in_bounds(*origin):
        return None
    ox, oy, oz = origin
    for radius in range(0, search_radius + 1):
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                for dz in range(-radius, radius + 1):
                    gx, gy, gz = ox + dx, oy + dy, oz + dz
                    if not grid.in_bounds(gx, gy, gz):
                        continue
                    wx, wy, wz = grid.grid_to_world(gx, gy, gz)
                    if _segment_clear(world, (wx, wy, wz), (wx, wy, wz), margin, exclude_building_id):
                        return gx, gy, gz
    return None


def _grid_neighbors(world: object, grid: Grid3D, node: tuple[int, int, int], margin: float, exclude_building_id: int | None) -> list[tuple[int, int, int]]:
    """Enumerate valid 3D neighbor voxels.

    Args:
        world: World model instance providing ``obstacles_in_path``.
        grid: Active planning grid.
        node: Current voxel index.
        margin: Obstacle safety margin.
        exclude_building_id: Optional building id to ignore.
    Returns:
        List of adjacent walkable voxel indices.
    """
    gx, gy, gz = node
    candidates: list[tuple[int, int, int]] = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                nx, ny, nz = gx + dx, gy + dy, gz + dz
                if not grid.in_bounds(nx, ny, nz):
                    continue
                p0 = grid.grid_to_world(gx, gy, gz)
                p1 = grid.grid_to_world(nx, ny, nz)
                if not _segment_clear(world, p0, p1, margin, exclude_building_id):
                    continue
                candidates.append((nx, ny, nz))
    return candidates


def _reconstruct_path(came_from: dict[tuple[int, int, int], tuple[int, int, int]], current: tuple[int, int, int]) -> list[tuple[int, int, int]]:
    """Reconstruct an A* path from predecessor links.

    Args:
        came_from: Map of child node to parent node.
        current: Goal node.
    Returns:
        Ordered list of grid nodes from start to goal.
    """
    path = [current]
    while current in came_from:
        current = came_from[current]
        path.append(current)
    path.reverse()
    return path


def _simplify_path(
    world: object,
    points: list[tuple[float, float, float]],
    margin: float,
    exclude_building_id: int | None,
    *,
    cell_size: float,
) -> list[tuple[float, float, float]]:
    """Reduce waypoint count by collapsing line-of-sight segments.

    Uses a stricter margin than planning (``margin + cell_size / 2``) to
    prevent diagonal corner-cuts: A* keeps voxel centers ``margin`` metres
    from walls, but a straight line between two such voxels taken diagonally
    can cut up to ``cell_size / 2`` closer to a wall corner. The stricter
    simplify margin absorbs that geometric excess.

    Args:
        world: World model instance providing ``obstacles_in_path``.
        points: Full waypoint sequence.
        margin: Planning obstacle safety margin.
        exclude_building_id: Optional building id to ignore.
        cell_size: Grid voxel size used during planning.
    Returns:
        Simplified waypoint list preserving collision safety.
    """
    if len(points) <= 2:
        return points

    simplify_margin = margin + cell_size / 2

    simplified = [points[0]]
    anchor_index = 0
    probe_index = 2

    while probe_index < len(points):
        if _segment_clear(
            world,
            points[anchor_index],
            points[probe_index],
            simplify_margin,
            exclude_building_id,
        ):
            probe_index += 1
            continue
        simplified.append(points[probe_index - 1])
        anchor_index = probe_index - 1
        probe_index = anchor_index + 2

    simplified.append(points[-1])
    return simplified


def find_3d_path(
    world: object,
    start: tuple[float, float, float],
    goal: tuple[float, float, float],
    *,
    margin: float = 1.0,
    exclude_building_id: int | None = None,
    cell_size: float = 1.0,
    max_altitude: float | None = None,
    max_iterations: int = 100_000,
) -> list[tuple[float, float, float]] | None:
    """Compute a collision-free 3D route using voxel A*.

    Args:
        world: World model instance with ``buildings`` and ``obstacles_in_path``.
        start: Start coordinate ``(x, y, z)``.
        goal: Goal coordinate ``(x, y, z)``.
        margin: Obstacle safety margin.
        exclude_building_id: Optional building id to ignore as obstacle.
        cell_size: Voxel size in metres.
        max_altitude: Optional top-of-search altitude.
        max_iterations: Maximum A* node expansions before abort.
    Returns:
        Ordered world-space waypoints from start to goal, or ``None``.
    """
    buildings = [b for b in world.buildings if getattr(b, "id", None) != exclude_building_id]
    min_x = min([start[0], goal[0], *(b.min_x for b in buildings)] or [start[0], goal[0]]) - 8.0
    max_x = max([start[0], goal[0], *(b.max_x for b in buildings)] or [start[0], goal[0]]) + 8.0
    min_z = min([start[2], goal[2], *(b.min_z for b in buildings)] or [start[2], goal[2]]) - 8.0
    max_z = max([start[2], goal[2], *(b.max_z for b in buildings)] or [start[2], goal[2]]) + 8.0
    min_y = max(0.0, min(start[1], goal[1]) - 2.0)
    tallest = max([start[1], goal[1], *(b.max_y for b in buildings)] or [start[1], goal[1]])
    max_y = max_altitude if max_altitude is not None else max(tallest + 10.0, goal[1] + 5.0, start[1] + 5.0)
    max_y = max(max_y, min_y + 5.0)

    grid = Grid3D(
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
        min_z=min_z,
        max_z=max_z,
        cell_size=cell_size,
    )

    start_grid = grid.world_to_grid(*start)
    goal_grid = grid.world_to_grid(*goal)
    start_grid = _find_nearest_walkable(world, grid, start_grid, margin, exclude_building_id)
    goal_grid = _find_nearest_walkable(world, grid, goal_grid, margin, exclude_building_id)
    if start_grid is None or goal_grid is None:
        return None

    open_heap: list[tuple[float, int, tuple[int, int, int]]] = []
    heap_counter = 0
    g_score: dict[tuple[int, int, int], float] = {start_grid: 0.0}
    came_from: dict[tuple[int, int, int], tuple[int, int, int]] = {}

    heapq.heappush(open_heap, (_distance_3d(start_grid, goal_grid), heap_counter, start_grid))
    in_open: set[tuple[int, int, int]] = {start_grid}

    iterations = 0
    while open_heap and iterations < max_iterations:
        iterations += 1
        _, _, current = heapq.heappop(open_heap)
        in_open.discard(current)

        if current == goal_grid:
            grid_path = _reconstruct_path(came_from, current)
            world_path = [grid.grid_to_world(*node) for node in grid_path]
            if world_path:
                world_path[0] = start
                world_path[-1] = goal
            return _simplify_path(world, world_path, margin, exclude_building_id, cell_size=cell_size)

        for neighbor in _grid_neighbors(world, grid, current, margin, exclude_building_id):
            tentative_g = g_score[current] + _distance_3d(current, neighbor)
            if tentative_g >= g_score.get(neighbor, float("inf")):
                continue

            came_from[neighbor] = current
            g_score[neighbor] = tentative_g
            if neighbor not in in_open:
                heap_counter += 1
                f_score = tentative_g + _distance_3d(neighbor, goal_grid)
                heapq.heappush(open_heap, (f_score, heap_counter, neighbor))
                in_open.add(neighbor)

    return None