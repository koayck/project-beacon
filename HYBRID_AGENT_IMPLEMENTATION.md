# Hybrid Agent Architecture — Implementation Plan

## Executive Summary

Refactor Project Beacon's agent architecture from **instruction-following** to **hybrid reasoning + orchestration**.

**Current state:** Agents execute deterministic procedures (paying LLM costs for flowchart logic)  
**Target state:** Agents reason strategically, functions execute reliably

**Expected outcomes:**
- 70% reduction in LLM API costs
- 10x faster mission execution (no LLM latency for routine ops)
- 100% offline capability for core operations
- Better testability and observability

---

## Architecture Principles

### Core Pattern
```
User Input
    ↓
[AGENT] Parse ambiguous natural language → structured intent
    ↓
[AGENT] Plan mission strategy (if complex) → execution plan
    ↓
[FUNCTION] Execute plan deterministically → results
    ↓
[AGENT] Recover from unexpected failures (if needed) → recovery plan
```

### Decision Matrix

| Task Type | Use Agent | Use Function |
|-----------|:---------:|:------------:|
| Natural language parsing | ✅ | ❌ |
| Mission planning (multi-constraint) | ✅ | ❌ |
| Strategic decision-making | ✅ | ❌ |
| Error recovery (adaptive) | ✅ | ❌ |
| Tool execution | ❌ | ✅ |
| Retry logic | ❌ | ✅ |
| Status reporting | ❌ | ✅ |
| Route calculation | ❌ | ✅ |
| Fleet coordination | ❌ | ✅ |

### Why This Matters for Project Beacon

1. **Offline-first requirement:** Orchestrators work without LLM → core operations resilient
2. **Starlink backup model:** Agents enhance experience when connected, not required for mission-critical ops
3. **Cost efficiency:** Disaster response missions may run 100s of commands → cost adds up
4. **Latency:** Real-time drone control can't wait 2-3 seconds for LLM reasoning on simple moves
5. **Reliability:** Deterministic code paths are testable, agents are probabilistic

---

## Implementation Phases

## Phase 1: Extract Orchestrators (Week 1)

**Goal:** Move all deterministic logic from agents to pure Python functions.

### Tasks

#### 1.1 Create Orchestrator Module Structure
```
backend/
├── orchestrator/
│   ├── __init__.py
│   ├── navigation.py      # Movement sequences
│   ├── scanning.py        # Scan sequences  
│   ├── supply.py          # Supply drop sequences
│   ├── fleet.py           # Fleet coordination
│   └── mission.py         # High-level mission execution
```

**Acceptance criteria:**
- [ ] Module created with proper `__init__.py`
- [ ] All files have type hints and docstrings
- [ ] Imports work from `backend.orchestrator`

#### 1.2 Refactor Navigation Logic

**Current state:** `backend/agents/navigation.py` has 50+ lines of procedural instructions in `_INSTRUCTION`

