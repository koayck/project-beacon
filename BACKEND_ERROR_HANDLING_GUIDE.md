# ADK AGENT ERROR HANDLING - Complete Analysis

## 1. SCAN_WORKFLOW AGENT - Error Handling Flow

**File**: `backend/agents/scan_workflow.py` (28 lines)  
**Type**: `SequentialAgent` (2-stage deterministic pipeline)

### Error Flow
```python
scan_workflow = SequentialAgent(
    name="scan_workflow",
    sub_agents=[_nav_for_scan, thermal_agent],
)
```

**How plan_route Errors Are Handled**:
1. scan_workflow delegates to `_nav_for_scan` (navigation agent)
2. Navigation calls `plan_route(asset_id, target_x, target_z, target_y)`
3. **If plan_route returns** `{"error": "..."}`, navigation agent instructions say:
   - "If the result has 'error': report it and stop"
4. Agent LLM reads error field, tells operator, **stops execution**
5. Thermal phase (Stage 2) never runs
6. ⚠️ **No automatic retry** in tool layer (but BLOCKED recovery in commander)

---

## 2. NAVIGATION AGENT - plan_route Tool

**File**: `backend/tools/drone_commands.py` (lines 140-281)

### Signature
```python
async def plan_route(
    asset_id: str,
    target_x: float,
    target_z: float,
    target_y: float | None = None,
) -> dict
```

### Three Routing Strategies (tried in order)
1. **Direct path**: If no obstacles → 1 waypoint
2. **Go over obstacles**: Climb → cruise → descend → 3 waypoints  
3. **Go around obstacles**: Detour left/right → 2 waypoints

### Success Response
```python
{
    "asset_id": "BEACON-01",
    "from": {"x": 0, "y": 0, "z": 0},
    "to": {"x": 10, "y": 15, "z": -20},
    "waypoints": [
        {"x": 0, "y": 15, "z": 0, "reason": "climb to clear obstacle"},
        {"x": 10, "y": 15, "z": -20, "reason": "cruise above obstacles"},
        {"x": 10, "y": 15, "z": -20, "reason": "descend to scan altitude"}
    ],
    "obstacle_count": 1,
    "strategy": "over",
    "summary": "3 waypoints, clearing obstacle via over. Scan alt=15m."
}
```

### Error Response
```python
{
    "asset_id": "BEACON-01",
    "error": "No clear route found",
    "obstacles": [
        {"id": "building-1", "cx": 5, "cz": -10, "h": 10},
        {"id": "building-2", "cx": 8, "cz": -15, "h": 12}
    ]
}
```

### Auto-Altitude Calculation
- If `target_y` not specified:
  - Checks for nearby building
  - If found: `target_y = building_top + 5m`
  - Else: `target_y = 10m` (default)

---

## 3. THERMAL AGENT - scan_area Tool

**File**: `backend/tools/drone_commands.py` (lines 74-81)

### Signature
```python
async def scan_area(
    asset_id: str, cx: float, cy: float, cz: float, radius: float = 5.0
) -> dict
```

### Implementation
```python
return await _get_client().scan_area(asset_id, cx, cy, cz, radius)
```

### Thermal Agent Instructions
```
SCAN PROCEDURE
1. Call get_drone_status(asset_id). Only proceed if battery > 20%.
   If battery 10-20%: warn operator before scanning.
2. Call get_drone_view(asset_id) to capture pre-scan sensor snapshot.
3. Call scan_area(asset_id, cx, cy, cz, radius). Default radius = 10 m.
4. Output structured report with findings.
```

