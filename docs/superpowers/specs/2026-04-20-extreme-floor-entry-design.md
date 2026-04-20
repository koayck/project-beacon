# Extreme-Floor Entry & Directional Sweep Design

**Date:** 2026-04-20
**Status:** Approved for implementation planning
**Scope:** `backend/services/navigation/route_planner.py`, `backend/services/navigation/sweep_planner.py`, `backend/services/navigation/a_star_3d.py`, `backend/services/workflows/sweep_workflow.py`

## Problem

Despite the existing 3D A* implementation and window-waypoint selection logic, drones sometimes clip the wall of a target building during building approach and vertical sweep. Two root causes have been identified:

1. **Middle-floor window entries create narrow approach corridors.** The current `select_window_waypoint` biases toward matching the drone's current altitude (`preferred_y`), which tends to pick middle-floor windows. These are boxed in by floors above and balconies below, so A* must thread a tight path that `_simplify_path` then collapses — sometimes grazing a corner.
2. **`_simplify_path` uses the same `margin` as planning.** A straight line between two voxels that each sit exactly `margin` metres from a wall can cut up to `cell_size / 2` closer on a diagonal, dipping below the planning margin.

## Goal

Reduce wall-clipping incidents during building approach and sweep, and make the sweep direction match the drone's approach direction (top-down if entering high, bottom-up if entering low).

## Non-goals

- Changing the A* cost function or neighborhood (still 26-connected, Euclidean).
- Changing the obstacle-clearance margin for planning itself (still 1.0m).
- Refactoring the sweep's serpentine ring logic.
- Altering existing callers that do not opt in to the new entry mode.

## Design

### 1. `plan_route` — new `entry_mode` parameter

**Location:** `backend/services/navigation/route_planner.py`

Add an opt-in parameter that restricts window-waypoint candidates to the lowest- and highest-floor windows only, and picks by 3D Euclidean distance to the drone's current position.

```python
async def plan_route(
    asset_id: str,
    target_x: float,
    target_z: float,
    target_y: float | None = None,
    snap_to_building_center: bool = False,
    exclude_building_id: int | None = None,
    entry_mode: Literal["nearest_floor", "extreme_floor"] = "nearest_floor",
) -> dict:
```

**Behavior when `entry_mode="extreme_floor"` AND `snap_to_building_center=True` AND the nearby building has windows:**

1. Fetch `available_window_waypoints = nearby.window_scan_waypoints(...)` as today.
2. Group waypoints by their `floor` field.
3. Compute `lowest_floor = min(floors)`, `highest_floor = max(floors)`.
4. Build `candidates = [wp for wp in available_window_waypoints if wp["floor"] in {lowest_floor, highest_floor}]`.
5. For each candidate, compute 3D Euclidean distance from the drone's `(cx, cy, cz)`.
6. Pick the candidate with minimum distance. When iterating, process lowest-floor candidates first so that ties resolve deterministically to `"lowest"`.
7. Set `target_x, target_y, target_z` to the chosen candidate's coordinates.
8. Record `entry_floor_kind` in `target_resolution` (`"lowest"` or `"highest"`; coerced to `"lowest"` when `lowest_floor == highest_floor`).

**Fallbacks:**

- `entry_mode="extreme_floor"` but no candidates (building has no windows, or all windows excluded): behave as if `entry_mode="nearest_floor"` — snap to building center, no window waypoint chosen. Record `entry_mode_fallback=True` in `target_resolution`.
- `entry_mode="extreme_floor"` but `snap_to_building_center=False`: `entry_mode` is ignored (documented in docstring).

**Default behavior (`entry_mode="nearest_floor"`):** byte-identical to today. All existing callers (`supply_workflow`, `return_workflow`, direct orchestrator calls) are untouched.

**`target_resolution` output additions (only when the extreme-floor pick succeeds):**

```python
"entry_mode": "extreme_floor",
"entry_floor_kind": "lowest" | "highest",
```

### 2. `plan_building_vertical_sweep` — new `entry_floor` parameter

**Location:** `backend/services/navigation/sweep_planner.py`

```python
def plan_building_vertical_sweep(
    target_x: float,
    target_z: float,
    level_step: float = 3.0,
    standoff: float = 2.0,
    flood_clearance: float = 0.5,
    approach_x: float | None = None,
    approach_z: float | None = None,
    entry_floor: Literal["lowest", "highest"] = "lowest",
) -> dict:
```

**Behavior change:**

1. Compute `floor_levels = sorted({round(w["y"], 2) for w in above_flood})` (ascending) as today.
2. If `entry_floor == "highest"`, reverse it: `floor_levels = list(reversed(floor_levels))`.
3. The existing entry-window selection (finds the `first_level_windows` closest to `(approach_x, approach_z)`) operates on `floor_levels[0]` — which, after the optional reverse, is the top floor when `entry_floor="highest"`. Because the sweep workflow passes the drone's current XZ (already at the `plan_route`-chosen entry window) as `approach_x/approach_z`, the sweep's own selection resolves to the same window by minimum-distance — no extra parameter needed to reconcile the two selections.
4. The serpentine ring logic, inter-floor climb handling, and final rooftop ascent are **unchanged**. We are only changing the iteration order of `floor_levels`.

