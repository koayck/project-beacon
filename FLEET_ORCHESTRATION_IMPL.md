# Fleet Orchestration — Implementation Guide

> **Purpose:** Step-by-step guide to implement proximity-based parallel drone fleet orchestration in a fresh worktree. Follow all steps in order.

## Overview

When an area with 2+ buildings is selected, dispatch multiple drones in parallel (one per building), assigning the closest available IDLE drones using greedy nearest-first matching.

**Before:** single drone `BEACON-01` (hardcoded), sequential `LoopAgent` scan  
**After:** `"auto"` sentinel → fleet assigner queries IDLE drones → `asyncio.gather()` parallel scans

---

## Step 1 — Add service functions to `backend/services/drone_control.py`

Add these two functions **before** `deploy_swarm()` at the end of the file. Also ensure `import math` is at the top of the file (add it if missing).

```python
async def assign_fleet_to_buildings(buildings: list[dict]) -> dict:
    """
    Assign the closest available drones to buildings using greedy nearest-first matching.

    For each building the nearest IDLE drone with battery > 20% is selected.
    Returns assignments (drone→building pairs), any unassigned buildings (more buildings
    than eligible drones), and idle drones that were not needed.
    """
    if not buildings:
        return {"assignments": [], "unassigned_buildings": [], "idle_drones": []}

    client = grpc_client
    asset_ids = client.registered_asset_ids()
    if not asset_ids:
        return {
            "error": "No drones uplinked.",
            "suggestion": "Use /uplink to connect a drone first.",
            "assignments": [],
            "unassigned_buildings": buildings,
        }

    statuses = await asyncio.gather(
        *[client.get_status(aid) for aid in asset_ids],
        return_exceptions=True,
    )

    eligible: list[dict] = []
    for status in statuses:
        if isinstance(status, Exception):
            continue
        if status.get("battery", 0) <= 20:
            continue
        if status.get("status", "") != "IDLE":
            continue
        eligible.append(status)

    if not eligible:
        busy = [s for s in statuses if not isinstance(s, Exception)]
        return {
            "error": "No eligible drones available (all busy or low battery).",
            "suggestion": f"{len(busy)} drone(s) registered but none are IDLE with battery > 20%.",
            "assignments": [],
            "unassigned_buildings": buildings,
        }

    # Greedy nearest-first: repeatedly pick the globally closest (drone, building) pair.
    remaining_drones = list(eligible)
    remaining_buildings = list(buildings)
    assignments: list[dict] = []

    while remaining_buildings and remaining_drones:
        best_drone: dict | None = None
        best_building: dict | None = None
        best_dist = float("inf")
        for drone in remaining_drones:
            for building in remaining_buildings:
                dist = math.sqrt(
                    (drone["x"] - building["x"]) ** 2 + (drone["z"] - building["z"]) ** 2
                )
                if dist < best_dist:
                    best_dist = dist
                    best_drone = drone
                    best_building = building

        if best_drone is None or best_building is None:
            break

        assignments.append({
            "asset_id": best_drone["asset_id"],
            "building": best_building,
            "distance_m": round(best_dist, 1),
        })
        remaining_drones = [d for d in remaining_drones if d["asset_id"] != best_drone["asset_id"]]
        remaining_buildings = [b for b in remaining_buildings if b is not best_building]

    return {
        "assignments": assignments,
        "unassigned_buildings": remaining_buildings,
        "idle_drones": [d["asset_id"] for d in remaining_drones],
        "total_assigned": len(assignments),
    }


async def parallel_fleet_scan(
    assignments: list[dict],
    unassigned_buildings: list[dict] | None = None,
) -> dict:
    """
    Execute sweep scans for all drone-building assignments concurrently.

    After the parallel first batch, any unassigned buildings are scanned
    sequentially by the first assignment's drone (fallback for when fewer
    drones than buildings are available).
    """
    if not assignments:
        return {"error": "No assignments provided.", "results": [], "total_survivors": 0}

    async def _scan_one(asset_id: str, building: dict) -> dict:
        result = await sweep_scan_building(
            asset_id=asset_id,
            target_x=building["x"],
            target_z=building["z"],
        )
        return {"asset_id": asset_id, "building": building, "scan_result": result}

    batch = await asyncio.gather(
        *[_scan_one(a["asset_id"], a["building"]) for a in assignments],
        return_exceptions=True,
    )

    all_results: list[dict] = []
    for i, r in enumerate(batch):
        if isinstance(r, Exception):
            all_results.append({
                "asset_id": assignments[i]["asset_id"],
                "building": assignments[i]["building"],
                "scan_result": {"error": str(r)},
            })
        else:
            all_results.append(r)

    # Sequential fallback: unassigned buildings handled by first assignment's drone.
    if unassigned_buildings:
        fallback_aid = assignments[0]["asset_id"]
        for building in unassigned_buildings:
            result = await sweep_scan_building(
                asset_id=fallback_aid,
                target_x=building["x"],
                target_z=building["z"],
            )
            all_results.append({"asset_id": fallback_aid, "building": building, "scan_result": result})

    # Build consolidated report.
    total_survivors = 0
    building_summaries: list[str] = []
    for r in all_results:
        scan = r["scan_result"]
        b = r["building"]
        if "error" in scan:
            building_summaries.append(
                f"Building at (x={b['x']}, z={b['z']}) [{r['asset_id']}]: SCAN ERROR — {scan['error']}"
            )
        else:
            count: int = scan.get("reported_survivor_count", 0)
            levels = scan.get("level_count", "?")
            wps = scan.get("waypoint_count", "?")
            total_survivors += count
            line = (
                f"Building at (x={b['x']:.1f}, z={b['z']:.1f}) [{r['asset_id']}]: "
                f"{count} survivor(s) across {levels} level(s). Waypoints: {wps}."
            )
            uniq: list[dict] = scan.get("unique_survivors_detected", [])
            if uniq:
                survivor_lines = []
                for s in uniq:
                    sub_tag = " [SUBMERGED — CRITICAL]" if s.get("submerged") else ""
                    survivor_lines.append(
                        f"  - Survivor {s['id']}: ({s['x']}, {s['y']}, {s['z']}){sub_tag}"
                    )
                if any(s.get("submerged") for s in uniq):
                    submerged_count = sum(1 for s in uniq if s.get("submerged"))
                    line += f" [CRITICAL: {submerged_count} submerged]"
                line += "\n" + "\n".join(survivor_lines)
            building_summaries.append(line)

    n = len(all_results)
    div = "═" * 39
    thin = "─" * 39
    total_line = (
        "No heat signatures detected across all scanned buildings."
        if total_survivors == 0
        else f"TOTAL SURVIVORS DETECTED: {total_survivors}"
    )
    summary = (
        f"{div}\n"
        f"  AREA SCAN COMPLETE — {n} building(s)\n"
        f"{div}\n"
        + "\n".join(building_summaries)
        + f"\n{thin}\n{total_line}\n{div}"
    )

    return {
        "success": True,
        "results": all_results,
        "total_buildings_scanned": n,
        "total_survivors": total_survivors,
        "summary": summary,
    }
```