**Target state:**
```python
# backend/orchestrator/navigation.py
from dataclasses import dataclass
from typing import Optional

@dataclass
class NavigationResult:
    success: bool
    final_position: Optional[Point3D]
    waypoints_completed: int
    error: Optional[str] = None

async def execute_navigation_sequence(
    asset_id: str,
    target: Point3D,
    altitude_override: Optional[float] = None,
    retry_strategy: RetryStrategy = RetryStrategy.ALTITUDE_ESCALATION
) -> NavigationResult:
    """
    Navigate drone to target with automatic retry and obstacle avoidance.
    
    Pure function — no LLM calls, deterministic execution.
    
    Args:
        asset_id: Drone identifier (e.g., "BEACON-01")
        target: Destination coordinates
        altitude_override: Force specific altitude, bypass auto-calculation
        retry_strategy: How to handle blocked routes
    
    Returns:
        NavigationResult with success status and final position
    """
    for attempt in range(3):
        # Calculate altitude offset for this attempt
        altitude_offset = 0 if altitude_override else (attempt * 5)
        adjusted_target = Point3D(
            target.x,
            altitude_override or (target.y + altitude_offset),
            target.z
        )
        
        # Plan route with obstacle awareness
        route = await plan_route(
            asset_id=asset_id,
            target=adjusted_target
        )
        
        if not route.success:
            continue  # Try next altitude
        
        # Execute waypoints sequentially
        for i, waypoint in enumerate(route.waypoints):
            move_result = await move_drone_to(asset_id, waypoint)
            
            if move_result.blocked:
                # Re-route from current position
                current_pos = await get_drone_position(asset_id)
                route = await plan_route(
                    asset_id=asset_id,
                    start=current_pos,
                    target=adjusted_target
                )
                if not route.success:
                    break  # Route failed, try next altitude
            
            if move_result.success and i == len(route.waypoints) - 1:
                # Reached final waypoint
                return NavigationResult(
                    success=True,
                    final_position=waypoint,
                    waypoints_completed=i + 1
                )
    
    return NavigationResult(
        success=False,
        final_position=None,
        waypoints_completed=0,
        error="No clear route found after 3 altitude attempts"
    )
```

**Acceptance criteria:**
- [ ] `execute_navigation_sequence()` function created
- [ ] All retry logic moved from agent instruction to function
- [ ] Returns strongly-typed `NavigationResult`
- [ ] Unit tests pass (see Phase 2)
- [ ] No LLM calls within function

#### 1.3 Refactor Scanning Logic

**Extract from:** `backend/agents/thermal.py` and `backend/agents/scan_workflow.py`

**Target state:**
```python
# backend/orchestrator/scanning.py

async def execute_single_building_scan(
    asset_id: str,
    building: Building
) -> BuildingScanResult:
    """Execute full scan sequence for one building."""
    # 1. Navigate to position above building
    nav_result = await execute_navigation_sequence(
        asset_id=asset_id,
        target=Point3D(
            building.center_x,
            building.height + 5.0,  # 5m above rooftop
            building.center_z
        )
    )
    
    if not nav_result.success:
        return BuildingScanResult.failure(
            building=building,
            error=f"Navigation failed: {nav_result.error}"
        )
    
    # 2. Check battery before scan
    status = await get_drone_status(asset_id)
    if status.battery_pct < 20:
        return BuildingScanResult.failure(
            building=building,
            error=f"Battery too low: {status.battery_pct}%"
        )
    
    # 3. Execute sweep scan
    scan_result = await sweep_scan_building(
        asset_id=asset_id,
        target_x=building.center_x,
        target_z=building.center_z
    )
    
    return BuildingScanResult.success(
        building=building,
        survivors=scan_result.survivors,
        battery_remaining=status.battery_pct
    )


async def execute_area_scan_mission(
    buildings: list[Building],
    fleet_ids: Optional[list[str]] = None
) -> AreaScanResult:
    """Execute parallel scan across multiple buildings."""
    # Auto-assign fleet if not specified
    if not fleet_ids or fleet_ids == ["auto"]:
        available_fleet = await get_available_drones()
        fleet_ids = [d.asset_id for d in available_fleet]
    
    # Assign buildings to drones (closest-first algorithm)
    assignments = await assign_fleet_to_buildings(
        buildings=buildings,
        fleet_ids=fleet_ids
    )
    
    # Execute scans in parallel
    tasks = [
        execute_single_building_scan(asset_id, building)
        for asset_id, building in assignments.items()
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Consolidate results
    return consolidate_scan_results(results)
```

**Acceptance criteria:**
- [ ] `execute_single_building_scan()` function created
- [ ] `execute_area_scan_mission()` function created
- [ ] Battery check, navigation, and scanning sequence fully deterministic
- [ ] Parallel execution via `asyncio.gather()`
- [ ] Returns consolidated `AreaScanResult`

