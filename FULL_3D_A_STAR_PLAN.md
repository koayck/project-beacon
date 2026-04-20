# Full 3D A* Pathfinding Implementation Plan for Project Beacon

## Executive Summary

This plan replaces the **altitude escalation fallback** (`try Y+5m, Y+10m, Y+15m`) with a **unified 3D A* algorithm** that simultaneously optimizes horizontal (XZ) and vertical (Y) movement. Instead of trying fixed altitude increments, the planner explores the full 3D space to find the genuinely shortest path around obstacles.

**Trade-off**: More computation (~50× grid) but better paths, especially for:
- Complex multi-building environments (your world has 5 buildings)
- Tight corridors where altitude must adjust mid-path
- Battery optimization (find lowest-cost altitude per segment)
- Insurance against altitude escalation exhaustion

---

## Part 1: Why Replace Altitude Escalation?

### Current Approach Limitations

**Scenario**: Drone at (0, 15, 0) targeting (-15, 15, -20) with buildings in between.

```bash
Current logic:
  Try Y=15m → blocked by building (height 12m)
  Try Y=20m → blocked (building extends to 12m, but need margin → 14.5m)
  Try Y=25m → SUCCESS! Path found.
  
Problem: What if there's a narrow canyon where:
  - Y=15m: blocked by two buildings approaching each other
  - Y=20m: blocked by merged building heights
  - Y=25m: blocked by tall tower (21m tall)
  - Y=30m: actually clear, but we gave up at Y=25m
```

### Full 3D A* Advantages

```bash
3D A* explores ALL paths:
  - Swerve left at Y=20m, climb to Y=25m mid-turn, descend on far side
  - Find natural "corridor" between buildings at Y=18m
  - Discover that going around the base (Y=15m) is actually viable with 10m detour
  - Pick the OPTIMAL path by total distance, not first that clears a fixed altitude
```

### Your Real-World Complexity

Looking at your `world.json`:

```
Buildings:
  - target (id=0):      h=12m, center at (-15, -20)
  - obstacle (id=1):    h=10m, center at (-7, -10)    ← between start & target
  - balcony (id=2):     h=9m,  center at (20, -20)
  - shophouse (id=3):   h=9m,  center at (12, -27)
  - nw_tower (id=4):    h=21m, center at (-28, -28)   ← TALL, complex escapes
```

**Example**: Route from (0, 15, 0) to target building at (-15, -20):
- **Altitude escalation** might fail if Y=30m isn't enough to clear combined obstacles
- **3D A*** would find natural altitude variations around each building

---

## Part 2: 3D Grid Architecture

### 2.1 Volumetric Grid Construction