---

## Step 2 — Register MCP tools in `backend/mcp/server.py`

### 2a. Add imports near the top (where other service imports are):

```python
from backend.services.drone_control import (
    assign_fleet_to_buildings,
    parallel_fleet_scan,
)
```

### 2b. Add these two tool registrations at the end of the file:

```python
@beacon_mcp.tool(name="assign_fleet_to_buildings")
async def assign_fleet_to_buildings_tool(buildings: list[dict]) -> dict:
    """
    Assign the closest available IDLE drones to a list of buildings using greedy
    nearest-first matching. Returns assignments (drone→building), unassigned buildings
    (when fewer drones than buildings), and idle drones that were not needed.
    """
    return await assign_fleet_to_buildings(buildings)


@beacon_mcp.tool(name="parallel_fleet_scan")
async def parallel_fleet_scan_tool(
    assignments: list[dict],
    unassigned_buildings: list[dict] | None = None,
) -> dict:
    """
    Execute sweep scans for multiple drone-building assignments concurrently.
    Unassigned buildings are handled sequentially by the first drone after the
    parallel batch completes. Returns a consolidated report with per-building
    survivor counts and a formatted summary.
    """
    return await parallel_fleet_scan(assignments, unassigned_buildings)
```

---

## Step 3 — Add `FLEET_TOOLS` group in `backend/agents/_mcp.py`

Find `SWARM_TOOLS = [...]` in the file and add `FLEET_TOOLS` directly after it:

