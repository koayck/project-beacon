# Project Beacon Solution Overview

## 1. Proposed Solution

### 1.1 Problem Statement
Project Beacon addresses search-and-rescue operations in comms-denied or degraded environments where cloud connectivity is unavailable or unreliable. Operators need to discover, control, and coordinate autonomous drones while maintaining real-time situational awareness and auditable mission logs. For mission-critical connectivity backup, the system supports Starlink satellite integration to maintain command-and-control uplink in remote locations.

### 1.2 Solution Goals
- Cloud-connected by default: Primary operation uses Gemini 2.5 Flash via Google AI API.
- Starlink backup connectivity: Satellite link maintains cloud access in remote areas.
- Offline fallback capability: Local LLM option for fully disconnected scenarios.
- Human-in-the-loop control: a commander can issue natural-language and direct operational commands.
- Multi-drone coordination: support concurrent assets and fleet-level tasks.
- Real-time observability: live telemetry and mission status visualization.
- Safety-first behavior: battery checks, obstacle-aware routing, return-to-base workflows, and controlled command execution.

### 1.3 Proposed End-to-End Capability
The proposed solution is a desktop Ground Control Station (GCS) built around local AI orchestration and containerized drone simulation:

1. Operator uses the desktop UI to discover drones, establish uplink, and issue commands.
2. FastAPI sidecar receives commands and routes natural-language intents through an agent system.
3. Gemini 2.5 Flash (via LiteLLM) selects/structures tool actions.
4. Tool layer invokes gRPC commands to drone simulators.
5. Drones execute movement/scan/return actions and emit telemetry via UDP.
6. Backend relays telemetry to frontend over WebSocket for live 3D visualization.
7. Mission events are persisted in SQLite for traceability.

### 1.4 Core Functional Modules
- Mission Control UI
  - Tactical dashboard, command console, drone state panels, and scene rendering.
- Agentic Command Layer
  - Commander agent routes to specialized navigation/thermal workflows.
- Drone Control Plane
  - gRPC contract and client/server stubs for deterministic command dispatch.
- Telemetry Plane
  - UDP heartbeat ingestion + WebSocket fan-out for near real-time updates.
- Persistence Layer
  - SQLite repositories for mission logs, asset records, and licensing data.
- Licensing and Access Gate
  - Offline license validation before mission operations are unlocked.

### 1.5 Why This Approach
- Deterministic operations + AI flexibility: natural-language convenience without replacing explicit control boundaries.
- Cloud-first with fallback resilience: Leverage powerful cloud LLMs via Starlink while maintaining offline capability.
- Clear separation of concerns: UI, API, agent logic, simulation, and storage are modular and independently testable.
- Scalable development path: architecture supports current simulation use cases and future real-hardware adapters.

### 1.6 Key Non-Functional Requirements
- Security: no hardcoded secrets, validated inputs, safe DB access patterns.
- Performance: low-latency command and telemetry paths.
- Maintainability: typed interfaces, bounded modules, explicit error handling.
- Testability: unit/integration workflow supported across backend, sim, and command orchestration.

---

## 2. System Architecture

### 2.1 High-Level Architecture

```text
+---------------------------------------------------------------+
| Host Machine (Commander Node)                                 |
|                                                               |
|  +------------------------+      HTTP/WS      +-------------+ |
|  | Desktop Frontend       | <----------------> | FastAPI    | |
|  | - Next.js (SSG)        |                    | Sidecar    | |
|  | - React Three Fiber    |                    |            | |
|  +------------------------+                    | - Agents   | |
|                                                | - Gemini   | |
|                                                | - FastMCP  | |
|                                                | - SQLite   | |
|                                                +------+-----+ |
+-------------------------------------------------------|-------+
                                                        | gRPC
                                   +--------------------+-------------------+
                                   | Docker Network (Simulated Drone Fleet) |
                                   | - beacon-01                              |
                                   | - beacon-02                              |
                                   | - beacon-03                              |
                                   | (Each: state machine + gRPC server +    |
                                   |  telemetry broadcaster)                  |
                                   +------------------------------------------+
```

### 2.2 Major Components and Responsibilities

#### Frontend (Desktop UI)
- Presents tactical controls and mission context.
- Sends commands to backend over HTTP.
- Subscribes to live telemetry via WebSocket.
- Renders drone movement/state in 3D scene.

#### Backend FastAPI Sidecar
- Central application runtime and API surface.
- Hosts agent workflows for interpretation and orchestration.
- Executes tool calls that map to drone operations.
- Manages telemetry ingestion and WebSocket broadcast.
- Persists mission and system state to SQLite.

#### Agent Layer (Commander, Navigation, Thermal)
- Commander: parses intent, chooses workflow, and delegates.
- Navigation: route planning, move/return operations, sweep logic.
- Thermal/Scan: survivor scanning workflows and result shaping.

#### Drone Simulation Layer
- Containerized per-drone service with isolated runtime.
- Accepts gRPC control requests and mutates drone state.
- Emits periodic telemetry snapshots over UDP.

#### Data and Storage Layer
- SQLite for mission logs, assets, and licensing state.
- Repository abstraction for persistence access.

### 2.3 Communication Architecture
- Frontend -> Backend: HTTP REST for command/control operations.
- Backend -> Frontend: WebSocket for continuous telemetry/event updates.
- Backend -> Drone Sim: gRPC + Protobuf for strongly typed, low-latency commands.
- Drone Sim -> Backend: UDP heartbeat/telemetry stream.

### 2.4 Command Execution Flow (Reference)
1. Operator submits a natural-language mission command.
2. Backend receives request and invokes commander agent.
3. Agent selects tools (navigation/thermal/supply/etc.) based on intent.
4. Tool execution triggers gRPC operations against one or more drones.
5. Drone state changes and telemetry updates are emitted.
6. Backend forwards updates to UI and stores mission events.
7. UI reflects movement/status in near real time.

### 2.5 Deployment Model
- Single host runs desktop app + backend sidecar.
- Docker Compose runs multiple drone simulators on an isolated bridge network.
- Gemini 2.5 Flash (accessed via LiteLLM) provides LLM inference with optional cloud connectivity.
- Starlink satellite connectivity available as backup for remote operations requiring external model access.

### 2.6 Security and Operational Constraints
- Primary mode: Cloud-connected via Gemini 2.5 Flash API with Starlink backup.
- Offline fallback: Local LLM option available for fully disconnected operations.
- License activation required for application access.
- gRPC is the source-of-truth command channel between control plane and drones.
- SQLite is the local system of record.
- Protobuf contract defines inter-service message compatibility.

### 2.7 Extensibility Path
- Add new operational tools by extending tool registry and gRPC contract.
- Add new specialized agents without changing UI transport model.
- Swap drone simulator adapters with real drone connectors while preserving API contracts.
- Expand telemetry analytics and mission replay from persisted logs.

---

## Summary
Project Beacon's solution combines cloud AI (Gemini 2.5 Flash), deterministic drone control, and real-time visualization into a resilient GCS architecture. Starlink backup connectivity enables cloud access in remote areas, while optional local LLM fallback provides full offline capability. This design is intentionally modular, testable, and deployment-practical for disaster-response operations where both cloud leverage and offline resilience are valuable.
