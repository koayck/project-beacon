# Extreme-Floor Entry & Directional Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce wall-clipping during building approach and vertical sweep by constraining entry waypoints to the lowest- or highest-floor windows (drone-closest wins), making the sweep iterate floors in the direction of the entry, and hardening the A* path simplifier against diagonal corner-cuts.

**Architecture:** Three local changes plus one workflow plumbing change. (1) `a_star_3d._simplify_path` uses a stricter margin (`planning_margin + cell_size/2`) than planning. (2) `route_planner.plan_route` gains opt-in `entry_mode="extreme_floor"` that picks the 3D-closest window waypoint from the lowest- or highest-floor set. (3) `sweep_planner.plan_building_vertical_sweep` gains opt-in `entry_floor` to reverse floor iteration order. (4) `sweep_workflow` calls `plan_route` with the new mode first, extracts `entry_floor_kind`, and forwards it to `plan_building_vertical_sweep`. MCP surface and existing non-sweep callers are unchanged.

**Tech Stack:** Python 3.x, pytest, pytest-asyncio, `uv` for dep mgmt. Project uses `from __future__ import annotations`.

**Reference spec:** `docs/superpowers/specs/2026-04-20-extreme-floor-entry-design.md`

---

## File Structure

**Modify:**
- `backend/services/navigation/a_star_3d.py` — `_simplify_path` signature + margin logic; `find_3d_path` passes `cell_size` through
- `backend/services/navigation/route_planner.py` — add `entry_mode` param + extreme-floor selection block
- `backend/services/navigation/sweep_planner.py` — add `entry_floor` param + optional reversal of `floor_levels`
- `backend/services/workflows/sweep_workflow.py` — restructure to call `plan_route` (extreme mode) pre-sweep and forward `entry_floor_kind`

**Create:**
- `tests/test_simplify_path_margin.py` — unit tests for `_simplify_path` margin behavior
- `tests/test_plan_route_extreme_floor.py` — unit tests for new `entry_mode` mode
- `tests/test_sweep_entry_floor.py` — unit tests for `entry_floor` parameter

**Touch (test adjustments):**
- `tests/test_sweep_smart_routing.py` — only if the restructure of sweep_workflow breaks an existing assertion (rerun full suite to detect)

---

## Phase 1 — A* simplifier margin hardening

Independent change that can land on its own. Unlocks safer simplification for all A* callers.

### Task 1: Failing test for `_simplify_path` diagonal corner-cut

**Files:**
- Create: `tests/test_simplify_path_margin.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_simplify_path_margin.py -v`
Expected: FAIL with `TypeError: _simplify_path() got an unexpected keyword argument 'cell_size'`

### Task 2: Add `cell_size` kwarg + simplify margin to `_simplify_path`

**Files:**
- Modify: `backend/services/navigation/a_star_3d.py` (function `_simplify_path` at lines 213-246; call site at line 321)

- [ ] **Step 1: Update `_simplify_path` signature and margin logic**

Replace the existing `_simplify_path` function (lines 213-246) with:

```python
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
```

- [ ] **Step 2: Update the single call site in `find_3d_path`**

In `find_3d_path` (around line 321), change:

```python
return _simplify_path(world, world_path, margin, exclude_building_id)
```

to:

```python
return _simplify_path(world, world_path, margin, exclude_building_id, cell_size=cell_size)
```

- [ ] **Step 3: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_simplify_path_margin.py -v`
Expected: PASS (both tests)

- [ ] **Step 4: Run the existing A* test suite to verify no regressions**

Run: `uv run pytest tests/test_a_star_3d.py -v`
Expected: PASS (all existing tests)

- [ ] **Step 5: Commit**

```bash
git add tests/test_simplify_path_margin.py backend/services/navigation/a_star_3d.py
git commit -m "fix: harden A* path simplifier against diagonal corner-cuts

_simplify_path now uses planning_margin + cell_size/2 for clearance
checks, absorbing the geometric excess of diagonal segments between
voxels that sit exactly at the planning margin.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2 — `plan_route` extreme-floor entry mode

