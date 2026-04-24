# Project Beacon Agent System Flow

This guide explains the current end-to-end flow of the agent system in practical terms.

The goal is to answer three questions clearly:
1. What happens from API request to mission result
2. Which parts are LLM reasoning versus deterministic execution
3. How scan and supply workflows run internally

## 1) Big Picture

Project Beacon uses a hybrid pattern:
- LLM agents handle command understanding, strategy, and adaptive choices.
- Deterministic Python functions and MCP tools handle execution, retries, and state updates.

At runtime, the main commander agent is created in FastAPI startup and used by command endpoints.

## 2) Runtime Entry Points

Main server and ADK runner setup:
- [backend/app.py](backend/app.py)

Command endpoints:
- Synchronous command endpoint: [backend/app.py](backend/app.py#L552)
- Streaming command endpoint: [backend/app.py](backend/app.py#L620)

On startup, the app builds an ADK Runner with the root commander agent and an in-memory session service.

## 3) Root Commander and Core Decision Flow

Root commander definition:
- [backend/agents/commander.py](backend/agents/commander.py)

Root commander sub-agents:
- [backend/agents/command_parser.py](backend/agents/command_parser.py)
- [backend/agents/mission_planner.py](backend/agents/mission_planner.py)
- [backend/agents/recovery.py](backend/agents/recovery.py)
- [backend/agents/navigation.py](backend/agents/navigation.py)
- [backend/agents/scan_agent.py](backend/agents/scan_agent.py)
- [backend/agents/supply_agent.py](backend/agents/supply_agent.py)

Commander logic in plain language:
1. Parse the operator command into structured intent.
2. Decide if planning is needed with is_complex_mission.
3. Route execution to specialist agent or workflow.
4. Use recovery logic when execution fails in a non-trivial way.

Complexity gate function:
- [backend/agents/commander.py](backend/agents/commander.py#L20)

## 4) Request Lifecycle from Operator to Result

### Step A: API receives command

The endpoint receives prompt and optional preferred asset, then builds an internal mission prompt.

Relevant code:
- [backend/app.py](backend/app.py#L541)
- [backend/app.py](backend/app.py#L552)

### Step B: Session is created

Each command creates a fresh ADK session id and session state.

Relevant code:
- [backend/app.py](backend/app.py#L563)

### Step C: Runner executes agent graph

The app calls runner.run_async and consumes events.

Relevant code:
- [backend/app.py](backend/app.py#L571)

### Step D: Tool calls happen inside agent turns

When an agent decides to use a tool, events include function call and function response payloads.

### Step E: Final operator response is produced

The backend returns final text and logs the mission.

Relevant code:
- [backend/app.py](backend/app.py#L605)

## 5) What Is LLM vs What Is Deterministic

### LLM-heavy responsibilities
- Command interpretation and ambiguity resolution
- Mission strategy selection
- Recovery rationale and alternative selection
- Operator-friendly summarization

### Deterministic responsibilities
- Drone status checks and movement APIs
- Route planning and movement execution
- Fleet assignment helpers
- Building and survivor lookup
- Queue progression and result aggregation

## 6) Navigation Specialist Flow

Navigation agent:
- [backend/agents/navigation.py](backend/agents/navigation.py)

It delegates real movement and return behavior to orchestrator functions:
- [backend/orchestrator/navigation.py](backend/orchestrator/navigation.py)

This means navigation behavior is mostly deterministic while the agent handles intent and reporting.

## 7) Scan Workflow Internal Flow

Scan workflow top-level:
- [backend/agents/scan_agent.py](backend/agents/scan_agent.py)

Current structure:
1. Resolve scan targets
2. Assign drones to buildings
3. Prepare fleet queue
4. Run parallel loop workers
5. Emit one consolidated report

Key composed stages:
- Fleet assignment stage: [backend/agents/scan_agent.py](backend/agents/scan_agent.py#L953)
- Fleet execution stage: [backend/agents/scan_agent.py](backend/agents/scan_agent.py#L962)
- Top-level scan_agent: [backend/agents/scan_agent.py](backend/agents/scan_agent.py#L974)

Important behavior:
- Queue state is stored in session state.
- Loop workers pick next building, navigate, sweep scan, save result.
- Final report is deterministic aggregation of saved results.

## 8) Supply Workflow Internal Flow

Supply workflow top-level:
- [backend/agents/supply_agent.py](backend/agents/supply_agent.py)

Current structure:
1. Resolve survivor targets
2. Assign drones to targets
3. Prepare dispatch queue
4. Run parallel supply loops
5. Emit one consolidated supply report

Key composed stages:
- Assignment stage: [backend/agents/supply_agent.py](backend/agents/supply_agent.py#L611)
- Execution stage: [backend/agents/supply_agent.py](backend/agents/supply_agent.py#L617)
- Top-level supply_agent: [backend/agents/supply_agent.py](backend/agents/supply_agent.py#L638)

Dynamic behavior:
- One initial target per drone is assigned first.
- Remaining targets stay in a shared queue.
- Workers keep claiming and dispatching until queue is empty.

## 9) Session State and Loop Coordination

Loop workflows rely heavily on shared session state keys.

Scan examples:
- scan_buildings
- fleet_assignments
- scan_results_list

Supply examples:
- supply_targets
- supply_assignments
- supply_pending_targets
- supply_results_structured

Because of this, scan and supply flows are resilient to complex multi-step operations while still producing one final user-facing report.

## 10) Tool Surfaces and MCP Integration

MCP toolset groups are declared in:
- [backend/agents/_mcp.py](backend/agents/_mcp.py)

This file defines grouped tool names such as NAV_TOOLS, THERMAL_TOOLS, and FLEET_TOOLS and builds MCP toolsets used by workflow agents.

## 11) Streaming Behavior

Streaming endpoint emits different event types such as:
- thought
- tool_call
- tool_result
- text
- final

Relevant implementation:
- [backend/app.py](backend/app.py#L620)

This gives UI-level observability into intermediate execution without waiting for final text.

## 12) Practical Mental Model

Use this model when debugging:

1. API accepted request
2. Commander parsed and routed mission
3. Specialist workflow executed tool calls
4. Session state evolved across loop iterations
5. Aggregator produced final response

If a mission output looks wrong, verify in this order:
1. Parse quality in command_parser
2. Planner decision via is_complex_mission and mission_planner
3. Workflow queue state and assignment functions
4. Tool function responses
5. Final report aggregation function

## 13) Where to Start Reading in Code

Suggested reading order:
1. [backend/app.py](backend/app.py)
2. [backend/agents/commander.py](backend/agents/commander.py)
3. [backend/agents/command_parser.py](backend/agents/command_parser.py)
4. [backend/agents/navigation.py](backend/agents/navigation.py)
5. [backend/agents/scan_agent.py](backend/agents/scan_agent.py)
6. [backend/agents/supply_agent.py](backend/agents/supply_agent.py)
7. [backend/agents/recovery.py](backend/agents/recovery.py)
8. [backend/agents/_mcp.py](backend/agents/_mcp.py)

This sequence gives the fastest path to understanding how missions actually run in production.