#### 1.4 Refactor Supply Drop Logic

**Extract from:** `backend/agents/supply_workflow.py`

**Target state:**
```python
# backend/orchestrator/supply.py

async def execute_supply_drop_mission(
    survivors: list[Survivor],
    fleet_ids: Optional[list[str]] = None
) -> SupplyDropResult:
    """Execute parallel supply drops to multiple survivors."""
    # Similar pattern to area_scan_mission
    # ...
```

**Acceptance criteria:**
- [ ] Supply drop orchestration extracted
- [ ] Deterministic fleet assignment
- [ ] Parallel execution

#### 1.5 Update Existing Agents to Use Orchestrators

**Modify:** `backend/agents/navigation.py`

**Before:**
```python
_INSTRUCTION = """You are a navigation specialist...

MOVE PROCEDURE
1. Call plan_route(asset_id, target_x, target_z, target_y).
2. If plan_route returns error, retry with target_y=max(current_y+5, 10).
3. If retry fails, retry once more...
"""
```

**After:**
```python
from backend.orchestrator.navigation import execute_navigation_sequence

_INSTRUCTION = """You are a navigation specialist.

When asked to move a drone, call the execute_navigation_sequence tool with:
- asset_id: drone identifier
- target: destination coordinates
- altitude_override: only if operator specified exact altitude

This tool handles obstacle avoidance, retry logic, and waypoint execution automatically.

Report the result to the operator in clear, concise language.
"""

navigation_agent = Agent(
    name="navigation_agent",
    model=QWEN3_INSTRUCT,
    instruction=_INSTRUCTION,
    tools=[
        FunctionTool(execute_navigation_sequence),
        FunctionTool(get_drone_status),
        FunctionTool(return_to_base)
    ]
)
```

**Acceptance criteria:**
- [ ] Agent instructions simplified to high-level guidance
- [ ] Agent calls orchestrator functions instead of raw tools
- [ ] No procedural step-by-step logic in agent instructions

---

## Phase 2: Add Unit Tests for Orchestrators (Week 1)

**Goal:** Ensure deterministic functions are 100% testable.

### Tasks

#### 2.1 Setup Test Infrastructure
```
tests/
├── orchestrator/
│   ├── test_navigation.py
│   ├── test_scanning.py
│   ├── test_supply.py
│   └── fixtures.py
```

**Acceptance criteria:**
- [ ] Test directory structure created
- [ ] `pytest` fixtures for mock drones, buildings, survivors
- [ ] All tests can run with `uv run pytest tests/orchestrator/`

#### 2.2 Write Navigation Tests

```python
# tests/orchestrator/test_navigation.py
import pytest
from backend.orchestrator.navigation import execute_navigation_sequence
from backend.models import Point3D

@pytest.mark.asyncio
async def test_navigation_success_direct_route(mock_drone):
    """Test successful navigation with clear route."""
    result = await execute_navigation_sequence(
        asset_id="BEACON-01",
        target=Point3D(10.0, 15.0, -5.0)
    )
    
    assert result.success is True
    assert result.final_position == Point3D(10.0, 15.0, -5.0)
    assert result.waypoints_completed > 0
    assert result.error is None

@pytest.mark.asyncio
async def test_navigation_retry_on_blocked_route(mock_drone):
    """Test altitude escalation when route blocked."""
    # Mock plan_route to fail on attempt 0, succeed on attempt 1
    result = await execute_navigation_sequence(
        asset_id="BEACON-01",
        target=Point3D(10.0, 15.0, -5.0)
    )
    
    assert result.success is True
    assert result.final_position.y >= 20.0  # Escalated altitude

@pytest.mark.asyncio
async def test_navigation_failure_after_max_retries(mock_drone):
    """Test failure when all altitude attempts blocked."""
    # Mock all plan_route calls to fail
    result = await execute_navigation_sequence(
        asset_id="BEACON-01",
        target=Point3D(10.0, 15.0, -5.0)
    )
    
    assert result.success is False
    assert "No clear route" in result.error
```

