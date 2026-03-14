# Project Beacon — Feature Roadmap

**Recommended implementation order: 2 → 1 → 3 → 6 → 4 → 5**

---

## Feature 2 — Complex Building Environment
*Independent, high impact*

The backend world model only has 2 buildings. The frontend already has ~55 city buildings. Close this gap so drones navigate around the full city.

### Changes
| File | Action |
|------|--------|
| `data/buildings.json` *(new)* | Single source of truth: `[cx, cz, w, d, h, category]` for all ~55 city + 2 SAR buildings |
| `backend/world/model.py` | Replace `_RAW_BUILDINGS` with a JSON loader |
| `drone-sim/world.py` | Same JSON loader so `next_position_blocked` knows about city buildings |
| `drone-sim/Dockerfile` | `COPY data/buildings.json /app/data/` |
| `backend/world/model.py` | Add bounding-box early-out to `obstacles_in_path` (55 buildings × 80 samples = 4400 checks per call) |

### Steps
1. Create `data/buildings.json` from the existing `CITY_BUILDINGS` const in `SARScene.tsx`
2. Load it in `backend/world/model.py` and `drone-sim/world.py`
3. Update Dockerfile to copy the file into the drone-sim image
4. Add AABB bounding-box pre-filter to `obstacles_in_path` to keep route planning fast

---

## Feature 1 — Windows on Buildings
*Frontend only, independent*

Add window geometry to buildings; lit floors correlate with survivor positions.

### Changes
| File | Action |
|------|--------|
| `frontend/src/components/SARScene.tsx` | Add `BuildingWindows` component, wire into `TargetBuilding` |

### Steps
1. Add window grid constants (`WINDOW_ROWS_PER_FLOOR`, `WINDOW_COLS_PER_WALL`, `WINDOW_W`, `WINDOW_H`)
2. Create `BuildingWindows` component using `<instancedMesh>` (avoids draw-call overhead for hundreds of windows)
3. Derive `litFloors: Set<number>` from `SURVIVOR_POSITIONS` — floors with a survivor get bright windows, others are dark
4. Replace the current full-height transparent glass walls in `TargetBuilding` with per-floor wall sections + independent window panes
5. Add simplified horizontal glass-band windows on tall city buildings (already partially done for buildings with `h >= 14`)

> **Gotcha:** The current `TargetBuilding` uses full-height transparent glass panels. These need to be replaced with a per-floor approach so each window's opacity can be controlled independently.

---

## Feature 3 — Fleet Orchestration
*Primarily frontend — backend already supports multiple drones*

Remove the hardcoded `ASSET_ID = 'BEACON-01'` and drive everything from the live telemetry map.

### Changes
| File | Action |
|------|--------|
| `frontend/src/components/SARScene.tsx` | Remove hardcoded `ASSET_ID`, render N `DroneMesh` instances, auto-uplink all |
| `frontend/src/components/CommandPanel.tsx` | Add drone selector (tab/dropdown), change `assetId` prop to `string \| null` |

### Steps
1. Remove `const ASSET_ID = 'BEACON-01'`. Drive selection from `Object.keys(drones)` with a `selectedDroneId` state
2. Render `DroneMesh` for every entry in the `drones` telemetry map; each instance gets its own `lerpPos` ref
3. Add `Html` label (from `@react-three/drei`) above each drone showing its asset_id
4. `DroneStatusPanel` — add `pointerEvents: 'auto'` and a click handler to set `selectedDroneId`
5. `CommandPanel` — add `availableDrones: string[]` prop and a header tab/dropdown to pick a drone or "FLEET"
6. Replace single `uplink(ASSET_ID)` with `getFleet()` then uplink all discovered drones
7. `FollowBeaconCamera` — track the selected drone, not a hardcoded one

> **Gotcha:** `DroneMesh.lerpPos` ref is currently initialised to `DRONE_START`. With multiple drones this must be per-instance — initialise from the drone's first telemetry frame.

