# Ground-Floor Scan Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change drone building-scan entry so it always starts at the nearest ground-floor window (by horizontal distance) and sweeps upward, removing the top-down / climb-to-roof-first branch.

**Architecture:** Two navigation-layer modules change their selection policy: `route_planner.py` restricts entry-window candidates to the lowest floor and ranks by XZ distance; `sweep_planner.py` always iterates floors ascending. The orchestrating `sweep_workflow.py` and the thin API wrapper in `control.py` are simplified accordingly. No data-model or API-surface changes outside the navigation services.

**Tech Stack:** Python 3.11+, pytest, pytest-asyncio. All changes are in `backend/services/navigation/`, `backend/services/api/`, `backend/services/workflows/`, and their `tests/` counterparts.

**Reference spec:** `docs/superpowers/specs/2026-04-22-ground-floor-scan-entry-design.md`

---

## Rename summary (reference while reading tasks)

- `entry_mode="extreme_floor"` → `entry_mode="ground_entry"` (route_planner.py + sweep_workflow.py + tests)
- `entry_floor` parameter → **removed** (sweep_planner.py + control.py + sweep_workflow.py + tests)
- `entry_floor_kind` in `target_resolution` payload → **removed** (route_planner.py + tests + sweep_workflow.py)

---

## Task 1: Update route_planner entry-selection logic (TDD)

**Files:**
- Modify: `backend/services/navigation/route_planner.py:45-193`
- Modify: `tests/test_plan_route_extreme_floor.py` (rename and rewrite)

### Step 1.1: Rename the existing test module

- [ ] **Rename the test file to reflect the new mode name.**

Run:
```bash
git mv tests/test_plan_route_extreme_floor.py tests/test_plan_route_ground_entry.py
```

### Step 1.2: Rewrite the test suite for ground-floor-only selection

- [ ] **Replace the contents of `tests/test_plan_route_ground_entry.py` with the test suite below.**

```python
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
        # Drone at roof altitude adjacent to the east facade. Previously this
        # flipped selection to a top-floor window. Ground-floor entry must
        # ignore Y and pick the lowest-floor window whose XZ is closest.
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
        # Building id=0 has lowest floor = 2.
        assert wp["floor"] == 2

    @pytest.mark.asyncio
    async def test_ground_entry_picks_window_nearest_by_xz(self, _mock_client):
        # Drone near south facade at arbitrary Y. Must pick a south-face,
        # lowest-floor window (not a north/east/west-face window).
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
        # The south face of building id=0 is the +z face closest to the drone.
        assert wp["face"] == "south"

    @pytest.mark.asyncio
    async def test_ground_entry_ignores_y_distance(self, _mock_client):
        # Place drone directly above a specific top-floor window (same XZ as
        # the window) but high in Y. Lowest-floor window beneath it (same XZ)
        # should still win because XZ distance is zero for both but we only
        # consider the lowest floor.
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
        # Building id=0 has floors 2, 3, 4. ground_entry must never return
        # floors 3 or 4 regardless of drone position.
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
        # Without entry_mode, selection uses preferred_y (building center by
        # default) and ref_x/ref_z = requested coords. Must produce identical
        # shape as today.
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
        # entry_mode is a no-op when snap_to_building_center=False.
        result = await plan_route(
            "BEACON-01", -15.0, -20.0,
            snap_to_building_center=False,
            entry_mode="ground_entry",
        )
        tr = result.get("target_resolution", {})
        assert "selected_window_waypoint" not in tr

    @pytest.mark.asyncio
    async def test_ground_entry_records_fallback_when_building_has_no_windows(self, _mock_client):
        # A building with no windows must record entry_mode_fallback=True and
        # snap to building center.
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
```

### Step 1.3: Run the new tests and verify they fail

- [ ] **Run the suite and confirm failures.**

Run: `uv run pytest tests/test_plan_route_ground_entry.py -v`

