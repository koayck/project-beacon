# Project Beacon — CLAUDE.md

## Project Overview

**Project Beacon** is an zero-cloud, offline-first Ground Control Station (GCS) for autonomous drone swarms in comms-denied environments (disaster zones, search & rescue). It uses a "Bring Your Own Compute" (BYOC) architecture — local LLMs via Ollama, zero cloud dependency.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│ HOST MACHINE (Commander Node)                                    │
│                                                                  │
│  ┌──────────────────┐         ┌──────────────────────────────┐  │
│  │ Tauri Desktop    │  HTTP   │ FastAPI Sidecar              │  │
│  │  Next.js (SSG)   │────────▶│  ├─ Google ADK               │  │
│  │  React Three     │         │  │   ├─ Commander Agent      │  │
│  │  Fiber (3D twin) │◀────────│  │   ├─ Navigation Agent     │  │
│  │                  │  WS     │  │   └─ Thermal Agent        │  │
│  └──────────────────┘         │  ├─ LiteLLM → Ollama (local) │  │
│                               │  ├─ FastMCP (tool bridge)    │  │
│                               │  └─ SQLite (mission logs)    │  │
│                               └──────────────┬───────────────┘  │
└──────────────────────────────────────────────┼──────────────────┘
                                               │ gRPC (protobuf)
                              ┌────────────────▼─────────────────┐
                              │ DOCKER NETWORK (Simulated MANET) │
                              │                                  │
                              │  ┌──────┐ ┌──────┐ ┌──────┐    │
                              │  │ B-01 │ │ B-02 │ │ B-03 │    │
                              │  │drone │ │drone │ │drone │    │
                              │  │ sim  │ │ sim  │ │ sim  │    │
                              │  └──┬───┘ └──┬───┘ └──┬───┘    │
                              │     └────────┴────────┘         │
                              │        UDP telemetry → UI       │
                              └──────────────────────────────────┘
```

### Data Flow (Deploy Swarm)

```
User clicks "Deploy Swarm"
  │
  ▼
Tauri UI ──HTTP──▶ FastAPI ──▶ ADK Commander Agent
                                    │
                              LiteLLM → Ollama (Qwen 3.5 4B)
                                    │
                              ADK tool call output
                                    │
                              FastMCP translates to Python function
                                    │
                              gRPC protobuf ──▶ Docker drone container
                                                      │
                                                updates X/Y/Z + battery
                                                      │
                                                UDP telemetry ──▶ WebSocket ──▶ R3F canvas moves
                                                      │
                                              SQLite mission log
