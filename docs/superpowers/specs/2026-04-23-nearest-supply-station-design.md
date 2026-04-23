# Nearest Supply Station — Design Spec

**Date:** 2026-04-23
**Status:** Approved (pending spec review)
**Scope:** Add operator-placed supply stations and route supply dispatches through the station nearest to each target, replacing the current always-return-to-(0,0,0) pickup step.

## Problem

Today, `dispatch_supply_to_building` in `backend/services/workflows/supply_workflow.py` makes every drone fly back to the single home base at `(0,0,0)` via `return_to_base_fn(asset_id)` before heading to the survivor drop point. This simulates a supply pickup, but it always uses one fixed location. In a wider disaster zone, a drone delivering to a distant building wastes a round trip flying all the way home.

## Goal

Allow the operator to place multiple supply stations on the map at runtime. On every supply dispatch, the drone picks up from the station whose distance to the **target** is smallest, then flies to the drop point. The existing home base at `(0,0,0)` is always included as a built-in station, so if the operator places zero stations the behavior is identical to today.

## Non-Goals

- Capacity / inventory per station — stations are unlimited pickup points.
- Cross-restart persistence — stations live in memory on the backend and reset on restart. Supabase integration is deferred.
- Station types (medical / water / food) — all stations are interchangeable.
- LLM-driven station placement — the agent does not have a tool for placing stations. Placement is a UI action only.
- Changes to scan or recall workflows — only the supply workflow routes through stations.

## Behavior Change Summary

| Aspect | Before | After |
|---|---|---|
| Pickup location | Always `(0,0,0)` home base | Nearest station to target (home base is one candidate) |
| Pickup step in `dispatch_supply_to_building` | `return_to_base_fn(asset_id)` | `go_to_station(asset_id, station)` using the existing route planner |
| Station data model | None | In-memory list `[{id, x, z}, ...]` with built-in `id="home"` entry |
| Station placement UX | N/A | Toggle button + click-to-place on R3F canvas, click-to-remove with confirmation |
| Station persistence | N/A | Session only; reset on backend restart |

## Design Decisions

1. **Nearest-to-target, not nearest-to-drone.** Station selection minimizes `dist(station → target)`, ignoring the drone's current position. Rationale: the drone usually starts idle at `(0,0,0)`, so a drone-position-aware metric would make user-placed stations effectively invisible in demos. Target-only selection makes station placement visibly meaningful.
2. **Home base is always a candidate.** It participates in selection under `id="home"`, so zero user-placed stations reproduces today's behavior exactly. No feature flag.
3. **Station choice is captured at dispatch start.** If the operator removes a station mid-flight, the in-flight dispatch continues to the originally chosen station. Avoids cancellation/reroute logic.
4. **Selection is deterministic, not an agent tool.** `select_best_station` is a plain Python call inside `dispatch_supply_to_building`. The LLM orchestrates the workflow as today; it does not reason about which station to pick.
5. **Placement validation on the backend.** The POST endpoint rejects positions inside building footprints or outside world bounds with 400. Frontend mirrors the check for a red ghost preview.

## Affected Files

### Backend

#### 1. `backend/services/supply_stations.py` (new)

In-memory station registry and selection.

```python
# Station record: {"id": str, "x": float, "z": float}

HOME_STATION = {"id": "home", "x": 0.0, "z": 0.0}

def list_stations() -> list[dict]:
    """Return home station plus all user-placed stations."""

def add_station(x: float, z: float) -> dict:
    """Validate and append a new station. Returns the new record.
    Raises ValueError with a user-facing message on invalid placement."""

def remove_station(station_id: str) -> bool:
    """Remove a user-placed station. Returns False if not found.
    Raises ValueError if caller attempts to remove 'home'."""

def select_best_station(target_x: float, target_z: float) -> dict:
    """Return the station minimizing 2D Euclidean distance to target.
    Always returns a station (home is the fallback)."""
```

Placement validity reuses the same world model already consulted by the route planner — `world.building_at(x, y, z)` returns non-None if the point is inside any building footprint. Out-of-bounds check uses the world's `min_x / max_x / min_z / max_z`.

