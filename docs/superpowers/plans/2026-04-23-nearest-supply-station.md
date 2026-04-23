# Nearest Supply Station Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the always-return-to-(0,0,0) pickup step in the supply workflow with a nearest-to-target selection over operator-placed supply stations plus a built-in home station.

**Architecture:** New backend module `backend/services/supply_stations.py` owns an in-memory station list (home baked in) and a deterministic nearest-by-target selector. Three REST routes (`GET/POST/DELETE /supply-stations`) expose the list to the frontend and broadcast create/remove events over the existing telemetry WebSocket. `dispatch_supply_to_building` calls the selector and routes the pickup leg via the chosen station instead of `return_to_base_fn`. Frontend adds a "Place Supply Station" toggle that enters a placement mode; clicks on valid ground call the POST endpoint; stations render as orange crate-stacks with a click-to-remove HUD.

**Tech Stack:** Python 3 / FastAPI / pytest (backend); Next.js / React / React Three Fiber / TypeScript (frontend).

**Design reference:** `docs/superpowers/specs/2026-04-23-nearest-supply-station-design.md`

---

## Task 1: Supply station registry module (TDD)

**Files:**
- Create: `backend/services/supply_stations.py`
- Test:   `tests/test_supply_stations.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_supply_stations.py`:

```python
"""Unit tests for the supply station registry and nearest-to-target selector."""
from __future__ import annotations

import pytest

from backend.services import supply_stations


@pytest.fixture(autouse=True)
def _reset_registry():
    supply_stations.reset()
    yield
    supply_stations.reset()


class TestRegistry:
    def test_list_defaults_to_home_only(self):
        stations = supply_stations.list_stations()
        assert len(stations) == 1
        assert stations[0]["id"] == "home"
        assert stations[0]["x"] == 0.0
        assert stations[0]["z"] == 0.0

    def test_add_station_returns_record_with_unique_id(self):
        a = supply_stations.add_station(x=20.0, z=5.0)
        b = supply_stations.add_station(x=-10.0, z=-30.0)
        assert a["x"] == 20.0 and a["z"] == 5.0
        assert b["x"] == -10.0 and b["z"] == -30.0
        assert a["id"] != b["id"]
        assert a["id"] != "home" and b["id"] != "home"

    def test_list_returns_home_plus_added_in_insertion_order(self):
        a = supply_stations.add_station(x=20.0, z=5.0)
        b = supply_stations.add_station(x=-10.0, z=-30.0)
        ids = [s["id"] for s in supply_stations.list_stations()]
        assert ids == ["home", a["id"], b["id"]]

    def test_remove_station_returns_true_when_found(self):
        a = supply_stations.add_station(x=20.0, z=5.0)
        assert supply_stations.remove_station(a["id"]) is True
        assert [s["id"] for s in supply_stations.list_stations()] == ["home"]

    def test_remove_station_returns_false_when_unknown(self):
        assert supply_stations.remove_station("does-not-exist") is False

    def test_remove_home_raises(self):
        with pytest.raises(ValueError):
            supply_stations.remove_station("home")


class TestPlacementValidation:
    def test_add_inside_building_raises(self, monkeypatch):
        class _FakeBuilding:
            pass

        class _FakeWorld:
            def building_at(self, x, y, z):
                # Any (x,z) pair here is treated as inside a building.
                return _FakeBuilding()

        monkeypatch.setattr(supply_stations, "_get_world", lambda: _FakeWorld())
        with pytest.raises(ValueError, match="inside building"):
            supply_stations.add_station(x=-15.0, z=-15.0)

    def test_add_out_of_bounds_raises(self):
        # Default WORLD_HALF_SPAN is 50.0. Anything strictly outside rejects.
        with pytest.raises(ValueError, match="out of bounds"):
            supply_stations.add_station(x=100.0, z=0.0)
        with pytest.raises(ValueError, match="out of bounds"):
            supply_stations.add_station(x=0.0, z=-100.0)


class TestSelectBestStation:
    def test_returns_home_when_no_user_stations(self):
        chosen = supply_stations.select_best_station(target_x=10.0, target_z=10.0)
        assert chosen["id"] == "home"

    def test_picks_station_closest_to_target(self):
        near = supply_stations.add_station(x=30.0, z=30.0)
        supply_stations.add_station(x=-30.0, z=-30.0)
        chosen = supply_stations.select_best_station(target_x=28.0, target_z=29.0)
        assert chosen["id"] == near["id"]

    def test_home_wins_when_target_closer_to_origin(self):
        supply_stations.add_station(x=45.0, z=45.0)
        chosen = supply_stations.select_best_station(target_x=1.0, target_z=1.0)
        assert chosen["id"] == "home"

    def test_deterministic_tiebreak_on_equal_distance(self):
        # Two user stations equidistant from target. Whichever tie-breaking
        # rule we pick must be stable across calls.
        a = supply_stations.add_station(x=10.0, z=0.0)
        b = supply_stations.add_station(x=-10.0, z=0.0)
        first = supply_stations.select_best_station(target_x=0.0, target_z=0.0)
        second = supply_stations.select_best_station(target_x=0.0, target_z=0.0)
        # Home is also equidistant (0), and comes first in the list, so it wins.
        assert first["id"] == "home"
        assert first["id"] == second["id"]
        # Sanity: user stations are in the pool but not chosen here.
        ids = {s["id"] for s in supply_stations.list_stations()}
        assert {a["id"], b["id"]} <= ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_supply_stations.py -v`