**Acceptance criteria:**
- [ ] 80%+ code coverage for `navigation.py`
- [ ] Tests for success, retry, and failure paths
- [ ] All tests pass in <100ms (no real API calls)

#### 2.3 Write Scanning Tests

Similar structure for `test_scanning.py`

**Acceptance criteria:**
- [ ] 80%+ code coverage for `scanning.py`
- [ ] Tests for single building, area scan, battery failures

---

## Phase 3: Add Mission Planner Agent (Week 2)

**Goal:** Introduce strategic reasoning layer for complex missions.

### Tasks

#### 3.1 Define Mission Plan Schema

```python
# backend/models/mission.py
from enum import Enum
from pydantic import BaseModel, Field

class MissionStrategy(str, Enum):
    PARALLEL_SWEEP = "parallel_sweep"
    SEQUENTIAL_RELAY = "sequential_relay"
    HUB_SPOKE = "hub_spoke"
    SINGLE_DRONE = "single_drone"

class FleetAssignment(BaseModel):
    asset_id: str
    target_id: str  # building ID or survivor ID
    reason: str  # Why this drone was assigned

class MissionPlan(BaseModel):
    mission_type: str  # "area_scan", "supply_drop", "patrol"
    strategy: MissionStrategy
    fleet_assignments: list[FleetAssignment]
    execution_order: list[str]  # ["resolve_locations", "assign_fleet", "execute"]
    contingencies: dict[str, str]  # {"low_battery": "sequential_relay"}
    estimated_duration_min: float
    confidence: float = Field(ge=0.0, le=1.0)
```

**Acceptance criteria:**
- [ ] Pydantic models defined with validation
- [ ] Enum for common strategies
- [ ] Type hints on all fields

#### 3.2 Create Mission Planner Agent

```python
# backend/agents/mission_planner.py
from google.adk.agents import Agent
from google.adk.tools import FunctionTool
from backend.agents._model import QWEN3_INSTRUCT, QWEN3_GEN_CONFIG
from backend.models.mission import MissionPlan

mission_planner = Agent(
    name="mission_planner",
    model=QWEN3_INSTRUCT,
    generate_content_config=QWEN3_GEN_CONFIG,
    description="Strategic mission planner for complex multi-drone operations.",
    instruction="""You are a tactical mission planner for drone swarms.

Your job: analyze mission requirements and fleet status, then output an optimal execution plan.

REASONING FRAMEWORK:
1. Analyze constraints:
   - Fleet status (battery, position, equipment)
   - Target distribution (clustered vs. scattered)
   - Urgency (time-critical vs. thorough coverage)
   - Environmental factors (weather, obstacles)

2. Generate 2-3 alternative strategies:
   - parallel_sweep: all drones work simultaneously (fast, high battery cost)
   - sequential_relay: drones take turns to conserve battery
   - hub_spoke: one central drone coordinates, others execute
   - single_drone: only one drone needed

3. Select best strategy based on:
   - Minimizing time (if urgent)
   - Maximizing coverage (if thorough)
   - Battery efficiency (if low power)

4. Output structured plan with contingencies:
   - What if a drone runs out of battery mid-mission?
   - What if a route is blocked?
   - What if a new target appears?

OUTPUT FORMAT:
Return a JSON object matching the MissionPlan schema:
{
  "mission_type": "area_scan",
  "strategy": "parallel_sweep",
  "fleet_assignments": [
    {"asset_id": "BEACON-01", "target_id": "building_5", "reason": "closest, full battery"},
    {"asset_id": "BEACON-02", "target_id": "building_7", "reason": "thermal equipped"}
  ],
  "execution_order": ["resolve_locations", "assign_fleet", "parallel_execute"],
  "contingencies": {
    "low_battery": "recall_and_swap",
    "blocked_route": "altitude_override"
  },
  "estimated_duration_min": 8.5,
  "confidence": 0.9
}

CRITICAL: Your output is WHAT to do, not HOW. Never include step-by-step procedures.
The orchestrator handles execution details.
""",
    tools=[
        FunctionTool(get_fleet_status),
        FunctionTool(estimate_route_duration),
        FunctionTool(get_building_locations)
    ],
    output_format=MissionPlan  # Gemini structured output
)
```