```

## Directory Structure

```
project-beacon/
├── backend/
│   ├── __init__.py
│   ├── app.py                # FastAPI application entry point
│   ├── agents/               # Google ADK agent definitions
│   │   ├── commander.py      # Root agent — routes to sub-agents
│   │   ├── navigation.py     # Flight path planning
│   │   └── thermal.py        # Thermal/camera feed analysis
│   ├── tools/                # FastMCP tool definitions (LLM → gRPC)
│   │   ├── drone_commands.py # move_to, return_home, scan_area
│   │   └── swarm_ops.py      # deploy_swarm, recall_swarm
│   ├── grpc/
│   │   ├── drone.proto       # Protobuf schema
│   │   ├── drone_pb2.py      # Generated stubs (do not edit)
│   │   └── client.py         # gRPC client for sending commands
│   ├── telemetry/
│   │   ├── udp_listener.py   # Receives drone heartbeats/coords
│   │   └── ws_bridge.py      # Forwards telemetry to frontend via WebSocket
│   └── db/
│       ├── schema.sql        # SQLite DDL
│       ├── models.py         # Pydantic models
│       └── repository.py     # Data access layer
├── drone-sim/
│   ├── Dockerfile
│   ├── sim.py                # Pure Python drone state machine
│   ├── grpc_server.py        # Receives commands from commander
│   └── telemetry.py          # Broadcasts UDP heartbeat + coords
├── frontend/                 # Next.js + Tauri + React Three Fiber
│   ├── src/
│   │   ├── app/              # Next.js pages (SSG)
│   │   ├── components/
│   │   │   ├── radar/        # 3D digital twin canvas
│   │   │   ├── spawner/      # Developer spawner panel
│   │   │   └── dashboard/    # Commander tactical dashboard
│   │   └── lib/
│   │       ├── ws.ts         # WebSocket client for telemetry
│   │       └── api.ts        # HTTP client for FastAPI sidecar
│   ├── src-tauri/            # Tauri Rust shell
│   ├── next.config.mjs       # output: 'export' (SSG)
│   └── package.json
├── proto/                    # Source-of-truth .proto files
│   └── beacon.proto
├── docker-compose.yml        # Drone swarm network
├── pyproject.toml
├── test.py                   # Ursina visual prototype (standalone demo)
└── CLAUDE.md
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Desktop shell | Tauri | Native window, filesystem access, sidecar management |
| Frontend | Next.js (SSG, `output: 'export'`) | Static HTML/JS/CSS bundled into Tauri |
| 3D visualization | React Three Fiber | Digital twin radar, drone model rendering |
| API server | FastAPI | Python sidecar, all business logic |
| AI orchestration | Google ADK | Multi-agent framework with tool calling |
| LLM routing | LiteLLM | Abstracts Ollama as OpenAI-compatible endpoint |
| Local LLM | Qwen 3.5 (4B) via Ollama | Offline inference, zero cloud |
| Tool bridge | FastMCP | Translates ADK tool calls → Python functions |
| Drone comms | gRPC + Protobuf | Low-latency commands to drone containers |
| Drone simulation | Pure Python (dataclasses) | Lightweight state machine in Docker |
| Telemetry | UDP broadcast + WebSocket relay | Drone coords → frontend in real-time |
| Storage | SQLite | Local mission logs, asset registry |
| Networking | Docker bridge network | Simulated MANET with isolated IPs |
| Python packaging | uv | Dependency management |

## ADK Agent Design

```
Commander Agent (root)
│   Role: Receives natural language commands, decides which
│         sub-agent handles the task, aggregates results.
│
├── Navigation Agent
│     Tools: move_drone_to(asset_id, x, y, z)
│            plan_sweep_pattern(area_bounds, spacing)
│            return_to_base(asset_id)
│     Role: Flight path computation, waypoint generation.
│
└── Thermal Agent
      Tools: scan_area(asset_id, x, y, z, radius)
             get_thermal_feed(asset_id)
      Role: Thermal camera analysis, survivor detection.
```

All agents use `LiteLLM` pointed at `http://localhost:11434` (Ollama). No external API calls.

## Key Workflows

### 1. Developer Spawner (Simulation Setup)
1. User selects asset class (Scout Quadcopter) → clicks **"Initialize Virtual Asset"**
2. FastAPI calls `docker run` to spin up a `drone-sim` container
3. Container starts gRPC server + UDP heartbeat broadcaster
4. Container appears as a network node on the Docker bridge

### 2. Drone Discovery & Uplink
1. User clicks **"Scan Local Frequencies"** → animated radar sweep in R3F
2. FastAPI `udp_listener` collects heartbeats from Docker containers
3. Unpaired assets populate: `BEACON-01 | SIGNAL: 98%`
4. User clicks **"Establish Uplink"** → FastAPI opens gRPC channel, registers in SQLite
5. R3F injects 3D drone model mapped to live telemetry coordinates

### 3. Mission Execution (Deploy Swarm)
1. User types natural language command in Tauri UI
2. Frontend sends HTTP POST to FastAPI → ADK Commander Agent
3. Commander routes to Navigation/Thermal agent → LiteLLM → Ollama
4. Agent returns tool call → FastMCP executes corresponding Python function
5. Function fires gRPC protobuf to target drone container(s)
6. Drone sim updates state (X/Y/Z, battery, status)
7. Drone broadcasts telemetry via UDP → FastAPI relays via WebSocket → R3F renders

## Implementation Phases

### Phase 1: Drone Simulation Layer
**Goal:** A working drone that receives gRPC commands and broadcasts telemetry.

