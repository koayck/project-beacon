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