Adds an opt-in entry mode that picks the 3D-closest window waypoint from the lowest- or highest-floor set.

### Task 3: Failing test for extreme-floor candidate set

**Files:**
- Create: `tests/test_plan_route_extreme_floor.py`

- [ ] **Step 1: Write the failing test**

Before writing, confirm the target building's geometry so test expectations match the fixture. Target building (id=0, cx=-15, cz=-20, h=12) has windows at:
- Floor 1 west: sill_y=0.4, y=1.2
- Floor 2 west: sill_y=3.4, y=4.2
- Floor 2 north: sill_y=3.4, y=4.2
- Floor 3 east: sill_y=6.4, y=7.2
- Floor 4 south: sill_y=9.4, y=10.2

`FLOOR_HEIGHT_M=3.0`, `WINDOW_SCAN_STANDOFF_M=4.0`. Lowest floor with windows = 1; highest = 4.

```python
"""Unit tests for plan_route entry_mode='extreme_floor'."""
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


class TestEntryModeExtremeFloor:
    """With entry_mode='extreme_floor', selection restricts to lowest/highest floors only."""

    @pytest.mark.asyncio
    async def test_extreme_floor_picks_from_top_when_drone_is_high(self, _mock_client):
        # Drone placed north-east of the building at roof altitude. The top-floor
        # south-face window is geometrically closest in 3D.
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -15.0, "y": 15.0, "z": -5.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="extreme_floor",
        )
        assert "target_resolution" in result
        tr = result["target_resolution"]
        assert tr.get("entry_mode") == "extreme_floor"
        assert tr.get("entry_floor_kind") == "highest"
        assert "selected_window_waypoint" in tr
        wp = tr["selected_window_waypoint"]
        assert wp["floor"] == 4
        assert wp["y"] == pytest.approx(10.2, abs=0.01)

    @pytest.mark.asyncio
    async def test_extreme_floor_picks_from_bottom_when_drone_is_low(self, _mock_client):
        # Drone placed just west of the building at water-level altitude.
        # The floor-1 west-face window is geometrically closest in 3D.
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -25.0, "y": 2.0, "z": -20.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="extreme_floor",
        )
        tr = result.get("target_resolution", {})
        assert tr.get("entry_floor_kind") == "lowest"
        assert tr["selected_window_waypoint"]["floor"] == 1
        assert tr["selected_window_waypoint"]["y"] == pytest.approx(1.2, abs=0.01)

    @pytest.mark.asyncio
    async def test_extreme_floor_excludes_middle_floor_candidates(self, _mock_client):
        # Drone placed so the legacy (nearest_floor) logic would pick floor 3
        # (y=7.2 is closest to the default preferred_y = h/2 = 6). extreme_floor
        # must instead return floor 1 or 4.
        _mock_client.get_status.return_value = {
            "asset_id": "BEACON-01",
            "x": -15.0, "y": 6.0, "z": -30.0,
            "battery": 80, "status": "IDLE",
        }
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=True,
            entry_mode="extreme_floor",
        )
        tr = result.get("target_resolution", {})
        floor = tr["selected_window_waypoint"]["floor"]
        assert floor in (1, 4), f"expected extreme floor, got {floor}"

    @pytest.mark.asyncio
    async def test_default_mode_preserves_legacy_behavior(self, _mock_client):
        # Without entry_mode, selection uses preferred_y (building center by default)
        # and ref_x/ref_z = requested coords. Must produce identical shape as today.
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
    async def test_extreme_floor_falls_back_when_no_snap(self, _mock_client):
        # entry_mode is a no-op when snap_to_building_center=False.
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=False,
            entry_mode="extreme_floor",
        )
        tr = result.get("target_resolution", {})
        # No window selected because no snap requested.
        assert "selected_window_waypoint" not in tr
        assert tr.get("entry_floor_kind") is None or "entry_floor_kind" not in tr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_plan_route_extreme_floor.py -v`
