# A* Pathfinding Implementation Plan for Project Beacon

## Executive Summary

Current navigation uses a simple heuristic: **Direct → Over (altitude) → Around (perpendicular detour)**. This plan replaces the crude "around" strategy with a robust **A* pathfinding** algorithm that:
- Navigates obstacles (buildings) on a 2D grid (XZ plane) with altitude escape routes
- Minimizes flight distance while respecting safety margins
- Integrates with existing hybrid agent/orchestrator architecture
- Extends to multi-drone fleet optimization and window-scanning sequences

---

## Part 1: Current State Analysis

### Existing Navigation Flow
```
LLM Command (e.g., "move to X")
  ↓
Navigation Agent (backend/agents/navigation.py)
  ↓
Orchestrator: route_planner.plan_route(from, to, altitude)
  ↓
Strategy selection:
  - Direct: No collision? Move straight.
  - Over: Direct blocked? Climb 5m, retry.
  - Around: Both blocked? Try perpendicular detours ❌ (CRUDE)
  - Altitude escalation: Fails? Retry +5m (max 3 attempts)
  ↓
Execute waypoints via gRPC
```

### Problem with Current "Around" Strategy
- **File**: `backend/services/navigation/route_planner.py` lines 220–270
- **Issue**: Only tries 2 perpendicular directions (left/right), then gives up
- **Result**: Gets stuck on complex obstacle fields; no optimization for distance/cost
- **Example**: Drone at (0,0) trying to reach (20,0) blocked by building at (10,0). Current code tries (0±5, 0)→(20,0), which may still be blocked or take very long paths.

### Obstacle Representation
- **Buildings**: AABB with `(cx, cz, w, d, h)` → stores min/max corners
- **Safety margin**: `building_proximity_margin_m = 2.0m` from config
- **Ray-casting collision check**: Current 40-point sampling on direct line is accurate but non-optimal for complex paths

---

## Part 2: A* Data Structures & Algorithm

### 2.1 Coordinate System & Grid

**World Space**:
- X: East-West (meters)
- Y: Vertical (meters, altitude)
- Z: North-South (meters)

**A* operates on**:
- **2D Grid (XZ plane)** for horizontal pathfinding
- **Altitude awareness**: Dynamic escalation outside A* (existing fallback mechanism)

### 2.2 Grid Construction from Obstacles

```python
class GridConfig:
    cell_size = 1.0  # 1m cells (configurable)
    margin_buffer = 2.5  # Building margin + safety
    altitude_cruising = 15.0  # Default cruise altitude (meters)
    altitude_max_climb = 50.0  # Max altitude to try

class Grid2D:
    """Discretized XZ plane with obstacle avoidance."""
    
    def __init__(self, bounds: Tuple[float, float, float, float], 
                 cell_size: float, obstacles: List[Building]):
        """
        bounds: (min_x, max_x, min_z, max_z)
        obstacles: list of Building AABBs with margins applied
        """
        self.cell_size = cell_size
        self.bounds = bounds
        self.width = int((bounds[1] - bounds[0]) / cell_size)
        self.height = int((bounds[3] - bounds[2]) / cell_size)
        
        # Initialize obstacle map: walkable=True, blocked=False
        self.walkable = [[True] * self.width for _ in range(self.height)]
        
        # Mark obstacle cells as unwalkable
        for building in obstacles:
            self._mark_obstacle_cells(building)
    
    def _mark_obstacle_cells(self, building: Building):
        """Expand building AABB by margin, mark cells as blocked."""
        margin = GridConfig.margin_buffer
        padded_aabb = (
            building.min_x - margin, building.min_z - margin,
            building.max_x + margin, building.max_z + margin
        )
        # Convert world coords to grid cells
        for cell_x, cell_z in self._cells_in_aabb(padded_aabb):
            if 0 <= cell_x < self.width and 0 <= cell_z < self.height:
                self.walkable[cell_z][cell_x] = False
    
    def world_to_grid(self, x: float, z: float) -> Tuple[int, int]:
        """Convert world XZ to grid cell indices."""
        gx = int((x - self.bounds[0]) / self.cell_size)
        gz = int((z - self.bounds[2]) / self.cell_size)
        return (gx, gz)
    
    def grid_to_world(self, gx: int, gz: int) -> Tuple[float, float]:
        """Convert grid cell to world XZ (cell center)."""
        x = self.bounds[0] + (gx + 0.5) * self.cell_size
        z = self.bounds[2] + (gz + 0.5) * self.cell_size
        return (x, z)
    
    def is_walkable(self, gx: int, gz: int) -> bool:
        """Check if grid cell is passable."""
        return (0 <= gx < self.width and 0 <= gz < self.height 
                and self.walkable[gz][gx])
    
    def neighbors(self, gx: int, gz: int, diagonal: bool = True) -> List[Tuple[int, int]]:
        """
        Return neighbors of cell (gx, gz).
        diagonal=True: 8-neighbors (includes diagonals)
        diagonal=False: 4-neighbors (cardinal only)
        """
        dirs = [(-1, 0), (1, 0), (0, -1), (0, 1)]  # Cardinal
        if diagonal:
            dirs += [(-1, -1), (-1, 1), (1, -1), (1, 1)]  # Diagonals
        
        result = []
        for dx, dz in dirs:
            nx, nz = gx + dx, gz + dz
            if self.is_walkable(nx, nz):
                result.append((nx, nz))
        return result
```

