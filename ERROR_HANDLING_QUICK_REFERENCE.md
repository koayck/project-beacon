# ADK ERROR HANDLING - Quick Reference Card

## 1️⃣  SCAN_WORKFLOW ERRORS (plan_route in navigation phase)
- **File**: `backend/agents/scan_workflow.py` (28 lines)
- **Error Response**: `{"error": "No clear route found", "obstacles": [...]}`
- **Handling**: Navigation agent instruction says "If result has error: report it and stop"
- **Result**: LLM reports to operator, stops (thermal phase skipped)
- **Retry**: No automatic retry (but BLOCKED recovery in commander)

## 2️⃣  PLAN_ROUTE TOOL (3-Strategy Router)
- **File**: `backend/tools/drone_commands.py` (lines 140-281, 142 lines)
- **Strategies**: Direct → Over → Around
- **Success**: `{"waypoints": [...], "strategy": "...", "summary": "..."}`
- **Failure**: `{"error": "No clear route found", "obstacles": [...]}`
- **Auto-Altitude**: If not specified, uses building_top + 5m or 10m default

## 3️⃣  SCAN_AREA TOOL (Thermal Imaging)
- **File**: `backend/tools/drone_commands.py` (lines 74-81, 8 lines)
- **Implementation**: Simple gRPC wrapper
- **Error Handling**: In thermal agent instructions
  - Battery > 20% required
  - Battery 10-20%: warn operator
  - Pre-scan snapshot required

## 4️⃣  ERROR HANDLING STRATEGY
```
Tool returns {"error": "..."} dict
         ↓
Agent reads "error" field
         ↓
LLM decision: Report to operator & stop
         ↓
ADK framework streams error event
         ↓
Frontend displays to user
```
**Philosophy**: Propagate errors, don't hide or auto-retry.

## 5️⃣  AGENT DEFINITIONS (Quick View)

### COMMANDER (51 lines) - Root orchestrator
- ✅ Checks `select_best_drone()` for error
- ✅ Routes to scan_workflow or navigation_agent
- ✅ Implements BLOCKED recovery: climb 5m & retry
- Temp: 0.5 (precise)

### SCAN_WORKFLOW (28 lines) - 2-Stage pipeline
- Stage 1: navigation_agent_scan (if fails → stop)
- Stage 2: thermal_agent (only if Stage 1 succeeds)

### NAVIGATION (76 lines) - Path planning
- ✅ Checks `plan_route()` for error
- ✅ Executes waypoints via `move_drone_to()`
- ✅ BLOCKED recovery: re-call `plan_route()`
- ⚠️ Doesn't check move_drone_to success
- Temp: 0.7 (balanced)

### THERMAL (42 lines) - Thermal imaging
- ✅ Battery pre-check (> 20% required)
- ✅ Pre-scan snapshot via `get_drone_view()`
- ✅ Executes `scan_area()`
- Temp: 0.7 (balanced)

## 6️⃣  ERROR SCENARIOS & RECOVERY

| Scenario | Detection | Recovery |
|----------|-----------|----------|
| **No Route** | plan_route error dict | Agent stops, reports obstacles |
| **BLOCKED** | Drone firmware detects | Commander retries with +5m altitude |
| **Low Battery** | get_drone_status < 20% | Thermal agent stops scan |
| **Drone Offline** | gRPC exception | Framework streams error to frontend |
| **No Eligible Drones** | select_best_drone error | Commander asks operator to retry |

## 7️⃣  ERROR RESPONSE PATTERNS

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

## 8️⃣  SSE STREAMING (Frontend)
```json
{"type": "tool_call", "name": "plan_route", "args": {...}}
{"type": "tool_result", "name": "plan_route", "success": true}
{"type": "error", "text": "No clear route found"}
{"type": "final", "text": "..."}
```

## 9️⃣  RETRY PATTERNS
- ✅ BLOCKED: Re-call `plan_route()` from current position
- 🔴 No Auto-Retry: Errors propagate, agent decides
- 🔴 No Fallback Drone: Mission fails if drone unavailable
- 🔴 No Path Caching: Recomputes every time

## 🔟 KEY FILES
- `backend/agents/commander.py` - Root agent
- `backend/agents/scan_workflow.py` - 2-stage pipeline
- `backend/agents/navigation.py` - Path planning (76 lines)
- `backend/agents/thermal.py` - Thermal imaging
- `backend/tools/drone_commands.py` - Tools (307 lines)
  - `plan_route()` [lines 140-281]
  - `scan_area()` [lines 74-81]
- `backend/app.py` - SSE streaming [lines 278-360]

## Design Philosophy
**"Deterministic over automatic"** — Tool returns error dict → Agent reads error → LLM decides action → Errors remain visible and auditable.

