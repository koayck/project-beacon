# Project Beacon

Zero-cloud, offline-first Ground Control Station for autonomous drone swarms in comms-denied environments. Local LLM (Qwen 3.5 4B via Ollama) drives all agent decisions — no internet required.

---

## Quick Start

```bash
# 1. Install dependencies
uv sync

# 2. Start the simulated swarm (3 drone containers)
docker compose up -d

# 3. Start the FastAPI sidecar
uv run python -m backend.app

# 4. (Optional) ADK dev UI — inspect agent traces
adk web backend/agents/commander.py

# 5. Run the CLI test suite against a live drone
uv run python tests/test_adk_cli.py
```

**Prerequisites:** Docker, Ollama with `qwen3.5:4b-q4_K_M` pulled, Python 3.11+, `uv`.

---

## Observability (Langfuse)

Langfuse tracing is integrated through LiteLLM and is **optional**.
Project Beacon stays offline-first by default; traces are only sent when Langfuse env vars are provided.
The backend uses `langfuse>=4,<5` and applies a startup compatibility shim for LiteLLM's
`sdk_integration` callback argument mismatch.

### 1) Configure environment

Copy `.env.example` to `.env` and set:

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_HOST` (optional, defaults to Langfuse cloud; set your local/self-hosted URL for offline deployments)

### 2) Start backend

```bash
uv run python -m backend.app
```

When both keys are present, backend logs include:

```text
Langfuse observability enabled
```

All ADK agent model calls routed via LiteLLM are then traceable in Langfuse for easier debugging.

---

## Sample Prompts

Send these via `POST /command` or the ADK web UI.
The world is a 52×52 m grid. Drones spawn at the south-east corner. Flood level = 1.4 m.

> All prompts assume at least one drone is uplinked. If you don't specify a drone,
> the commander calls `select_best_drone` automatically and picks the nearest IDLE
> drone with battery > 20%.

---

### Status & Discovery

```
What is the status of all drones?
```
```
List every uplinked drone with its position and battery.
```
```
Is BEACON-01 ready for a mission?
```

---

### Movement (navigation_agent)

Move to an explicit coordinate:
```
Move BEACON-01 to coordinates 10, 15, -20.
```

Move to a named sector (Y=10 default):
```
Send BEACON-02 north.
```
```
Fly BEACON-01 to the east sector at altitude 20.
```

High-altitude overwatch above the centre of the grid:
```
Ascend BEACON-01 to overwatch position at 0, 25, 0.
```

Return to home pad:
```
Return BEACON-01 to base.
```
```
Recall all drones to home.
```

---

### Scan Workflows (scan_agent → navigation + thermal)

The commander navigates the drone to the target first, then scans.
It will automatically pick the best available drone if none is specified.

**Scan the central cluster — three survivors at Y=3.8, Y=7.8, Y=11.8:**
```
Scan the building at 0, 0 for survivors.
```
```
Scan coordinates -1, 5, 1 with radius 8 for heat signatures.
```

**Scan for flood victims** (ground-level survivors at Y=0.4 are submerged — flagged CRITICAL):
```
Scan the flooded area at 8, 0, 5 for survivors.
```
```
Check coordinates -7, 0, -6 for casualties — there may be people in the water.
```
```
Scan the flood zone at 25, 0, -10 radius 5.
```

**Scan a mid-rise building:**
```
Scan the building at -22, 0, 2 — suspected survivor on upper floors.
```
```
Scan 20, 5, 0 radius 6 for thermal signatures.
```

**Scan a tall building (30 m) — survivor at Y=31:**
```
Scan the tall building at -10, 0, -8. Check upper floors.
```

**Scan the tower district (south-east, 40 m tower):**
```
Scan the tower at 30, 20, -38. Survivor reported near the top.
```

---

### Sweep Patterns (navigation_agent)

Systematic lawnmower sweep over a rectangular area:
```
Plan a sweep over the area from -10, -10 to 10, 10 at altitude 12, spacing 3.
```
```
Run a sweep pattern over the north sector from -20, -60 to 20, -30.
```

---

### Swarm Operations

Deploy in formation (supported: `spread`, `line`, `triangle`):
```
Deploy BEACON-01, BEACON-02, and BEACON-03 in triangle formation.
```
```
Deploy all drones in a spread formation to the north.
```

Recall:
```
Recall the swarm — mission complete.
```

---

### Edge Cases & Safety Checks

**Low-battery warning** (commander blocks dispatch below 20%):
```
Move BEACON-01 to 50, 10, 0.
```
*(If BEACON-01 is low, commander will offer an alternative.)*

**Obstacle avoidance** — building at (-14, -12) is 20 m tall:
```
Move BEACON-01 to -14, 10, -12.
```
*(Navigation agent detects obstacle, climbs to clear it.)*

**Out-of-bounds confirmation** — anything beyond ±200 m requires explicit confirm:
```
Send BEACON-01 to 250, 10, 0.
```

**No eligible drones:**
```
Deploy BEACON-01 to the south sector.
```
*(While BEACON-01 is already MOVING — commander will reject and explain.)*

---

## World Reference

| Feature | Coordinates | Notes |
|---------|------------|-------|
| Home pad / base | (0, 0, 0) | All drones spawn and return here |
| Target building | (-15, ?, -20) h=12 m | 4-floor glass tower; 3 survivors inside |
| Obstacle | (-7, ?, -10) h=10 m | Solid block on direct route base → target |
| Survivor — floor 2 | (-16.5, 3.65, -19.0) | Inside target building |
| Survivor — floor 3 | (-14.5, 6.65, -20.5) | Inside target building |
| Survivor — floor 4 | (-13.5, 9.65, -21.0) | Inside target building |
| Survivor detection radius | 12 m sphere | Drone must be within 12 m (3D) to detect |
| North sector default | (0, 10, -50) | Named sector target |
| South sector default | (0, 10, 50) | Named sector target |
| East sector default | (50, 10, 0) | Named sector target |
| West sector default | (-50, 10, 0) | Named sector target |

---

## Agent Architecture

```
Commander (temp=0.5)
├── select_best_drone()   ← picks nearest IDLE drone with battery > 20%
├── scan_agent         ← SequentialAgent: navigation_agent → thermal_agent
│     navigation_agent (temp=0.7)   move + obstacle avoidance
│     thermal_agent     (temp=0.7)  scan + structured report
├── navigation_agent      ← movement-only commands
├── deploy_swarm()
└── recall_swarm()
```

All agents use `qwen3.5:4b-q4_K_M` via Ollama at `localhost:11434`. No cloud calls.

---

## Development Commands

```bash
# Regenerate gRPC stubs after editing proto/beacon.proto
bash scripts/gen_proto.sh

# Watch a single drone container
docker compose logs -f beacon-01

# Run tests
uv run pytest
uv run python tests/test_adk_cli.py
```