**Acceptance criteria:**
- [ ] Agent created with strategic reasoning instructions
- [ ] Output constrained to `MissionPlan` Pydantic model
- [ ] Tools for context gathering (fleet status, locations)
- [ ] No procedural "step 1, step 2" logic

#### 3.3 Integrate Planner into Command Flow

```python
# backend/app.py
@app.post("/api/command")
async def execute_command(request: CommandRequest):
    """Main command endpoint with hybrid agent flow."""
    
    # 1. Parse natural language (Agent)
    intent = await parse_command_intent(request.natural_language)
    
    # 2. Decide if mission planning needed
    if intent.is_complex_mission():
        # Complex: use mission planner (Agent)
        plan = await mission_planner.run(
            user_input=intent.to_prompt(),
            context={
                "fleet_status": await get_fleet_status(),
                "environment": await get_environment_state()
            }
        )
    else:
        # Simple: generate plan directly (Function)
        plan = generate_simple_plan(intent)
    
    # 3. Execute plan (Orchestrator - deterministic)
    result = await execute_mission_plan(plan)
    
    # 4. Format response
    return format_operator_report(result)
```

**Acceptance criteria:**
- [ ] Mission planner integrated into command flow
- [ ] Conditional use (complex missions only)
- [ ] Simple commands bypass planner (fast path)

---

## Phase 4: Add Recovery Agent (Week 2)

**Goal:** Handle unexpected failures adaptively.

### Tasks

#### 4.1 Define Error Context Schema

```python
# backend/models/recovery.py
from pydantic import BaseModel

class ErrorContext(BaseModel):
    error_type: str  # "navigation_blocked", "low_battery", "communication_lost"
    asset_id: str
    mission_plan: MissionPlan
    current_state: dict  # Position, battery, etc.
    partial_results: Optional[dict]  # What succeeded before error

class RecoveryPlan(BaseModel):
    action: str  # "abort", "swap_drone", "altitude_override", "retry"
    modified_plan: Optional[MissionPlan]
    rationale: str
```

**Acceptance criteria:**
- [ ] Pydantic models for error context and recovery plans
- [ ] Type-safe error handling

#### 4.2 Create Recovery Agent

```python
# backend/agents/recovery.py
recovery_agent = Agent(
    name="recovery_agent",
    model=QWEN3_INSTRUCT,
    instruction="""You are a recovery specialist for drone mission failures.

When a mission encounters an unexpected error, your job is to:
1. Analyze the error context and mission state
2. Propose a recovery strategy
3. Output a structured recovery plan

RECOVERY STRATEGIES:
- abort: mission cannot continue safely → recall all drones
- swap_drone: replace failed drone with available backup
- altitude_override: blocked route → try +10m altitude
- retry: transient error → retry same operation
- partial_completion: complete mission with remaining drones

DECISION FACTORS:
- Battery remaining (abort if <10%)
- Mission urgency (retry if time-critical)
- Fleet availability (swap if backup exists)
- Partial completion value (worth continuing?)

OUTPUT: RecoveryPlan JSON with action, modified plan (if continuing), and rationale.
""",
    tools=[FunctionTool(get_fleet_status), FunctionTool(get_available_drones)],
    output_format=RecoveryPlan
)
```

**Acceptance criteria:**
- [ ] Agent created with recovery-specific reasoning
- [ ] Output constrained to `RecoveryPlan` schema
- [ ] Clear decision criteria in instructions