### Thermal Agent Error Handling
- ✅ Battery pre-check (won't scan if < 20%)
- ✅ Battery warning (if 10-20%)
- ✅ Pre-scan sensor snapshot
- ✅ Structured reporting with positions/directions
- ⚠️ No explicit error recovery for scan_area failure

---

## 4. ERROR HANDLING STRATEGY

**Pattern**: PROPAGATE + AGENT-LEVEL CHECKING

| Layer | Strategy |
|-------|----------|
| **Tool Layer** | Returns `{"error": "..."}` dict on failure |
| **Agent Layer** | Instructions enforce error checks via LLM |
| **gRPC Layer** | Exceptions propagate (no catch) |
| **Framework Layer** | SSE streaming errors to frontend |

**Key Design**: **No automatic retry in tool layer**. LLM agent reads error field and decides action.

---

## 5. COMPLETE AGENT DEFINITIONS

### COMMANDER Agent (51 lines)
**File**: `backend/agents/commander.py`

```python
commander = Agent(
    name="commander",
    model=QWEN3_INSTRUCT,
    description="Root agent. Routes drone swarm commands to the correct specialist sub-agent.",
    generate_content_config=QWEN3_GEN_CONFIG_COMMANDER,
    instruction="""You are the Ground Control Station commander for an autonomous drone swarm.

WORKFLOW — follow these steps in order:

1. SELECT DRONE (if operator did not name one):
   Call select_best_drone(target_x, target_z).
   If it returns an error, tell the operator and stop.
   Confirm selection: "Selecting BEACON-02 — nearest eligible drone, 34 m away, 88% battery."

2. ROUTE to the correct handler:
   - Scan a location / building  → delegate to scan_workflow
   - Movement only              → delegate to navigation_agent
   - Deploy swarm formation     → call deploy_swarm(asset_ids, formation)
   - Recall swarm               → call recall_swarm(asset_ids)  [ask confirmation first]

SAFETY RULES:
- Normalise asset IDs to uppercase, for example: "beacon-01" → "BEACON-01".
- Ask for confirmation before recalling the entire swarm or sending drones beyond ±200 m.
- Never re-task a drone whose status is MOVING, SCANNING, or RETURNING.
- If a drone reports BLOCKED: tell navigation_agent to climb 5 m and retry.
""",
    sub_agents=[scan_workflow, navigation_agent],
    tools=[select_best_drone, list_all_drones, deploy_swarm, recall_swarm],
)
```

**Error Handling**:
- ✅ Checks `select_best_drone()` for "error" field
- ✅ Reports error to operator, stops
- ✅ Implements BLOCKED recovery: "climb 5 m and retry"

### SCAN_WORKFLOW Agent (28 lines)
**File**: `backend/agents/scan_workflow.py`

```python
scan_workflow = SequentialAgent(
    name="scan_workflow",
    description="Navigate a drone to a target location then scan it for heat signatures.",
    sub_agents=[_nav_for_scan, thermal_agent],
)
```

**Execution**: Stage 1 (navigation) → Stage 2 (thermal, if Stage 1 succeeds)

### NAVIGATION Agent (76 lines)
**File**: `backend/agents/navigation.py`

```python
def make_navigation_agent(name: str = "navigation_agent") -> Agent:
    return Agent(
        name=name,
        model=QWEN3_INSTRUCT,
        description="Handles all drone movement and flight path planning.",
        generate_content_config=QWEN3_GEN_CONFIG,
        output_key="nav_result",
        instruction="""You are a navigation specialist for autonomous drones.

MOVE PROCEDURE
1. Call plan_route(asset_id, target_x, target_z, target_y).
   - If the result has "error": report it and stop.
2. Report the "summary" to the operator.
3. For each waypoint in "waypoints", call move_drone_to(asset_id, wp.x, wp.y, wp.z).
4. After the final move: "BEACON-XX arrived at (x, y, z)."

BLOCKED RECOVERY: Call plan_route again from current position — it recomputes.
""",
        tools=[plan_route, move_drone_to, return_to_base, get_drone_status, plan_sweep_pattern],
    )

# Two instances (ADK single-parent constraint):
navigation_agent = make_navigation_agent()  # Used by commander
_nav_for_scan = make_navigation_agent(name="navigation_agent_scan")  # Used by scan_workflow
```

**Error Handling**:
- ✅ Checks `plan_route()` for "error" field
- ✅ Reports error and stops
- ✅ BLOCKED recovery: re-call `plan_route()` from current position
- ⚠️ Doesn't check `move_drone_to()` success

### THERMAL Agent (42 lines)
**File**: `backend/agents/thermal.py`

```python
thermal_agent = Agent(
    name="thermal_agent",
    model=QWEN3_INSTRUCT,
    description="Handles thermal imaging, area scanning, and survivor detection.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction="""You are a thermal imaging specialist for search and rescue drones.

SCAN PROCEDURE
1. Call get_drone_status(asset_id). Only proceed if battery > 20%.
   If battery 10-20%: warn operator before scanning.
2. Call get_drone_view(asset_id) to capture pre-scan sensor snapshot.
3. Call scan_area(asset_id, cx, cy, cz, radius). Default radius = 10 m.
4. Output structured report with findings.

If no signatures found: "No heat signatures detected."
Survivors in flood water = CRITICAL priority.
""",
    tools=[scan_area, get_drone_status, get_drone_view],
)
```

**Error Handling**:
- ✅ Pre-scan battery check (> 20% required)
- ✅ Battery warning (if 10-20%)
- ✅ Pre-scan sensor snapshot

---

## 6. ERROR FLOW EXAMPLE: TARGET UNREACHABLE

```
User: "Scan building at (100, -50)"
  ↓
Commander: select_best_drone(100, -50) → "BEACON-01 found"
  ↓
Delegate to scan_workflow
  ↓
Navigation Phase:
  plan_route("BEACON-01", 100, -50):
    Strategy 1 (direct): BLOCKED by Building-A
    Strategy 2 (over): BLOCKED by Building-C
    Strategy 3 (around): BLOCKED by Building-B
    
  Returns: {"error": "No clear route found", "obstacles": [A, B, C]}
  
  Agent sees "error" → Instruction: "report it and stop"
  
  Output: "Cannot reach target. Surrounded by 3 buildings:
           Building-A (25m), Building-B (22m), Building-C (28m)."
  ↓
STOP execution (don't call move_drone_to, thermal phase skipped)
  ↓
Frontend receives SSE error event: {"type": "error", "text": "..."}
```

---

## 7. ERROR HANDLING SUMMARY TABLE

| Error Type | Detection | Strategy | Recovery |
|---|---|---|---|
| No eligible drones | `select_best_drone()` | Check "error" field | Stop, ask operator |
| No route found | `plan_route()` returns error | Check "error" field | Stop, report obstacles |
| BLOCKED/re-plan | `plan_route()` returns error | LLM sees BLOCKED | **Retry**: Re-call `plan_route()` |
| Drone unreachable (gRPC) | Exception in get_status() | Exception propagates | Stream error to frontend |
| Battery too low | `get_drone_status()` < 20% | LLM conditional | Stop scan, warn operator |
| Connection lost mid-cmd | gRPC exception | Unhandled exception | SSE error event |
| Collision/firmware error | Drone reports BLOCKED | Firmware signals | Commander handles BLOCKED |

---

## 8. TOOL ERROR RESPONSE PATTERNS

### Success Pattern
```python
# plan_route success:
{
    "waypoints": [...],
    "strategy": "direct|over|around",
    "summary": "...",
    "obstacle_count": N
}

# move_drone_to success:
{"success": true, "message": "Drone moving..."}

# scan_area success:
{"success": true, "message": "Scan complete, X signatures found"}
```

### Error Pattern
```python
# plan_route error:
{
    "error": "No clear route found",
    "obstacles": [{"id": "...", "cx": 0, "cz": 0, "h": 10}]
}

# gRPC error:
# Exception → asyncio.gather(return_exceptions=True) → dict with error
{"asset_id": "...", "error": "KeyError: No gRPC connection"}
```

---

## 9. STREAMING ERROR HANDLING

**File**: `backend/app.py` (lines 278-360)

```python
async def generate() -> AsyncGenerator[str, None]:
    # ...
    if kind == "error":
        yield f"data: {json.dumps({'type': 'error', 'text': str(data)})}\n\n"
        break
```

**SSE Event Format**:
```json
{"type": "tool_call", "name": "plan_route", "args": {...}, "agent": "navigation_agent"}
{"type": "tool_result", "name": "plan_route", "success": true, "result": "..."}
{"type": "error", "text": "No clear route found"}
{"type": "final", "text": "..."}
```

---

## 10. DESIGN PATTERNS

| Pattern | Used? | Example |
|---------|-------|---------|
| **Propagate** | ✅ Primary | Errors surface as response dicts |
| **Retry** | 🟡 Limited | Only BLOCKED: re-call `plan_route()` |
| **Fallback** | 🔴 No | No alternative paths or drones |
| **Circuit Breaker** | 🔴 No | No gRPC timeout handling |
| **Exponential Backoff** | 🔴 No | No retry delays |

**Philosophy**: "Deterministic over automatic" — Agent instructions enforce checks, LLM decides action, errors remain visible.

---

## 11. IMPLEMENTATION GAPS

| Gap | Impact | Suggested Fix |
|---|---|---|
| No `move_drone_to` success check | Silent failures | Check "success" field after each move |
| No gRPC timeouts | Requests can hang | `timeout=30s` on gRPC stubs |
| No fallback drone | Mission fails | Try next nearest eligible drone |
| No path caching | Recomputes on BLOCKED | Cache from this session |
| Limited logging | No audit trail | Log all tool calls + responses |
| No exponential backoff | Fails on transient errors | Retry with delays (100ms, 200ms, 400ms) |

---

## 12. KEY FILES

- `backend/agents/commander.py` - Root agent orchestration
- `backend/agents/scan_workflow.py` - 2-stage sequential pipeline
- `backend/agents/navigation.py` - Path planning & movement
- `backend/agents/thermal.py` - Thermal imaging
- `backend/tools/drone_commands.py` - Tool implementations
- `backend/app.py` - SSE streaming with error events