Expected: FAIL — `plan_route()` rejects `entry_mode` kwarg with `TypeError`.

### Task 4: Implement `entry_mode="extreme_floor"` in `plan_route`

**Files:**
- Modify: `backend/services/navigation/route_planner.py` (signature at lines 45-52; selection block at lines 75-91)

- [ ] **Step 1: Update imports at top of file**

Add to the imports block (after line 4):

```python
from typing import Any, Literal
```

(If `Any` is already imported, just add `Literal`.)

- [ ] **Step 2: Update `plan_route` signature and docstring**

Replace lines 45-68 (the `async def plan_route(...)` signature and docstring) with:

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
    """
    Pre-compute a collision-free route from the drone's current position.

    ``exclude_building_id`` removes a specific building from obstacle checks -
    used when the destination IS the target building (e.g. rooftop approach).

    ``entry_mode`` controls window-waypoint selection when ``snap_to_building_center``
    is True and the target building has windows:
      - ``"nearest_floor"`` (default): pick the window closest in Y to ``target_y``
        (building center by default), with XZ distance as tiebreaker. Preserves
        historical behavior.
      - ``"extreme_floor"``: restrict candidates to the lowest- and highest-floor
        windows only, and pick the one minimizing 3D Euclidean distance from the
        drone's current position. When the restricted set is empty, fall back to
        ``nearest_floor`` behavior with ``entry_mode_fallback=True`` recorded.

    Args:
        asset_id: Drone identifier.
        target_x: Target X coordinate.
        target_z: Target Z coordinate.
        target_y: Optional target altitude.
        snap_to_building_center: Whether to snap target onto building center/window waypoint.
        exclude_building_id: Optional building id to ignore as obstacle.
        entry_mode: Window-waypoint selection policy (see above).
    Returns:
        Structured route payload with strategy, waypoints, and optional error.
    """
```

- [ ] **Step 3: Add the extreme-floor selection block**

Replace lines 82-93 (the `if snap_to_building_center and nearby is not None:` block) with:

```python
    entry_floor_kind: str | None = None
    entry_mode_fallback = False
    if snap_to_building_center and nearby is not None:
        target_x = nearby.cx
        target_z = nearby.cz

        if entry_mode == "extreme_floor" and available_window_waypoints:
            floors = {int(wp["floor"]) for wp in available_window_waypoints}
            lowest_floor = min(floors)
            highest_floor = max(floors)
            # Iterate lowest-floor candidates first so ties resolve to "lowest"
            # (Python's min() is stable on equal keys).
            ordered_candidates: list[dict] = [
                wp for wp in available_window_waypoints
                if int(wp["floor"]) == lowest_floor
            ] + [
                wp for wp in available_window_waypoints
                if int(wp["floor"]) == highest_floor and highest_floor != lowest_floor
            ]

            def _drone_dist_3d(wp: dict) -> float:
                dx = float(wp["x"]) - cx
                dy = float(wp["y"]) - cy
                dz = float(wp["z"]) - cz
                return math.sqrt(dx * dx + dy * dy + dz * dz)

            if ordered_candidates:
                selected_window_waypoint = min(ordered_candidates, key=_drone_dist_3d)
                entry_floor_kind = (
                    "lowest"
                    if int(selected_window_waypoint["floor"]) == lowest_floor
                    else "highest"
                )
            else:
                entry_mode_fallback = True

        if selected_window_waypoint is None:
            # Either entry_mode == "nearest_floor", or extreme_floor fallback.
            selected_window_waypoint = select_window_waypoint(
                available_window_waypoints,
                ref_x=requested_x,
                ref_z=requested_z,
                preferred_y=target_y if target_y is not None else nearby.h / 2,
            )

        if selected_window_waypoint is not None:
            target_x = float(selected_window_waypoint["x"])
            target_z = float(selected_window_waypoint["z"])