```python
FLEET_TOOLS = [
    "assign_fleet_to_buildings",
    "parallel_fleet_scan",
    "discover_fleet",
]
```

Also update the import in any file that needs it (covered in Step 4).

---

## Step 4 — Rewrite `backend/agents/scan_workflow.py`

This is the largest change. The file's module docstring, imports, and the bottom half (agents + workflow) need to change. The LoopAgent code in the middle of the file can be left as dead code.

### 4a. Replace the module docstring (top of file):

```python
"""
Scan Workflow — navigate then sweep-scan one or more buildings, then emit a
single consolidated final report.

Works for both single-building and multi-building (area) commands:
  - "Scan building at (-15, -20) with BEACON-01"
      → resolver wraps the single building in a 1-item list
      → fleet assigner creates one assignment for BEACON-01
      → executor runs one scan

  - "Scan all buildings near (-10, -15) radius 30m"  (asset_id: "auto")
      → resolver calls find_buildings_in_area → N-item list, asset_id="auto"
      → fleet assigner queries all IDLE drones, greedy nearest-first assignment
      → executor runs N scans in parallel (one per assigned drone)

Structure:
    scan_workflow (SequentialAgent)
    ├── scan_resolver_agent      # builds state["scan_buildings"] list
    ├── fleet_assigner_agent     # assigns drones → buildings, writes state["fleet_assignments"]
    └── fleet_scan_executor_agent # parallel_fleet_scan(), emits final report

Session state keys:
    scan_buildings       JSON — {"asset_id": str | "auto", "buildings": [{id,x,z,height,bounds},…]}
    fleet_assignments    JSON — {"assignments": [{asset_id, building, distance_m}], ...}
"""
```

### 4b. Update the import block to include `FLEET_TOOLS`:

```python
from backend.agents._mcp import FLEET_TOOLS, NAV_TOOLS, THERMAL_TOOLS, make_toolset
```

### 4c. Add `finalize_scan` FunctionTool (after existing queue tools, before fleet tools section):

```python
def finalize_scan(tool_context: ToolContext) -> dict:
    """
    Signal that the scan workflow is complete. Used by the final agent to
    cleanly terminate the LoopAgent after all buildings have been scanned.
    """
    tool_context.actions.escalate = True
    return {"done": True}


_finalize_tool = FunctionTool(func=finalize_scan)
```

### 4d. Add fleet orchestration FunctionTools (new section after `_finalize_tool`):

```python
# ── Fleet orchestration FunctionTools ─────────────────────────────────────────

async def assign_drones_to_buildings(tool_context: ToolContext) -> dict:
    """
    Read state["scan_buildings"], assign the closest available IDLE drones to
    each building using greedy nearest-first matching, and write the result to
    state["fleet_assignments"].

    When asset_id is an explicit drone ID the drone is assigned to the first
    building; remaining buildings are queued as unassigned (sequential fallback).
    When asset_id is "auto" or absent the full fleet is queried for assignments.
    """
    from backend.services.drone_control import assign_fleet_to_buildings

    raw = tool_context.state.get("scan_buildings", "{}")
    try:
        scan_data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        scan_data = {}

    buildings: list[dict] = scan_data.get("buildings", [])
    asset_id: str = scan_data.get("asset_id", "auto") or "auto"

    if asset_id.upper() not in ("AUTO", "", "UNKNOWN"):
        # Explicit single-drone: first building gets the drone; rest are queued.
        if not buildings:
            result: dict = {"assignments": [], "unassigned_buildings": [], "idle_drones": []}
        elif len(buildings) == 1:
            result = {
                "assignments": [{"asset_id": asset_id, "building": buildings[0], "distance_m": 0.0}],
                "unassigned_buildings": [],
                "idle_drones": [],
            }
        else:
            result = {
                "assignments": [{"asset_id": asset_id, "building": buildings[0], "distance_m": 0.0}],
                "unassigned_buildings": buildings[1:],
                "idle_drones": [],
                "note": f"Single drone {asset_id} — remaining buildings scanned sequentially.",
            }
    else:
        result = await assign_fleet_to_buildings(buildings)

    tool_context.state["fleet_assignments"] = json.dumps(result)
    return result


async def execute_parallel_fleet_scan(tool_context: ToolContext) -> dict:
    """
    Read state["fleet_assignments"] and execute all drone-building scan missions
    concurrently. Unassigned buildings are scanned sequentially by the first
    drone once the parallel batch finishes.
    Returns the consolidated scan report.
    """
    from backend.services.drone_control import parallel_fleet_scan

    raw = tool_context.state.get("fleet_assignments", "{}")
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError):
        data = {}

    if "error" in data:
        return {"error": data["error"], "suggestion": data.get("suggestion", "")}

    assignments: list[dict] = data.get("assignments", [])
    unassigned: list[dict] = data.get("unassigned_buildings", [])

    if not assignments:
        return {"error": "No drone assignments available. Cannot proceed with scan."}

    return await parallel_fleet_scan(assignments, unassigned)


_assign_drones_tool = FunctionTool(func=assign_drones_to_buildings)
_exec_fleet_scan_tool = FunctionTool(func=execute_parallel_fleet_scan)
```