```python
class Grid3D:
    """Full 3D voxel grid for pathfinding."""
    
    def __init__(self, 
                 bounds_xz: Tuple[float, float, float, float],  # (min_x, max_x, min_z, max_z)
                 altitude_range: Tuple[float, float],            # (min_y, max_y)
                 cell_size: float,
                 obstacles: List[Building],
                 config: GridConfig):
        """
        bounds_xz: bounding box in horizontal plane
        altitude_range: (min_altitude, max_altitude) to explore, e.g., (3m, 50m)
        cell_size: 1.0m typical (same as 2D)
        obstacles: list of buildings with AABBs
        config: building_margin, floor_height, etc.
        """
        self.cell_size = cell_size
        self.bounds_xz = bounds_xz
        self.altitude_range = altitude_range
        
        # Grid dimensions
        self.width = int((bounds_xz[1] - bounds_xz[0]) / cell_size)
        self.depth = int((bounds_xz[3] - bounds_xz[2]) / cell_size)
        self.height = int((altitude_range[1] - altitude_range[0]) / cell_size)
        
        # 3D walkability array: walkable[y][z][x]
        # Initialize as all walkable, then carve out obstacles
        self.walkable = [
            [[True] * self.width for _ in range(self.depth)]
            for _ in range(self.height)
        ]
        
        # Mark obstacle voxels as unwalkable
        for building in obstacles:
            self._mark_obstacle_voxels(building, config)
    
    def _mark_obstacle_voxels(self, building: Building, config: GridConfig):
        """
        Expand building AABB by margin, mark all voxels within as unwalkable.
        
        Building spans:
          - XZ: (cx ± w/2, cz ± d/2) with margin
          - Y:  (0, h) with margin
        """
        margin = config.building_proximity_margin_m
        
        # Padded building bounds
        min_x = building.cx - building.w/2 - margin
        max_x = building.cx + building.w/2 + margin
        min_z = building.cz - building.d/2 - margin
        max_z = building.cz + building.d/2 + margin
        min_y = 0  # Buildings sit on ground
        max_y = building.h + margin  # Above buildings is clear
        
        # Convert world coords to grid indices
        (gx_min, gx_max) = self._world_x_to_grid_range(min_x, max_x)
        (gz_min, gz_max) = self._world_z_to_grid_range(min_z, max_z)
        (gy_min, gy_max) = self._world_y_to_grid_range(min_y, max_y)
        
        # Mark voxels
        for gy in range(max(0, gy_min), min(self.height, gy_max + 1)):
            for gz in range(max(0, gz_min), min(self.depth, gz_max + 1)):
                for gx in range(max(0, gx_min), min(self.width, gx_max + 1)):
                    self.walkable[gy][gz][gx] = False
    
    def world_to_grid(self, x: float, y: float, z: float) -> Tuple[int, int, int]:
        """Convert world XYZ to grid cell indices."""
        gx = int((x - self.bounds_xz[0]) / self.cell_size)
        gy = int((y - self.altitude_range[0]) / self.cell_size)
        gz = int((z - self.bounds_xz[2]) / self.cell_size)
        return (gx, gy, gz)
    
    def grid_to_world(self, gx: int, gy: int, gz: int) -> Tuple[float, float, float]:
        """Convert grid indices to world XYZ (cell centers)."""
        x = self.bounds_xz[0] + (gx + 0.5) * self.cell_size
        y = self.altitude_range[0] + (gy + 0.5) * self.cell_size
        z = self.bounds_xz[2] + (gz + 0.5) * self.cell_size
        return (x, y, z)
    
    def is_walkable(self, gx: int, gy: int, gz: int) -> bool:
        """Check if voxel is passable."""
        if not (0 <= gx < self.width and 0 <= gy < self.height and 0 <= gz < self.depth):
            return False
        return self.walkable[gy][gz][gx]
    
    def neighbors_3d(self, gx: int, gy: int, gz: int, 
                     prefer_horizontal: bool = True) -> List[Tuple[int, int, int]]:
        """
        26-neighbor 3D connectivity (3×3×3 cube around cell, minus center).
        
        prefer_horizontal=True: Penalize steep climbs (weight diagonal moves higher)
        """
        neighbors = []
        
        # Cardinal + diagonal directions in 3D
        # dx, dy, dz with optional preference for horizontal over vertical
        directions = []
        
        # Horizontal moves (cardinal & diagonal in XZ) — preferred, low cost
        for dx in [-1, 0, 1]:
            for dz in [-1, 0, 1]:
                if dx != 0 or dz != 0:  # Skip center
                    directions.append((dx, 0, dz, "horizontal"))
        
        # Vertical-only moves — higher cost to discourage unnecessary climbing
        for dy in [-1, 1]:
            directions.append((0, dy, 0, "vertical"))
        
        # Mixed vertical-horizontal — medium cost
        for dx in [-1, 0, 1]:
            for dz in [-1, 0, 1]:
                for dy in [-1, 1]:
                    if (dx != 0 or dz != 0) and dy != 0:  # Mixed move
                        directions.append((dx, dy, dz, "mixed"))
        
        for dx, dy, dz, move_type in directions:
            nx, ny, nz = gx + dx, gy + dy, gz + dz
            if self.is_walkable(nx, ny, nz):
                neighbors.append((nx, ny, nz))
        
        return neighbors
    
    def _world_x_to_grid_range(self, min_x: float, max_x: float) -> Tuple[int, int]:
        """Convert world X range to grid cell range."""
        gx_min = int((min_x - self.bounds_xz[0]) / self.cell_size)
        gx_max = int((max_x - self.bounds_xz[0]) / self.cell_size)
        return (gx_min, gx_max)
    
    def _world_z_to_grid_range(self, min_z: float, max_z: float) -> Tuple[int, int]:
        """Convert world Z range to grid cell range."""
        gz_min = int((min_z - self.bounds_xz[2]) / self.cell_size)
        gz_max = int((max_z - self.bounds_xz[2]) / self.cell_size)
        return (gz_min, gz_max)
    
    def _world_y_to_grid_range(self, min_y: float, max_y: float) -> Tuple[int, int]:
        """Convert world Y (altitude) range to grid cell range."""
        gy_min = int((min_y - self.altitude_range[0]) / self.cell_size)
        gy_max = int((max_y - self.altitude_range[0]) / self.cell_size)
        return (gy_min, gy_max)
```

