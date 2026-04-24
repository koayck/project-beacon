# CLAUDE.md

DO NOT create subagents, ever.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Zero-cloud, offline-first Ground Control Station for autonomous drone swarms in comms-denied environments. Defaults to **Gemini 3 Flash** via LiteLLM; BYOC mode swaps in a local Ollama model at `backend/agents/_model.py`. Avoid over-engineering — prefer clarity over cleverness.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Desktop shell | Tauri (wraps static Next.js export) |
| Frontend | Next.js 14 SSG (`output: 'export'`), React Three Fiber |
| API server | FastAPI (Python sidecar) |
| AI orchestration | Google ADK multi-agent graph |
| LLM routing | LiteLLM → Gemini 3 Flash (default) or Ollama |
| Tool bridge | FastMCP (mounted at `/mcp/`) |
| Drone comms | gRPC + Protobuf (`proto/beacon.proto` is source of truth) |
| Drone simulation | Pure Python state machine in Docker containers |
| Telemetry | UDP broadcast → WebSocket relay to frontend |
| Storage | Supabase PostgreSQL (asyncpg, no ORM) |
| ADK sessions | PostgreSQL via `DatabaseSessionService` |
| Python packaging | `uv` |

## Commands

```bash
# Backend
uv sync                                      # Install Python deps
uv run python -m backend.app                 # Start FastAPI on :8000
adk web backend/agents/commander.py          # ADK dev UI for agent traces

# Tests
uv run pytest                                # All tests
uv run pytest tests/test_plan_route.py       # Single file
uv run pytest -k "test_name"                 # Filter by name

# Drone simulation
docker compose up -d                         # Start simulated swarm (beacon-01/02/03)
docker compose logs -f beacon-01             # Watch a drone

# Frontend
cd frontend && bun install && bun run dev    # Next.js dev server
cd frontend && bun run tauri:dev             # Tauri desktop shell

# Proto / gRPC stubs
bash scripts/gen_proto.sh                    # Regenerate from proto/beacon.proto

# Production
docker compose -f docker-compose.prod.yml up -d
```

## Repo Structure

- `backend/` — FastAPI sidecar, all Python business logic, agents, and services
  - `agents/` — ADK agent definitions (commander, navigation, scan/supply workflows, recovery)
  - `services/` — Deterministic mission logic consumed by MCP tools and endpoints
  - `mcp/` — FastMCP server that exposes drone control tools to the agent graph
  - `grpc/` — gRPC client managing connections to drone containers; generated stubs live here
  - `orchestrator/` — Low-level execution helpers for navigation and scanning steps
  - `world/` — World grid model, flood physics, and thermal visibility helpers
  - `telemetry/` — UDP heartbeat listener and WebSocket broadcaster
  - `db/` — asyncpg repositories for `assets`, `mission_logs`, `licenses` (Supabase)
  - `licensing/` — Offline license key validation, activation routes, and storage
- `drone-sim/` — Simulated drone containers: gRPC server, state machine, UDP telemetry emitter
- `frontend/` — Next.js + React Three Fiber tactical desktop UI (Tauri shell wraps static export)
- `proto/` — `beacon.proto` is the source of truth for the gRPC contract; never hand-edit generated stubs
- `shared/` — World definition JSON files consumed by both backend and the frontend build step
- `tests/` — pytest unit and integration tests for backend logic
- `scripts/` — Proto stub generation and network utility scripts

## Architecture

### Request Flow

```
Operator
  → POST /command  (or SSE stream: /command/stream)
  → ADK Runner (shared PostgreSQL session)
    → commander agent (Gemini 3 Flash, temp=0.35, thinking enabled)
      ├── sub_agents: [recovery_agent, navigation_agent, scan_agent, supply_agent]
      └── tools: [AgentTool(command_parser), AgentTool(scan_resolver), AgentTool(supply_resolver), McpToolset]
            → FastMCP server (/mcp/)
              → services/api/  (business logic)
                → DroneGrpcClient → gRPC → drone-sim containers
```

### Key Layers

**`backend/agents/`** — All ADK agents. `commander.py` is the root; `_model.py` sets the model and two temperature profiles (strategic `QWEN3_GEN_CONFIG_COMMANDER` and execution `QWEN3_GEN_CONFIG_EXECUTION`). `_mcp.py` provides `make_toolset()` — each agent must get its own `McpToolset` instance (ADK single-parent rule). `schemas.py` holds Pydantic mission/intent schemas.