#### 2. `backend/services/api/` (new routes module or additions to `control.py`)

```
GET    /supply-stations          → {"stations": [...]}
POST   /supply-stations          → body {"x": float, "z": float}; 200 {station} | 400 {error}
DELETE /supply-stations/{id}     → 200 {ok: true} | 400 (cannot remove home) | 404
```

Each mutating endpoint broadcasts a WebSocket event via the existing `ws_broadcaster` used elsewhere for activity/telemetry:

```
{type: "supply_station_added",   station: {id, x, z}}
{type: "supply_station_removed", id: str}
```

#### 3. `backend/services/workflows/supply_workflow.py` (modify)

Replace the base-return step inside `dispatch_supply_to_building`:

```python
# BEFORE
to_base = await return_to_base_fn(asset_id)
if "error" in to_base:
    return {...error path...}

# AFTER
from backend.services.supply_stations import select_best_station
station = select_best_station(target_x=drop_x, target_z=drop_z)
pickup_result = await _go_to_station(
    asset_id=asset_id,
    station=station,
    plan_route_fn=plan_route_fn,
    move_drone_to_fn=move_drone_to_fn,
    wait_until_waypoint_reached_fn=wait_until_waypoint_reached_fn,
)
if "error" in pickup_result:
    return {...error path with station context...}
```

`_go_to_station` is a new helper in the same module that:
- Calls `plan_route_fn(asset_id, station["x"], 2.0, station["z"], snap_to_building_center=False)` (pickup altitude matches the existing home-pad landing altitude of 2.0m).
- Iterates waypoints with the same move-and-wait pattern already used for the delivery leg.
- Retries once at `y=15.0` on initial failure, matching the existing retry pattern for the delivery leg.

The `return_to_base_fn` parameter of `dispatch_supply_to_building` remains in the signature for v1 but is no longer invoked for pickup. Removing it requires touching the parallel-fleet dispatcher and its test surface; keeping it in place minimizes diff and risk. Remove in a follow-up cleanup PR once confirmed unused across all call sites.

#### 4. `backend/app.py` (modify)

Register the new routes and ensure the supply-station module is reset on application lifespan start (for clean session state across dev reloads).

### Frontend

#### 5. `frontend/src/lib/api.ts` (modify)

Add thin wrappers: `fetchSupplyStations()`, `placeSupplyStation(x, z)`, `removeSupplyStation(id)`.

#### 6. `frontend/src/lib/ws.ts` (modify)

Handle `supply_station_added` and `supply_station_removed` event types and dispatch into client state.

#### 7. `frontend/src/components/scene-props/SupplyStations.tsx` (new)

Renders all user-placed stations. Each station:
- Orange crate-stack (2 stacked boxes) on a glowing hex-pad base.
- Soft pulsing halo ring for visibility from the radar view.
- Click handler → emits a selection event that the UI layer renders as a floating "Remove / Cancel" HUD card.

Visually distinct from:
- `BasePad` (blue/teal) — the home base, which is not re-rendered by this component.
- `SupplyCrate` (single small orange crate) — the in-flight crate that appears after a successful delivery.

#### 8. `frontend/src/components/panels/Controls.tsx` (or similar existing panel)