### 2.3 A* Algorithm

```python
import heapq
from dataclasses import dataclass
from typing import Dict, Optional

@dataclass
class Node:
    pos: Tuple[int, int]  # (grid_x, grid_z)
    g_cost: float  # Actual distance from start
    h_cost: float  # Heuristic to goal
    
    def f_cost(self) -> float:
        return self.g_cost + self.h_cost
    
    def __lt__(self, other: "Node") -> bool:
        return self.f_cost() < other.f_cost()

class AStarPathfinder:
    """2D A* for drone horizontal pathfinding."""
    
    def __init__(self, grid: Grid2D):
        self.grid = grid
    
    def heuristic(self, pos1: Tuple[int, int], pos2: Tuple[int, int]) -> float:
        """
        Euclidean distance heuristic (admissible for grid movement).
        Could use Manhattan for faster computation.
        """
        dx = pos1[0] - pos2[0]
        dz = pos1[1] - pos2[1]
        return (dx**2 + dz**2)**0.5
    
    def movement_cost(self, pos1: Tuple[int, int], pos2: Tuple[int, int]) -> float:
        """
        Cost to move from pos1 to pos2.
        Diagonal: sqrt(2) * cell_size
        Cardinal: cell_size
        """
        dx = abs(pos1[0] - pos2[0])
        dz = abs(pos1[1] - pos2[1])
        if dx == 1 and dz == 1:  # Diagonal
            return (2**0.5) * self.grid.cell_size
        else:  # Cardinal (dx==1, dz==0 or vice versa)
            return self.grid.cell_size
    
    def find_path(self, start: Tuple[float, float], 
                  goal: Tuple[float, float]) -> Optional[List[Tuple[float, float]]]:
        """
        Find shortest path from start to goal (world coordinates).
        Returns list of waypoints in world XZ, or None if no path exists.
        """
        # Convert world coords to grid
        start_grid = self.grid.world_to_grid(start[0], start[1])
        goal_grid = self.grid.world_to_grid(goal[0], goal[1])
        
        # Validate start/goal are walkable
        if not self.grid.is_walkable(*start_grid) or not self.grid.is_walkable(*goal_grid):
            return None
        
        # A* search
        open_set = []
        closed_set = set()
        came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
        g_costs: Dict[Tuple[int, int], float] = {start_grid: 0.0}
        
        start_node = Node(
            pos=start_grid,
            g_cost=0.0,
            h_cost=self.heuristic(start_grid, goal_grid)
        )
        heapq.heappush(open_set, start_node)
        
        while open_set:
            current = heapq.heappop(open_set)
            
            if current.pos == goal_grid:
                # Reconstruct path
                path = [self.grid.grid_to_world(*goal_grid)]
                node = goal_grid
                while node in came_from:
                    node = came_from[node]
                    path.append(self.grid.grid_to_world(*node))
                return list(reversed(path))
            
            closed_set.add(current.pos)
            
            for neighbor in self.grid.neighbors(*current.pos, diagonal=True):
                if neighbor in closed_set:
                    continue
                
                tentative_g = g_costs[current.pos] + self.movement_cost(current.pos, neighbor)
                
                if neighbor not in g_costs or tentative_g < g_costs[neighbor]:
                    came_from[neighbor] = current.pos
                    g_costs[neighbor] = tentative_g
                    h = self.heuristic(neighbor, goal_grid)
                    neighbor_node = Node(pos=neighbor, g_cost=tentative_g, h_cost=h)
                    heapq.heappush(open_set, neighbor_node)
        
        # No path found
        return None
```

