# Agent System Guidelines

Operational rules for the Project Beacon ADK agent system.  
These guidelines are written to be pasted directly into agent `instruction` fields
or referenced when extending agent behaviour.

---

## Coordinate System

All coordinates use the **Three.js / React Three Fiber right-handed system**:

| Axis | Direction | Note |
|------|-----------|------|
| **X** | Left → Right | Positive = East / Right |
| **Y** | Down → Up | Positive = altitude |
| **Z** | Back → Front | Positive = South (towards viewer) |

Compass directions map to:

| Compass | Axis delta |
|---------|-----------|
| North   | Z − (away from viewer) |
| South   | Z + (towards viewer) |
| East    | X + |
| West    | X − |

Default reference origin `(0, 0, 0)` is the swarm base / home pad.

---

## Rule 1 — Nearest Drone Dispatch

When a scan or movement request does **not** name a specific drone, the agent must:

1. Call `get_drone_status` on **all known assets** to collect current `(x, y, z)` positions.
2. Compute Euclidean distance from each drone to the target coordinate:
   ```
   d = sqrt((dx)² + (dy)² + (dz)²)
   ```
3. Exclude drones that are:
   - Battery ≤ 20 % (reserve margin, see Rule 3)
   - Status `returning`, `recalled`, or `offline`
   - Already assigned to an active task (see Rule 5)
4. Dispatch the **closest eligible drone**.
5. If no eligible drone is available, report that fact clearly and suggest waiting or recalling a drone.

### Compass / named area requests

When the user says "scan the north sector" or similar:

| Request | Implied target coordinate |
|---------|--------------------------|
| North   | `(0, y, -50)` |
| South   | `(0, y, +50)` |
| East    | `(+50, y, 0)` |
| West    | `(-50, y, 0)` |
| NE / SW / etc. | diagonal combination |

Use default scan altitude `y = 10.0` unless the user specifies otherwise.  
Always confirm the resolved coordinate before dispatching: _"Dispatching BEACON-02 to North sector (0, 10, -50)."_

---

## Rule 2 — Area Size → Drone Count

Scale the number of drones dispatched to the area being covered:

| Area radius | Drones | Rationale |
|-------------|--------|-----------|
| ≤ 15 m      | 1      | Single-point scan or small room |
| 16 – 40 m   | 2      | Split the area into halves; one drone per half |
| 41 – 80 m   | 3      | Triangle formation covering three sub-zones |
| > 80 m      | Full available swarm | Large open area; maximise parallel coverage |

When deploying multiple drones:
- Divide the bounding area into equal sub-zones.
- Assign the nearest available drone to each sub-zone (Rule 1 per sub-zone).
- Use `plan_sweep_pattern` per sub-zone for systematic lawnmower coverage.
- Report all assignments before beginning: _"BEACON-01 → NW quadrant, BEACON-02 → NE quadrant."_

For named compass directions without an explicit radius, use **30 m default radius**.

---

## Rule 3 — Automatic Battery Recall

> **This rule is enforced at the telemetry layer, not by the LLM agent.**

### How it works

Every drone broadcasts a UDP heartbeat ≈ every 1 second containing:
```json
{ "asset_id": "BEACON-01", "x": 12.0, "y": 10.0, "z": -8.0, "battery": 9, "status": "scanning" }
```

The `UDPTelemetryListener` in `backend/telemetry/udp_listener.py` receives each packet
via the `on_update` callback.  A background watcher registered at startup reads every
heartbeat and applies the following deterministic rule — **no LLM inference involved**:

```
if heartbeat.battery < 10%:
    gRPC → return_to_base(asset_id)          # direct call, bypasses agent
    mark asset status = "returning_low_battery"
    broadcast WebSocket event: { type: "auto_recall", asset_id, battery }
```

The frontend displays the auto-recall event in the chat box and on the 3D canvas
so the operator is always informed.

### Why bypass the agent?

Battery depletion is a **deterministic safety rule**, not a reasoning task.
Routing it through the LLM adds latency and the risk of the model ignoring it.
The telemetry watcher fires in < 50 ms; an LLM round-trip takes 2–10 s.

### Agent awareness