Expected: FAIL with ImportError on `backend.services.supply_stations`.

- [ ] **Step 3: Write minimal implementation**

Create `backend/services/supply_stations.py`:

```python
"""In-memory registry for supply stations and nearest-to-target selection.

Home base at (0,0,0) is a built-in, non-removable station. Additional stations
are placed at runtime via the REST API. Selection minimizes 2D Euclidean
distance from target to station. The first station in list order wins ties,
which means home (always first) wins ties at the origin.
"""
from __future__ import annotations

import math
import threading
from itertools import count
from typing import Iterable

HOME_STATION_ID = "home"
HOME_STATION: dict = {"id": HOME_STATION_ID, "x": 0.0, "z": 0.0}

# Placement validity bounds. World2 is a 100×100 grid centered at origin.
# A station must sit on walkable ground inside this square.
WORLD_HALF_SPAN = 50.0

_lock = threading.Lock()
_id_counter = count(1)
_user_stations: list[dict] = []


def _get_world():
    """Lazy import to avoid circular imports during test fixtures."""
    from backend.services.core import context as service_context
    return service_context.get_world()


def reset() -> None:
    """Clear all user-placed stations. Home remains. For tests / lifespan restart."""
    global _id_counter
    with _lock:
        _user_stations.clear()
        _id_counter = count(1)


def list_stations() -> list[dict]:
    """Return home followed by user-placed stations in insertion order."""
    with _lock:
        return [dict(HOME_STATION)] + [dict(s) for s in _user_stations]


def add_station(*, x: float, z: float) -> dict:
    """Validate and append a user-placed station.

    Raises:
        ValueError: If placement is out of bounds or inside a building.
    """
    if abs(x) > WORLD_HALF_SPAN or abs(z) > WORLD_HALF_SPAN:
        raise ValueError(f"Placement out of bounds: ({x}, {z})")

    world = _get_world()
    # y=0 samples the ground plane. building_at returns the containing building
    # (AABB hit) or None for open ground.
    if world.building_at(x, 0.0, z) is not None:
        raise ValueError(f"Placement inside building at ({x}, {z})")

    with _lock:
        station = {"id": f"station-{next(_id_counter)}", "x": float(x), "z": float(z)}
        _user_stations.append(station)
        return dict(station)


def remove_station(station_id: str) -> bool:
    """Remove a user-placed station. Returns False if not found.

    Raises:
        ValueError: If caller attempts to remove the built-in home station.
    """
    if station_id == HOME_STATION_ID:
        raise ValueError("Home station cannot be removed")
    with _lock:
        for i, station in enumerate(_user_stations):
            if station["id"] == station_id:
                _user_stations.pop(i)
                return True
    return False


def select_best_station(*, target_x: float, target_z: float) -> dict:
    """Return the station minimizing 2D Euclidean distance to (target_x, target_z).

    Home is always in the candidate pool, so the result is never None. Ties go
    to the earliest station in list order (home first, then insertion order).
    """
    candidates: Iterable[dict] = list_stations()
    best = min(
        candidates,
        key=lambda s: math.hypot(s["x"] - target_x, s["z"] - target_z),
    )
    return dict(best)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_supply_stations.py -v`