---

## Part 3: Integration with Existing Navigation

### 3.1 Modified Route Planner (`backend/services/navigation/route_planner.py`)

**New flow**:
```
plan_route(from_xyz, to_xyz, altitude):
    1. Try DIRECT (existing ray-cast)
       ✓ Success? Return straight path
    
    2. Try ALTITUDE ESCALATION (existing fallback)
       - Current: Retry at +5m, +10m, +15m
       ✓ Success? Return path at higher altitude
    
    3. Try A* HORIZONTAL PATHFINDING (NEW)
       - Build 2D grid from world obstacles
       - A* search on XZ plane
       - Return waypoints at target altitude
       ✓ Success? Execute A* path with altitude tracking
    
    4. FAIL with error
```

### 3.2 New Classes & Methods

```python
# File: backend/services/navigation/a_star.py (NEW)
class AStarPlanner:
    """
    Public interface for A* pathfinding integrated with world model.
    """
    
    def __init__(self, world_model):
        self.world_model = world_model
        self._grid_cache = None  # Cache grid to avoid recomputation
        self._grid_seed = None   # Hash of world state for invalidation
    
    def plan_around_obstacles(self, 
                              start_xyz: Tuple[float, float, float],
                              goal_xyz: Tuple[float, float, float],
                              altitude: float = 15.0) -> Optional[List[Tuple[float, float, float]]]:
        """
        Main entry point: A* pathfinding to avoid buildings.
        
        Args:
            start_xyz, goal_xyz: (x, y, z) start and target positions
            altitude: Cruising altitude for horizontal path (y-coordinate)
        
        Returns:
            List of 3D waypoints, or None if no path exists within limits.
        """
        # Project to 2D for A* search
        start_2d = (start_xyz[0], start_xyz[2])  # (x, z)
        goal_2d = (goal_xyz[0], goal_xyz[2])
        
        # Lazy-load/update grid
        grid = self._get_or_build_grid()
        pathfinder = AStarPathfinder(grid)
        
        # A* search
        path_2d = pathfinder.find_path(start_2d, goal_2d)
        if not path_2d:
            return None
        
        # Lift to 3D: add altitude to each waypoint
        path_3d = [(x, altitude, z) for x, z in path_2d]
        return path_3d
    
    def _get_or_build_grid(self) -> Grid2D:
        """Lazy-load grid; rebuild if world state changed."""
        world_seed = hash(tuple(
            (b.cx, b.cz, b.w, b.d, b.h) 
            for b in self.world_model.buildings
        ))
        
        if self._grid_cache is None or world_seed != self._grid_seed:
            bounds = self.world_model.compute_scene_bounds()
            self._grid_cache = Grid2D(bounds, cell_size=1.0, 
                                       obstacles=self.world_model.buildings)
            self._grid_seed = world_seed
        
        return self._grid_cache
```

### 3.3 Update Route Planner

```python
# In backend/services/navigation/route_planner.py

def plan_route(from_xyz, to_xyz, altitude=15.0, max_altitude=50.0):
    """
    Updated: Direct → Altitude Escalation → A* → Fail
    """
    # 1. TRY DIRECT
    if not WORLD.obstacles_in_path(from_xyz[0], from_xyz[1], from_xyz[2],
                                     to_xyz[0], to_xyz[1], to_xyz[2]):
        return [from_xyz, to_xyz]
    
    # 2. TRY ALTITUDE ESCALATION
    for alt_step in range(1, 4):  # +5m, +10m, +15m
        test_alt = altitude + (alt_step * 5)
        if test_alt > max_altitude:
            break
        if not WORLD.obstacles_in_path(from_xyz[0], test_alt, from_xyz[2],
                                         to_xyz[0], test_alt, to_xyz[2]):
            return [
                (from_xyz[0], from_xyz[1], from_xyz[2]),  # Current
                (from_xyz[0], test_alt, from_xyz[2]),      # Climb
                (to_xyz[0], test_alt, to_xyz[2]),          # Cruise
                (to_xyz[0], to_xyz[1], to_xyz[2]),         # Descend
            ]
    
    # 3. TRY A* (NEW)
    planner = AStarPlanner(WORLD)
    a_star_path = planner.plan_around_obstacles(from_xyz, to_xyz, altitude)
    if a_star_path:
        return a_star_path
    
    # 4. FAIL
    raise NavigationException(f"No path found from {from_xyz} to {to_xyz}")
```

