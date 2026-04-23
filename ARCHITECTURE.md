# Project Beacon Architecture Overview

This document is a living architecture reference for contributors and agents.
It reflects the current repository structure and runtime behavior.

## 1. Project Structure

### 1.1 Repository Map (ASCII)

```text
project-beacon/
|-- backend/                 FastAPI sidecar, ADK agents, MCP, gRPC client, DB
|   |-- agents/              Command parser, commander, mission workflows
|   |-- services/            Deterministic mission logic (fleet/nav/workflows)
|   |-- grpc/                Python gRPC client + generated protobuf stubs
|   |-- telemetry/           UDP listener + WS broadcaster
|   |-- db/                  SQLite schema + repositories + models
|   |-- licensing/           Offline key activation/status/provisioning
|   |-- mcp/                 FastMCP server exposing mission tools
|   |-- orchestrator/        Low-level navigation/scanning execution helpers
|   |-- world/               World model and vision helper modules
|   `-- app.py               FastAPI app entrypoint and endpoint wiring
|-- drone-sim/               Drone container runtime (state machine + gRPC + UDP)
|   |-- sim.py               Core drone state machine
|   |-- grpc_server.py       DroneControl service implementation
|   |-- telemetry.py         UDP heartbeat broadcast loop
|   `-- main.py              Process bootstrap + signal handling
|-- frontend/                Next.js + React Three Fiber tactical UI
|   |-- src/app/             App shell and page entry
|   |-- src/components/      3D scene, overlays, panels, animation
|   |-- src/lib/             HTTP and WebSocket clients to backend
|   |-- src/types/           Shared frontend domain types
|   `-- next.config.mjs      Static export for desktop packaging
|-- proto/
|   `-- beacon.proto         gRPC contract source of truth
|-- scripts/                 Proto generation + network utility scripts
|-- shared/                  Shared world definitions (world.json variants)
|-- tests/                   Pytest unit/integration coverage
|-- docs/                    System flow and API behavior docs
|-- docker-compose.yml       Multi-drone simulation network topology
`-- pyproject.toml           Python dependencies and test config
```

### 1.2 Backend Breakdown (ASCII)

```text
backend/
|-- app.py
|-- runtime.py               Shared singleton instances
|-- output_format.py
|-- agents/
|   |-- commander.py         Root enhanced commander agent
|   |-- command_parser.py    NL command extraction
|   |-- mission_planner.py   Planning support (referenced by commander)
|   |-- navigation.py        Navigation specialist agent
|   |-- thermal.py           Thermal specialist agent
|   |-- scan_workflow.py     Multi-drone scan workflow
|   |-- supply_workflow.py   Multi-drone supply workflow
|   |-- recovery.py          Error-recovery specialist
|   |-- schemas.py           Pydantic mission/intent schemas
|   |-- _mcp.py              MCP tool groups + toolset factory
|   `-- _model.py            ADK model and generation config
|-- services/
|   |-- api/control.py       High-level API service wrappers
|   |-- fleet.py             Fleet operations
|   |-- fleet_assignment.py  Drone-to-target assignment logic
|   |-- auto_recall.py       Auto return-to-base behavior
|   |-- swarm_control.py     Multi-drone formation/recall helpers
|   |-- scan_reporting.py    Scan report formatting/aggregation
|   |-- navigation/
|   |   |-- route_planner.py
|   |   |-- sweep_planner.py
|   |   `-- target_resolution.py
|   `-- workflows/
|       |-- sweep_workflow.py
|       |-- supply_workflow.py
|       `-- return_workflow.py
|-- telemetry/
|   |-- udp_listener.py
|   `-- ws_bridge.py
|-- grpc/
|   `-- client.py
|-- db/
|   |-- schema.sql
|   |-- models.py
|   `-- repository.py
|-- licensing/
|   |-- routes.py
|   |-- validator.py
|   `-- models.py
|-- mcp/
|   `-- server.py
|-- orchestrator/
|   |-- navigation.py
|   `-- scanning.py
`-- world/
    |-- model.py
    `-- vision.py