### 2.2 Movement Cost Function (3D)

```python
def movement_cost_3d(self, pos1: Tuple[int, int, int], 
                     pos2: Tuple[int, int, int],
                     factors: Dict[str, float] = None) -> float:
    """
    Cost to move from pos1 to pos2 in 3D grid.
    
    Encourages horizontal movement, penalizes unnecessary vertical.
    
    factors:
      horizontal_weight: cost multiplier for horizontal moves (default 1.0)
      vertical_weight: cost multiplier for pure vertical (default 2.0)
      diagonal_weight: cost for diagonal XZ (default 1.41)
      mixed_weight: cost for vertical+horizontal (default 2.0)
    """
    if factors is None:
        factors = {
            'horizontal_weight': 1.0,
            'vertical_weight': 2.0,
            'diagonal_weight': 1.41,
            'mixed_weight': 2.0,
        }
    
    dx = abs(pos1[0] - pos2[0])
    dy = abs(pos1[1] - pos2[1])
    dz = abs(pos1[2] - pos2[2])
    
    base_cost = self.cell_size
    
    # Classify move type
    if dy == 0:  # Horizontal only
        if dx == 1 and dz == 1:  # Diagonal in XZ
            return base_cost * factors['diagonal_weight']
        else:  # Cardinal in XZ
            return base_cost * factors['horizontal_weight']
    
    elif dx == 0 and dz == 0:  # Vertical only
        return base_cost * factors['vertical_weight']
    
    else:  # Mixed: vertical + horizontal
        return base_cost * factors['mixed_weight']
```

---

## Part 3: Full 3D A* Algorithm