Expected: All tests fail because `entry_mode="ground_entry"` is not accepted by `plan_route` yet. Typical error: `ValueError` or `AssertionError` on the `entry_mode` type literal.

### Step 1.4: Update `plan_route` to accept the new mode and restrict to lowest floor

- [ ] **Open `backend/services/navigation/route_planner.py`. Change the `entry_mode` type literal at line 52 from `"extreme_floor"` to `"ground_entry"`:**

```python
    entry_mode: Literal["nearest_floor", "ground_entry"] = "nearest_floor",
```

- [ ] **Update the docstring around lines 60-68 to describe the new semantics:**

```python
    ``entry_mode`` controls window-waypoint selection when ``snap_to_building_center``
    is True and the target building has windows:
      - ``"nearest_floor"`` (default): pick the window closest in Y to ``target_y``
        (building center by default), with XZ distance as tiebreaker. Preserves
        historical behavior.
      - ``"ground_entry"``: restrict candidates to the lowest-floor windows only,
        and pick the one minimizing horizontal (XZ) distance from the drone's
        current position. This mimics a human pilot entering a building at the
        ground floor nearest their approach, rather than climbing to the roof
        first. When the restricted set is empty (e.g. building has no windows),
        fall back to ``nearest_floor`` behavior with ``entry_mode_fallback=True``
        recorded.
```

### Step 1.5: Replace the extreme_floor selection branch

- [ ] **Replace the block at lines 100-131 (currently the `entry_mode == "extreme_floor"` branch) with the ground-entry branch:**

```python
        if entry_mode == "ground_entry" and available_window_waypoints:
            floors = {int(wp["floor"]) for wp in available_window_waypoints}
            lowest_floor = min(floors)
            ground_candidates: list[dict] = [
                wp for wp in available_window_waypoints
                if int(wp["floor"]) == lowest_floor
            ]
            assert ground_candidates, (
                "ground_entry candidate set is empty despite non-empty "
                "available_window_waypoints — this is a logic error"
            )

            def _drone_dist_xz(wp: dict) -> float:
                dx = float(wp["x"]) - cx
                dz = float(wp["z"]) - cz
                return math.sqrt(dx * dx + dz * dz)

            selected_window_waypoint = min(ground_candidates, key=_drone_dist_xz)
```

- [ ] **Update the fallback block at lines 133-144. Change `entry_mode == "extreme_floor"` to `entry_mode == "ground_entry"`:**

```python
        if selected_window_waypoint is None:
            # Either entry_mode == "nearest_floor", or ground_entry had no
            # candidates (e.g. building has no windows). In the latter case,
            # record the fallback so callers can detect it.
            if entry_mode == "ground_entry":
                entry_mode_fallback = True
            selected_window_waypoint = select_window_waypoint(
                available_window_waypoints,
                ref_x=requested_x,
                ref_z=requested_z,
                preferred_y=target_y if target_y is not None else nearby.h / 2,
            )
```

### Step 1.6: Remove `entry_floor_kind` from the target_resolution payload

- [ ] **Replace the block at lines 186-192 with the simpler form:**

```python
    if target_resolution is not None:
        if entry_mode == "ground_entry":
            target_resolution["entry_mode"] = "ground_entry"
            if entry_mode_fallback:
                target_resolution["entry_mode_fallback"] = True
```

- [ ] **Delete the local variable assignment at line 94 (`entry_floor_kind: str | None = None`) — it is no longer used.** The `entry_mode_fallback = False` line immediately below it stays.

### Step 1.7: Run the new tests and verify they pass

- [ ] **Run the suite.**

Run: `uv run pytest tests/test_plan_route_ground_entry.py -v`

Expected: All 7 tests pass.

### Step 1.8: Commit

- [ ] **Commit.**