---

## Feature 6 — Quick Actions in CommandPanel
*Frontend only*

Expand the existing `DIRECT` action bar with one-click mission shortcuts.

### Changes
| File | Action |
|------|--------|
| `frontend/src/components/CommandPanel.tsx` | Add scrollable quick-action button row and keyboard shortcut handler |
| `frontend/src/components/CommandPalette.tsx` *(new)* | Ctrl+K searchable command palette |

### Steps
1. Define a typed `QUICK_ACTIONS` config array: `{ id, label, icon, prompt, category }`

   | id | label | icon | category |
   |----|-------|------|----------|
   | `scan-building` | Scan Building | 🔍 | scan |
   | `return-fleet` | Return Fleet | ↩ | fleet |
   | `deploy-spread` | Deploy Formation | ⊕ | fleet |
   | `fleet-status` | Fleet Status | 📡 | status |
   | `sweep-area` | Sweep Area | ◧ | scan |

2. Render a scrollable button row below the existing speed/reset buttons; clicking sends the prompt through `onCommand` (same ADK pipeline)
3. Color-code by category: `scan` = amber, `fleet` = cyan, `status` = gray
4. Create `CommandPalette.tsx` — Ctrl+K opens a modal with a search input that filters all actions; Escape closes
5. Coordinate-aware actions — when a ground coordinate is double-clicked, offer a contextual "Move here" / "Scan here" floating mini-menu

> **Key decision:** Quick-action buttons go through the ADK agent (LLM inference), not direct API calls. The `DIRECT` bar (speed toggle, reset) stays for instant hardware-level commands.

---

## Feature 4 — Better Agent Logs
*Minimal backend, mostly frontend*

Richer event rendering in CommandPanel and a persistent mission history panel.

### Changes
| File | Action |
|------|--------|
| `backend/app.py` | Add `GET /mission-logs` endpoint |
| `backend/db/repository.py` | Add `list_all(limit)` to `_MissionLogRepository` |
| `frontend/src/lib/api.ts` | Add `getMissionLogs()` |
| `frontend/src/components/CommandPanel.tsx` | Replace raw string rendering with structured `AgentEventLine` component |
| `frontend/src/components/MissionLogPanel.tsx` *(new)* | Persistent history panel |

### Steps
1. Add `GET /mission-logs?asset_id=&limit=50` endpoint; add `list_all(limit)` to the repo
2. Create `AgentEventLine` component replacing the current raw-line renderer:
   - **Tool calls** — wrench icon, tool name in blue, collapsible args block
   - **Tool results** — ✓/✗ icon, color by tool type, truncated JSON with expand toggle
   - **Sweep results** — collapse to one-line summary by default
3. Tool color map: `move_drone_to` = green, `scan_area`/`thermal_scan` = amber, `return_to_base` = cyan, `error` = red
4. Create `MissionLogPanel.tsx` — side panel showing SQLite-persisted history, auto-refreshes on command completion, filterable by drone
5. Replace the simple toast `<MissionLog>` component in `SARScene.tsx` with the new panel

> **Note:** The simple runtime log (uplink status, "moving to...") and the SQLite mission log are different things. Keep the runtime toast; the new panel shows persisted ADK mission history.

---

## Feature 5 — Supply Delivery to Survivors
*Full-stack vertical slice — depends on Feature 3*

New drone capability: fly near a survivor and drop supplies.

