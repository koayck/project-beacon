# Ground-Floor Scan Entry — Design Spec

**Date:** 2026-04-22
**Status:** Approved (pending spec review)
**Scope:** Change drone building-scan entry behavior to always start at the nearest ground-floor window and sweep upward, removing the top-down / climb-to-roof-first branch.

## Problem

When a drone is told to scan a building, the current behavior can send it to the rooftop first and sweep top-down. This happens because the entry-window selection compares the lowest-floor and highest-floor candidates by **3D** distance from the drone, so a drone cruising at high altitude can end up "closer" to a top-floor window than to any ground-floor window.

This feels unlike how a human pilot would fly the mission. A human operator arriving at a building starts at the nearest ground-floor window and works upward — not climbing to the roof first.

## Goal

Always enter the sweep at a **ground-floor window**, specifically the one with the smallest horizontal (XZ) distance to the drone's arrival position. Sweep floor-by-floor upward from there. Remove the top-down code paths.

## Non-Goals

- Changing the approach routing (A* / collision avoidance to reach the entry window). Approach behavior stays the same.
- Changing the serpentine corner-to-corner pattern within each floor.
- Changing fleet assignment or per-drone loop execution.
- Removing the final rooftop scan waypoint — it remains at the end of the sweep as a quick overhead pass.

## Behavior Change Summary

| Aspect | Before | After |
|---|---|---|
| Entry-window selection | Lowest OR highest floor, whichever is closest in 3D distance | Lowest floor only, closest by horizontal (XZ) distance |
| Floor iteration order | Ascending or descending based on entry floor | Always ascending |
| `entry_floor` parameter | `"lowest"` \| `"highest"` | Removed |
| `entry_mode` option | `"nearest_floor"` \| `"extreme_floor"` | `"nearest_floor"` \| `"ground_entry"` (renamed) |
| Rooftop scan waypoint | Emitted at end | Emitted at end (unchanged) |

## Affected Files

### 1. `backend/services/navigation/route_planner.py`

Current behavior at approx. lines 94–131: when `entry_mode == "extreme_floor"`, builds a candidate list from lowest- and highest-floor window waypoints, picks by 3D Euclidean distance, and records `entry_floor_kind` as `"lowest"` or `"highest"`.

**Change:**
- Rename the mode from `"extreme_floor"` to `"ground_entry"`.
- Restrict candidates to `lowest_floor` windows only.
- Select by **horizontal (XZ)** distance from the drone's current position, not 3D.
- `entry_floor_kind` is no longer needed; remove it from the `target_resolution` payload.

### 2. `backend/services/navigation/sweep_planner.py`

Current behavior at approx. lines 23–98: accepts `entry_floor: Literal["lowest", "highest"] = "lowest"` and reverses `floor_levels` when `"highest"`.

**Change:**
- Remove the `entry_floor` parameter entirely.
- `floor_levels` is always ascending (delete the `if entry_floor == "highest": floor_levels = list(reversed(floor_levels))` branch).
- The existing entry-window selection at lines 133–155 (pick the closest window on `floor_levels[0]` to `approach_x/approach_z`) stays — this is already the desired behavior for the first processed floor.

### 3. `backend/services/api/control.py`

The wrapper at approx. lines 167–186 forwards `entry_floor` to the sweep planner.

**Change:** Remove the `entry_floor` parameter from the wrapper signature and forward call.

### 4. `backend/services/workflows/sweep_workflow.py`

Current behavior at approx. lines 81–96: reads `entry_floor_kind` from the entry-route result and passes it as `entry_floor=entry_floor_kind` to `plan_building_vertical_sweep`.

**Change:**
- Remove the `entry_floor_kind` read.
- Remove the `entry_floor=` argument from the `plan_building_vertical_sweep` call.
- Update the `plan_route_fn` call to pass `entry_mode="ground_entry"` instead of `"extreme_floor"`.

## Testing

### Unit tests

**`test_sweep_planner.py`** (new or updated):
- Given a building with windows on floors 1–3 and a drone at approach position `(approach_x, approach_z)`:
  - Assert the first waypoint is a window on floor 1 (never floors 2 or 3).
  - Assert among floor-1 windows, the one with smallest XZ distance to `(approach_x, approach_z)` is chosen.
  - Assert `floor_levels` in the returned plan is ascending.
  - Assert the rooftop scan waypoint is still emitted as the last waypoint.

**`test_route_planner.py`** (new or updated):
- With `entry_mode="ground_entry"` and a building with windows on multiple floors:
  - Assert the selected window is on the lowest floor regardless of drone Y.
  - Assert XZ distance (not 3D) drives the choice. Verify by placing the drone at high altitude directly above a top-floor window; the ground-floor window beneath it should still win because their XZ coordinates match.

### Regression scan

Grep for any test or caller that currently asserts:
- `entry_floor_kind == "highest"`
- `entry_mode == "extreme_floor"`
- `entry_floor="highest"`

Update or delete those assertions to match the new behavior.

### Manual verification

- Spawn a single drone; issue a scan on a building it is not currently near. Watch the R3F canvas: drone should approach, descend to ground-floor altitude near a window on the face closest to it, then spiral upward floor-by-floor.
- Run a fleet scan with 2–3 drones on multiple buildings. Confirm each drone enters its assigned building at ground level.

## Risks

**Low.** No data model changes, no breaking API changes to agents or tools. The parameter removals are internal to the navigation services layer. The main observable behavior difference is in cases where A* previously cruised the drone at high altitude before arrival — those scans could flip to top-down before, and will now remain bottom-up.

## Rollout

Single PR, single commit series. No migrations, no config flags.