```

### 1.3 Frontend Breakdown (ASCII)

```text
frontend/src/
|-- app/
|   |-- layout.tsx
|   `-- page.tsx             Dynamic load of 3D scene
|-- components/
|   |-- scene.tsx            Main tactical scene + mission UI orchestration
|   |-- panels/              Command panel, status bars, control overlays
|   |-- scene-props/         Buildings, terrain, drones, survivors, props
|   `-- animation/           Camera tracking and throw animation
|-- lib/
|   |-- api.ts               REST + SSE event stream client
|   `-- ws.ts                Telemetry websocket hook
|-- types/
|   `-- worldTypes.ts
`-- generated/
    `-- world environment generated assets
```

## 2. High-Level System Diagram

```text
                           Operator (Desktop)
                                  |
                                  v
             +----------------------------------------------+
             | Frontend (Next.js + React Three Fiber)       |
             | - Command UI / Tactical 3D / Activity feeds  |
             +----------------------------------------------+
                     | HTTP + SSE                 | WS telemetry
                     v                            ^
      +--------------------------------------------------------------+
      | Backend FastAPI Sidecar                                      |
      | - Endpoints (/command, /fleet, /spawn, /uplink, /license)   |
      | - ADK runner + agents + workflows                            |
      | - FastMCP tool surface                                       |
      | - SQLite repos + mission logs + license store                |
      +--------------------------------------------------------------+
              | gRPC command/control              ^ UDP heartbeats
              v                                   |
      +--------------------------------------------------------------+
      | Drone Containers (beacon-01..beacon-05 via Docker compose)   |
      | - drone-sim state machine                                    |
      | - gRPC server (MoveTo/GetStatus/ScanArea/...)               |
      | - telemetry broadcaster                                      |
      +--------------------------------------------------------------+