Expected: 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/services/supply_stations.py tests/test_supply_stations.py
git commit -m "feat(supply): add supply station registry with nearest-to-target selection"
```

---

## Task 2: REST + WebSocket API for stations

**Files:**
- Modify: `backend/services/api/control.py` — add thin wrappers
- Modify: `backend/services/api/__init__.py` — re-export new functions
- Modify: `backend/app.py` — register REST routes, broadcast WS events on mutation, reset registry in lifespan
- Test:   `tests/test_supply_station_routes.py`

### Step 1: Write the failing test

Create `tests/test_supply_station_routes.py`:

```python
"""Integration tests for /supply-stations REST endpoints + WS broadcast behavior."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.services import supply_stations


@pytest.fixture
def client(monkeypatch):
    # Replace the WS broadcaster with a stub so we can assert on broadcasts.
    broadcasts: list[dict] = []
    stub = MagicMock()
    stub.broadcast.side_effect = lambda payload: broadcasts.append(payload)
    monkeypatch.setattr("backend.app.ws_broadcaster", stub)

    supply_stations.reset()
    from backend.app import app
    with TestClient(app) as tc:
        tc.broadcasts = broadcasts  # type: ignore[attr-defined]
        yield tc
    supply_stations.reset()


class TestSupplyStationRoutes:
    def test_get_returns_only_home_by_default(self, client):
        resp = client.get("/supply-stations")
        assert resp.status_code == 200
        stations = resp.json()["stations"]
        assert [s["id"] for s in stations] == ["home"]

    def test_post_adds_station_and_broadcasts(self, client):
        resp = client.post("/supply-stations", json={"x": 20.0, "z": 5.0})
        assert resp.status_code == 200
        body = resp.json()
        assert body["station"]["x"] == 20.0
        assert body["station"]["z"] == 5.0
        assert body["station"]["id"].startswith("station-")

        assert client.broadcasts == [
            {"type": "supply_station_added", "station": body["station"]}
        ]

    def test_post_rejects_out_of_bounds_with_400(self, client):
        resp = client.post("/supply-stations", json={"x": 999.0, "z": 0.0})
        assert resp.status_code == 400
        assert "out of bounds" in resp.json()["detail"].lower()
        assert client.broadcasts == []

    def test_delete_removes_and_broadcasts(self, client):
        added = client.post("/supply-stations", json={"x": 1.0, "z": 2.0}).json()["station"]
        client.broadcasts.clear()

        resp = client.delete(f"/supply-stations/{added['id']}")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

        assert client.broadcasts == [
            {"type": "supply_station_removed", "id": added["id"]}
        ]

    def test_delete_home_returns_400(self, client):
        resp = client.delete("/supply-stations/home")
        assert resp.status_code == 400
        assert "home" in resp.json()["detail"].lower()
        assert client.broadcasts == []

    def test_delete_unknown_returns_404(self, client):
        resp = client.delete("/supply-stations/station-999")
        assert resp.status_code == 404
        assert client.broadcasts == []
```

### Step 2: Run test to verify it fails

Run: `uv run pytest tests/test_supply_station_routes.py -v`
Expected: FAIL with 404 on the routes.

### Step 3: Add control-layer wrappers

In `backend/services/api/control.py`, add (place near the other thin async wrappers, after `return_to_base`):

```python
from backend.services import supply_stations as _supply_stations_registry


def list_supply_stations() -> dict:
    """Return all known supply stations (home + user-placed)."""
    return {"stations": _supply_stations_registry.list_stations()}


def add_supply_station(x: float, z: float) -> dict:
    """Validate and append a user-placed station. Raises ValueError on invalid placement."""
    station = _supply_stations_registry.add_station(x=x, z=z)
    return {"station": station}


def remove_supply_station(station_id: str) -> dict:
    """Remove a user-placed station. Raises ValueError for 'home'. Returns {'ok': False} if unknown."""
    removed = _supply_stations_registry.remove_station(station_id)
    return {"ok": removed}
```

In `backend/services/api/__init__.py`, add the imports and re-exports:

```python
# Add to the import block:
from backend.services.api.control import (
    # ... existing imports ...
    add_supply_station,
    list_supply_stations,
    remove_supply_station,
)

# Add to __all__:
__all__ = [
    # ... existing entries ...
    "add_supply_station",
    "list_supply_stations",
    "remove_supply_station",
]
```

### Step 4: Register REST routes and lifespan reset

In `backend/app.py`:

1. Add imports at the top of the file near the other `backend.services.api` imports:

```python
from backend.services.api import (
    # ... existing imports ...
    add_supply_station,
    list_supply_stations,
    remove_supply_station,
)
from backend.services import supply_stations as _supply_stations_registry
```

2. Add a request model near the other `BaseModel` definitions:

```python
class SupplyStationCreateRequest(BaseModel):
    x: float
    z: float
```

3. Add the routes, placing them alongside the other `/fleet` / `/scout` routes:

```python
@app.get("/supply-stations")
async def get_supply_stations() -> dict:
    """Return all known supply stations (home + user-placed)."""
    return list_supply_stations()


@app.post("/supply-stations")
async def create_supply_station(req: SupplyStationCreateRequest) -> dict:
    """Place a new user station. 400 on invalid placement."""
    try:
        result = add_supply_station(x=req.x, z=req.z)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    ws_broadcaster.broadcast({"type": "supply_station_added", "station": result["station"]})
    return result


@app.delete("/supply-stations/{station_id}")
async def delete_supply_station(station_id: str) -> dict:
    """Remove a user station. 400 for 'home', 404 if unknown."""
    try:
        result = remove_supply_station(station_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result["ok"]:
        raise HTTPException(status_code=404, detail=f"Station {station_id} not found")
    ws_broadcaster.broadcast({"type": "supply_station_removed", "id": station_id})
    return {"ok": True}
```

4. In `app_lifespan`, reset the registry on startup (place next to the other reset/start calls). Insert after `await restore_registered_connections()`:

```python
    _supply_stations_registry.reset()
```

### Step 5: Run tests to verify they pass

Run: `uv run pytest tests/test_supply_station_routes.py -v`
Expected: 6 tests PASS.

### Step 6: Commit

```bash
git add backend/services/api/control.py backend/services/api/__init__.py backend/app.py tests/test_supply_station_routes.py
git commit -m "feat(supply): REST + WS API for placing and removing supply stations"
```

---

## Task 3: Route the supply workflow pickup leg through the chosen station

**Files:**
- Modify: `backend/services/workflows/supply_workflow.py:59-223` — replace the `return_to_base_fn` call with `_go_to_station`; add the helper.
- Test:   `tests/test_supply_workflow_station_pickup.py`

### Step 1: Write the failing test

Create `tests/test_supply_workflow_station_pickup.py`:

```python
"""Tests that dispatch_supply_to_building uses the nearest station for pickup."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services import supply_stations
from backend.services.workflows.supply_workflow import dispatch_supply_to_building


@pytest.fixture(autouse=True)
def _reset_registry():
    supply_stations.reset()
    yield
    supply_stations.reset()


def _make_world():
    world = MagicMock()
    world.building_at.return_value = None
    return world