### 4e. Add fleet agents (add before the resolver agent section):

```python
# ── Fleet agents ──────────────────────────────────────────────────────────────

_FLEET_ASSIGNER_INSTRUCTION = """You assign available drones to buildings for a fleet scan.

1. Call assign_drones_to_buildings().
   The tool reads the scan queue and assigns the closest IDLE drones to buildings.
2. If the result contains "error": output the error message clearly and stop.
3. Otherwise output a brief assignment summary — one line per assignment:
   Fleet assigned: <total_assigned> drone(s) dispatched.
   <asset_id> → Building at (x=<x>, z=<z>) [<distance_m>m]
   (repeat for each assignment)
   If unassigned_buildings is non-empty: "<N> building(s) queued for sequential fallback."
"""

_fleet_assigner_agent = Agent(
    name="fleet_assigner_agent",
    model=QWEN3_INSTRUCT,
    description="Assigns the closest available IDLE drones to buildings using proximity-based greedy matching.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_FLEET_ASSIGNER_INSTRUCTION,
    tools=[_assign_drones_tool],
)


_FLEET_EXECUTOR_INSTRUCTION = """You execute the fleet scan missions for all assigned drone-building pairs.

1. Call execute_parallel_fleet_scan().
   This runs all assigned drone-building scans concurrently. Any unassigned
   buildings (fewer drones than buildings) are handled sequentially afterward.
2. If the result contains "error": output the error message to the operator and stop.
3. If the result contains "success": output result["summary"] verbatim.
   Do NOT reformat, summarise, or add any extra text around it.
"""

_fleet_scan_executor_agent = Agent(
    name="fleet_scan_executor_agent",
    model=QWEN3_INSTRUCT,
    description="Executes parallel sweep scans for all fleet assignments and emits the consolidated final report.",
    generate_content_config=QWEN3_GEN_CONFIG,
    instruction=_FLEET_EXECUTOR_INSTRUCTION,
    tools=[_exec_fleet_scan_tool],
)
```

### 4f. Replace the `_RESOLVER_INSTRUCTION` string:

Find the existing `_RESOLVER_INSTRUCTION = """..."""` block and replace its content with:

```python
_RESOLVER_INSTRUCTION = """You build the list of buildings to scan.

COORDINATES: X=East, Y=Up, Z=South.

MULTI-BUILDING EXPLICIT — command lists two or more buildings with coordinates:
  (e.g. "scan building A at (20, -20) and building B at (12, -27)")
  1. For EACH building coordinate, call resolve_scan_target(target_x, target_z).
  2. Collect every matched_building result into the buildings list.
  3. asset_id = the asset_id from the command; if none is mentioned use "auto".

SINGLE BUILDING — command targets one specific building or coordinate:
  1. Call resolve_scan_target(target_x, target_z).
  2. If matched_building=true, wrap the resolved building in a 1-item list.
  3. If matched_building=false, use the provided coordinates as a 1-item list
     with id=-1, height=0, bounds={min_x:x, max_x:x, min_z:z, max_z:z}.
  4. asset_id = the asset_id from the command; if none is mentioned use "auto".

AREA SCAN — command mentions area / zone / radius / "all buildings" with no explicit list:
  1. Call find_buildings_in_area(center_x, center_z, radius).
     Default radius = 30.0 m unless the operator specifies one.
  2. asset_id = "auto" (fleet assignment will pick the best drones).

ASSET ID RULE: Use "auto" whenever no specific drone is named in the command.
Only use a real asset_id (e.g. "BEACON-01") when the operator explicitly names it.

In all cases, output ONLY valid JSON — no markdown, no extra text:
  {"asset_id": "<asset_id or auto>", "buildings": [<building objects>]}

Each building object must have: id, x, z, height, bounds{min_x,max_x,min_z,max_z}.
"""
```