- [ ] Define `proto/beacon.proto` (MoveTo, GetStatus, Heartbeat messages)
- [ ] Build `drone-sim/sim.py` — pure Python drone state machine (position, battery, status)
- [ ] Build `drone-sim/grpc_server.py` — receives commands, updates sim state
- [ ] Build `drone-sim/telemetry.py` — UDP heartbeat broadcaster (ID, position, battery, timestamp)
- [ ] Create `drone-sim/Dockerfile`
- [ ] Create `docker-compose.yml` with 3 drone containers on isolated bridge network
- [ ] **Test:** `grpcurl` sends MoveTo → drone position changes → UDP heartbeat reflects new coords

### Phase 2: Backend Sidecar (FastAPI + gRPC Client)
**Goal:** FastAPI that can send commands to drones and relay telemetry to frontend.

- [ ] Scaffold `backend/app.py` — FastAPI with CORS, lifespan events
- [ ] Build `backend/grpc/client.py` — gRPC client for drone commands
- [ ] Build `backend/telemetry/udp_listener.py` — async listener for drone heartbeats
- [ ] Build `backend/telemetry/ws_bridge.py` — WebSocket endpoint forwarding telemetry
- [ ] Build `backend/db/` — SQLite schema, repository pattern for asset registry
- [ ] REST endpoints: `POST /spawn`, `POST /uplink/{asset_id}`, `POST /command`, `GET /assets`
- [ ] **Test:** curl spawns drone → uplink → send move command → WebSocket streams position updates

### Phase 3: AI Brain (ADK + FastMCP)
**Goal:** Natural language commands are interpreted by local LLM and executed.

- [ ] Install Ollama + pull Qwen 3.5 (4B)
- [ ] Configure LiteLLM to point at Ollama
- [ ] Build `backend/agents/commander.py` — ADK root agent
- [ ] Build `backend/agents/navigation.py` — with `move_drone_to`, `plan_sweep_pattern` tools
- [ ] Build `backend/agents/thermal.py` — with `scan_area`, `get_thermal_feed` tools
- [ ] Build `backend/tools/` — FastMCP tool definitions that call gRPC client
- [ ] Wire ADK into FastAPI `POST /command` endpoint
- [ ] **Test:** POST "scan building at coordinates 5,0,5 for survivors" → agent picks correct tool → gRPC fires → drone moves

### Phase 4: Frontend (Tauri + Next.js + R3F)
**Goal:** Desktop app with 3D digital twin, tactical dashboard, and license gating.

- [ ] Scaffold Next.js with `output: 'export'` in `next.config.mjs`
- [ ] Initialize Tauri with Next.js as frontend source
- [ ] Build license gate — first-launch screen requiring a valid license key before accessing the app (see License Activation below)
- [ ] Build R3F canvas — terrain, grid, basic drone model
- [ ] Build WebSocket client — connects to FastAPI, receives telemetry, updates drone positions
- [ ] Build Spawner panel — "Initialize Virtual Asset" button → calls `POST /spawn`
- [ ] Build Radar sweep — "Scan Local Frequencies" animation → calls `GET /assets`
- [ ] Build Uplink flow — "Establish Uplink" → calls `POST /uplink/{id}` → drone materializes in 3D
- [ ] Build Command input — text box → sends to `POST /command`
- [ ] **Test:** App blocks access without valid license key; full flow works after activation

### Phase 5: Polish & Integration
- [ ] Mission logging — all commands and telemetry persisted to SQLite
- [ ] Multi-drone coordination — swarm formation patterns
- [ ] Battery management — low-battery auto-return
- [ ] Error recovery — lost connection handling, drone reconnection
- [ ] License management UI — view license status, expiry, deactivation
- [ ] Tauri packaging for distribution

## Development Commands