---

## Part 4: Advanced Features

### 4.1 Weighted Cost Functions (Phase 2)

Extend A* with risk/energy metrics:

```python
def movement_cost_weighted(self, pos1, pos2, factors):
    """
    Multi-factor cost: distance, proximity to buildings, altitude changes.
    
    factors: {
        'distance_weight': 1.0,
        'building_proximity_penalty': 0.5,  # Avoid tight corridors
        'altitude_change_penalty': 0.2,
    }
    """
    basic_cost = self.movement_cost(pos1, pos2)
    
    # Proximity penalty: cells near building edges get higher cost
    mid_x = (pos1[0] + pos2[0]) / 2
    mid_z = (pos1[1] + pos2[1]) / 2
    wx, wz = self.grid.grid_to_world(int(mid_x), int(mid_z))
    
    proximity = WORLD.min_distance_to_building(wx, wz)
    if proximity < 5.0:  # Within 5m of building
        proximity_cost = (5.0 - proximity)  # Higher cost closer to building
        basic_cost += factors['building_proximity_penalty'] * proximity_cost
    
    return basic_cost
```

### 4.2 Multi-Drone Fleet Optimization (Phase 2)

Use A* to compute shortest paths for each drone, then solve assignment:

```python
def optimize_fleet_routes(missions: List[Mission], 
                          fleet: List[Drone]) -> Dict[Drone, List[Tuple[float, float, float]]]:
    """
    Compute optimal A* path for each drone-mission pair.
    Assign drones to minimize total flight distance/time.
    """
    # Step 1: Compute A* path for each (drone, mission) combination
    dist_matrix = {}
    for drone in fleet:
        for mission in missions:
            planner = AStarPlanner(WORLD)
            path = planner.plan_around_obstacles(
                drone.position, mission.target, altitude=15.0
            )
            distance = sum(euclidean_3d(path[i], path[i+1]) 
                          for i in range(len(path)-1))
            dist_matrix[(drone.id, mission.id)] = distance
    
    # Step 2: Solve assignment problem (Hungarian algorithm)
    # Minimize total distance
    assignment = hungarian_algorithm(dist_matrix)
    return assignment
```

### 4.3 Window Scanning Sequence Optimization (Phase 2)

Apply A* to order window visitation:

```python
def plan_window_scan_sequence(building_id: int, drone_pos: Tuple[float, float, float]) -> List[int]:
    """
    Order windows for thermal scanning to minimize total flight distance.
    Traveling salesman variant: Start → Window1 → Window2 → ... → End
    """
    building = WORLD.buildings[building_id]
    windows = building.windows
    
    # Compute approach waypoint for each window
    window_approaches = [
        building.window_scan_waypoints(w.floor, w.face)[0]  # First approach point
        for w in windows
    ]
    
    # TSP-like: nearest neighbor (greedy) or A* + DFS for small N (<10)
    if len(windows) <= 8:
        # Use greedy TSP for small sets
        order = tsp_nearest_neighbor(drone_pos, window_approaches)
        return [windows[i].id for i in order]
    else:
        # Fall back to random ordering for large sets
        return list(range(len(windows)))
```

---

## Part 5: Testing Strategy

### 5.1 Unit Tests

