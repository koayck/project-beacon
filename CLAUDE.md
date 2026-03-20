# Project Beacon — CLAUDE.md

## Project Overview

**Project Beacon** is a cloud-first Ground Control Station (GCS) for autonomous drone swarms in search and rescue operations. It uses Gemini 2.5 Flash (via Google AI API) for natural language command interpretation and multi-agent orchestration. Starlink provides backup internet connectivity in remote deployment scenarios. The system coordinates drone fleets through gRPC communication with real-time telemetry visualization.

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
│  └──────────────────┘         │  ├─ Gemini 2.5 Flash (API)  │  │
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
                              Gemini 2.5 Flash (via API)
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
│   ├── runtime.py            # Shared runtime state (gRPC client, telemetry)
│   ├── agents/               # Google ADK agent definitions
│   │   ├── commander.py      # Root agent — routes to workflows/agents
│   │   ├── navigation.py     # Flight path planning and movement
│   │   ├── thermal.py        # Thermal/camera feed analysis
│   │   ├── scan_workflow.py  # Area/building scan orchestration
│   │   ├── supply_workflow.py # Survivor supply dispatch orchestration
│   │   ├── _model.py         # Shared Gemini model config + Langfuse
│   │   └── _mcp.py           # MCP tool filtering per agent
│   ├── mcp/                  # FastMCP server
│   │   └── server.py         # MCP tools exposed to agents
│   ├── tools/                # Tool implementations
│   │   └── drone_commands.py # move_to, scan_area, status, etc.
│   ├── services/             # Business logic layer
│   │   ├── api.py            # Fleet management, uplink, discovery
│   │   └── auto_recall.py    # Low-battery auto-return monitoring
│   ├── grpc/
│   │   ├── beacon.proto      # Protobuf schema
│   │   ├── beacon_pb2.py     # Generated stubs (do not edit)
│   │   ├── beacon_pb2_grpc.py # Generated gRPC stubs
│   │   └── client.py         # gRPC client for drone commands
│   ├── telemetry/
│   │   ├── udp_listener.py   # Receives drone heartbeats/coords
│   │   └── ws_bridge.py      # WebSocket relay to frontend
│   ├── db/
│   │   ├── schema.sql        # SQLite DDL
│   │   ├── models.py         # Pydantic models (Asset, MissionLog)
│   │   └── repository.py     # Data access layer
│   ├── licensing/            # Offline license validation
│   │   ├── routes.py         # License activation/status endpoints
│   │   ├── models.py         # License key models
│   │   └── validator.py      # Format validation logic
│   └── world/                # World state management
│       ├── model.py          # World data structures
│       └── vision.py         # Survivor tracking
├── drone-sim/
│   ├── Dockerfile
│   ├── sim.py                # Pure Python drone state machine
│   ├── grpc_server.py        # Receives commands from commander
│   └── telemetry.py          # UDP heartbeat broadcaster
├── frontend/                 # Next.js + Tauri + React Three Fiber
│   ├── src/
│   │   ├── app/              # Next.js pages (SSG)
│   │   ├── components/
│   │   │   ├── three/        # 3D visualization components
│   │   │   ├── ui/           # Dashboard UI components
│   │   │   └── license/      # License activation flow
│   │   └── lib/
│   │       ├── ws.ts         # WebSocket telemetry client
│   │       └── api.ts        # HTTP API client
│   ├── src-tauri/            # Tauri Rust shell
│   ├── next.config.mjs       # output: 'export' (SSG)
│   └── package.json
├── proto/                    # Source-of-truth .proto files
│   └── beacon.proto
├── scripts/
│   └── gen_proto.sh          # Protobuf code generation
├── tests/
│   └── test_adk_cli.py       # Integration test (full pipeline)
├── docker-compose.yml        # 5-drone simulation fleet
├── pyproject.toml
└── CLAUDE.md
```

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Desktop shell | Tauri | Native window, process management |
| Frontend | Next.js (SSG) | Static bundled UI |
| 3D visualization | React Three Fiber | Real-time drone position rendering |
| API server | FastAPI | Python backend, all business logic |
| AI orchestration | Google ADK | Multi-agent framework with tool calling |
| LLM | Gemini 2.5 Flash (gemini-3-flash-preview) | Natural language understanding via Google AI API |
| Observability | Langfuse (optional) | LLM tracing when credentials provided |
| Tool bridge | FastMCP | Exposes MCP tools to ADK agents |
| Drone comms | gRPC + Protobuf | Low-latency command/response |
| Drone simulation | Python + Docker | Stateful drone containers with physics |
| Telemetry | UDP broadcast → WebSocket relay | Real-time position streaming to UI |
| Storage | SQLite | Mission logs, asset registry, licenses |
| Networking | Docker bridge network | Isolated container communication |
| Python packaging | uv | Fast dependency management |

## ADK Agent Design

Current implementation uses three main components:

### Commander Agent
- **Role**: Root agent that receives natural language, routes to workflows/agents
- **Routing logic**: Analyzes prompt, delegates to Navigation Agent or orchestration workflows
- **Temperature**: 0.5 for precise routing decisions

### Navigation Agent
- **Role**: Direct drone movement, sweep patterns, status queries
- **Tools**: `move_to`, `return_to_base`, `get_status`, `plan_sweep`
- **Temperature**: 0.7 for balanced tool reasoning

### Workflows (Multi-Agent Orchestration)

**Scan Workflow** (`scan_workflow.py`)
- Orchestrates building/area scans for survivor detection
- Steps: drone selection → navigation → thermal scan loop → survivor report
- Uses both Navigation Agent tools and direct thermal scanning

**Supply Workflow** (`supply_workflow.py`)
- Coordinates parallel supply delivery to multiple survivors
- Steps: survivor discovery → drone assignment → concurrent dispatch → confirmation

All agents use Gemini 2.5 Flash via Google AI API with thinking enabled (chain-of-thought visible in stream). Optional Langfuse observability when `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set.