```

- [ ] **Step 4: Record `entry_mode` / `entry_floor_kind` in `target_resolution`**

After the existing block that builds `target_resolution` (lines 104-121), add:

```python
    if target_resolution is not None:
        if entry_mode == "extreme_floor":
            target_resolution["entry_mode"] = "extreme_floor"
            if entry_floor_kind is not None:
                target_resolution["entry_floor_kind"] = entry_floor_kind
            if entry_mode_fallback:
                target_resolution["entry_mode_fallback"] = True
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_plan_route_extreme_floor.py -v`
Expected: PASS (all five tests)

- [ ] **Step 6: Run the existing plan_route test suite to verify no regressions**

Run: `uv run pytest tests/test_plan_route.py -v`
Expected: PASS (all existing tests)

- [ ] **Step 7: Commit**

```bash
git add tests/test_plan_route_extreme_floor.py backend/services/navigation/route_planner.py
git commit -m "feat: add entry_mode='extreme_floor' to plan_route

Opt-in mode restricts window-waypoint candidates to the lowest- and
highest-floor windows only, picking the 3D-closest to the drone. Avoids
middle-floor window entries whose narrow approach corridors were the
main source of wall-clipping. Default behavior preserved for all existing
callers; MCP surface unchanged.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3 — `plan_building_vertical_sweep` directional iteration

### Task 5: Failing test for `entry_floor="highest"`

**Files:**
- Create: `tests/test_sweep_entry_floor.py`

- [ ] **Step 1: Write the failing test**

```python
"""Unit tests for plan_building_vertical_sweep entry_floor parameter."""
from __future__ import annotations

from backend.services.navigation.sweep_planner import plan_building_vertical_sweep


class TestEntryFloor:
    def test_entry_floor_lowest_iterates_floors_ascending(self):
        """Default behavior: first floor-level waypoint is at the lowest level."""
        plan = plan_building_vertical_sweep(
            target_x=-18.0, target_z=-22.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-28.0,
            entry_floor="lowest",
        )
        assert plan["matched_building"] is True
        levels = plan["levels"]
        # The first non-transit waypoint with a floor level equals levels[0].
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        assert non_transit, "expected at least one non-transit waypoint"
        first_level_y = non_transit[0]["level_y"]
        # levels may include rooftop_y at the end; the lowest scanning level
        # should be the first encountered.
        assert first_level_y == min(l for l in levels if l < plan["rooftop_position"]["y"])

    def test_entry_floor_highest_iterates_floors_descending(self):
        """With entry_floor='highest', first scanning waypoint is at the top floor."""
        plan = plan_building_vertical_sweep(
            target_x=-18.0, target_z=-22.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-28.0,
            entry_floor="highest",
        )
        assert plan["matched_building"] is True
        levels_scanning = [
            l for l in plan["levels"] if l < plan["rooftop_position"]["y"]
        ]
        assert levels_scanning, "expected at least one scanning level"
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        first_level_y = non_transit[0]["level_y"]
        assert first_level_y == max(levels_scanning)

    def test_entry_floor_highest_still_ends_on_rooftop(self):
        """Top-down sweep still ends on the rooftop waypoint."""
        plan = plan_building_vertical_sweep(
            target_x=-18.0, target_z=-22.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-28.0,
            entry_floor="highest",
        )
        last_wp = plan["waypoints"][-1]
        assert last_wp["reason"] == "rooftop scan"
        assert last_wp["y"] == plan["rooftop_position"]["y"]

    def test_entry_floor_default_matches_legacy(self):
        """Calling without entry_floor preserves existing behavior."""
        plan_legacy = plan_building_vertical_sweep(
            target_x=-18.0, target_z=-22.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-28.0,
        )
        plan_explicit = plan_building_vertical_sweep(
            target_x=-18.0, target_z=-22.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-28.0,
            entry_floor="lowest",
        )
        assert plan_legacy["waypoint_count"] == plan_explicit["waypoint_count"]
        assert plan_legacy["levels"] == plan_explicit["levels"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sweep_entry_floor.py -v`