def _make_async_kwargs(routes: list[dict] | None = None):
    """Shared kwargs for dispatch_supply_to_building in these tests."""
    # Return a successful 1-waypoint route for every plan_route_fn call.
    # The test inspects which target coordinates each call received.
    plan_route_calls: list[dict] = []

    async def _plan_route_fn(*, asset_id, target_x, target_z, target_y=None, snap_to_building_center=True):
        plan_route_calls.append(
            {"asset_id": asset_id, "target_x": target_x, "target_y": target_y, "target_z": target_z}
        )
        return {
            "waypoints": [{"x": float(target_x), "y": float(target_y or 5.0), "z": float(target_z)}],
            "to": {"x": float(target_x), "y": float(target_y or 5.0), "z": float(target_z)},
        }

    async def _move(*, asset_id, x, y, z):
        return {"success": True}

    async def _wait(*_args, **_kwargs):
        return {"ok": True}

    async def _status(_aid):
        return {"x": 0.0, "y": 2.0, "z": 0.0, "battery": 80.0, "status": "IDLE"}

    return {
        "plan_route_fn": _plan_route_fn,
        "move_drone_to_fn": _move,
        "wait_until_waypoint_reached_fn": _wait,
        "get_status_fn": _status,
        "plan_route_calls": plan_route_calls,
    }


@pytest.mark.asyncio
async def test_pickup_uses_home_when_no_user_stations():
    kwargs = _make_async_kwargs()
    return_to_base_fn = AsyncMock(return_value={"success": True})

    result = await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 1, "x": 20.0, "z": 20.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        return_to_base_fn=return_to_base_fn,
        plan_route_fn=kwargs["plan_route_fn"],
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    assert result.get("success") is True
    # First plan_route_fn call is the pickup leg, targeting home (0,0).
    pickup_call = kwargs["plan_route_calls"][0]
    assert pickup_call["target_x"] == 0.0
    assert pickup_call["target_z"] == 0.0
    # return_to_base_fn is NOT invoked — pickup now goes through the station planner.
    return_to_base_fn.assert_not_called()


@pytest.mark.asyncio
async def test_pickup_uses_nearest_user_station():
    supply_stations.add_station(x=18.0, z=18.0)
    kwargs = _make_async_kwargs()

    result = await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 2, "x": 20.0, "z": 20.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        return_to_base_fn=AsyncMock(return_value={"success": True}),
        plan_route_fn=kwargs["plan_route_fn"],
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    assert result.get("success") is True
    pickup_call = kwargs["plan_route_calls"][0]
    assert pickup_call["target_x"] == 18.0
    assert pickup_call["target_z"] == 18.0


@pytest.mark.asyncio
async def test_in_flight_dispatch_uses_captured_station_even_after_removal():
    """Station removed mid-flight does not affect an in-flight dispatch."""
    added = supply_stations.add_station(x=18.0, z=18.0)
    kwargs = _make_async_kwargs()

    # Remove the station BEFORE dispatch completes by simulating a removal
    # after select_best_station has captured it. We achieve this by wrapping
    # plan_route_fn so the first call triggers the removal synchronously.
    removal_triggered = False

    async def _plan_route_with_side_effect(**call_kwargs):
        nonlocal removal_triggered
        if not removal_triggered:
            supply_stations.remove_station(added["id"])
            removal_triggered = True
        return await kwargs["plan_route_fn"](**call_kwargs)

    result = await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 4, "x": 20.0, "z": 20.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        return_to_base_fn=AsyncMock(return_value={"success": True}),
        plan_route_fn=_plan_route_with_side_effect,
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    assert result.get("success") is True
    # First call still uses the captured station coords, not home.
    pickup_call = kwargs["plan_route_calls"][0]
    assert pickup_call["target_x"] == 18.0
    assert pickup_call["target_z"] == 18.0


@pytest.mark.asyncio
async def test_pickup_ignores_far_station_when_home_is_closer():
    supply_stations.add_station(x=45.0, z=45.0)
    kwargs = _make_async_kwargs()

    await dispatch_supply_to_building(
        asset_id="BEACON-01",
        building={"id": 3, "x": 2.0, "z": 2.0},
        resolve_scan_target=lambda x, z: {"building": None, "recommended_window_waypoint": None},
        world=_make_world(),
        window_scan_standoff_m=4.0,
        select_window_waypoint=lambda *a, **k: None,
        return_to_base_fn=AsyncMock(return_value={"success": True}),
        plan_route_fn=kwargs["plan_route_fn"],
        move_drone_to_fn=kwargs["move_drone_to_fn"],
        wait_until_waypoint_reached_fn=kwargs["wait_until_waypoint_reached_fn"],
        get_status_fn=kwargs["get_status_fn"],
    )

    pickup_call = kwargs["plan_route_calls"][0]
    assert pickup_call["target_x"] == 0.0
    assert pickup_call["target_z"] == 0.0