```python
import heapq
from dataclasses import dataclass

@dataclass
class Node3D:
    pos: Tuple[int, int, int]  # (grid_x, grid_y, grid_z)
    g_cost: float
    h_cost: float
    
    def f_cost(self) -> float:
        return self.g_cost + self.h_cost
    
    def __lt__(self, other: "Node3D") -> bool:
        return self.f_cost() < other.f_cost()

class AStarPathfinder3D:
    """Full 3D A* pathfinding."""
    
    def __init__(self, grid: Grid3D):
        self.grid = grid
    
    def heuristic_3d(self, pos1: Tuple[int, int, int], 
                     pos2: Tuple[int, int, int]) -> float:
        """
        3D Euclidean distance heuristic (admissible).
        
        Note: For uniform-cost grids, Manhattan distance is also admissible
        and sometimes faster (especially for grid-based movement).
        This implementation uses Euclidean for optimality.
        """
        dx = pos1[0] - pos2[0]
        dy = pos1[1] - pos2[1]
        dz = pos1[2] - pos2[2]
        return (dx**2 + dy**2 + dz**2)**0.5
    
    def find_path_3d(self, start: Tuple[float, float, float],
                     goal: Tuple[float, float, float],
                     max_iterations: int = 50000) -> Optional[List[Tuple[float, float, float]]]:
        """
        Find shortest 3D path from start to goal.
        
        Args:
            start, goal: (x, y, z) world coordinates
            max_iterations: Safety limit to prevent infinite loops
        
        Returns:
            List of 3D waypoints, or None if no path exists.
        """
        # Convert to grid
        start_grid = self.grid.world_to_grid(*start)
        goal_grid = self.grid.world_to_grid(*goal)
        
        # Validate start/goal walkable
        if not self.grid.is_walkable(*start_grid) or not self.grid.is_walkable(*goal_grid):
            return None
        
        # A* search with iteration limit
        open_set = []
        closed_set = set()
        came_from = {}
        g_costs = {start_grid: 0.0}
        
        start_node = Node3D(
            pos=start_grid,
            g_cost=0.0,
            h_cost=self.heuristic_3d(start_grid, goal_grid)
        )
        heapq.heappush(open_set, start_node)
        
        iterations = 0
        while open_set and iterations < max_iterations:
            iterations += 1
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
            
            for neighbor in self.grid.neighbors_3d(*current.pos):
                if neighbor in closed_set:
                    continue
                
                tentative_g = g_costs[current.pos] + self.grid.movement_cost_3d(
                    current.pos, neighbor
                )
                
                if neighbor not in g_costs or tentative_g < g_costs[neighbor]:
                    came_from[neighbor] = current.pos
                    g_costs[neighbor] = tentative_g
                    h = self.heuristic_3d(neighbor, goal_grid)
                    neighbor_node = Node3D(
                        pos=neighbor,
                        g_cost=tentative_g,
                        h_cost=h
                    )
                    heapq.heappush(open_set, neighbor_node)
        
        # No path found
        return None
```

---

## Part 4: Integration with Existing Navigation

### 4.1 Simplified Route Planner (3D A* Only)

```python
# File: backend/services/navigation/route_planner.py (REVISED)

def plan_route(from_xyz, to_xyz, max_altitude=50.0):
    """
    SIMPLIFIED: Direct → 3D A* → Fail
    
    No intermediate altitude escalation; A* handles vertical exploration.
    """
    # 1. TRY DIRECT (fast ray-cast check)
    if not WORLD.obstacles_in_path(from_xyz[0], from_xyz[1], from_xyz[2],
                                     to_xyz[0], to_xyz[1], to_xyz[2]):
        return [from_xyz, to_xyz]
    
    # 2. TRY FULL 3D A* (NEW)
    planner_3d = AStarPlanner3D(WORLD)
    path_3d = planner_3d.plan_in_3d(
        start_xyz=from_xyz,
        goal_xyz=to_xyz,
        max_altitude=max_altitude
    )
    
    if path_3d:
        return path_3d
    
    # 3. FAIL
    raise NavigationException(f"No 3D path found from {from_xyz} to {to_xyz}")
```

### 4.2 New Wrapper Class

```python
# File: backend/services/navigation/a_star_3d.py (NEW)

class AStarPlanner3D:
    """
    Public interface for full 3D A* pathfinding.
    Replaces altitude escalation + 2D A* with unified 3D search.
    """
    
    def __init__(self, world_model):
        self.world_model = world_model
        self._grid_cache = None
        self._grid_seed = None
    
    def plan_in_3d(self, start_xyz: Tuple[float, float, float],
                   goal_xyz: Tuple[float, float, float],
                   max_altitude: float = 50.0) -> Optional[List[Tuple[float, float, float]]]:
        """
        Main entry point: Full 3D A* search.
        
        Args:
            start_xyz, goal_xyz: (x, y, z) start and target
            max_altitude: Maximum altitude to explore (e.g., 50m)
        
        Returns:
            List of 3D waypoints optimizing for shortest path, or None.
        """
        # Get or build 3D grid
        min_y = self.world_model.compute_min_flight_altitude()  # e.g., 3m (floor height)
        grid = self._get_or_build_grid(max_altitude=max_altitude)
        
        pathfinder = AStarPathfinder3D(grid)
        path = pathfinder.find_path_3d(start_xyz, goal_xyz)
        
        return path
    
    def _get_or_build_grid(self, max_altitude: float) -> Grid3D:
        """Lazy-load 3D grid; rebuild if world changed."""
        world_seed = hash(tuple(
            (b.cx, b.cz, b.w, b.d, b.h) 
            for b in self.world_model.buildings
        ))
        
        if self._grid_cache is None or world_seed != self._grid_seed:
            bounds_xz = self.world_model.compute_scene_bounds()
            altitude_range = (3.0, max_altitude)  # Floor to max_altitude
            
            config = GridConfig(
                building_proximity_margin_m=2.0,
                cell_size=1.0
            )
            
            self._grid_cache = Grid3D(
                bounds_xz=bounds_xz,
                altitude_range=altitude_range,
                cell_size=1.0,
                obstacles=self.world_model.buildings,
                config=config
            )
            self._grid_seed = world_seed
        
        return self._grid_cache
```