```bash
# Python backend
uv sync                           # Install dependencies
uv run python -m backend.app      # Start FastAPI sidecar
uv run pytest                     # Run tests

# Protobuf generation
python -m grpc_tools.protoc -I proto/ --python_out=backend/grpc/ --grpc_python_out=backend/grpc/ proto/beacon.proto

# Drone simulation
docker compose up -d              # Start simulated swarm
docker compose logs -f beacon-01  # Watch a single drone

# Frontend (Phase 4)
cd frontend && npm install
npm run dev                       # Next.js dev server
npm run tauri dev                 # Tauri desktop app

# Ursina visual prototype (standalone demo, not part of production)
uv run python test.py
```

## Coding Conventions

- **Python:** PEP 8, type hints on all function signatures, `uv` for packages
- **FastAPI:** Async handlers, Pydantic models for all request/response schemas
- **gRPC:** All drone communication uses protobuf — never REST/HTTP between commander and drones
- **ADK agents:** Single responsibility per agent, no shared mutable state between agents
- **FastMCP tools:** Each tool maps to exactly one gRPC operation
- **SQLite:** Parameterized queries only — never interpolate strings into SQL
- **Frontend:** Next.js SSG mode only — no API routes in Next.js, all calls go to FastAPI sidecar
- **Immutability:** Return new objects, never mutate existing ones
- **Error handling:** Explicit at every layer, user-friendly in UI, detailed in server logs

## License Activation

The Tauri app requires a valid license key on first launch. The app is fully blocked until activation succeeds.

### Flow

```
App launches
  │
  ▼
Check local license store (Tauri fs / SQLite)
  │
  ├─ Valid license found → proceed to Commander Dashboard
  │
  └─ No license / expired → License Gate Screen
                                │
                          User enters license key
                                │
                          POST /license/activate → FastAPI
                                │
                          FastAPI validates key:
                            - Format check (prefix + checksum)
                            - Lookup in local license DB
                            - Check expiry / seat count
                                │
                          ├─ Valid → store locally, unlock app
                          └─ Invalid → show error, stay on gate
```

### Design Decisions

- **Offline-compatible:** License validation runs against a local SQLite table (`licenses`), not a cloud server. Pre-provisioned keys are bundled or imported via USB/file.
- **Key format:** `BEACON-XXXX-XXXX-XXXX-XXXX` with a checksum suffix for typo detection.
- **Storage:** Activated license stored via Tauri's secure filesystem API (`$APPDATA/beacon-license.json`), containing key, activation timestamp, and expiry.
- **Grace period:** If license expires, app shows a warning for 7 days before hard-locking.
- **No phone-home:** License checks never require internet. This is a hard constraint.

### Files

```
backend/
└── licensing/
    ├── models.py          # LicenseKey Pydantic model (key, org, expiry, seats)
    ├── validator.py       # Format check, checksum, expiry logic
    ├── repository.py      # SQLite CRUD for licenses table
    └── routes.py          # POST /license/activate, GET /license/status

frontend/
└── src/
    ├── components/
    │   └── license-gate/  # Full-screen license key input UI
    └── lib/
        └── license.ts     # Read/write local license store, check validity
```

## Hard Constraints

- **Zero cloud:** No external API calls in any production code path. Ollama runs locally.
- **Offline-first:** Every feature must work without internet connectivity.
- **gRPC only** for commander ↔ drone communication. No REST/HTTP between nodes.
- **Docker isolation:** Each drone container gets its own IP on an isolated bridge network.
- **SQLite only:** No external databases. All data stays on the local machine.
- **No Ursina in production:** `test.py` is a standalone visual demo. Production drone sim uses pure Python dataclasses.
- **Protobuf is source of truth:** `proto/beacon.proto` defines the contract. Backend and drone-sim both generate from it.
- **License required:** App must not be usable without a valid license key. No backdoors, no skip buttons.
- **License is offline:** License validation never contacts an external server. Keys are pre-provisioned locally.

## Testing

- **Unit tests:** FastAPI endpoints, ADK agent logic, drone sim state machine
- **Integration tests:** FastMCP tool → gRPC client → drone sim round-trip
- **Telemetry tests:** UDP broadcast → WebSocket relay correctness
- **Run:** `uv run pytest`
- **Coverage target:** 80%+