```python
# File: tests/test_a_star_pathfinding.py (NEW)

def test_a_star_direct_path_no_obstacles():
    """Simple straight-line path, no obstacles."""
    world = WorldModel(buildings=[])
    planner = AStarPlanner(world)
    
    path = planner.plan_around_obstacles(
        start_xyz=(0, 15, 0),
        goal_xyz=(20, 15, 0)
    )
    assert len(path) >= 2
    assert path[0] == (0, 15, 0)
    assert path[-1] == (20, 15, 0)

def test_a_star_navigates_single_building():
    """Drone avoids single building obstacle."""
    building = Building(id=0, cx=10, cz=0, w=4, d=4, h=10)
    world = WorldModel(buildings=[building])
    planner = AStarPlanner(world)
    
    path = planner.plan_around_obstacles(
        start_xyz=(0, 15, 0),
        goal_xyz=(20, 15, 0)
    )
    # Path should detour around building center
    assert path is not None
    # Verify no collision on path
    for i in range(len(path)-1):
        assert not world.obstacles_in_path(
            path[i][0], path[i][1], path[i][2],
            path[i+1][0], path[i+1][1], path[i+1][2]
        )

def test_a_star_navigates_complex_obstacle_field():
    """Multiple buildings create complex maze; A* finds valid path."""
    buildings = [
        Building(id=0, cx=-10, cz=-10, w=4, d=4, h=10),
        Building(id=1, cx=0, cz=0, w=6, d=6, h=12),
        Building(id=2, cx=10, cz=10, w=4, d=4, h=10),
    ]
    world = WorldModel(buildings=buildings)
    planner = AStarPlanner(world)
    
    path = planner.plan_around_obstacles(
        start_xyz=(-20, 15, -20),
        goal_xyz=(20, 15, 20)
    )
    assert path is not None
    assert len(path) > 2  # Non-trivial path
    
    # Verify collision-free
    for i in range(len(path)-1):
        assert not world.obstacles_in_path(*path[i], *path[i+1])

def test_a_star_no_path_impossible_scenario():
    """Enclosed building should report no path."""
    # Imagine building completely surrounds goal
    building = Building(id=0, cx=10, cz=10, w=30, d=30, h=20)  # Huge building
    world = WorldModel(buildings=[building])
    planner = AStarPlanner(world)
    
    # Goal inside building (or margin), start outside
    path = planner.plan_around_obstacles(
        start_xyz=(0, 15, 0),
        goal_xyz=(10, 15, 10)  # Inside margin
    )
    assert path is None  # Unreachable

def test_grid_cell_walkability():
    """Grid correctly marks obstacle cells as unwalkable."""
    building = Building(id=0, cx=0, cz=0, w=10, d=10, h=10)
    grid = Grid2D(
        bounds=(-50, 50, -50, 50),
        cell_size=1.0,
        obstacles=[building]
    )
    
    # Center of building should be unwalkable (with margin)
    center_cell = grid.world_to_grid(0, 0)
    assert not grid.is_walkable(*center_cell)
    
    # Far point should be walkable
    far_cell = grid.world_to_grid(40, 40)
    assert grid.is_walkable(*far_cell)

def test_heuristic_admissibility():
    """Heuristic never overestimates actual distance."""
    pathfinder = AStarPathfinder(grid=None)  # Heuristic is grid-independent
    
    pos1 = (0, 0)
    pos2 = (10, 10)
    h = pathfinder.heuristic(pos1, pos2)
    
    # Euclidean distance should be >= heuristic (or equal)
    # For Euclidean heuristic, should be exact
    assert h == ((10**2 + 10**2)**0.5)
```

### 5.2 Integration Tests

```python
# Test with mock drone and route planner

def test_route_planner_fallback_chain():
    """Route planner tries Direct → Altitude → A* in order."""
    
    # Setup: Building blocking direct path
    world_state = {
        'buildings': [
            Building(id=0, cx=10, cz=0, w=4, d=4, h=10)
        ]
    }
    
    from_xyz = (0, 15, 0)
    to_xyz = (20, 15, 0)
    
    # Call plan_route()
    path = plan_route(from_xyz, to_xyz, altitude=15.0)
    
    # Should succeed via one of the fallbacks
    assert path is not None
    assert len(path) >= 2
    
    # Verify no collisions
    for i in range(len(path)-1):
        assert not WORLD.obstacles_in_path(*path[i], *path[i+1])
```

---

## Part 6: Implementation Roadmap