---

## Part 5: Performance & Memory Analysis

### Grid Size Comparison

For a typical scenario: 100m × 100m XZ area, 3m–50m altitude range

| Approach | Grid Size | Cells | Typical A* Visits | Time (ms) | Memory |
|----------|-----------|-------|-------------------|-----------|--------|
| **2D (XZ only)** | 100×100 | 10K | ~100K | 50–100 | 10KB |
| **Altitude escalation (fixed Y)** | 100×100×3 | 30K | ~300K | 150–300 | 30KB |
| **3D A* (full)** | 100×100×50 | 500K | ~2–5M | 500–2000 | 500KB |

**Your world scenario**:
- Bounds: ~60m × 60m (buildings span -30 to +20 in X, -30 to +5 in Z)
- With margins: ~80m × 80m safe space
- 3D grid at 1m resolution: **80×80×47 ≈ 300K cells**
- Expected A* visits: **500K–1.5M nodes** ≈ **500–1500ms**

### Optimization Strategies

```python
# STRATEGY 1: Reduce cell size near ground, coarsen at altitude
class AdaptiveGrid3D(Grid3D):
    """Variable-resolution grid: fine near obstacles, coarse at high altitudes."""
    
    def _world_y_to_grid_range(self, min_y: float, max_y: float):
        # Y < 20m: 0.5m cells (detailed)
        # Y >= 20m: 2m cells (coarse, few obstacles at altitude)
        ...

# STRATEGY 2: A* with pruning (close node limit)
# Stop if open_set grows beyond threshold, use best-so-far path
if len(open_set) > 10000:
    # Return best path found so far (even if not optimal)
    return best_path_so_far

# STRATEGY 3: Jump Point Search (JPS)
# Preprocesses grid to skip unnecessary nodes
# ~10× speedup for uniform grids, 3D variant available
```

---

## Part 6: Testing Strategy

### Unit Tests