**`backend/mcp/server.py`** — FastMCP server exposing drone control tools to ADK agents. Mounted as a sub-app in FastAPI at `/mcp/`.

**`backend/services/`** — Deterministic business logic consumed by MCP tools and REST endpoints.
- `api/` — high-level wrappers (fleet discovery, uplink, movement, scanning, assignment)
- `navigation/` — route_planner, sweep_planner, target_resolution
- `workflows/` — sweep, supply, return workflow implementations
- `fleet.py`, `fleet_assignment.py`, `auto_recall.py`, `swarm_control.py`, `scan_reporting.py`

**`backend/orchestrator/`** — Low-level execution helpers for navigation and scanning.

**`backend/grpc/client.py`** — Manages per-drone gRPC connections. Stubs (`beacon_pb2*`) are generated from `proto/beacon.proto` — run `scripts/gen_proto.sh` if missing.

**`backend/db/repository.py`** — asyncpg repository for `assets`, `mission_logs`, `licenses` tables in Supabase. `SUPABASE_DB_URL` env var is required at startup.

**`backend/telemetry/`** — `udp_listener.py` receives drone heartbeat broadcasts; `ws_bridge.py` fans them to WebSocket clients at `/ws/telemetry`.

**`backend/world/`** — `model.py` encodes the 52×52 m grid, flood levels, and physics; `vision.py` handles thermal visibility.

**`backend/licensing/`** — Offline key activation (`BEACON-XXXX-XXXX-XXXX-XXXX` format + checksum). Keys stored in Supabase `licenses` table. Validation never contacts an external server. App is hard-locked without a valid key; 7-day grace period on expiry.

**`backend/runtime.py`** — Shared singleton instances (`grpc_client`, `udp_listener`, `ws_broadcaster`) imported by app.py and services.

**`drone-sim/`** — Each container runs a gRPC server + UDP telemetry broadcaster. Statically addressed at `172.28.0.11–13` on the `beacon-net` bridge.

**`frontend/src/`**
- `components/scene.tsx` — Main tactical scene and mission UI orchestration
- `components/panels/` — Command panel, status bars, overlays
- `components/scene-props/` — Buildings, terrain, drones, survivors
- `components/animation/` — Camera tracking and throw animation
- `lib/api.ts` — REST + SSE event stream client to FastAPI
- `lib/ws.ts` — Telemetry WebSocket hook
- `generated/` — World environment types auto-generated at build time from `shared/world2.json`

**`shared/`** — World definition JSON files (world.json variants) shared between backend and frontend build.

### ADK Session Persistence

ADK sessions are persisted in PostgreSQL via `DatabaseSessionService`. A shared session is created at startup (`_ensure_adk_shared_session`) so all HTTP requests share mission context across backend restarts.

### LLM Configuration

Change the active model in `backend/agents/_model.py` — the `model` variable at the top. Ollama config is commented out below it. Two temperature profiles:
- `QWEN3_GEN_CONFIG_COMMANDER` — strategic agents (temp=0.35, thinking enabled)
- `QWEN3_GEN_CONFIG_EXECUTION` — execution agents (temp=0.25)

### Environment

`SUPABASE_DB_URL` is required — missing causes startup failure. Optional: `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` for LiteLLM → Langfuse tracing. `BEACON_MCP_URL` defaults to `http://127.0.0.1:8000/mcp/`.

## Coding Conventions

- All drone communication uses gRPC — never REST between commander and drone containers
- No API routes in Next.js — all logic lives in FastAPI sidecar
- Parameterized queries only in repository layer — never interpolate strings into SQL
- ADK agents are single-responsibility; no shared mutable state between agents
- Each `McpToolset` instance must be owned by exactly one agent

## Code commit guidelines
- make frequent, small, focused commits, with each commit addressing a single, logical change or task. This makes changes easy to review and debug.
- Utilize the Conventional Commits format (e.g., feat:, fix:, docs:) to provide a clear, standardized history of changes. Messages should be in the imperative mood and kept short

## Architecture Change guidelines
- for every architecture change, update ./ARCHITECTURE.md to reflect the latest architecture