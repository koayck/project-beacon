# Deploy Scout Sweep Flow

This document describes the end-to-end flow after the user presses **DEPLOY SCOUT** and sends:

> Deploy the scout drone to survey the disaster zone and map every sector.

## 1) Frontend trigger

- The quick-action prompt constant is defined in `frontend/src/components/panels/CommandPanel.tsx`.
- The **DEPLOY SCOUT** button calls `submit(SCOUT_DEPLOY_PROMPT)`.
- `submit(...)` calls the panel's `onCommand(...)` callback.

## 2) Scene command pipeline

- `onCommand` is implemented by `handleCommand(...)` in `frontend/src/components/scene.tsx`.
- It creates an `AbortController`, marks the UI as busy, and starts streaming with:
  - `streamCommand(effectiveAssetId, prompt, ac.signal)`
- As stream events arrive, it forwards them to the panel and updates mission activity state.

## 3) SSE request to backend

- `streamCommand(...)` in `frontend/src/lib/api.ts` sends a `POST` request to `/command/stream`.
- It parses Server-Sent Events (`data: ...`) and yields structured events:
  - `tool_call`
  - `tool_result`
  - `text`
  - `final`
  - `heartbeat`
  - `error`
  - `done`

## 4) Backend stream endpoint and ADK run

- FastAPI endpoint: `POST /command/stream` in `backend/app.py`.
- Backend creates an ADK session and runs the commander agent asynchronously.
- A heartbeat task emits elapsed-time updates every 3 seconds while the mission runs.
- Tool calls/results and text are streamed back to the frontend as SSE.

## 5) Commander routing decision

- Commander instructions in `backend/agents/commander.py` explicitly map scout/recon language to `deploy_scout_sweep`.
- Instructions also explicitly say scout commands should **not** be routed to `navigation_agent` or `scan_agent`.
- Commander has MCP swarm tools enabled (including `deploy_scout_sweep`).

## 6) MCP tool execution

- Tool entrypoint: `deploy_scout_sweep_tool()` in `backend/mcp/server.py`.
- Flow inside the tool:
  1. `ensure_scout_uplink()` ensures `BEACON-SCOUT` is connected.
  2. `start_scout_sweep()` starts (or reuses) the running sweep task.
  3. The tool `await`s task completion.
- This is intentionally long-running: the agent call waits for physical sweep completion.
- On completion, tool returns structured mapping intel (sector counts, thermal anomaly sectors, and per-sector details).

## 7) Scout service mission behavior

- Core mission logic: `backend/services/scout.py`.
- `run_scout_sweep()` sequence:
  1. Takeoff to cruise altitude.
  2. Enable exploration tracking only after takeoff.
  3. Fly a lawnmower pattern over a 5x5 grid (25 sectors).
  4. Disable tracking before descent/RTB.
  5. Return to base.
- `start_scout_sweep()` is idempotent: if a sweep is already active, it returns the existing task.

## 8) Sector reveal and fog-of-war updates

- Telemetry heartbeat path updates exploration state in `backend/telemetry/ws_bridge.py`.
- For `BEACON-SCOUT` heartbeats:
  - `process_heartbeat(...)` updates explored sectors.
  - Payload is enriched with `explored_sectors`.
  - Newly revealed sectors are emitted as `sector_reveals`.
- Sector reveal metadata comes from `ExplorationTracker._build_reveal_info(...)`, including:
  - `building_count`
  - `max_height`
  - `thermal_anomalies`
  - `survivor_count`

## 9) What the operator sees

- In `CommandPanel`:
  - elapsed time from `heartbeat`
  - tool calls and results
  - final summary text
  - completion metrics from `done` (`ttft_ms`, `tps`)
- In the 3D view:
  - fog-of-war sectors reveal progressively as scout telemetry updates stream in.

## Important distinction

There are two ways to start scout sweep in this codebase:

1. Natural-language path (used by DEPLOY SCOUT quick action):
   - `POST /command/stream` -> commander routing -> `deploy_scout_sweep` MCP tool

2. Direct API path:
   - `POST /scout/sweep`

The quick action described in this flow uses the natural-language/agent path, not the direct `/scout/sweep` route.