## Key Workflows (Current Implementation)

### 1. Drone Discovery & Uplink
1. Backend starts → `UDPTelemetryListener` begins listening on port 5005
2. Docker drone containers broadcast heartbeats every 1 second
3. User calls `GET /scan` → returns unpaired drones discovered via UDP
4. User calls `POST /uplink/BEACON-01` → opens gRPC channel, registers in SQLite
5. Telemetry streaming begins via WebSocket at `ws://localhost:8000/ws/telemetry`

### 2. Natural Language Mission Execution
1. User sends prompt: `"Scan building at -15, -20 for survivors"`
2. `POST /command/stream` → Commander Agent receives prompt
3. Commander analyzes intent, routes to Scan Workflow
4. Scan Workflow:
   - Queries fleet via MCP tool `get_fleet_status`
   - Selects nearest available drone
   - Calls `move_to` tool → gRPC command to drone
   - Executes thermal scan loop
   - Compiles survivor report with coordinates
5. Drone updates position → UDP telemetry → WebSocket → UI updates
6. Mission logged to SQLite `mission_logs` table

### 3. Auto-Recall (Low Battery Protection)
1. `AutoRecallMonitor` runs in background (if `AUTO_RECALL_ENABLED=true`)
2. Monitors telemetry stream for battery levels
3. When battery < threshold (default 10%), triggers `return_to_base`
4. Per-drone cooldown prevents repeated recalls
5. Events logged for debugging

## Implementation Status

### ✅ Phase 1: Drone Simulation Layer
- ✅ `proto/beacon.proto` with MoveTo, GetStatus, Heartbeat, ScanArea, SetSpeed messages
- ✅ `drone-sim/sim.py` — Python drone state machine with physics
- ✅ `drone-sim/grpc_server.py` — command receiver
- ✅ `drone-sim/telemetry.py` — UDP broadcaster
- ✅ `docker-compose.yml` with 5 drone containers (beacon-01 through beacon-05)