```bash
git add backend/services/navigation/route_planner.py tests/test_plan_route_ground_entry.py
git rm tests/test_plan_route_extreme_floor.py
git commit -m "refactor(navigation): replace extreme_floor with ground_entry mode

Restrict entry-window selection to lowest-floor candidates only, ranked by
horizontal (XZ) distance from the drone. Removes the 3D-distance / top-floor
branch that caused high-cruising drones to flip into top-down scans."
```

---

## Task 2: Simplify sweep_planner (remove entry_floor parameter)

**Files:**
- Modify: `backend/services/navigation/sweep_planner.py:23-98`
- Modify: `tests/test_sweep_entry_floor.py` (rename and rewrite)

### Step 2.1: Rename the test module

- [ ] **Rename the file to reflect its new scope.**

Run:
```bash
git mv tests/test_sweep_entry_floor.py tests/test_sweep_ground_entry.py
```

### Step 2.2: Rewrite the sweep planner tests

- [ ] **Replace the contents of `tests/test_sweep_ground_entry.py` with:**

```python
"""Unit tests for plan_building_vertical_sweep ground-entry behavior.

After the ground-entry refactor, plan_building_vertical_sweep always iterates
floors ascending and enters at a lowest-floor window closest to the drone's
approach coordinates.
"""
from __future__ import annotations

from backend.services.navigation.sweep_planner import plan_building_vertical_sweep


class TestGroundEntrySweep:
    def test_first_scanning_waypoint_is_on_lowest_floor(self):
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
        )
        assert plan["matched_building"] is True
        levels = plan["levels"]
        rooftop_y = plan["rooftop_position"]["y"]
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        assert non_transit, "expected at least one non-transit waypoint"
        first_level_y = non_transit[0]["level_y"]
        scanning_levels = [l for l in levels if l < rooftop_y]
        assert scanning_levels, "expected at least one scanning level"
        assert first_level_y == min(scanning_levels)

    def test_floors_iterate_ascending(self):
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
        )
        rooftop_y = plan["rooftop_position"]["y"]
        scanning_levels = [l for l in plan["levels"] if l < rooftop_y]
        assert scanning_levels == sorted(scanning_levels), (
            f"expected ascending floor order, got {scanning_levels}"
        )

    def test_sweep_still_ends_on_rooftop(self):
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-5.0,
        )
        last_wp = plan["waypoints"][-1]
        assert last_wp["reason"] == "rooftop scan"
        assert last_wp["y"] == plan["rooftop_position"]["y"]

    def test_entry_window_is_closest_to_approach_on_lowest_floor(self):
        # Approach from the north side: approach_z << min_z. Entry window
        # should be on the north face at the lowest floor.
        plan = plan_building_vertical_sweep(
            target_x=-15.0, target_z=-15.0,
            level_step=3.0, standoff=2.0,
            approach_x=-15.0, approach_z=-50.0,
        )
        rooftop_y = plan["rooftop_position"]["y"]
        scanning_levels = [l for l in plan["levels"] if l < rooftop_y]
        lowest_y = min(scanning_levels)
        non_transit = [w for w in plan["waypoints"] if not w.get("transit")]
        first = non_transit[0]
        assert first["level_y"] == lowest_y
        assert "window scan" in first["reason"], (
            f"expected first waypoint to be a window scan, got {first['reason']}"
        )
```

### Step 2.3: Run and verify the new tests fail

- [ ] **Run the suite.**

Run: `uv run pytest tests/test_sweep_ground_entry.py -v`

Expected: Tests may still pass because the default `entry_floor="lowest"` already exhibits this behavior. The tests exist to lock the behavior in. Note any failures and proceed.

### Step 2.4: Remove the `entry_floor` parameter from sweep_planner

- [ ] **Open `backend/services/navigation/sweep_planner.py`. Replace the function signature at lines 23-32 with:**

```python
def plan_building_vertical_sweep(
    target_x: float,
    target_z: float,
    level_step: float = 3.0,
    standoff: float = 2.0,
    flood_clearance: float = 0.5,
    approach_x: float | None = None,
    approach_z: float | None = None,
) -> dict:
```