#### 4.3 Integrate Recovery into Orchestrators

```python
# backend/orchestrator/mission.py
async def execute_mission_plan(plan: MissionPlan) -> MissionResult:
    """Execute mission with automatic recovery on failures."""
    try:
        # Execute based on strategy
        if plan.strategy == MissionStrategy.PARALLEL_SWEEP:
            result = await execute_parallel_sweep(plan)
        elif plan.strategy == MissionStrategy.SEQUENTIAL_RELAY:
            result = await execute_sequential_relay(plan)
        else:
            result = await execute_default(plan)
        
        return result
    
    except UnrecoverableError as e:
        # Invoke recovery agent
        recovery_plan = await recovery_agent.run(
            error_context=ErrorContext(
                error_type=e.error_type,
                asset_id=e.asset_id,
                mission_plan=plan,
                current_state=await get_mission_state(),
                partial_results=e.partial_results
            )
        )
        
        if recovery_plan.action == "abort":
            return MissionResult.aborted(recovery_plan.rationale)
        
        # Execute recovery plan
        return await execute_mission_plan(recovery_plan.modified_plan)
```

**Acceptance criteria:**
- [ ] Orchestrators catch `UnrecoverableError`
- [ ] Recovery agent invoked only on unexpected failures
- [ ] Recovery plan executed automatically

---

## Phase 5: Command Parser Agent (Week 3)

**Goal:** Replace keyword routing with true NL understanding.

### Tasks

#### 5.1 Define Intent Schema

```python
# backend/models/intent.py
from pydantic import BaseModel

class CommandIntent(BaseModel):
    mission_type: str  # "move", "scan", "supply_drop", "return_home"
    targets: list[dict]  # Flexible target representation
    constraints: dict  # Priority, urgency, etc.
    asset_ids: Optional[list[str]]  # Specific drones or "auto"
    
    def is_complex_mission(self) -> bool:
        """Determine if mission planner needed."""
        return (
            len(self.targets) > 1 or
            self.asset_ids == ["auto"] or
            "urgency" in self.constraints
        )
```

**Acceptance criteria:**
- [ ] Intent schema supports all mission types
- [ ] `is_complex_mission()` logic implemented

#### 5.2 Create Command Parser Agent

```python
# backend/agents/command_parser.py
command_parser = Agent(
    name="command_parser",
    model=QWEN3_INSTRUCT,
    instruction="""Parse natural language commands into structured intent.

EXAMPLES:

Input: "scan the flooded school for survivors"
Output: {
  "mission_type": "scan",
  "targets": [{"type": "building", "class": "school", "context": "flooded"}],
  "constraints": {"detect": "survivors", "priority": "submerged"},
  "asset_ids": ["auto"]
}

Input: "move BEACON-01 to coordinates (10, 20, -5)"
Output: {
  "mission_type": "move",
  "targets": [{"type": "coordinates", "x": 10, "y": 20, "z": -5}],
  "constraints": {},
  "asset_ids": ["BEACON-01"]
}

Input: "deploy all drones to scan the entire district"
Output: {
  "mission_type": "scan",
  "targets": [{"type": "area", "name": "district", "scope": "entire"}],
  "constraints": {"urgency": "high"},
  "asset_ids": ["auto"]
}

Handle ambiguity by making reasonable inferences. Default to "auto" for asset_ids if not specified.
""",
    output_format=CommandIntent
)
```

**Acceptance criteria:**
- [ ] Agent parses diverse NL inputs
- [ ] Output matches `CommandIntent` schema
- [ ] Handles ambiguity gracefully

---

## Phase 6: Offline Mode Support (Week 3)

**Goal:** Ensure core operations work without LLM.

### Tasks

#### 6.1 Create Offline Command Parser