```

### Step 2: Run tests to verify they fail

Run: `uv run pytest tests/test_supply_workflow_station_pickup.py -v`
Expected: FAIL — today's code calls `return_to_base_fn` and routes to (0,0,0), so `return_to_base_fn.assert_not_called()` fails and the user-station test sees `target_x=0.0`.

### Step 3: Add the `_go_to_station` helper and replace the pickup call

In `backend/services/workflows/supply_workflow.py`:

1. Add the import near the top, with the other `backend.services.*` imports:

```python
from backend.services.supply_stations import select_best_station
```

2. Add the helper above `dispatch_supply_to_building`:

```python
async def _go_to_station(
    *,
    asset_id: str,
    station: dict,
    plan_route_fn: Callable[..., Awaitable[dict]],
    move_drone_to_fn: Callable[..., Awaitable[dict]],
    wait_until_waypoint_reached_fn: Callable[..., Awaitable[dict]],
) -> dict:
    """Route the drone to a supply station's (x, z) at pickup altitude.

    Uses the same move-and-wait pattern as the delivery leg, with a single
    high-altitude retry on initial route failure.
    """
    pickup_y = 2.0  # Matches the home-pad landing altitude used by return_workflow.

    route = await plan_route_fn(
        asset_id=asset_id,
        target_x=float(station["x"]),
        target_z=float(station["z"]),
        target_y=pickup_y,
        snap_to_building_center=False,
    )
    if "error" in route:
        retry_route = await plan_route_fn(
            asset_id=asset_id,
            target_x=float(station["x"]),
            target_z=float(station["z"]),
            target_y=max(pickup_y + 5.0, 15.0),
            snap_to_building_center=False,
        )
        if "error" in retry_route:
            return {
                "error": route["error"],
                "pickup_station": station,
                "route": route,
            }
        route = retry_route

    for index, waypoint in enumerate(route.get("waypoints", []), start=1):
        move_result = await move_drone_to_fn(
            asset_id=asset_id,
            x=float(waypoint["x"]),
            y=float(waypoint["y"]),
            z=float(waypoint["z"]),
        )
        if not move_result.get("success", True):
            return {
                "error": move_result.get("message", "Failed while moving on pickup route."),
                "pickup_station": station,
                "waypoint": waypoint,
                "move_result": move_result,
            }

        wait_result = await wait_until_waypoint_reached_fn(
            asset_id,
            float(waypoint["x"]),
            float(waypoint["y"]),
            float(waypoint["z"]),
            timeout_s=90.0,
            poll_s=0.2,
        )
        if not wait_result.get("ok", False):
            return {
                "error": wait_result.get("error", "Pickup waypoint not reached."),
                "pickup_station": station,
                "waypoint": waypoint,
                "failed_waypoint_index": index,
                "status": wait_result.get("status"),
            }

    return {"success": True, "pickup_station": station}
```

3. In `dispatch_supply_to_building`, replace the `return_to_base_fn` block. Find lines equivalent to:

```python
        to_base = await return_to_base_fn(asset_id)
        if "error" in to_base:
            return {
                "asset_id": asset_id,
                "error": f"Failed to return to base before supply dispatch: {to_base['error']}",
                "building": building,
                "return_result": to_base,
            }
```

Replace with:

```python
        station = select_best_station(target_x=drop_x, target_z=drop_z)
        pickup_result = await _go_to_station(
            asset_id=asset_id,
            station=station,
            plan_route_fn=plan_route_fn,
            move_drone_to_fn=move_drone_to_fn,
            wait_until_waypoint_reached_fn=wait_until_waypoint_reached_fn,
        )
        if "error" in pickup_result:
            return {
                "asset_id": asset_id,
                "error": f"Failed to reach supply station before dispatch: {pickup_result['error']}",
                "building": building,
                "pickup_station": station,
                "pickup_result": pickup_result,
            }
```

4. Include the chosen station in the success return so the caller can log it. Find the existing success return at the end of `dispatch_supply_to_building` and add `"pickup_station": station,` to its dict.

The `return_to_base_fn` parameter stays on the signature (see spec decision — kept for v1 to minimize diff).

### Step 4: Run the new test plus the existing workflow tests

Run: `uv run pytest tests/test_supply_workflow_station_pickup.py tests/test_supply_workflow.py -v`

Expected: all 4 new tests PASS. The existing `tests/test_supply_workflow.py` may have assertions that assumed `return_to_base_fn` was called — if so, update those tests to assert on the pickup-leg instead. Do **not** weaken assertions; replace them with equivalent checks against the new station-based flow.

### Step 5: Commit

```bash
git add backend/services/workflows/supply_workflow.py tests/test_supply_workflow_station_pickup.py tests/test_supply_workflow.py
git commit -m "feat(supply): route pickup leg through nearest station, replacing return-to-base"
```

---

## Task 4: Frontend — API + WS wiring for stations

**Files:**
- Modify: `frontend/src/lib/api.ts` — add `SupplyStation` type + 3 fetch helpers
- Modify: `frontend/src/lib/ws.ts` — handle `supply_station_added` / `supply_station_removed` events

### Step 1: Add types and fetch helpers

In `frontend/src/lib/api.ts`, add near the other interfaces:

```typescript
export interface SupplyStation {
  id: string
  x: number
  z: number
}
```

Add these exported functions near the other REST helpers:

```typescript
export async function fetchSupplyStations(): Promise<SupplyStation[]> {
  const res = await fetch(`${BASE}/supply-stations`)
  if (!res.ok) throw new Error(`Supply-stations fetch failed: ${res.status}`)
  const body: { stations: SupplyStation[] } = await res.json()
  return body.stations
}

export async function placeSupplyStation(x: number, z: number): Promise<SupplyStation> {
  const res = await fetch(`${BASE}/supply-stations`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ x, z }),
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`Place station failed: ${res.status} ${detail}`)
  }
  const body: { station: SupplyStation } = await res.json()
  return body.station
}