### Changes
| File | Action |
|------|--------|
| `proto/beacon.proto` | Add `SupplyDropRequest` message and `SupplyDrop` RPC |
| `backend/grpc/drone_pb2.py` + `drone_pb2_grpc.py` | Regenerate stubs |
| `drone-sim/sim.py` | Add `supply_drop(survivor_id, supply_type)` method |
| `drone-sim/grpc_server.py` | Implement `SupplyDrop` handler |
| `backend/world/model.py` | Add `delivered_to: set[int]` + `mark_delivered` / `is_delivered` |
| `backend/grpc/client.py` | Add `supply_drop(asset_id, survivor_id, supply_type)` |
| `backend/tools/drone_commands.py` | Add `deliver_supply` tool function |
| `backend/mcp/server.py` | Register `deliver_supply` MCP tool |
| `backend/agents/thermal.py` | Add `deliver_supply` to tool list and instructions |
| `backend/app.py` | Add `GET /survivors` endpoint (positions + delivery status) |
| `frontend/src/components/SARScene.tsx` | Animate delivered survivors (green, no pulse, checkmark) |

### Steps

**1. Proto + Sim**
1. Add `SupplyDropRequest { string asset_id; int32 survivor_id; string supply_type }` and `SupplyDrop` RPC to `beacon.proto`
2. Regenerate Python stubs
3. `sim.py` — `supply_drop()`: check drone within 5m of survivor, enter brief `SCANNING` state, add to `delivered: set[int]`
4. `grpc_server.py` — implement `SupplyDrop` handler calling `self._sim.supply_drop(...)`

**2. Backend**
1. `world/model.py` — add `delivered_to: set[int] = field(default_factory=set)` to `WorldModel`
2. `grpc/client.py` — add `supply_drop` gRPC call
3. `drone_commands.py` — `deliver_supply(asset_id, survivor_id, supply_type)`: validate proximity, call gRPC, call `WORLD.mark_delivered(survivor_id)`
4. `mcp/server.py` + thermal agent — register tool, update agent instructions
5. `app.py` — `GET /survivors` returns `[{ id, x, y, z, submerged, delivered }]`

**3. Frontend**
1. Poll `GET /survivors` periodically (or on command completion)
2. `Survivors` component — delivered survivors: green colour, no pulse, small supply-drop indicator
3. Brief falling-box animation when delivery state first changes

> **Gotcha:** Drone must be within 5m of the survivor (building is 8×8m, floors 3m tall). The agent should call `get_drone_view` to confirm survivors are in range before calling `deliver_supply`.
>
> **Gotcha:** `WORLD.delivered_to` is in-process mutable state — resets on server restart. Good enough for now; add SQLite persistence in a follow-up.

---

## Key File Summary

| File | Features |
|------|----------|
| `frontend/src/components/SARScene.tsx` | 1, 2, 3, 4, 5, 6 |
| `frontend/src/components/CommandPanel.tsx` | 3, 4, 6 |
| `frontend/src/lib/api.ts` | 4, 5 |
| `backend/world/model.py` | 2, 5 |
| `backend/tools/drone_commands.py` | 5 |
| `backend/mcp/server.py` | 5 |
| `backend/app.py` | 4, 5 |
| `backend/db/repository.py` | 4 |
| `proto/beacon.proto` | 5 |
| `drone-sim/sim.py` | 5 |
| `drone-sim/grpc_server.py` | 5 |
| `data/buildings.json` | 2 *(new)* |
| `frontend/src/components/CommandPalette.tsx` | 6 *(new)* |
| `frontend/src/components/MissionLogPanel.tsx` | 4 *(new)* |

---

## Success Criteria

- [ ] Windows visible on target building floors; lit floors match survivor positions
- [ ] City buildings registered as obstacles in both backend and drone-sim; routes navigate around the full city
- [ ] Multiple drones render in 3D scene simultaneously with independent telemetry
- [ ] CommandPanel allows selecting which drone to command, or addressing the whole fleet
- [ ] Mission logs accessible via `GET /mission-logs` and rendered in a dedicated panel
- [ ] Tool call/result events in CommandPanel are colour-coded and collapsible
- [ ] `deliver_supply` MCP tool works end-to-end: agent calls it, drone sim executes, survivor marker updates
- [ ] Quick-action buttons send commands through the ADK agent pipeline
- [ ] Command palette opens with Ctrl+K and filters actions