### 4g. Replace the `scan_workflow` SequentialAgent definition:

Find the existing `scan_workflow = SequentialAgent(...)` block and replace with:

```python
scan_workflow = SequentialAgent(
    name="scan_workflow",
    description=(
        "Navigate a drone fleet to scan one or more buildings for heat signatures "
        "and emit a single consolidated final report. "
        "Automatically assigns the closest available drones in parallel when multiple "
        "buildings are targeted. "
        "Use for ANY scan/thermal/survivor-detection command — single building or area scan."
    ),
    sub_agents=[_scan_resolver_agent, _fleet_assigner_agent, _fleet_scan_executor_agent],
)
```

> **Note:** The old `sub_agents=[_scan_resolver_agent, _building_scan_loop]` becomes `sub_agents=[_scan_resolver_agent, _fleet_assigner_agent, _fleet_scan_executor_agent]`. The old LoopAgent and related agents can remain in the file as dead code.

---

## Step 5 — Update `backend/app.py`

Find `_build_agent_prompt()` and update the conditional to skip the asset hint when `asset_id` is `"auto"`:

```python
def _build_agent_prompt(req: CommandRequest) -> str:
    prompt_parts: list[str] = []
    if req.asset_id and req.asset_id.upper() not in ("AUTO", ""):
        prompt_parts.append(
            f"Preferred asset: {req.asset_id}. Use it if it is active and suitable, "
            "but discover the fleet first before committing to it."
        )
    prompt_parts.append(f"Mission: {req.prompt}")
    return " ".join(prompt_parts)
```

The key change is adding `req.asset_id.upper() not in ("AUTO", "")` to the condition (previously only checked truthiness).

---

## Step 6 — Update frontend: `frontend/src/components/CommandPanel.tsx`

### 6a. Add `externalAssetId` to the Props interface:

```typescript
interface Props {
  assetId: string
  connected: boolean
  uplinked: boolean
  battery: number | null
  onCommand: (prompt: string, onEvent: (e: AgentStreamEvent) => void, assetIdOverride?: string) => Promise<void>
  onStop?: () => void
  externalPrompt?: string | null
  onExternalPromptConsumed?: () => void
  externalAssetId?: string | null   // ← ADD THIS
}
```

### 6b. Add `externalAssetId` to the function signature destructuring:

```typescript
export default function CommandPanel({ assetId, connected, uplinked, battery, onCommand, onStop, externalPrompt, onExternalPromptConsumed, externalAssetId }: Props) {
```

### 6c. In the external prompt auto-submit `useEffect`, pass `externalAssetId` as the 3rd arg to `onCommand`:

Find the `onCommand(externalPrompt, (event) => {` call inside the `useEffect` and change its closing `)` to:

```typescript
      }, externalAssetId ?? undefined).catch(err => {
```

(i.e., after the event handler callback closing `}`, add `, externalAssetId ?? undefined`)

---

## Step 7 — Update frontend: `frontend/src/components/SARScene.tsx`

### 7a. Update `handleCommand` to accept optional `assetIdOverride`:

```typescript
const handleCommand = useCallback(async (
  prompt: string,
  onEvent: (e: AgentStreamEvent) => void,
  assetIdOverride?: string,
): Promise<void> => {
  const ac = new AbortController()
  abortRef.current = ac
  addLog(`⬆ ${prompt}`)
  const effectiveAssetId = assetIdOverride ?? ASSET_ID   // ← use override when provided
  try {
    for await (const event of streamCommand(effectiveAssetId, prompt, ac.signal)) {
      onEvent(event)
      if (event.type === 'done') addLog('✓ Agent responded')
    }
  } catch (e: unknown) {
    if (e instanceof Error && e.name === 'AbortError') {
      addLog('⚠ Command aborted')
    } else {
      throw e
    }
  }
}, [addLog])
```

### 7b. Add `pendingScanAssetId` state (near `pendingScanPrompt`):

```typescript
const [pendingScanPrompt, setPendingScanPrompt] = useState<string | null>(null)
const [pendingScanAssetId, setPendingScanAssetId] = useState<string | null>(null)   // ← ADD
```