```python
# backend/offline/command_parser.py
import re
from backend.models.intent import CommandIntent

COMMAND_PATTERNS = {
    r"move|navigate|fly.*?to.*?\(?([\d.-]+)[,\s]+([\d.-]+)[,\s]+([\d.-]+)": "move",
    r"scan|search.*?(building|area|district)": "scan",
    r"return|recall|come back": "return_home",
    r"deploy.*?swarm": "deploy_swarm",
}

def parse_command_offline(user_input: str) -> CommandIntent:
    """Pattern-based parsing for offline mode."""
    user_input_lower = user_input.lower()
    
    for pattern, mission_type in COMMAND_PATTERNS.items():
        match = re.search(pattern, user_input_lower)
        if match:
            if mission_type == "move":
                x, y, z = match.groups()
                return CommandIntent(
                    mission_type="move",
                    targets=[{"type": "coordinates", "x": float(x), "y": float(y), "z": float(z)}],
                    constraints={},
                    asset_ids=["BEACON-01"]  # Default to first drone
                )
            elif mission_type == "scan":
                return CommandIntent(
                    mission_type="scan",
                    targets=[{"type": "area", "scope": "default"}],
                    constraints={},
                    asset_ids=["auto"]
                )
    
    # Fallback: unknown command
    return CommandIntent(
        mission_type="unknown",
        targets=[],
        constraints={},
        asset_ids=[]
    )
```

**Acceptance criteria:**
- [ ] Regex patterns for common commands
- [ ] Falls back gracefully on unknown input
- [ ] No LLM dependency

#### 6.2 Add Connectivity Detection

```python
# backend/services/connectivity.py
import asyncio

_starlink_available = False
_last_check = 0

async def check_starlink_available() -> bool:
    """Check if Starlink connection active."""
    global _starlink_available, _last_check
    
    now = asyncio.get_event_loop().time()
    if now - _last_check < 60:  # Cache for 60s
        return _starlink_available
    
    try:
        # Try to reach Gemini API
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get("https://generativelanguage.googleapis.com")
            _starlink_available = resp.status_code < 500
    except Exception:
        _starlink_available = False
    
    _last_check = now
    return _starlink_available
```

**Acceptance criteria:**
- [ ] Connectivity check with caching
- [ ] Fast timeout (5s max)
- [ ] Safe default (offline)

#### 6.3 Implement Graceful Degradation

```python
# backend/app.py
@app.post("/api/command")
async def execute_command(request: CommandRequest):
    """Hybrid command execution with offline fallback."""
    
    # Check connectivity
    online = await check_starlink_available()
    
    if online:
        # Full agent reasoning
        intent = await command_parser.run(request.natural_language)
        if intent.is_complex_mission():
            plan = await mission_planner.run(intent=intent)
        else:
            plan = generate_simple_plan(intent)
    else:
        # Offline: pattern matching + heuristics
        intent = parse_command_offline(request.natural_language)
        plan = generate_simple_plan(intent)
    
    # Orchestration always works (no LLM)
    result = await execute_mission_plan(plan)
    
    return format_operator_report(result)
```

**Acceptance criteria:**
- [ ] Online: full agent capabilities
- [ ] Offline: pattern matching + deterministic execution
- [ ] Seamless transition between modes

---

## Phase 7: Observability & Monitoring (Week 4)

**Goal:** Clear visibility into agent vs. orchestrator performance.

### Tasks

#### 7.1 Add Structured Logging

```python
# backend/observability/logger.py
import structlog

logger = structlog.get_logger()

async def execute_navigation_sequence(...):
    logger.info(
        "orchestrator.navigation.start",
        asset_id=asset_id,
        target=target.dict(),
        retry_strategy=retry_strategy.value
    )
    
    try:
        result = await _navigate(...)
        logger.info(
            "orchestrator.navigation.success",
            asset_id=asset_id,
            waypoints_completed=result.waypoints_completed,
            duration_ms=duration
        )
        return result
    except Exception as e:
        logger.error(
            "orchestrator.navigation.error",
            asset_id=asset_id,
            error=str(e)
        )
        raise
```