### ✅ Phase 2: Backend Core
- ✅ `backend/app.py` — FastAPI with CORS, lifespan management
- ✅ `backend/grpc/client.py` — gRPC client
- ✅ `backend/telemetry/udp_listener.py` — async UDP listener
- ✅ `backend/telemetry/ws_bridge.py` — WebSocket relay
- ✅ `backend/db/` — SQLite with Asset and MissionLog models
- ✅ REST endpoints: `/scan`, `/uplink`, `/command`, `/assets`, `/fleet`, `/spawn`
- ✅ Auto-recall monitoring for low battery conditions

### ✅ Phase 3: AI Orchestration
- ✅ Gemini 2.5 Flash integration (`gemini-3-flash-preview`)
- ✅ `backend/agents/commander.py` — root routing agent (temp 0.5)
- ✅ `backend/agents/navigation.py` — movement and planning (temp 0.7)
- ✅ `backend/agents/thermal.py` — thermal analysis
- ✅ `backend/agents/scan_workflow.py` — multi-step scan orchestration
- ✅ `backend/agents/supply_workflow.py` — parallel supply delivery
- ✅ `backend/mcp/server.py` — FastMCP tool server with per-agent filtering
- ✅ Langfuse observability (optional, via environment variables)
- ✅ Streaming command endpoint with SSE (`/command/stream`)

### ✅ Phase 4: Additional Features
- ✅ License activation system (`backend/licensing/`)
- ✅ World state management (`backend/world/`)
- ✅ Survivor tracking and vision system
- ✅ Mock Starlink network status simulation
- ✅ Integration test (`tests/test_adk_cli.py`)

### 🚧 Phase 5: Frontend (In Progress)
- Frontend structure exists but needs integration with current backend API
- Tauri desktop shell needs completion
- 3D visualization with React Three Fiber needs implementation

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

- **Connectivity model:** Cloud-first with Gemini 2.5 Flash via Google AI API. Optional Starlink provides backup internet in remote locations. Local LLM fallback (Ollama) can be configured via `backend/agents/_model.py`.
- **gRPC only** for commander ↔ drone communication. No REST/HTTP between nodes.
- **Docker isolation:** Each drone container gets its own IP on an isolated bridge network.
- **SQLite only:** No external databases. All data stays on the local machine.
- **Protobuf is source of truth:** `proto/beacon.proto` defines the contract. Backend and drone-sim both generate from it.
- **Observability is optional:** Langfuse tracing only enabled when both `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` are set.

## Current API Endpoints

### Core Operations
- `GET /health` - service health check
- `GET /scan` - discover active unpaired drones via UDP
- `POST /uplink/{asset_id}` - establish gRPC connection to drone
- `GET /assets` - list all registered drones
- `GET /fleet` - active fleet view (used by MCP tools)
- `POST /command` - execute natural language command (non-streaming)
- `POST /command/stream` - SSE streaming with thoughts/tool calls/results

### Fleet Management
- `POST /fleet/recall` - recall all drones to base
- `POST /fleet/speed` - set speed for all drones
- `POST /drone/{asset_id}/speed` - set individual drone speed
- `POST /drone/{asset_id}/reset` - return specific drone to base

### World & Network
- `POST /world/{world_id}` - switch all connected drones to new world state
- `GET /network/mock-status` - Starlink network mock status
- `GET /config/auto-recall` - auto-recall configuration

### License Management
- `POST /license/activate` - activate license key
- `GET /license/status` - check current license status
- `POST /license/provision` - provision license records (admin)

### WebSocket
- `GET /ws/telemetry` - real-time telemetry stream

## Testing

Current test coverage:
- ✅ Integration test (`tests/test_adk_cli.py`) — full pipeline from prompt to drone movement
- ✅ gRPC client/server communication
- ✅ UDP telemetry broadcast and reception
- 🚧 Unit tests for individual agents
- 🚧 WebSocket relay tests

Run: `uv run pytest`