```python
# File: tests/test_a_star_3d.py (NEW)

def test_3d_a_star_direct_path():
    """Simple straight-line path in 3D."""
    world = WorldModel(buildings=[])
    planner = AStarPlanner3D(world)
    
    path = planner.plan_in_3d(
        start_xyz=(0, 15, 0),
        goal_xyz=(20, 15, 0)
    )
    assert len(path) >= 2
    assert path[-1] == (20, 15, 0)

def test_3d_a_star_over_building():
    """Drone climbs over single building."""
    building = Building(id=0, cx=10, cz=0, w=4, d=4, h=10)
    world = WorldModel(buildings=[building])
    planner = AStarPlanner3D(world)
    
    path = planner.plan_in_3d(
        start_xyz=(0, 15, 0),
        goal_xyz=(20, 15, 0)
    )
    
    assert path is not None
    # Should climb over building
    max_y = max(p[1] for p in path)
    assert max_y > 15  # Higher than start altitude
    
    # Check no collisions
    for i in range(len(path)-1):
        assert not world.obstacles_in_path(*path[i], *path[i+1])

def test_3d_a_star_complex_maze():
    """Navigate complex multi-building environment."""
    buildings = [
        Building(id=0, cx=-15, cz=-20, w=8, d=8, h=12),  # Target
        Building(id=1, cx=-7, cz=-10, w=6, d=5, h=10),   # Obstacle
        Building(id=4, cx=-28, cz=-28, w=10, d=10, h=21),  # Tall tower
    ]
    world = WorldModel(buildings=buildings)
    planner = AStarPlanner3D(world)
    
    # Route from outside to target building
    path = planner.plan_in_3d(
        start_xyz=(0, 15, 0),
        goal_xyz=(-15, 15, -20)
    )
    
    assert path is not None
    assert len(path) > 2  # Non-trivial path
    
    # Verify collision-free
    for i in range(len(path)-1):
        assert not world.obstacles_in_path(*path[i], *path[i+1])

def test_3d_grid_voxel_marking():
    """Grid correctly marks obstacle voxels."""
    building = Building(id=0, cx=10, cz=10, w=10, d=10, h=15)
    grid = Grid3D(
        bounds_xz=(-50, 50, -50, 50),
        altitude_range=(3, 50),
        cell_size=1.0,
        obstacles=[building],
        config=GridConfig()
    )
    
    # Voxel inside building should be unwalkable
    vx, vy, vz = grid.world_to_grid(10, 8, 10)  # Inside building at Y=8m
    assert not grid.is_walkable(vx, vy, vz)
    
    # Voxel above building should be walkable
    vx, vy, vz = grid.world_to_grid(10, 30, 10)  # At Y=30m (above building)
    assert grid.is_walkable(vx, vy, vz)

def test_3d_movement_cost_horizontal_preferred():
    """Horizontal moves should have lower cost than vertical."""
    grid = Grid3D(
        bounds_xz=(-50, 50, -50, 50),
        altitude_range=(3, 50),
        cell_size=1.0,
        obstacles=[],
        config=GridConfig()
    )
    
    # Same distance, different direction
    h_cost = grid.movement_cost_3d((0, 0, 0), (1, 0, 0))  # Horizontal
    v_cost = grid.movement_cost_3d((0, 0, 0), (0, 1, 0))  # Vertical
    
    assert h_cost < v_cost  # Prefer horizontal
```

### Integration Tests

```python
def test_route_planner_fallback_3d():
    """Route planner uses Direct → 3D A* chain."""
    world_state = {
        'buildings': [
            Building(id=1, cx=-7, cz=-10, w=6, d=5, h=10)
        ]
    }
    
    from_xyz = (0, 15, 0)
    to_xyz = (-15, 15, -20)
    
    # Call plan_route()
    path = plan_route(from_xyz, to_xyz)
    
    assert path is not None
    assert len(path) >= 2
    
    # No collisions
    for i in range(len(path)-1):
        assert not WORLD.obstacles_in_path(*path[i], *path[i+1])
```

---

## Part 7: Implementation Roadmap

### Phase 1: Core 3D Grid & A* (Week 1–2)

1. **Create** `backend/services/navigation/a_star_3d.py`:
   - `Grid3D` class with 3D voxel marking
   - `AStarPathfinder3D` with 3D neighbors & movement cost
   - `AStarPlanner3D` wrapper

2. **Update** `backend/services/navigation/route_planner.py`:
   - Simplify `plan_route()` to `Direct → 3D A*`
   - Remove altitude escalation loop

3. **Tests**: All unit & integration tests pass

### Phase 2: Performance Optimization (Week 2–3)

1. **Adaptive grid**: Variable resolution by altitude
2. **Jump Point Search (JPS)**: Optional speedup
3. **Pruning**: Limit open_set size for soft real-time
4. **Benchmarking**: Profile on your world.json

### Phase 3: Advanced Features (Week 3–4)

1. **Weighted A***: Trade distance for speed (replanning)
2. **Bidirectional A***: Search from both ends
3. **Path smoothing**: Remove unnecessary waypoints
4. **Telemetry**: Log exploration metrics

### Phase 4: Deployment (Week 4–5)