**Acceptance criteria:**
- [ ] All orchestrators log start/success/error
- [ ] Structured logs (JSON format)
- [ ] Duration tracking

#### 7.2 Add Agent Performance Metrics

```python
# backend/observability/metrics.py
from prometheus_client import Counter, Histogram

agent_calls = Counter(
    "agent_llm_calls_total",
    "Total LLM calls by agent",
    ["agent_name", "success"]
)

agent_latency = Histogram(
    "agent_llm_latency_seconds",
    "LLM call latency by agent",
    ["agent_name"]
)

@agent_latency.labels(agent_name="command_parser").time()
async def parse_with_agent(...):
    result = await command_parser.run(...)
    agent_calls.labels(agent_name="command_parser", success="true").inc()
    return result
```

**Acceptance criteria:**
- [ ] Prometheus metrics for agent calls, latency, costs
- [ ] Metrics endpoint at `/metrics`

---

## Success Metrics

### Performance
- [ ] **Latency:** 90th percentile command execution <500ms (down from ~2s)
- [ ] **LLM calls per mission:** <2 (down from 5-7)
- [ ] **Offline capability:** 100% core operations work without Starlink

### Cost
- [ ] **API cost per mission:** <$0.05 (down from $0.15)
- [ ] **Monthly savings at 10k missions:** $1000+

### Code Quality
- [ ] **Test coverage:** 80%+ for orchestrators
- [ ] **Type safety:** 100% type hints on orchestrators
- [ ] **LOC reduction:** 40% fewer lines in agent instructions

### Reliability
- [ ] **Deterministic operations:** 100% reproducible in tests
- [ ] **Error handling:** All exceptions caught and logged
- [ ] **Recovery success rate:** 80%+ of failures auto-recovered

---

## Migration Strategy

### Backward Compatibility
During migration, both old agents and new orchestrators will coexist:

```python
# Feature flag for gradual rollout
USE_HYBRID_ARCHITECTURE = os.getenv("HYBRID_AGENTS", "false") == "true"

@app.post("/api/command")
async def execute_command(request: CommandRequest):
    if USE_HYBRID_ARCHITECTURE:
        return await execute_command_hybrid(request)
    else:
        return await execute_command_legacy(request)
```

### Testing Strategy
1. **Phase 1-2:** Test orchestrators in isolation (unit tests)
2. **Phase 3-4:** Test agent + orchestrator integration (integration tests)
3. **Phase 5-6:** Test online/offline parity (E2E tests)
4. **Phase 7:** Monitor production metrics, compare old vs. new

### Rollback Plan
If issues arise:
1. Set `HYBRID_AGENTS=false` (instant rollback)
2. All old agent code remains in place
3. No database migrations needed (state schema unchanged)

---

## Open Questions

1. **Mission Planner Threshold:** When to use planner vs. simple plan?
   - Proposal: Use planner if `len(targets) > 1` OR `asset_ids == ["auto"]`

2. **Recovery Agent Scope:** Should it handle equipment failures (e.g., camera offline)?
   - Proposal: Yes, but as Phase 4.5 (after core recovery working)

3. **Offline Mode UX:** How to signal to user when in offline mode?
   - Proposal: Status indicator in UI, degraded NL parsing warning

4. **Cost Monitoring:** Should we hard-cap LLM spend per mission?
   - Proposal: Add budget guardrails in Phase 7 (e.g., max 3 calls per mission)

---

## Next Steps

1. **Review this plan** — confirm phases, priorities, success metrics
2. **Set up orchestrator module** — create file structure (Phase 1.1)
3. **Extract navigation logic** — move first orchestrator (Phase 1.2)
4. **Write tests** — ensure new code is solid (Phase 2.1)
5. **Iterate** — one phase per week, measure improvements

**Ready to start Phase 1?** Let me know if you want to adjust priorities or scope.