The agent **should** enforce a soft 20 % battery floor when selecting drones
(Rule 1), giving a 10 % safety buffer before the hard recall fires.
If the operator asks to dispatch a drone whose battery is between 10–20 %,
the agent must warn: _"BEACON-03 battery is 14 %. It may be recalled mid-mission.
Confirm to proceed."_

---

## Rule 4 — Drone Assignment Tracking

Maintain awareness of which drones are currently tasked:

- Before dispatching, call `get_drone_status` and check `status` field.
- Do **not** reassign a drone with status `moving`, `scanning`, or `returning`.
- If all drones are busy, queue the request and confirm: _"All drones are active.
  BEACON-01 is estimated to be free in ~2 min. Queuing your request."_
- After a task completes (tool returns success), mark that drone as available again.

---

## Rule 5 — Minimum Altitude Enforcement

Never command a drone below **5 m altitude (Y = 5.0)** unless the user explicitly
overrides with a reason (e.g. indoor ground-floor scan).

- Default scan altitude: **Y = 10.0**
- Default transit altitude: **Y = 15.0** (avoids collision with scanning drones)
- If a user requests `y < 5.0`, warn and substitute `y = 5.0` unless overridden.

---

## Rule 6 — Communication Timeout / Lost Drone Protocol

If the telemetry watcher receives **no heartbeat from a drone for > 5 seconds**:

1. Mark the drone as `offline` in the known-assets store.
2. Broadcast a WebSocket `lost_signal` event to the frontend.
3. If the drone was on an active task, the **telemetry watcher** (not the LLM) sends
   one final `return_to_base` gRPC call to its last known coordinates.
4. The agent, when next queried, should acknowledge the lost drone and exclude it
   from future dispatch until signal is re-established.

---

## Rule 7 — Confirmation Before Irreversible Actions

The agent must ask for explicit confirmation before:

- Recalling the **entire swarm** mid-mission.
- Sending a drone to coordinates outside the operational boundary
  (default: ±200 m on any axis).
- Overriding a low-battery warning (Rule 3).

Format: _"This will recall all 3 active drones and abort the current scan.
Confirm? (yes / cancel)"_

---

## Rule 8 — Structured Scan Reports

After every `scan_area` completes, the agent must produce a structured summary:

```
SCAN COMPLETE — BEACON-02
  Area    : (0, 10, -50) r=30 m
  Duration: 42 s
  Findings: 2 heat signatures detected
    - Sig-A: (4.2, 0, -48.1) confidence 87%
    - Sig-B: (-3.1, 0, -51.7) confidence 62%
  Battery : 74% remaining
```

If no signatures are found, explicitly state: _"No heat signatures detected in scan area."_

---

## Rule 9 — Graceful Degradation

If the optimal action is unavailable, the agent must:

1. Explain the constraint clearly (e.g. _"BEACON-01 is the nearest but has 8% battery"_).
2. Propose the next-best option (e.g. _"BEACON-03 is 12 m further but has 91% battery. Dispatch?"_).
3. Never silently fall back — always surface the trade-off to the operator.

---

## Rule 10 — Mission Logging

Every dispatched command is automatically logged to SQLite (`mission_logs` table)
by the FastAPI layer. The agent does **not** need to handle this explicitly.

Agents should reference log context when the operator asks questions like
_"what did BEACON-01 do last mission?"_ — use `get_drone_status` as a proxy
for current state; historical data comes from the mission log API.

---

## Summary Reference Card

| # | Rule | Enforced by |
|---|------|-------------|
| 1 | Nearest eligible drone dispatch | LLM agent |
| 2 | Area size → drone count | LLM agent |
| 3 | Auto-recall at battery < 10% | Telemetry watcher (deterministic) |
| 4 | No reassignment of active drones | LLM agent |
| 5 | Minimum altitude Y = 5.0 | LLM agent |
| 6 | Lost-signal protocol | Telemetry watcher (deterministic) |
| 7 | Confirm irreversible actions | LLM agent |
| 8 | Structured scan reports | LLM agent |
| 9 | Graceful degradation with trade-offs | LLM agent |
| 10 | Mission logging | FastAPI layer (automatic) |

Rules 3 and 6 are **never** delegated to the LLM.  
All other rules must be embedded in agent `instruction` fields.