Add `[ Place Supply Station ]` toggle button. When active:
- Button shows an "active" highlight.
- R3F canvas enters placement mode (see #9).
- Esc or re-clicking the button exits the mode.

#### 9. `frontend/src/components/scene.tsx` (modify)

While placement mode is active:
- Mouse move → raycast against the ground plane; render a ghost crate-stack at the hovered position.
- Ghost is **green** on valid ground, **red** if the hovered position fails client-side validity checks (inside a building footprint or out-of-bounds).
- Left-click on valid spot → call `placeSupplyStation(x, z)`. On success, the WS event re-renders the station via `SupplyStations`.
- Left-click on invalid spot → no-op (visual feedback only).

#### 10. `frontend/src/app/page.tsx` (hydration)

On initial mount (after WS connect), fire `fetchSupplyStations()` once to populate local state. Thereafter, rely on WS events.

## Data Flow

### Placement
```
User clicks [Place Supply Station]
  → frontend enters placement mode
User hovers ground
  → raycast returns (x, z)
  → ghost preview renders at (x, z) with color by validity
User clicks valid spot
  → POST /supply-stations {x, z}
  → backend validates (not inside building, in bounds), appends to list
  → broadcasts supply_station_added
  → all clients update state, SupplyStations re-renders
```

### Supply dispatch
```
Operator: "deliver supplies to the apartment block"
  → commander agent routes to supply_workflow
  → supply_resolver → supply_assigner → supply_prep → parallel supply loops
For each dispatch:
  dispatch_supply_to_building(asset_id, building)
    → resolve drop point (unchanged)
    → station = select_best_station(target_x=drop_x, target_z=drop_z)
    → _go_to_station(asset_id, station, ...)    # pickup leg
    → plan_route_fn(target=drop)                # delivery leg
    → move + wait waypoints
    → register_supplied_target(building)
```

### Removal
```
User clicks an existing station
  → HUD card shows [Remove] [Cancel]
User clicks Remove
  → DELETE /supply-stations/{id}
  → backend removes, broadcasts supply_station_removed
  → all clients drop the station from state
```

## Error Handling

| Condition | Handling |
|---|---|
| POST with position inside a building | 400 `{error: "Placement inside building is not allowed"}` |
| POST with position out of world bounds | 400 `{error: "Placement outside world bounds is not allowed"}` |
| DELETE home station | 400 `{error: "Home station cannot be removed"}` |
| DELETE unknown station id | 404 |
| Pickup-leg route fails after retry | Return the existing `dispatch_supply_to_building` error payload with `pickup_station: station` added for debugging |
| Station removed during in-flight dispatch | No effect — dispatch uses its captured station copy |
| Zero user stations placed | `select_best_station` returns home; dispatch identical to today |

## Testing

### `tests/test_supply_stations.py` (new)
- `select_best_station` picks the station with smallest distance to target
- `list_stations` always includes home as first entry
- `add_station` returns a unique id and appends
- `remove_station` succeeds for user-placed stations
- `remove_station("home")` raises / returns rejection
- `add_station` inside a building footprint raises
- `add_station` out of bounds raises

### `tests/test_supply_workflow.py` (update)
- Zero user stations → dispatch routes via `(0,0,0)` (regression check for today's behavior)
- One user station placed closer to the target than home → pickup leg waypoints include that station's coordinates, not home
- Two user stations, target closer to station B → station B chosen
- Station removed after dispatch starts → in-flight dispatch still completes via captured station (unit test on selection capture semantics)

### Manual / integration
- Click-to-place 2 stations → issue supply command → observe drone pickup leg goes to the nearer station on the R3F canvas
- Remove a station with pending supply → drone continues to the now-removed station's coordinates (this is expected per decision #3)

## Deferred

Each of these is non-structural and can be added later without reworking this design:

- **Capacity / inventory** — stations become resource pools with crate counts, depletion events, and "empty" UI state.
- **Cross-restart persistence** — persist stations to Supabase; hydrate on backend lifespan startup.
- **Station types** — medical / water / food; dispatcher picks nearest station of the right type for the target.
- **LLM-driven placement tool** — expose `place_station_at(x, z)` as an ADK tool so the operator can say "drop a station near the collapsed hospital."
- **Pickup animation** — emissive pulse on the station as the drone arrives, broadcast as a WS event.
- **Removing `return_to_base_fn` from `dispatch_supply_to_building` signature** — left in place in v1 to minimize diff; remove in a cleanup PR once confirmed unused.

## Fallback Plan

If click-to-place feels clunky in practice, we revert the frontend placement UX (Sections #8, #9) to a baked-in variant: three stations hardcoded in `World2Data.ts` at interesting positions, seeded into the backend list at lifespan startup. Everything else — backend selection, workflow integration, station rendering, WS events — stays identical. The toggle button and ghost-preview logic are the only pieces removed.