export async function removeSupplyStation(id: string): Promise<void> {
  const res = await fetch(`${BASE}/supply-stations/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`Remove station failed: ${res.status}`)
}
```

### Step 2: Extend the WS event union

In `frontend/src/lib/ws.ts`, add new event types to the module's public surface. The current hook returns telemetry/exploration only and funnels non-telemetry events through `onSystemEvent`. Add a parallel callback for station events so stations land in a clean, typed stream.

Add near the top:

```typescript
import type { SupplyStation } from './api'

export type SupplyStationEvent =
  | { type: 'supply_station_added'; station: SupplyStation }
  | { type: 'supply_station_removed'; id: string }
```

Extend the hook's options. Update the `useTelemetry` signature:

```typescript
export function useTelemetry(
  url: string,
  onSystemEvent?: (event: SystemEvent) => void,
  onSupplyStationEvent?: (event: SupplyStationEvent) => void,
): { ... }
```

Inside `useTelemetry`, add a ref for the new callback (mirroring the pattern used for `onSystemEvent`), and in the `onmessage` handler, after the `system_event` block and before the telemetry fallthrough:

```typescript
          if (raw.type === 'supply_station_added' || raw.type === 'supply_station_removed') {
            onSupplyStationEventRef.current?.(raw as SupplyStationEvent)
            return
          }
```

### Step 3: Verify the TypeScript compiles

Run: `cd frontend && npm run build`
Expected: build succeeds with no type errors.

### Step 4: Commit

```bash
git add frontend/src/lib/api.ts frontend/src/lib/ws.ts
git commit -m "feat(supply): frontend API + WS wiring for supply station events"
```

---

## Task 5: Frontend — SupplyStations R3F renderer

**Files:**
- Create: `frontend/src/components/scene-props/SupplyStations.tsx`

### Step 1: Create the component

```typescript
'use client'

import { useFrame } from '@react-three/fiber'
import { useMemo, useRef } from 'react'
import * as THREE from 'three'
import type { SupplyStation } from '../../lib/api'

interface SupplyStationsProps {
  stations: SupplyStation[]
  selectedId: string | null
  onSelect: (id: string | null) => void
}

export function SupplyStations({ stations, selectedId, onSelect }: SupplyStationsProps) {
  // Home station is rendered separately by BasePad; filter it out here.
  const userStations = useMemo(
    () => stations.filter(s => s.id !== 'home'),
    [stations],
  )
  const haloRefs = useRef<Map<string, THREE.Mesh>>(new Map())

  useFrame(({ clock }) => {
    const t = clock.elapsedTime
    haloRefs.current.forEach(mesh => {
      const mat = mesh.material as THREE.MeshBasicMaterial
      mat.opacity = 0.2 + 0.15 * Math.abs(Math.sin(t * 1.4))
    })
  })

  if (userStations.length === 0) return null

  return (
    <group>
      {userStations.map(s => {
        const isSelected = s.id === selectedId
        return (
          <group
            key={s.id}
            position={[s.x, 0, s.z]}
            onClick={e => {
              e.stopPropagation()
              onSelect(isSelected ? null : s.id)
            }}
          >
            {/* Lower crate */}
            <mesh position={[0, 0.4, 0]} castShadow>
              <boxGeometry args={[1.4, 0.8, 1.4]} />
              <meshStandardMaterial
                color="#ff8800"
                emissive={isSelected ? '#ffdd55' : '#cc5500'}
                emissiveIntensity={isSelected ? 0.9 : 0.45}
              />
            </mesh>
            {/* Upper crate */}
            <mesh position={[0, 1.2, 0]} castShadow>
              <boxGeometry args={[1.1, 0.6, 1.1]} />
              <meshStandardMaterial
                color="#ff8800"
                emissive={isSelected ? '#ffdd55' : '#cc5500'}
                emissiveIntensity={isSelected ? 0.9 : 0.45}
              />
            </mesh>
            {/* Pulsing halo ring at ground level */}
            <mesh
              ref={mesh => {
                if (mesh) haloRefs.current.set(s.id, mesh)
                else haloRefs.current.delete(s.id)
              }}
              rotation={[-Math.PI / 2, 0, 0]}
              position={[0, 0.02, 0]}
            >
              <ringGeometry args={[1.6, 2.1, 32]} />
              <meshBasicMaterial color="#ff8800" transparent opacity={0.25} />
            </mesh>
          </group>
        )
      })}
    </group>
  )
}
```

### Step 2: Verify the frontend builds

Run: `cd frontend && npm run build`
Expected: build succeeds.

### Step 3: Commit

```bash
git add frontend/src/components/scene-props/SupplyStations.tsx
git commit -m "feat(supply): add SupplyStations R3F component for user-placed stations"
```

---

## Task 6: Frontend — placement mode ghost preview

**Files:**
- Create: `frontend/src/components/scene-props/StationGhost.tsx`

### Step 1: Create the ghost preview

```typescript
'use client'

import { useMemo } from 'react'
import * as THREE from 'three'

interface StationGhostProps {
  position: THREE.Vector3 | null
  valid: boolean
}

/**
 * Semi-transparent placement preview that follows the cursor while the
 * operator is in station-placement mode. Green = valid, red = invalid.
 */
export function StationGhost({ position, valid }: StationGhostProps) {
  const color = valid ? '#33ff66' : '#ff3344'
  const emissive = useMemo(() => new THREE.Color(color), [color])

  if (!position) return null

  return (
    <group position={[position.x, 0, position.z]}>
      <mesh position={[0, 0.4, 0]}>
        <boxGeometry args={[1.4, 0.8, 1.4]} />
        <meshStandardMaterial
          color={color}
          emissive={emissive}
          emissiveIntensity={0.5}
          transparent
          opacity={0.5}
        />
      </mesh>
      <mesh position={[0, 1.2, 0]}>
        <boxGeometry args={[1.1, 0.6, 1.1]} />
        <meshStandardMaterial
          color={color}
          emissive={emissive}
          emissiveIntensity={0.5}
          transparent
          opacity={0.5}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.02, 0]}>
        <ringGeometry args={[1.6, 2.1, 32]} />
        <meshBasicMaterial color={color} transparent opacity={0.35} />
      </mesh>
    </group>
  )
}
```

### Step 2: Verify build

Run: `cd frontend && npm run build`
Expected: succeeds.

### Step 3: Commit

```bash
git add frontend/src/components/scene-props/StationGhost.tsx
git commit -m "feat(supply): add StationGhost placement preview"
```

---

## Task 7: Frontend — wire stations + placement mode into the scene

**Files:**
- Modify: `frontend/src/components/scene.tsx`
- Modify: `frontend/src/components/panels/Controls.tsx` — add a `[Place Supply Station]` toggle button
- Modify: `frontend/src/components/scene.tsx` — state for placement mode, validity check, click handlers, remove HUD

### Step 1: Add a "place station" toggle to the Controls panel

In `frontend/src/components/panels/Controls.tsx`, add to `ControlsProps`:

```typescript
  placingStation: boolean
  onTogglePlaceStation: () => void
```

Destructure the new props in the function signature and render a new button in the same row as the existing toggles:

```tsx
        <button
          onClick={onTogglePlaceStation}
          className={buttonClass(
            placingStation,
            'border-[#ff8800] bg-[rgba(255,136,0,0.18)] text-[#ffaa55]',
            'border-[rgba(40,60,100,0.25)] bg-[rgba(10,14,24,0.6)] text-[#7a8a9a]',
          )}
          title="Click the ground to place a supply station"
        >
          {placingStation ? 'PLACING…  Esc' : '+ STATION'}
        </button>
```

### Step 2: Add placement state and hydration in `scene.tsx`

At the top of `SARScene`, near the existing `useState` calls, add:

```typescript
import {
  // existing imports…
  fetchSupplyStations,
  placeSupplyStation,
  removeSupplyStation,
  type SupplyStation,
} from '../lib/api'
import type { SupplyStationEvent } from '../lib/ws'
import { SupplyStations } from './scene-props/SupplyStations'
import { StationGhost } from './scene-props/StationGhost'
```

Add state:

```typescript
const [stations, setStations] = useState<SupplyStation[]>([])
const [placingStation, setPlacingStation] = useState(false)
const [selectedStationId, setSelectedStationId] = useState<string | null>(null)
const [ghostPos, setGhostPos] = useState<THREE.Vector3 | null>(null)
```

Hydrate on mount:

```typescript
useEffect(() => {
  fetchSupplyStations()
    .then(setStations)
    .catch(err => console.warn('supply stations hydrate failed', err))
}, [])
```

Handle WS events — pass a callback into `useTelemetry` (wherever that hook is called in `scene.tsx`):

```typescript
const onSupplyStationEvent = useCallback((e: SupplyStationEvent) => {
  if (e.type === 'supply_station_added') {
    setStations(prev => (prev.some(s => s.id === e.station.id) ? prev : [...prev, e.station]))
  } else {
    setStations(prev => prev.filter(s => s.id !== e.id))
    setSelectedStationId(sel => (sel === e.id ? null : sel))
  }
}, [])

// Then pass as third arg to the existing useTelemetry call:
// const { drones, ... } = useTelemetry(wsUrl, onSystemEvent, onSupplyStationEvent)
```

### Step 3: Validity check + placement handlers

Add near the other helpers inside `SARScene`:

```typescript
const WORLD_HALF_SPAN = 50.0

const isValidStationPosition = useCallback(
  (pt: THREE.Vector3) => {
    if (Math.abs(pt.x) > WORLD_HALF_SPAN || Math.abs(pt.z) > WORLD_HALF_SPAN) return false
    // Mirror backend check: reject points inside any building footprint.
    // SimBuilding stores center + size, not min/max bounds.
    for (const b of simBuildings) {
      const halfW = b.w / 2
      const halfD = b.d / 2
      if (
        pt.x >= b.cx - halfW && pt.x <= b.cx + halfW &&
        pt.z >= b.cz - halfD && pt.z <= b.cz + halfD
      ) return false
    }
    return true
  },
  [simBuildings],
)

const handleGroundHover = useCallback(
  (pt: THREE.Vector3 | null) => {
    setHoverPt(pt)
    if (placingStation) setGhostPos(pt)
  },
  [placingStation],
)

const handlePlacementClick = useCallback(
  async (pt: THREE.Vector3) => {
    if (!placingStation) return
    if (!isValidStationPosition(pt)) return
    try {
      await placeSupplyStation(pt.x, pt.z)
      // WS event will update state; no local append needed.
    } catch (err) {
      console.warn('place station failed', err)
    }
  },
  [placingStation, isValidStationPosition],
)

const handleRemoveSelected = useCallback(
  async () => {
    if (!selectedStationId) return
    try {
      await removeSupplyStation(selectedStationId)
    } catch (err) {
      console.warn('remove station failed', err)
    }
  },
  [selectedStationId],
)

useEffect(() => {
  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      setPlacingStation(false)
      setGhostPos(null)
      setSelectedStationId(null)
    }
  }
  window.addEventListener('keydown', onKey)
  return () => window.removeEventListener('keydown', onKey)
}, [])
```

### Step 4: Wire GroundProbe + render stations

Find the existing `<GroundProbe ... onMove={setHoverPt} onDoubleClick={handleGroundClick} />` and update it to forward hover + a single-click handler:

```tsx
<GroundProbe
  worldSpan={worldSpan}
  onMove={handleGroundHover}
  onDoubleClick={handleGroundClick}
  onClick={placingStation ? handlePlacementClick : undefined}
/>
```

If `GroundProbe` does not currently accept `onClick`, add it alongside `onDoubleClick` — the existing double-click handler stays intact. Find the component definition and extend its props.

Add the renderer just before `<SupplyCrates ...>` in the scene JSX:

```tsx
<SupplyStations
  stations={stations}
  selectedId={selectedStationId}
  onSelect={setSelectedStationId}
/>
{placingStation && (
  <StationGhost
    position={ghostPos}
    valid={ghostPos ? isValidStationPosition(ghostPos) : false}
  />
)}
```

Pass the new props to `Controls`:

```tsx
<Controls
  // existing props…
  placingStation={placingStation}
  onTogglePlaceStation={() => {
    setPlacingStation(v => !v)
    setGhostPos(null)
  }}
/>
```

### Step 5: Add the remove HUD

Outside the `<Canvas>` (next to the other overlay panels), render a floating HUD when a station is selected:

```tsx
{selectedStationId && (() => {
  const s = stations.find(st => st.id === selectedStationId)
  if (!s) return null
  return (
    <div className="pointer-events-auto absolute bottom-28 left-1/2 z-30 -translate-x-1/2 rounded border border-[rgba(255,136,0,0.4)] bg-[rgba(18,12,4,0.92)] px-3 py-2 font-mono text-xs text-[#ffaa55] shadow-lg">
      <div className="mb-1.5 text-[11px] tracking-[0.8px] text-[#ff9933]">
        STATION @ ({s.x.toFixed(1)}, {s.z.toFixed(1)})
      </div>
      <div className="flex gap-2">
        <button
          onClick={handleRemoveSelected}
          className="rounded border border-[#ff5544] bg-[rgba(80,20,10,0.7)] px-2 py-1 text-[#ff8877] hover:bg-[rgba(120,30,15,0.85)]"
        >
          REMOVE
        </button>
        <button
          onClick={() => setSelectedStationId(null)}
          className="rounded border border-[rgba(100,120,140,0.35)] bg-[rgba(15,20,30,0.75)] px-2 py-1 text-[#9aabbc] hover:bg-[rgba(25,30,45,0.9)]"
        >
          CANCEL
        </button>
      </div>
    </div>
  )
})()}
```

### Step 6: Verify build and type-check

Run: `cd frontend && npm run build`
Expected: build succeeds with no type errors.

### Step 7: Smoke-test in the browser

Run the backend (`uv run python -m backend.app`) and frontend (`cd frontend && npm run dev`). In the browser:

1. Click `+ STATION` on the Controls panel. Button highlights, cursor mode activates.
2. Hover ground — green crate ghost follows cursor.
3. Hover a building — ghost turns red, can't place.
4. Click valid ground — station materializes (orange crate stack with pulsing halo).
5. Click the station — REMOVE/CANCEL HUD appears.
6. Click REMOVE — station disappears.
7. Place 2 stations. Send a supply command through the existing command box targeting a survivor near one of them — watch the drone's pickup leg go to that station instead of (0,0,0).

If all 7 steps work cleanly, the feature is a keep. If steps 1–6 feel clunky, invoke the fallback plan from the spec (drop placement UI, hardcode stations in `World2Data.ts`).

### Step 8: Commit

```bash
git add frontend/src/components/scene.tsx frontend/src/components/panels/Controls.tsx
git commit -m "feat(supply): click-to-place supply stations with ghost preview and remove HUD"
```

---

## Self-Review Notes

- **Spec coverage check:** Backend module (Task 1), REST+WS API (Task 2), workflow integration (Task 3), frontend API/WS (Task 4), station renderer (Task 5), ghost preview (Task 6), scene wiring + remove HUD (Task 7). Every file listed in the spec's "Affected Files" section appears in at least one task. Deferred items (capacity, persistence, LLM placement, pickup animation) are not in scope, matching the spec.
- **Fallback plan:** The "click-to-place feels clunky" fallback from the spec is surfaced in Task 7 Step 7. If triggered, the work to revert is deleting Tasks 6-7 changes and adding a seeded list in `World2Data.ts` — backend stays identical.
- **`return_to_base_fn` parameter retention:** Kept on `dispatch_supply_to_building`'s signature per spec decision. Task 3 Step 4 notes that existing tests in `tests/test_supply_workflow.py` may need updating to match the new pickup flow, but the parameter's presence keeps the diff minimal.
