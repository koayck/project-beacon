# ADK Agent Error Handling - Documentation Index

## 📚 Documentation Files Created

### 1. **BACKEND_ERROR_HANDLING_GUIDE.md** (13 KB)
   **Comprehensive deep-dive analysis**
   - Complete agent definitions with code
   - Error flow examples (unreachable target, BLOCKED recovery, low battery)
   - Detailed error handling strategy across layers
   - Tool response patterns
   - SSE streaming implementation
   - Design patterns & gaps
   
   **Best for**: Understanding the complete architecture, implementation details

### 2. **ERROR_HANDLING_QUICK_REFERENCE.md** (4.2 KB)
   **One-page quick reference**
   - Error scenarios table
   - Agent definitions summary
   - Response formats
   - Retry patterns
   - Key files list
   
   **Best for**: Quick lookup, debugging, team reference

## 🎯 Your Questions Answered

### 1. SCAN_WORKFLOW Agent - Error Handling ✅
**Location**: `backend/agents/scan_workflow.py` (28 lines)

Error flow:
```
scan_workflow (SequentialAgent)
  ├─ Stage 1: navigation_agent_scan
  │  └─ Calls plan_route()
  │  └─ If {"error": "..."} → Agent instruction: "report it and stop"
  │  └─ LLM reads error, reports to operator
  │  └─ STOPS (doesn't call move_drone_to)
  │
  └─ Stage 2: thermal_agent (skipped if Stage 1 fails)
```

**Retry**: No automatic retry in tool layer (but BLOCKED recovery in commander)

---

### 2. NAVIGATION Agent - plan_route Tool ✅
**Location**: `backend/tools/drone_commands.py` (lines 140-281, 142 lines)

3 routing strategies (tried in order):
1. **Direct path** → 1 waypoint
2. **Go over obstacles** → 3 waypoints (climb, cruise, descend)
3. **Go around obstacles** → 2 waypoints (detour left/right)

Success response:
```json
{
  "waypoints": [...],
  "strategy": "direct|over|around",
  "summary": "...",
  "obstacle_count": N
}
```

Error response:
```json
{
  "error": "No clear route found",
  "obstacles": [{"id": "...", "cx": 0, "cz": 0, "h": 10}]
}
```

**Auto-altitude**: building_top + 5m or 10m default if not specified

---

### 3. THERMAL Agent - scan_area Tool ✅
**Location**: `backend/tools/drone_commands.py` (lines 74-81, 8 lines)

Simple gRPC wrapper:
```python
async def scan_area(asset_id, cx, cy, cz, radius=5.0) -> dict:
    return await _get_client().scan_area(asset_id, cx, cy, cz, radius)
```

Error handling in thermal agent instructions:
- ✅ Battery > 20% required
- ✅ Battery 10-20%: warn operator
- ✅ Pre-scan snapshot via get_drone_view()

---

### 4. Error Handling Logic ✅
**Strategy**: PROPAGATE + AGENT-LEVEL CHECKING

```
Layer 1: Tool Layer
  └─ Returns {"error": "..."} dict on failure
  └─ No auto-retry logic

Layer 2: Agent Layer
  └─ Instructions enforce error checks via LLM
  └─ "If result has error: report it and stop"

Layer 3: gRPC Layer
  └─ Exceptions propagate (no catch)

Layer 4: Framework Layer
  └─ ADK catches exceptions, streams to frontend via SSE
```

**Retry patterns**:
- ✅ BLOCKED: Re-call plan_route() from current position
- 🔴 No auto-retry on other errors
- 🔴 No fallback alternatives
- 🔴 No path caching

---

### 5. Complete Agent Definitions ✅

#### COMMANDER (51 lines) - Root orchestrator
- ✅ Checks select_best_drone() for error
- ✅ Routes to scan_workflow or navigation_agent
- ✅ Implements BLOCKED recovery: climb 5m & retry
- Temperature: 0.5 (precise routing)
- Tools: select_best_drone, list_all_drones, deploy_swarm, recall_swarm

#### SCAN_WORKFLOW (28 lines) - 2-stage pipeline
- Stage 1: navigation_agent_scan (if fails → stop)
- Stage 2: thermal_agent (only if Stage 1 succeeds)
- SequentialAgent (deterministic, not LLM-routed)

#### NAVIGATION (76 lines) - Path planning & movement
- ✅ Checks plan_route() for error field
- ✅ Executes waypoints via move_drone_to()
- ✅ BLOCKED recovery: re-call plan_route()
- ⚠️ Doesn't check move_drone_to() success
- Temperature: 0.7 (balanced creativity)
- Output: output_key="nav_result" (stored for next agent)
- Two instances: navigation_agent (commander), navigation_agent_scan (scan_workflow)

#### THERMAL (42 lines) - Thermal imaging
- ✅ Battery pre-check (> 20% required)
- ✅ Battery warning (if 10-20%)
- ✅ Pre-scan sensor snapshot
- ✅ Structured reporting with positions/directions
- Temperature: 0.7 (balanced creativity)
- Tools: scan_area, get_drone_status, get_drone_view