- [ ] **Replace the docstring at lines 33-41 with:**

```python
    """Plan a perimeter sweep around a building across all heights above water level.

    The sweep always enters at a lowest-floor window closest to
    ``(approach_x, approach_z)`` and iterates floors ascending, concluding with
    a rooftop scan waypoint at the building center.
    """
```

- [ ] **Delete the `Literal` import if nothing else in the file uses it.** Check imports at top of file.

### Step 2.5: Remove the descending-floor branch

- [ ] **Delete lines 97-98 (the `if entry_floor == "highest"` branch):**

Remove:
```python
    if entry_floor == "highest":
        floor_levels = list(reversed(floor_levels))
```

So `floor_levels = sorted({round(w["y"], 2) for w in above_flood})` is immediately followed by the `perimeter_margin = 1.0` line.

### Step 2.6: Run the tests and verify they pass

- [ ] **Run the suite.**

Run: `uv run pytest tests/test_sweep_ground_entry.py -v`

Expected: All 4 tests pass.

### Step 2.7: Commit

- [ ] **Commit.**

```bash
git add backend/services/navigation/sweep_planner.py tests/test_sweep_ground_entry.py
git rm tests/test_sweep_entry_floor.py
git commit -m "refactor(navigation): drop entry_floor parameter from sweep planner

Sweep now always iterates floors ascending from a lowest-floor entry window.
Eliminates the top-down sweep path used by the removed extreme_floor mode."
```

---

## Task 3: Update the API wrapper in control.py

**Files:**
- Modify: `backend/services/api/control.py:167-186`

### Step 3.1: Remove `entry_floor` from the wrapper signature

- [ ] **Open `backend/services/api/control.py`. Replace lines 167-186 with:**

```python
def plan_building_vertical_sweep(
    target_x: float,
    target_z: float,
    level_step: float = 3.0,
    standoff: float = 2.0,
    flood_clearance: float = 0.5,
    approach_x: float | None = None,
    approach_z: float | None = None,
) -> dict:
    return _plan_building_vertical_sweep(
        target_x=target_x,
        target_z=target_z,
        level_step=level_step,
        standoff=standoff,
        flood_clearance=flood_clearance,
        approach_x=approach_x,
        approach_z=approach_z,
    )
```

- [ ] **Check the file for the `Literal` import. If no other function in this module uses `Literal`, remove it from the imports.**

Run: `grep -n "Literal" backend/services/api/control.py`

If only the now-removed signature referenced it, delete the import.

### Step 3.2: Sanity-check by running the full navigation test set

- [ ] **Run the affected tests.**

Run: `uv run pytest tests/test_sweep_ground_entry.py tests/test_plan_route_ground_entry.py tests/test_vertical_sweep.py -v`

Expected: All pass.

### Step 3.3: Commit

- [ ] **Commit.**

```bash
git add backend/services/api/control.py
git commit -m "refactor(api): drop entry_floor from plan_building_vertical_sweep wrapper"
```

---

## Task 4: Update sweep_workflow plumbing (TDD)

**Files:**
- Modify: `backend/services/workflows/sweep_workflow.py:63-97`
- Modify: `tests/test_sweep_workflow_entry_floor.py` (rename and rewrite)

### Step 4.1: Rename the workflow test module

- [ ] **Rename the file.**

Run:
```bash
git mv tests/test_sweep_workflow_entry_floor.py tests/test_sweep_workflow_ground_entry.py
```

### Step 4.2: Rewrite the workflow tests

- [ ] **Replace the contents of `tests/test_sweep_workflow_ground_entry.py` with:**