### 7c. In `handleAreaScan`, set `pendingScanAssetId` to `'auto'` for multi-building:

Find the block that sets `setPendingScanPrompt(prompt)` and add the line before it:

```typescript
// Inject prompt into CommandPanel; use "auto" asset for multi-building so the
// fleet assigner picks the closest available drones.
setPendingScanAssetId(buildingNames.length > 1 ? 'auto' : null)
setPendingScanPrompt(prompt)
```

### 7d. Pass `externalAssetId` prop to `CommandPanel`:

Find the `<CommandPanel ... />` JSX and add:

```tsx
externalAssetId={pendingScanAssetId}
```

Also update `onExternalPromptConsumed` to clear both states:

```tsx
onExternalPromptConsumed={() => {
  setPendingScanPrompt(null)
  setPendingScanAssetId(null)
}}
```

---

## Step 8 — Create test file `tests/test_fleet_orchestration.py`

```python
"""Tests for fleet orchestration: assign_fleet_to_buildings and parallel_fleet_scan."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.drone_control import assign_fleet_to_buildings, parallel_fleet_scan


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_status(asset_id: str, x: float, z: float, battery: float = 80.0, status: str = "IDLE") -> dict:
    return {"asset_id": asset_id, "x": x, "y": 0.0, "z": z, "battery": battery, "status": status}


def _make_building(id: int, x: float, z: float) -> dict:
    return {"id": id, "x": x, "z": z, "height": 10.0, "bounds": {"min_x": x - 5, "max_x": x + 5, "min_z": z - 5, "max_z": z + 5}}


def _mock_client(asset_ids: list[str], statuses: list[dict]) -> MagicMock:
    """Build a mock gRPC client where registered_asset_ids() is sync and get_status is async."""
    client = MagicMock()
    client.registered_asset_ids.return_value = asset_ids
    client.get_status = AsyncMock(side_effect=statuses)
    return client


# ── assign_fleet_to_buildings tests ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_assign_two_buildings_three_drones_picks_closest():
    """2 buildings, 3 drones: only the 2 closest drones are assigned."""
    buildings = [_make_building(0, 0.0, 0.0), _make_building(1, 20.0, 0.0)]

    # BEACON-01 at (1, 0) — closest to building 0
    # BEACON-02 at (18, 0) — closest to building 1
    # BEACON-03 at (50, 0) — farther from both; should stay idle
    statuses = [
        _make_status("BEACON-01", 1.0, 0.0),
        _make_status("BEACON-02", 18.0, 0.0),
        _make_status("BEACON-03", 50.0, 0.0),
    ]
    mock_client = _mock_client(["BEACON-01", "BEACON-02", "BEACON-03"], statuses)

    with patch("backend.services.drone_control.grpc_client", mock_client):
        result = await assign_fleet_to_buildings(buildings)

    assert "error" not in result
    assert result["total_assigned"] == 2
    assigned_ids = {a["asset_id"] for a in result["assignments"]}
    assert assigned_ids == {"BEACON-01", "BEACON-02"}
    assert result["idle_drones"] == ["BEACON-03"]
    assert result["unassigned_buildings"] == []


@pytest.mark.asyncio
async def test_assign_more_buildings_than_drones():
    """3 buildings, 1 drone: 1 assignment + 2 unassigned buildings."""
    buildings = [_make_building(0, 0.0, 0.0), _make_building(1, 10.0, 0.0), _make_building(2, 20.0, 0.0)]
    statuses = [_make_status("BEACON-01", 0.5, 0.0)]
    mock_client = _mock_client(["BEACON-01"], statuses)

    with patch("backend.services.drone_control.grpc_client", mock_client):
        result = await assign_fleet_to_buildings(buildings)

    assert "error" not in result
    assert result["total_assigned"] == 1
    assert len(result["unassigned_buildings"]) == 2


@pytest.mark.asyncio
async def test_assign_no_eligible_drones_all_busy():
    """All drones busy: returns error."""
    buildings = [_make_building(0, 0.0, 0.0)]
    statuses = [_make_status("BEACON-01", 0.0, 0.0, status="BLOCKED")]
    mock_client = _mock_client(["BEACON-01"], statuses)

    with patch("backend.services.drone_control.grpc_client", mock_client):
        result = await assign_fleet_to_buildings(buildings)

    assert "error" in result
    assert result["assignments"] == []
    assert result["unassigned_buildings"] == buildings


@pytest.mark.asyncio
async def test_assign_no_eligible_drones_low_battery():
    """All drones have battery ≤ 20%: returns error."""
    buildings = [_make_building(0, 0.0, 0.0)]
    statuses = [_make_status("BEACON-01", 0.0, 0.0, battery=15.0)]
    mock_client = _mock_client(["BEACON-01"], statuses)

    with patch("backend.services.drone_control.grpc_client", mock_client):
        result = await assign_fleet_to_buildings(buildings)

    assert "error" in result


@pytest.mark.asyncio
async def test_assign_no_drones_uplinked():
    """No drones registered at all: returns error."""
    buildings = [_make_building(0, 0.0, 0.0)]
    mock_client = _mock_client([], [])

    with patch("backend.services.drone_control.grpc_client", mock_client):
        result = await assign_fleet_to_buildings(buildings)

    assert "error" in result
    assert "No drones uplinked" in result["error"]


@pytest.mark.asyncio
async def test_assign_empty_buildings():
    """Empty building list returns empty assignments immediately."""
    mock_client = _mock_client(["BEACON-01"], [])

    with patch("backend.services.drone_control.grpc_client", mock_client):
        result = await assign_fleet_to_buildings([])

    assert result["assignments"] == []
    assert result["unassigned_buildings"] == []


@pytest.mark.asyncio
async def test_assign_greedy_picks_globally_closest():
    """
    Greedy selection should pick the globally closest (drone, building) pair.

    Drones: D1 at (0,0), D2 at (5,0)
    Buildings: B1 at (1,0), B2 at (4,0)

    D1→B1 = 1, D1→B2 = 4
    D2→B1 = 4, D2→B2 = 1

    Greedy: best pair = (D1,B1) dist 1. Then (D2,B2) dist 1. Both assigned.
    """
    buildings = [_make_building(0, 1.0, 0.0), _make_building(1, 4.0, 0.0)]
    statuses = [_make_status("BEACON-01", 0.0, 0.0), _make_status("BEACON-02", 5.0, 0.0)]
    mock_client = _mock_client(["BEACON-01", "BEACON-02"], statuses)

    with patch("backend.services.drone_control.grpc_client", mock_client):
        result = await assign_fleet_to_buildings(buildings)

    assert result["total_assigned"] == 2
    assignment_map = {a["asset_id"]: a["building"]["id"] for a in result["assignments"]}
    assert assignment_map["BEACON-01"] == 0  # B1
    assert assignment_map["BEACON-02"] == 1  # B2


# ── parallel_fleet_scan tests ─────────────────────────────────────────────────

def _make_scan_result(survivors: int = 0) -> dict:
    return {
        "success": True,
        "reported_survivor_count": survivors,
        "level_count": 3,
        "waypoint_count": 12,
        "unique_survivors_detected": [],
    }


@pytest.mark.asyncio
async def test_parallel_fleet_scan_runs_concurrently():
    """parallel_fleet_scan dispatches all assignments via asyncio.gather."""
    assignments = [
        {"asset_id": "BEACON-01", "building": _make_building(0, 0.0, 0.0), "distance_m": 1.0},
        {"asset_id": "BEACON-02", "building": _make_building(1, 20.0, 0.0), "distance_m": 2.0},
    ]
    call_order: list[str] = []

    async def fake_sweep(asset_id, target_x, target_z, **_kwargs):
        call_order.append(asset_id)
        return _make_scan_result()

    with patch("backend.services.drone_control.sweep_scan_building", side_effect=fake_sweep):
        result = await parallel_fleet_scan(assignments)

    assert result["success"] is True
    assert result["total_buildings_scanned"] == 2
    assert set(call_order) == {"BEACON-01", "BEACON-02"}


@pytest.mark.asyncio
async def test_parallel_fleet_scan_sequential_fallback():
    """Unassigned buildings are scanned sequentially by the first drone."""
    assignments = [
        {"asset_id": "BEACON-01", "building": _make_building(0, 0.0, 0.0), "distance_m": 1.0},
    ]
    unassigned = [_make_building(1, 20.0, 0.0)]

    async def fake_sweep(asset_id, target_x, target_z, **_kwargs):
        return _make_scan_result()

    with patch("backend.services.drone_control.sweep_scan_building", side_effect=fake_sweep):
        result = await parallel_fleet_scan(assignments, unassigned)

    assert result["total_buildings_scanned"] == 2
    # Both scanned by BEACON-01 (only drone available)
    assert all(r["asset_id"] == "BEACON-01" for r in result["results"])


@pytest.mark.asyncio
async def test_parallel_fleet_scan_partial_failure():
    """One drone failure does not prevent other drones from completing."""
    assignments = [
        {"asset_id": "BEACON-01", "building": _make_building(0, 0.0, 0.0), "distance_m": 1.0},
        {"asset_id": "BEACON-02", "building": _make_building(1, 20.0, 0.0), "distance_m": 2.0},
    ]

    async def fake_sweep(asset_id, target_x, target_z, **_kwargs):
        if asset_id == "BEACON-01":
            raise RuntimeError("gRPC connection lost")
        return _make_scan_result()

    with patch("backend.services.drone_control.sweep_scan_building", side_effect=fake_sweep):
        result = await parallel_fleet_scan(assignments)

    assert result["total_buildings_scanned"] == 2
    errors = [r for r in result["results"] if "error" in r["scan_result"]]
    successes = [r for r in result["results"] if "error" not in r["scan_result"]]
    assert len(errors) == 1
    assert len(successes) == 1
    assert errors[0]["asset_id"] == "BEACON-01"


@pytest.mark.asyncio
async def test_parallel_fleet_scan_empty_assignments():
    """Empty assignments returns error immediately."""
    result = await parallel_fleet_scan([])
    assert "error" in result


@pytest.mark.asyncio
async def test_parallel_fleet_scan_summary_format():
    """Consolidated summary follows expected report format."""
    assignments = [
        {"asset_id": "BEACON-01", "building": _make_building(0, -15.0, -20.0), "distance_m": 5.0},
    ]

    async def fake_sweep(asset_id, target_x, target_z, **_kwargs):
        return {
            "success": True,
            "reported_survivor_count": 2,
            "level_count": 3,
            "waypoint_count": 12,
            "unique_survivors_detected": [
                {"id": 1, "x": -15.0, "y": 3.0, "z": -20.0, "submerged": False},
                {"id": 2, "x": -15.0, "y": 1.0, "z": -20.0, "submerged": True},
            ],
        }

    with patch("backend.services.drone_control.sweep_scan_building", side_effect=fake_sweep):
        result = await parallel_fleet_scan(assignments)

    assert result["total_survivors"] == 2
    assert "AREA SCAN COMPLETE" in result["summary"]
    assert "TOTAL SURVIVORS DETECTED: 2" in result["summary"]
    assert "SUBMERGED — CRITICAL" in result["summary"]
    assert "CRITICAL: 1 submerged" in result["summary"]
```