Expected: FAIL — `plan_building_vertical_sweep()` rejects `entry_floor` kwarg.

### Task 6: Implement `entry_floor` in `plan_building_vertical_sweep`

**Files:**
- Modify: `backend/services/navigation/sweep_planner.py` (signature at lines 22-29; iteration at line 86)

- [ ] **Step 1: Add `Literal` import**

At the top of `sweep_planner.py`, after `import math` (line 3), add:

```python
from typing import Literal
```

- [ ] **Step 2: Update `plan_building_vertical_sweep` signature**

Replace lines 22-30 (the function signature and opening docstring) with:

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
    """Plan a perimeter sweep around a building across all heights above water level.

    ``entry_floor`` controls the direction of floor-by-floor iteration:
      - ``"lowest"`` (default): sweep bottom-up, matching legacy behavior.
      - ``"highest"``: sweep top-down. The entry window is chosen from the
        top-floor windows closest to the approach coordinates, and floors
        are processed in descending order. Final rooftop scan still closes
        the mission.
    """
```

- [ ] **Step 3: Reverse `floor_levels` when `entry_floor == "highest"`**

Locate line 86 (`floor_levels = sorted({round(w["y"], 2) for w in above_flood})`) and replace it with:

```python
    floor_levels = sorted({round(w["y"], 2) for w in above_flood})
    if entry_floor == "highest":
        floor_levels = list(reversed(floor_levels))
```

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_sweep_entry_floor.py -v`
Expected: PASS (all four tests)

- [ ] **Step 5: Run the existing vertical-sweep test suite to verify no regressions**

Run: `uv run pytest tests/test_vertical_sweep.py tests/test_sweep_window_waypoints.py tests/test_sweep_smart_routing.py tests/test_sweep_scan_report.py -v`
Expected: PASS (all existing tests)

- [ ] **Step 6: Commit**