```python
"""Integration-style unit tests for sweep_workflow ground-entry plumbing."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.workflows.sweep_workflow import sweep_scan_building


def _make_sweep_plan_stub() -> MagicMock:
    stub = MagicMock()
    stub.return_value = {
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
    return stub


@pytest.mark.asyncio
async def test_sweep_workflow_requests_ground_entry_mode():
    """plan_route must be invoked with entry_mode='ground_entry' and
    snap_to_building_center=True."""
    plan_route_fn = AsyncMock()
    plan_route_fn.return_value = {
        "asset_id": "BEACON-01",
        "from": {"x": 0.0, "y": 15.0, "z": 0.0},
        "to": {"x": -11.0, "y": 4.2, "z": -20.0},
        "waypoints": [
            {"x": -11.0, "y": 4.2, "z": -20.0, "reason": "arrive at target"},
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
                "x": -11.0, "y": 4.2, "z": -20.0, "face": "east", "floor": 2,
            },
            "entry_mode": "ground_entry",
        },
    }

    plan_building_vertical_sweep = _make_sweep_plan_stub()

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

    found = False
    for call in plan_route_fn.call_args_list:
        kwargs = call.kwargs
        if kwargs.get("entry_mode") == "ground_entry" and kwargs.get("snap_to_building_center") is True:
            found = True
            break
    assert found, (
        f"expected plan_route call with entry_mode='ground_entry'; "
        f"calls={plan_route_fn.call_args_list}"
    )


@pytest.mark.asyncio
async def test_sweep_workflow_does_not_pass_entry_floor_to_sweep_plan():
    """plan_building_vertical_sweep must be called without an entry_floor kwarg."""
    plan_route_fn = AsyncMock()
    plan_route_fn.return_value = {
        "asset_id": "BEACON-01",
        "from": {"x": 0.0, "y": 10.0, "z": 0.0},
        "to": {"x": -15.0, "y": 4.2, "z": -20.0},
        "waypoints": [{"x": -15.0, "y": 4.2, "z": -20.0, "reason": "x"}],
        "strategy": "direct",
        "summary": "",
    }

    plan_building_vertical_sweep = _make_sweep_plan_stub()

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
    assert "entry_floor" not in sweep_kwargs, (
        f"entry_floor should no longer be forwarded; got kwargs={sweep_kwargs}"
    )
```

### Step 4.3: Run the new tests and verify they fail

- [ ] **Run the suite.**

Run: `uv run pytest tests/test_sweep_workflow_ground_entry.py -v`

Expected: Both tests fail. The first fails because `entry_mode="extreme_floor"` is still passed. The second fails because `entry_floor="lowest"` (or whatever `entry_floor_kind` resolves to) is still forwarded.

### Step 4.4: Update sweep_workflow to use the new mode and drop entry_floor

- [ ] **Open `backend/services/workflows/sweep_workflow.py`. Replace the block at lines 63-97 with:**

```python
    # 1. Pick the entry window via drone-XZ-distance on lowest-floor windows
    #    only, and compute a collision-free route to it. Ground-entry mimics
    #    a human pilot entering a building at the ground floor nearest to
    #    their approach rather than climbing to the roof first.
    entry_route = await plan_route_fn(
        asset_id=asset_id,
        target_x=target_x,
        target_z=target_z,
        snap_to_building_center=True,
        entry_mode="ground_entry",
    )
    if "error" in entry_route:
        return {
            "asset_id": asset_id,
            "error": "Sweep route blocked",
            "route_error": entry_route["error"],
            "route_obstacles": entry_route.get("obstacles", []),
            "completed_waypoints": 0,
        }

    # 2. Build the sweep plan. The drone will be navigated to the entry window
    #    first (below), so by the time the sweep executes, approach_x/approach_z
    #    naturally match the first sweep waypoint and the sweep's internal
    #    window selection re-chooses it.
    plan = plan_building_vertical_sweep(
        target_x=target_x,
        target_z=target_z,
        level_step=level_step,
        standoff=standoff,
        approach_x=status.get("x"),
        approach_z=status.get("z"),
    )
```

### Step 4.5: Run the new tests and verify they pass

- [ ] **Run the suite.**