---

## Verification

Run tests to confirm all 12 pass:

```bash
uv run pytest tests/test_fleet_orchestration.py -v
```

Expected output: **12 passed**.

---

## Edge Cases & Behaviour Summary

| Scenario | Behaviour |
|----------|-----------|
| 3 drones, 2 buildings | 2 closest assigned in parallel; 3rd stays idle |
| 1 drone, 3 buildings | 1 parallel scan + 2 sequential fallback (same drone) |
| All drones busy/low battery | Error returned; operator notified |
| No drones uplinked | `"No drones uplinked."` error |
| Explicit `"BEACON-01 scan X"` | Single-drone assignment, no fleet query (backward compatible) |
| One drone fails mid-scan | Others continue; failed building logged as error in report |
| `asset_id = "auto"` | Fleet assigner queries all IDLE drones, assigns by proximity |

## Key Design Notes

- **`asyncio.gather(return_exceptions=True)`** is critical — without it, one failure cancels all
- **`FunctionTool` not MCP** for fleet agents — avoids MCP 10s timeout during long parallel scans
- **Greedy nearest-first is O(N²)** but optimal for N ≤ 5 drones/buildings in practice
- **`ASSET_ID = 'BEACON-01'`** stays hardcoded in `SARScene.tsx` for manual/single-drone commands — only area scans override with `"auto"`
- **`AsyncMock` gotcha**: `AsyncMock()` makes ALL attributes async. Use `MagicMock()` + separate `AsyncMock` for `get_status` in tests