```bash
git add tests/test_sweep_entry_floor.py backend/services/navigation/sweep_planner.py
git commit -m "feat: add entry_floor parameter to plan_building_vertical_sweep

entry_floor='highest' reverses floor iteration so the sweep runs
top-down when the drone entered at the top floor. Final rooftop scan
still closes the mission. Default 'lowest' preserves legacy behavior.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4 — `sweep_workflow` plumbing

### Task 7: Thread `entry_floor_kind` through `sweep_workflow`

**Files:**
- Modify: `backend/services/workflows/sweep_workflow.py` (pre-sweep planning block around lines 57-70)

This restructure swaps the order of the two planning calls:

**Before:** `plan_building_vertical_sweep` (picks entry window) → `plan_route` (navigates to it).
**After:** `plan_route(entry_mode="extreme_floor")` (picks entry window via drone-distance AND plans path there) → `plan_building_vertical_sweep(entry_floor=...)` (builds the sweep starting from that window).

Because the drone is *already at* the chosen window when the sweep plan is built, and `approach_x/approach_z` still equal the drone's XZ, the sweep's internal entry-window selection re-chooses the same window by minimum-distance — no extra parameter plumbing needed beyond `entry_floor`.

- [ ] **Step 1: Write a unit test for the new plumbing**

Add to an existing or new test file. Create `tests/test_sweep_workflow_entry_floor.py`:

```python
"""Integration-style unit tests for sweep_workflow entry_floor plumbing."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.workflows.sweep_workflow import sweep_scan_building


@pytest.mark.asyncio
async def test_sweep_workflow_forwards_entry_floor_kind_to_sweep_plan():
    """plan_route is called first with entry_mode='extreme_floor'; entry_floor_kind
    from its target_resolution is passed to plan_building_vertical_sweep.
    """
    plan_route_fn = AsyncMock()
    plan_route_fn.return_value = {
        "asset_id": "BEACON-01",
        "from": {"x": 0.0, "y": 15.0, "z": 0.0},
        "to": {"x": -11.0, "y": 10.5, "z": -20.0},
        "waypoints": [
            {"x": -11.0, "y": 10.5, "z": -20.0, "reason": "arrive at target"},
        ],
        "strategy": "direct",
        "summary": "",
        "target_resolution": {
            "building_id": 0,
            "input": {"x": -15.0, "z": -20.0},
            "resolved": {"x": -11.0, "z": -20.0},
            "center": {"x": -15.0, "z": -20.0},
            "bounds": {"min_x": -19.0, "max_x": -11.0, "min_z": -24.0, "max_z": -16.0},
            "selected_window_waypoint": {
                "x": -11.0, "y": 10.5, "z": -20.0, "face": "east", "floor": 4,
            },
            "entry_mode": "extreme_floor",
            "entry_floor_kind": "highest",
        },
    }

    plan_building_vertical_sweep = MagicMock()
    # Return an empty plan to short-circuit the rest of the workflow.
    plan_building_vertical_sweep.return_value = {
        "matched_building": True,
        "building": {
            "id": 0, "min_x": -19.0, "max_x": -11.0,
            "min_z": -24.0, "max_z": -16.0,
            "center_x": -15.0, "center_z": -20.0, "height": 12.0,
        },
        "flood_level": 1.4,
        "levels": [],
        "level_count": 0,
        "waypoints": [],
        "waypoint_count": 0,
        "rooftop_position": {"x": -15.0, "y": 14.0, "z": -20.0},
        "summary": "",
    }

    get_status = AsyncMock()
    get_status.return_value = {
        "asset_id": "BEACON-01", "x": 0.0, "y": 15.0, "z": 0.0,
        "battery": 80, "status": "IDLE",
    }

    await sweep_scan_building(
        "BEACON-01",
        target_x=-15.0, target_z=-20.0,
        scan_radius=8.0, level_step=3.0, standoff=2.0,
        floor_height_m=3.0, thermal_horiz_fov_half_deg=22.5,
        plan_route_fn=plan_route_fn,
        plan_building_vertical_sweep=plan_building_vertical_sweep,
        wait_until_waypoint_reached=AsyncMock(return_value={"reached": True}),
        get_status=get_status,
        move_to=AsyncMock(return_value={"success": True}),
        scan_area=AsyncMock(return_value={"success": True}),
        get_view=AsyncMock(return_value={"objects": []}),
        end_scan=None,
        get_speed=lambda _: 5.0,
        register_detected_survivors=lambda _: 0,
        build_sweep_scan_report=lambda **_: "",
    )

    # plan_route_fn called with entry_mode='extreme_floor' and snap_to_building_center=True
    found = False
    for call in plan_route_fn.call_args_list:
        kwargs = call.kwargs
        if kwargs.get("entry_mode") == "extreme_floor" and kwargs.get("snap_to_building_center") is True:
            found = True
            break
    assert found, f"expected plan_route call with entry_mode='extreme_floor'; calls={plan_route_fn.call_args_list}"

    # plan_building_vertical_sweep called with entry_floor='highest'
    sweep_kwargs = plan_building_vertical_sweep.call_args.kwargs
    assert sweep_kwargs.get("entry_floor") == "highest"


@pytest.mark.asyncio
async def test_sweep_workflow_defaults_entry_floor_to_lowest_when_missing():
    """If plan_route omits entry_floor_kind (e.g. fallback), workflow passes 'lowest'."""
    plan_route_fn = AsyncMock()
    plan_route_fn.return_value = {
        "asset_id": "BEACON-01",
        "from": {"x": 0.0, "y": 10.0, "z": 0.0},
        "to": {"x": -15.0, "y": 6.0, "z": -20.0},
        "waypoints": [{"x": -15.0, "y": 6.0, "z": -20.0, "reason": "x"}],
        "strategy": "direct",
        "summary": "",
        # No target_resolution → no entry_floor_kind
    }

    plan_building_vertical_sweep = MagicMock()
    plan_building_vertical_sweep.return_value = {
        "matched_building": True,
        "building": {
            "id": 0, "min_x": -19.0, "max_x": -11.0,
            "min_z": -24.0, "max_z": -16.0,
            "center_x": -15.0, "center_z": -20.0, "height": 12.0,
        },
        "flood_level": 1.4,
        "levels": [], "level_count": 0,
        "waypoints": [], "waypoint_count": 0,
        "rooftop_position": {"x": -15.0, "y": 14.0, "z": -20.0},
        "summary": "",
    }

    get_status = AsyncMock()
    get_status.return_value = {
        "asset_id": "BEACON-01", "x": 0.0, "y": 10.0, "z": 0.0,
        "battery": 80, "status": "IDLE",
    }

    await sweep_scan_building(
        "BEACON-01",
        target_x=-15.0, target_z=-20.0,
        scan_radius=8.0, level_step=3.0, standoff=2.0,
        floor_height_m=3.0, thermal_horiz_fov_half_deg=22.5,
        plan_route_fn=plan_route_fn,
        plan_building_vertical_sweep=plan_building_vertical_sweep,
        wait_until_waypoint_reached=AsyncMock(return_value={"reached": True}),
        get_status=get_status,
        move_to=AsyncMock(return_value={"success": True}),
        scan_area=AsyncMock(return_value={"success": True}),
        get_view=AsyncMock(return_value={"objects": []}),
        end_scan=None,
        get_speed=lambda _: 5.0,
        register_detected_survivors=lambda _: 0,
        build_sweep_scan_report=lambda **_: "",
    )

    sweep_kwargs = plan_building_vertical_sweep.call_args.kwargs
    assert sweep_kwargs.get("entry_floor") == "lowest"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_sweep_workflow_entry_floor.py -v`
Expected: FAIL — current `sweep_workflow` doesn't pass `entry_floor` or call `plan_route` with `entry_mode="extreme_floor"`.

- [ ] **Step 3: Modify `sweep_workflow.sweep_scan_building` to do pre-sweep entry planning**

In `backend/services/workflows/sweep_workflow.py`, locate the block starting at line 57 (`status = await get_status(asset_id)`) through line 70 (end of the first `plan_building_vertical_sweep` call). Replace it with:

```python
    status = await get_status(asset_id)
    if target_x is None:
        target_x = status["x"]
    if target_z is None:
        target_z = status["z"]

    # 1. Pick the entry window via drone-distance on lowest/highest floors only,
    #    and compute a collision-free route to it. This also returns entry_floor_kind
    #    so we can iterate the sweep in the matching direction.
    entry_route = await plan_route_fn(
        asset_id=asset_id,
        target_x=target_x,
        target_z=target_z,
        snap_to_building_center=True,
        entry_mode="extreme_floor",
    )
    if "error" in entry_route:
        return {
            "asset_id": asset_id,
            "error": "Sweep route blocked",
            "route_error": entry_route["error"],
            "route_obstacles": entry_route.get("obstacles", []),
            "completed_waypoints": 0,
        }
    entry_floor_kind = (
        entry_route.get("target_resolution", {}).get("entry_floor_kind") or "lowest"
    )

    # 2. Build the sweep plan with the matching iteration direction. The drone
    #    will be navigated to the entry window first (below), so by the time
    #    the sweep executes, approach_x/approach_z naturally match the first
    #    sweep waypoint and the sweep's internal window selection re-chooses it.
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

- [ ] **Step 4: Remove the now-duplicate pre-sweep transition route**

The previous `transition_route` call (originally at lines 118-134) navigated the drone to `plan["waypoints"][0]`. With the new flow, `entry_route` already contains that navigation — but it targets the window waypoint (same coordinates as `plan["waypoints"][0]` by construction). To avoid duplicate movement, replace the existing `if plan["waypoints"]: first_wp = plan["waypoints"][0] ... transition_route = await plan_route_fn(...)` block (originally lines 118-134, but line numbers will have shifted by Step 3's insertions) with:

```python
    if plan["waypoints"]:
        # Use the entry route computed pre-sweep to drive the drone to the first
        # sweep waypoint. The sweep's first waypoint equals the entry window we
        # already routed to, so no second route computation is needed.
        transition_route = entry_route
```

(Keep the subsequent `for move_wp in transition_route.get("waypoints", []):` loop unchanged — it now iterates `entry_route`'s waypoints.)

- [ ] **Step 5: Run the new workflow tests to verify they pass**

Run: `uv run pytest tests/test_sweep_workflow_entry_floor.py -v`
Expected: PASS (both tests)

- [ ] **Step 6: Fix pre-existing test helpers that assume `target_y` is always passed**

Under the new flow, the pre-sweep `plan_route` call does not pass `target_y` (it lets `plan_route` derive altitude from the building). Two helper mocks in `tests/test_sweep_workflow_blocked_replan.py` (lines 48, 119) read `kwargs["target_y"]` directly, which will raise `KeyError` under the new flow. Update both occurrences from:

```python
"y": kwargs["target_y"],
```

to:

```python
"y": kwargs.get("target_y", 10.0),
```

The default 10.0 is the plan_route fallback altitude for non-building targets and is safe for these test fixtures (which also have rooftop_position.y = 29.0 for the actual sweep). This preserves the existing assertions while accommodating the new call pattern.

- [ ] **Step 7: Run the full sweep-related test suite to verify no regressions**

Run: `uv run pytest tests/test_vertical_sweep.py tests/test_sweep_smart_routing.py tests/test_sweep_workflow_blocked_replan.py tests/test_sweep_window_waypoints.py tests/test_sweep_scan_report.py tests/test_sweep_summary_counting.py -v`
Expected: PASS.

If any other pre-existing test fails, investigate the root cause. Do NOT weaken coverage — assertions must still verify that both planning calls happen with the correct arguments.

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest -x`
Expected: PASS (all tests across the repo).

- [ ] **Step 9: Commit**

```bash
git add tests/test_sweep_workflow_entry_floor.py backend/services/workflows/sweep_workflow.py tests/test_sweep_workflow_blocked_replan.py
git commit -m "feat: thread entry_floor_kind through sweep_workflow

Sweep workflow now calls plan_route with entry_mode='extreme_floor'
first, extracts entry_floor_kind, and passes it to
plan_building_vertical_sweep. The drone enters at the nearest extreme
floor and the sweep iterates in that direction (top-down or bottom-up).
Second pre-sweep route call removed; entry_route is reused for
navigation to the first sweep waypoint.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review Checklist (complete after finishing all tasks)

- [ ] All tests from Phases 1-4 pass (`uv run pytest tests/test_simplify_path_margin.py tests/test_plan_route_extreme_floor.py tests/test_sweep_entry_floor.py tests/test_sweep_workflow_entry_floor.py -v`)
- [ ] Full pre-existing test suite still passes (`uv run pytest`)
- [ ] Spec requirements covered:
  - [x] `plan_route` has new `entry_mode` param (Task 4)
  - [x] Extreme-floor candidate set = lowest + highest floors (Task 4)
  - [x] 3D Euclidean distance selection (Task 4)
  - [x] `entry_floor_kind` recorded in `target_resolution` (Task 4)
  - [x] Tie-break resolves to `"lowest"` (ordered_candidates construction in Task 4)
  - [x] Fallback when building has no windows (Task 4)
  - [x] `plan_building_vertical_sweep` has `entry_floor` param (Task 6)
  - [x] Floor iteration reverses for `entry_floor="highest"` (Task 6)
  - [x] Rooftop scan still closes mission (Task 5 test, Task 6 preserves unchanged)
  - [x] `_simplify_path` uses `margin + cell_size/2` (Task 2)
  - [x] `sweep_workflow` plumbs `entry_floor_kind` end-to-end (Task 7)
  - [x] MCP surface unchanged (no tasks modify `backend/mcp/server.py`)
  - [x] Non-sweep callers unchanged (defaults preserve legacy behavior)