Run: `uv run pytest tests/test_sweep_workflow_ground_entry.py -v`

Expected: Both tests pass.

### Step 4.6: Commit

- [ ] **Commit.**

```bash
git add backend/services/workflows/sweep_workflow.py tests/test_sweep_workflow_ground_entry.py
git rm tests/test_sweep_workflow_entry_floor.py
git commit -m "refactor(workflow): route sweep through ground_entry mode

Drop entry_floor_kind read and entry_floor forwarding. plan_route is now
called with entry_mode='ground_entry', and plan_building_vertical_sweep
no longer needs an iteration-direction hint."
```

---

## Task 5: Hunt remaining references and fix collateral tests

**Files (potential):**
- Any file in `tests/` or `backend/` still referencing `extreme_floor`, `entry_floor`, or `entry_floor_kind`.

### Step 5.1: Search for stale references

- [ ] **Search the full repo for stragglers.**

Run:
```bash
git grep -nE "extreme_floor|entry_floor_kind|entry_floor\b" -- backend tests
```

Expected: No matches except possibly in `docs/superpowers/specs/2026-04-22-ground-floor-scan-entry-design.md` (the spec itself). If the search returns any code or test references, address each one:
- In production code: update to `ground_entry` / remove the parameter as appropriate.
- In tests: update assertions to match the new behavior (lowest-floor entry, no top-down branch).

### Step 5.2: Run the full backend test suite

- [ ] **Run all tests to catch any regression.**

Run: `uv run pytest tests/ -v`

Expected: Full green. If anything fails, triage:
- Failures that assert old behavior (e.g. "expected floor 4 entry") — update the test to the new expectation.
- Failures that assert on a dict key that no longer exists (`entry_floor_kind`) — remove the assertion.
- Unexpected failures in unrelated files — stop and investigate; do not blanket-update assertions.

### Step 5.3: Commit any follow-up fixes

- [ ] **If Step 5.2 required further test or code edits, commit them.**

```bash
git add <changed-files>
git commit -m "test: align stragglers with ground_entry behavior"
```

If Step 5.2 was already green, skip this step.

---

## Task 6: Manual verification (R3F)

No code changes in this task. Run the app and visually confirm the new behavior.

### Step 6.1: Start the stack

- [ ] **Start drones.**

Run: `docker compose up -d`

- [ ] **Start the backend.**

Run: `uv run python -m backend.app`

- [ ] **Start the frontend.**

Run: `cd frontend && npm run tauri dev`

### Step 6.2: Single-drone check

- [ ] **Spawn one drone at the base; from the command panel issue `scan building at <coords>` for a multi-floor building several units away.**

Expected observable behavior:
- Drone departs base, cruises to the building.
- On arrival, drone **descends to ground-floor altitude** at the window on the face closest to its approach.
- Drone sweeps floor 1 around the perimeter, then floor 2, then floor 3, …
- Final move is a brief rooftop center pass.
- Drone never climbs above rooftop-plus-standoff before starting the ground-floor sweep.

### Step 6.3: Fleet check

- [ ] **Spawn 2-3 drones and issue a scan covering multiple buildings.**

Expected: Each drone enters its assigned building at ground level following the same pattern. No drone performs a top-down sweep.

### Step 6.4: Note any anomalies

- [ ] **If the behavior matches expectations, the plan is complete. If anything looks off (drone still climbing before entry, wrong face selected, stalled routing), capture:**
  - Drone ID
  - Target building ID
  - Drone arrival coordinates
  - First 5 waypoints from the FastAPI logs

Open a follow-up issue with that data rather than patching blindly.

---

## Completion Criteria

- [ ] `uv run pytest tests/ -v` passes.
- [ ] `git grep -nE "extreme_floor|entry_floor_kind|entry_floor\b" -- backend tests` returns no matches.
- [ ] Manual R3F check confirms ground-floor entry for both single-drone and fleet scans.
- [ ] All six task commits landed on the working branch.