**Rooftop wrap-up:** The final "ascent to rooftop altitude" + "rooftop scan" waypoints are unchanged. For top-down sweeps, the drone descends through floors and then ascends from the final bottom-floor corner to `rooftop_y`. This ascent is short but still ensures every mission ends on the roof, matching the return_workflow's assumptions.

### 3. Workflow plumbing — `sweep_workflow`

**Location:** `backend/services/workflows/sweep_workflow.py`

The sweep workflow already calls `plan_route_fn` at line 120 for transitions between scans. Add a **pre-sweep route call** that selects the extreme-floor entry window, then forward `entry_floor_kind` into the sweep call.

Rough shape (actual implementation details deferred to the implementation plan):

```python
route = await plan_route_fn(
    asset_id,
    target_x,
    target_z,
    snap_to_building_center=True,
    entry_mode="extreme_floor",
)
entry_floor_kind = (
    route.get("target_resolution", {}).get("entry_floor_kind", "lowest")
)

plan = plan_building_vertical_sweep(
    target_x=target_x,
    target_z=target_z,
    level_step=level_step,
    standoff=standoff,
    approach_x=status.get("x"),
    approach_z=status.get("z"),
    entry_floor=entry_floor_kind,
)
```

The `approach_x/approach_z` remain the drone's current XZ position so the serpentine start corner is still picked correctly. `entry_floor` tells the sweep which extreme to begin at.

### 4. `_simplify_path` margin hardening

**Location:** `backend/services/navigation/a_star_3d.py`

Pass a stricter margin to `_segment_clear` calls made during path simplification. Planning margin is unchanged.

```python
def _simplify_path(
    world: object,
    points: list[tuple[float, float, float]],
    margin: float,
    exclude_building_id: int | None,
    *,
    cell_size: float,
) -> list[tuple[float, float, float]]:
    simplify_margin = margin + cell_size / 2
    # ...existing loop, passing simplify_margin to _segment_clear
```

`find_3d_path` passes its own `cell_size` through at the single call site (line 321). No signature change on `find_3d_path` itself.

**Rationale:** A* keeps path voxels at least `margin` metres from walls. A straight line between two such voxels, when taken diagonally, can cut up to `cell_size / 2` closer to a wall corner than the voxel centres themselves. Bumping the simplification margin by `cell_size / 2` absorbs the geometric excess so the simplified segment stays at least `margin` metres from walls along its entire length, not just at endpoints. With defaults (`margin=1.0`, `cell_size=1.0`), the simplification margin becomes `1.5`.

## Edge cases

| Case | Handling |
|------|----------|
| Building has no windows | `plan_route` falls through to current building-center snap. `plan_building_vertical_sweep` falls through to its existing rooftop-only scan (`if not floor_levels` branch). |
| Building has one floor of windows (lowest == highest) | Candidate set is that single floor. `entry_floor_kind="lowest"` for determinism. Sweep iterates the single level; direction is irrelevant. |
| 3D-distance tie between a lowest and highest candidate | Lowest-floor candidates are iterated first; Python's `min` is stable, so tie resolves to `"lowest"`. Deterministic and documented. |
| `entry_mode="extreme_floor"` with `snap_to_building_center=False` | `entry_mode` is ignored. Documented in docstring. |
| Drone already at the chosen window | `plan_route`'s existing `already_at_destination` branch handles it unchanged. |
| Extreme-floor pick fails (e.g. all windows of those floors are somehow filtered out) | `entry_mode_fallback=True` recorded; behaves as `nearest_floor`. |

## API compatibility

- `plan_route`'s new `entry_mode` parameter defaults to `"nearest_floor"`, preserving current behavior for every existing caller.
- `plan_building_vertical_sweep`'s new `entry_floor` parameter defaults to `"lowest"`, preserving current behavior. `sweep_workflow` is the only caller that will opt in initially.
- `find_3d_path`'s signature is unchanged. `_simplify_path` gains an internal `cell_size` kwarg.
- MCP tool definitions (`backend/mcp/server.py`) do not need to expose `entry_mode` — the sweep workflow is the consumer and it's Python-internal.

## Testing approach

Deferred to the implementation plan, but the following coverage is expected:

1. **Unit test — extreme-floor selection:** mock a building with windows on floors 1, 3, 5 (or similar). Place the drone at various positions; verify only floor-1 and floor-5 candidates are considered, and the 3D-closest wins.
2. **Unit test — lowest == highest edge:** single-floor-windows building; verify `entry_floor_kind="lowest"` and the selected waypoint is on that floor.
3. **Unit test — extreme-floor fallback:** building with no windows; verify `entry_mode_fallback=True` and target snaps to building center.
4. **Unit test — sweep direction reversal:** given `entry_floor="highest"`, verify first sweep waypoint is on the top floor, last floor-level waypoint is on the bottom floor, and the plan still ends at `rooftop_y`.
5. **Unit test — `_simplify_path` margin:** construct a path where the planning margin (1.0) passes a simplified diagonal segment but the simplification margin (1.5) rejects it, forcing an intermediate waypoint.
6. **Integration test (optional):** run a sweep against a representative building from the world fixture and confirm no waypoint lies within `margin` of any wall.

## Out of scope

- Changing A*'s planning margin or neighborhood.
- Exposing `entry_mode` in the MCP tool surface.
- Changing `select_window_waypoint`'s existing behavior for callers that don't opt in.
- Adding a `simplify_margin` kwarg to `find_3d_path` (deferred; revisit only if tight inter-building gaps still clip after this change).