### Phase 1: Core A* (Week 1–2)
1. **Create** `backend/services/navigation/a_star.py` with:
   - `Grid2D` class
   - `AStarPathfinder` class
   - Unit tests for grid & A* algorithm

2. **Update** `backend/services/navigation/route_planner.py`:
   - Add `AStarPlanner` integration
   - Modify `plan_route()` fallback chain
   - Update tests in `tests/test_plan_route.py`

3. **Verify**:
   - All existing tests pass
   - New A* tests pass
   - Integration tests validate fallback chain

### Phase 2: Advanced Features (Week 3–4)
1. **Weighted costs**: Proximity penalties, corridor avoidance
2. **Fleet optimization**: A* + assignment algorithm
3. **Window sequencing**: TSP on window approaches
4. **Performance tuning**: Cache grid, prune distant cells

### Phase 3: Refinement & Deployment (Week 5–6)
1. **Telemetry**: Log A* metrics (grid cells explored, distance savings)
2. **UI visualization**: Show path in R3F digital twin
3. **Performance testing**: Benchmark on large obstacle fields
4. **Deployment**: Roll out with feature flags

---

## Part 7: Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **2D grid (XZ plane)** | Altitude is handled separately via escalation; simplifies search space and computation |
| **1m cell size** | Balances resolution (building margins ~2.5m) with memory/speed; adjustable per config |
| **8-neighbors + diagonals** | Allows more natural paths vs. 4-neighbors; cost formula handles diagonal penalty |
| **Euclidean heuristic** | Admissible, efficient; Manhattan alternative for speed if needed |
| **Lazy grid rebuild** | Rebuild only on world changes; cache reduces per-call overhead |
| **Fallback chain** | A* is Phase 1; altitude escalation remains as fast path for common cases |
| **No dynamic obstacles** | Plan assumes static world; drones don't replan mid-flight (scope for future) |

---

## Part 8: Failure Modes & Recovery

| Scenario | Current Behavior | A* Improvement |
|----------|------------------|-----------------|
| **Direct path blocked** | Retry +5m altitude | Fast detection; escalate immediately vs. ray-casting |
| **Around detour fails** | Give up / timeout | A* finds *all* feasible paths; more robust |
| **Complex maze** | Altitude escalation exhausted | A* navigates horizontal space optimally |
| **Unreachable goal** | Timeout | A* terminates early with definite "no path" |
| **Real-time replanning** | Not supported (scope for Phase 2) | A* grid can be reused for fast replans |

---

## Part 9: File Structure

```
backend/
├── services/navigation/
│   ├── route_planner.py        # MODIFIED: Add A* fallback
│   ├── a_star.py               # NEW: Grid2D, AStarPathfinder, AStarPlanner
│   └── __init__.py
├── orchestrator/
│   └── navigation.py           # MODIFIED: Export AStarPlanner to agents
└── agents/
    └── navigation.py           # MODIFIED: Doc updates on A* availability

tests/
├── test_plan_route.py          # MODIFIED: Add A* fallback tests
├── test_a_star_pathfinding.py  # NEW: Unit + integration tests
└── test_fleet_orchestration.py # MODIFIED (Phase 2): Fleet optimization tests
```

---

## Part 10: Success Criteria

- ✅ A* finds collision-free paths in all tested scenarios
- ✅ A* paths are ≤ 20% longer than optimal (near-optimality)
- ✅ Fallback chain completes <500ms for typical 50m×50m scenes
- ✅ Grid memory usage <10MB for 100×100 cell grid
- ✅ All existing tests pass (backward compatibility)
- ✅ New tests achieve ≥80% code coverage for A* module

---

## Part 11: Future Extensions

1. **Dynamic obstacles**: Recompute grid incrementally as drones/obstacles move
2. **Bidirectional A***: Search from both start and goal simultaneously
3. **Jump point search (JPS)**: Faster A* variant on uniform-cost grids
4. **Theta***: Any-angle pathfinding (not restricted to grid edges)
5. **Weighted A***: Trade optimality for speed (useful for real-time replanning)
6. **Cooperative A***: Multi-drone conflict-free paths via temporal A*

---

## References

- A* Algorithm: Hart, Nilsson, & Raphael (1968)
- Admissible Heuristics: Consistentcy & optimality requirements
- Grid-based pathfinding: Sturtevant & Buro (2005)