1. **Feature flag**: A/B test 3D A* vs. old method
2. **Telemetry comparison**: Path length, time, altitude usage
3. **UI visualization**: Show 3D path in R3F
4. **Rollout**: Default to 3D once stable

---

## Part 8: Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **26-neighbor connectivity** | Allows diagonal+vertical moves; more realistic than 4/6-neighbor |
| **Movement cost weighting** | Penalize pure vertical (cost 2.0) vs. horizontal (cost 1.0) to prefer efficient paths |
| **1m cell size** | Matches building margins (~2m), fine enough for detail; coarsenable at altitude |
| **Euclidean heuristic** | Admissible for 3D; can swap for Manhattan if needed |
| **Lazy grid rebuild** | Cache valid until world changes; avoids per-call overhead |
| **50m max altitude** | Reasonable for SAR; configurable; can escape most buildings |
| **Direct → 3D A* chain** | Direct path fast-path; A* for complex scenarios |

---

## Part 9: Trade-offs vs. 2D Hybrid

| Aspect | 2D Hybrid | Full 3D |
|--------|-----------|---------|
| **Computation** | ~100K nodes | ~2M nodes (20×) |
| **Optimality** | Good (if altitude escalation hits) | Optimal* |
| **Path quality** | Fixed altitudes (rigid) | Natural altitude variation (smooth) |
| **Memory** | ~10KB grid | ~500KB grid |
| **Latency** | 50–100ms | 500–2000ms |
| **Battery cost** | Higher (fixed altitude overfly) | Lower (variable altitude) |
| **Failure recovery** | Limited (max altitude bounds) | Better (explores all altitudes) |
| **Complexity** | Lower | Higher |

*Optimal within grid resolution; can smooth for near-optimal continuous paths.

---

## Part 10: Failure Modes & Recovery

| Scenario | Handling |
|----------|----------|
| **Start/goal inside obstacle** | Return `None`, cascade to error handling |
| **Completely enclosed goal** | A* terminates with "no path"; error to user |
| **Open set grows huge** | Pruning: stop early, return best path so far |
| **Max iterations exceeded** | Safety limit: return `None` if >50K iterations |
| **Tall tower blocks all paths** | Explore up to max_altitude; if still blocked, fail cleanly |
| **Altitude limit too low** | User provides `max_altitude=50m`; validate in config |

---

## Part 11: Success Criteria

- ✅ 3D A* finds collision-free paths in all scenarios
- ✅ Paths are near-optimal (within 5% of true shortest)
- ✅ Latency <1s for typical 60×60m scenes on modest hardware
- ✅ Memory usage <1MB for grid storage
- ✅ Backward compatible: existing tests pass
- ✅ Coverage ≥80% for A* module
- ✅ Telemetry shows improvement over altitude escalation (shorter paths, lower battery)

---

## Part 12: Migration Path

### Step 1: Parallel Deployment
- Keep old `plan_route()` (altitude escalation)
- Add new `plan_route_3d()`
- Feature flag to switch

### Step 2: Validation Phase
- Flight tests with 3D A* enabled
- Log both old & new paths, compare metrics
- Collect telemetry: path length, altitude, battery drain

### Step 3: Cutover
- Once 3D A* proves superior, default to it
- Option to fall back to old method via config
- Document in release notes

### Step 4: Cleanup (Phase 2)
- Deprecate altitude escalation code after 2–3 releases
- Simplify route planner

---

## Part 13: Future Extensions

1. **Theta***: Any-angle pathfinding (paths aren't restricted to grid edges)
2. **RRT* (Rapidly-exploring Random Trees)**: Probabilistic variant for very large spaces
3. **Dynamic A***: Recompute incrementally as world changes
4. **Cooperative A***: Multi-drone conflict-free paths
5. **Weighted A***: Balance speed vs. optimality at runtime

---

## References

- A* Algorithm: Hart, Nilsson, & Raphael (1968)
- 3D Pathfinding: Akenine-Möller, Haines, & Hoffman (2018), "Real-Time Rendering"
- Jump Point Search: Online et al. (2011)
- Theta*: Nash, Koenig, & Tovey (2007)