---

## 📊 Error Scenarios Table

| Error Type | Detection Point | Strategy | Recovery |
|---|---|---|---|
| **No Route Found** | plan_route returns error dict | Check "error" field | Agent reports, stops |
| **BLOCKED/Re-plan** | plan_route returns error | LLM sees BLOCKED | Retry: Re-call plan_route() |
| **Drone Unreachable** | gRPC exception | Exception propagates | Stream error to frontend |
| **Battery Too Low** | get_drone_status < 20% | LLM conditional | Stop scan, warn operator |
| **No Eligible Drones** | select_best_drone() error | Check "error" field | Stop, ask operator |
| **Connection Lost** | gRPC exception mid-command | Unhandled exception | SSE error event |

---

## 📁 Key Source Files

**Agents** (`backend/agents/`):
- `commander.py` (51 lines) - Root agent
- `scan_workflow.py` (28 lines) - 2-stage pipeline
- `navigation.py` (76 lines) - Path planning
- `thermal.py` (42 lines) - Thermal imaging
- `_model.py` (50 lines) - LLM config (temperature tuning)

**Tools** (`backend/tools/`):
- `drone_commands.py` (307 lines) - Main tool implementations
  - `plan_route()` [lines 140-281] - 3-strategy router
  - `move_drone_to()` [lines 57-61]
  - `scan_area()` [lines 74-81]
  - `get_drone_status()` [lines 69-71]
  - `select_best_drone()` [lines 99-137]
  - Other: get_drone_view, return_to_base, list_all_drones, plan_sweep_pattern
- `swarm_ops.py` (40 lines) - Multi-drone operations

**Framework** (`backend/`):
- `app.py` (FastAPI) - [lines 253-360] SSE streaming with error handling
- `grpc/client.py` - gRPC connection wrapper

---

## 🔑 Key Design Patterns

### ✅ Implemented
- **Propagate**: Errors surface as response dicts
- **Agent-Level Checking**: Instructions enforce error validation
- **SSE Streaming**: Real-time error events to frontend
- **BLOCKED Recovery**: Commander handles via re-planning

### 🔴 Not Implemented
- **Auto-Retry**: No automatic retries (except BLOCKED)
- **Fallback Alternatives**: No backup paths or drones
- **Circuit Breaker**: No gRPC timeout handling
- **Exponential Backoff**: No retry delays
- **Path Caching**: No caching of successful routes

---

## 🎯 Philosophy

**"Deterministic over Automatic"**
- Tool returns `{"error": "..."}` dict
- Agent reads error field
- LLM decides action (report, retry, etc.)
- Errors remain **visible and auditable**

---

## ⚠️ Critical Implementation Gaps

| Gap | Impact | Suggested Fix |
|---|---|---|
| No move_drone_to success check | Silent failures | Check "success" field |
| No gRPC timeouts | Requests hang | timeout=30s on stubs |
| No fallback drone | Mission fails | Try next nearest |
| No path caching | Recomputes each time | Cache from session |
| Limited logging | No audit trail | Log all tool calls |
| No exponential backoff | Fails immediately | Retry: 100ms, 200ms, 400ms |

---

## 📝 Error Response Formats

### plan_route Success
```json
{
  "waypoints": [{"x": 0, "y": 15, "z": 0, "reason": "climb"}],
  "strategy": "direct|over|around",
  "summary": "2 waypoints, direct path clear",
  "obstacle_count": 0
}
```

### plan_route Error
```json
{
  "error": "No clear route found",
  "obstacles": [{"id": "building-1", "cx": 5, "cz": -10, "h": 10}]
}
```

### SSE Streaming (Frontend)
```json
{"type": "tool_call", "name": "plan_route", "args": {...}}
{"type": "tool_result", "name": "plan_route", "success": true}
{"type": "error", "text": "No clear route found"}
{"type": "final", "text": "..."}
```

---

## 🚀 Quick Start

1. **For understanding the complete architecture**: Read `BACKEND_ERROR_HANDLING_GUIDE.md`
2. **For quick reference during debugging**: Use `ERROR_HANDLING_QUICK_REFERENCE.md`
3. **For specific error scenarios**: See section 7 of BACKEND_ERROR_HANDLING_GUIDE.md

---

## 📞 Common Error Paths

**Scenario 1: No Route Found**
```
plan_route() → {"error": "No clear route found"}
             → Navigation agent: "If error: report and stop"
             → Output: "Cannot reach target — surrounded by 3 buildings"
             → Thermal phase skipped
```

**Scenario 2: BLOCKED Mid-Operation**
```
Drone firmware detects obstacle
    → Drone reports status: BLOCKED
    → Commander: "If BLOCKED: climb 5m and retry"
    → Navigation calls plan_route() again
    → plan_route() returns new waypoints
    → Continue with new plan
```

**Scenario 3: Low Battery During Scan**
```
Thermal agent checks battery
    → get_drone_status() returns 15%
    → Agent: "Only proceed if battery > 20%"
    → Output: "Battery at 15%, cannot scan"
    → Stop (scan_area never called)
```