```

## 3. Core Components

### 3.1 Frontend

Name: Tactical Desktop UI

Description: Single-page tactical interface with 3D world visualization, command submission, telemetry display, activity feed, and operator controls (fleet recall/speed, world switch, area interactions).

Technologies: Next.js 14, React 18, TypeScript, React Three Fiber, Drei, Three.js, Tailwind CSS.

Deployment: Static export (output: export), intended for desktop shell integration.

### 3.2 Backend Services

#### 3.2.1 API Sidecar

Name: FastAPI Application

Description: Hosts REST/SSE/WebSocket endpoints, runs app lifecycle orchestration, initializes ADK runner, starts telemetry listener, restores gRPC uplinks, and logs missions.

Technologies: FastAPI, Pydantic, asyncio, StreamingResponse.

Deployment: Local Python process (uv run python -m backend.app).

#### 3.2.2 Agent Layer

Name: ADK Agent Graph

Description: Hybrid LLM-driven orchestration with specialist sub-agents and deterministic tool execution. Root commander routes requests to navigation, scan workflow, supply workflow, and recovery.

Technologies: Google ADK, LiteLLM-compatible model configuration, FastMCP toolsets.

Deployment: In-process under FastAPI lifespan.

#### 3.2.3 Mission Services

Name: Deterministic Service Layer

Description: Implements concrete fleet control, route planning, assignment, report synthesis, and workflow primitives consumed by MCP tools and endpoints.

Technologies: Python async services and orchestrator modules.

Deployment: In-process backend modules.

#### 3.2.4 Drone Simulation Runtime

Name: Drone Simulator Containers

Description: Each drone runs a state machine with gRPC command surface and UDP telemetry emission. Compose network simulates a local fleet.

Technologies: Python, grpcio, Docker Compose.

Deployment: Docker containers on bridge network beacon-net.

## 4. Data Stores

### 4.1 Primary Operational DB

Name: Beacon Supabase DB

Type: PostgreSQL (Supabase) via asyncpg

Purpose: Stores registered assets/uplink data, mission logs, and pre-provisioned license records.

Key Schemas/Tables: assets, mission_logs, licenses.

### 4.2 In-Memory Runtime State

Name: Telemetry + Session State

Type: In-memory Python state

Purpose: Latest telemetry snapshots per drone and connected websocket clients.

### 4.3 Persistent Agent Session Store

Name: ADK Session Database

Type: PostgreSQL (Supabase) via ADK DatabaseSessionService

Purpose: Persists ADK user/session/app state and conversation events across backend restarts so multi-step mission context survives process lifecycle changes.

## 5. External Integrations and APIs

1. Docker Engine
   Purpose: Runs multi-drone simulation containers.
   Integration Method: docker compose and docker CLI invocation.

2. gRPC Drone Control API
   Purpose: Command/observe each drone simulator.
   Integration Method: protobuf stubs from proto/beacon.proto.

3. Model Provider via ADK/LiteLLM config
   Purpose: LLM reasoning for command understanding/workflow orchestration.
   Integration Method: Model configured in backend/agents/\_model.py.

4. Langfuse (optional)
   Purpose: Observability/tracing for model/tool calls when configured.
   Integration Method: Langfuse SDK callbacks through LiteLLM instrumentation.

## 6. Deployment and Infrastructure

Cloud Provider: GCP.

Key Services Used: Docker bridge network, local FastAPI service, local SQLite file, local static frontend export.

Runtime Configuration Notes:
- `SUPABASE_DB_URL` is required for backend startup to initialize ADK `DatabaseSessionService`.
- Session scope remains keyed by (`app_name`, `user_id`, `session_id`) and now persists in PostgreSQL.

CI/CD Pipeline: No repository-local CI pipeline config found in .github at this time.

Monitoring and Logging: Python logging in backend, optional Langfuse tracing.

## 7. Security Considerations

Authentication: No user auth layer on mission endpoints currently; access is assumed to be local trusted operator environment.

Authorization: No RBAC/ACL currently implemented in API layer.

Data Encryption: No explicit TLS termination in local dev setup; traffic is plain localhost/container network by default.

License Control: Offline key format + checksum + local DB lookup + expiry enforcement through /license routes.

Operational Notes:

- Input validation is handled via Pydantic and explicit validators.
- SQL statements are parameterized in repository layer.
- Ensure environment secrets (if used for observability/model backends) are injected via env vars only.

## 8. Development and Testing Environment

Local Setup:

1. Install dependencies with uv sync.
2. Start simulated drones with docker compose up -d.
3. Start backend with uv run python -m backend.app.
4. Start frontend in frontend with npm install and npm run dev.

Testing Frameworks: pytest, pytest-asyncio, httpx test client support.

Current Test Layout:

- tests/ contains unit and integration-style backend/domain tests.
- tests/integration/ contains integration test set.

Code Quality Tools:

- Python formatting/linting expectations reference black/isort/ruff in coding rules.
- Type annotations and Pydantic schemas are used across backend APIs.

## 9. Future Considerations and Roadmap

1. Align model configuration with strict offline-only requirements across environments.
2. Add API authn/authz for non-local or multi-operator deployments.
3. Expand CI automation (lint, tests, coverage gates).
4. Continue modularizing workflow logic while preserving deterministic hot paths.
5. Add explicit infrastructure profiles for desktop packaging and field deployment.

## 10. Project Identification

Project Name: Project Beacon

Repository URL: Local workspace repository (no canonical remote URL documented here)

Primary Contact/Team: Not explicitly defined in repository metadata

Date of Last Update: 2026-04-18

## 11. Glossary and Acronyms

ADK: Google Agent Development Kit used to define and run the agent graph.

MCP: Model Context Protocol interface used for tool calling between agents and deterministic services.

gRPC: Binary RPC protocol used for backend to drone command/control.

SSE: Server-Sent Events used by /command/stream for incremental event delivery.

WS: WebSocket channel for live telemetry updates.

RTB: Return To Base safety behavior.

MANET (simulated): Container network emulating multi-node local connectivity.
