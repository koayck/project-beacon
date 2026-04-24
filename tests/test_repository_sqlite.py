"""Integration tests for the SQLite-backed repository layer.

Each test gets an isolated temp database created via the `fresh_db` fixture.
No Postgres instance is required.
"""
from __future__ import annotations

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.db.models import Asset, LicenseRecord, MissionLog, MissionRun
from backend.db.repository import (
    asset_repo,
    init_db,
    license_repo,
    mission_log_repo,
    mission_run_repo,
)
from backend.services.simulation_store import SimulationStore


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test an isolated SQLite database with schema applied."""
    monkeypatch.setenv("BEACON_DB_PATH", str(tmp_path / "test.db"))
    await init_db()


# ── AssetRepository ───────────────────────────────────────────────────────────


async def test_asset_upsert_get_list_delete() -> None:
    asset = Asset(asset_id="BEACON-01", asset_class="scout_quadcopter", grpc_host="127.0.0.1", grpc_port=50051)

    await asset_repo.upsert(asset)

    fetched = await asset_repo.get("BEACON-01")
    assert fetched is not None
    assert fetched.asset_id == "BEACON-01"
    assert fetched.grpc_port == 50051

    assets = await asset_repo.list_all()
    assert len(assets) == 1

    # Upsert again with updated port — should overwrite.
    asset2 = Asset(asset_id="BEACON-01", asset_class="scout_quadcopter", grpc_host="127.0.0.1", grpc_port=50099)
    await asset_repo.upsert(asset2)
    updated = await asset_repo.get("BEACON-01")
    assert updated is not None
    assert updated.grpc_port == 50099

    await asset_repo.delete("BEACON-01")
    assert await asset_repo.get("BEACON-01") is None
    assert await asset_repo.list_all() == []


# ── MissionLogRepository ──────────────────────────────────────────────────────


async def test_mission_log_create_and_list_for_asset() -> None:
    log1 = MissionLog(asset_id="BEACON-01", command="scan", params=None, result="ok")
    log2 = MissionLog(asset_id="BEACON-01", command="move", params='{"x":1}', result="done")
    log3 = MissionLog(asset_id="BEACON-02", command="scan", params=None, result="ok")

    await mission_log_repo.create(log1)
    await mission_log_repo.create(log2)
    await mission_log_repo.create(log3)

    logs = await mission_log_repo.list_for_asset("BEACON-01")
    assert len(logs) == 2
    # Most recent first.
    assert logs[0].command == "move"
    assert logs[1].command == "scan"

    other_logs = await mission_log_repo.list_for_asset("BEACON-02")
    assert len(other_logs) == 1


# ── LicenseRepository ─────────────────────────────────────────────────────────


async def test_license_insert_get_by_key_get_active_deactivate() -> None:
    record = LicenseRecord(
        license_key="BEACON-AAAA-BBBB-CCCC-DDDD",
        org_name="Test Org",
        expiry_date="2027-12-31",
        seat_count=5,
    )

    # No active license yet.
    assert await license_repo.get_active() is None

    await license_repo.insert(record)

    fetched = await license_repo.get_by_key("BEACON-AAAA-BBBB-CCCC-DDDD")
    assert fetched is not None
    assert fetched.org_name == "Test Org"
    assert fetched.seat_count == 5
    assert fetched.is_active is True

    active = await license_repo.get_active()
    assert active is not None
    assert active.license_key == "BEACON-AAAA-BBBB-CCCC-DDDD"

    await license_repo.deactivate("BEACON-AAAA-BBBB-CCCC-DDDD")

    deactivated = await license_repo.get_by_key("BEACON-AAAA-BBBB-CCCC-DDDD")
    assert deactivated is not None
    assert deactivated.is_active is False
    assert await license_repo.get_active() is None


# ── MissionRunRepository ──────────────────────────────────────────────────────


async def test_mission_run_create_list_overview() -> None:
    now = datetime.now(timezone.utc)

    run = MissionRun(
        asset_id="BEACON-01",
        prompt="scan building A",
        status="success",
        started_at=now,
        ended_at=now,
        duration_ms=2000,
        ttft_ms=150,
        tool_call_count=3,
        survivors_detected=2,
        survivors_rescued=2,
        langfuse_trace_id="trace-abc",
    )
    row_id = await mission_run_repo.create(run)
    assert row_id > 0

    rows = await mission_run_repo.list_recent(limit=10)
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].langfuse_trace_id == "trace-abc"

    overview = await mission_run_repo.overview()
    assert overview["total_missions"] == 1
    assert overview["total_survivors_rescued"] == 2
    assert isinstance(overview["rescue_success_rate"], float)


# ── SimulationStore ───────────────────────────────────────────────────────────
# The `fresh_db` fixture (autouse) already sets BEACON_DB_PATH and calls init_db(),
# so SimulationStore() with no explicit path picks up the same temp SQLite file.


async def test_simulation_store_create_mark_scanned_merge() -> None:
    store = SimulationStore()

    sim_id = await store.create("test-sim-1")
    assert sim_id == "test-sim-1"

    await store.mark_buildings_scanned("test-sim-1", [3, 7])

    snapshot = await store.get("test-sim-1")
    assert snapshot is not None
    scanned_ids = {b["building_id"] for b in snapshot["scanned_buildings"]}
    assert scanned_ids == {3, 7}

    already = await store.get_already_scanned_buildings("test-sim-1", [3, 7, 9])
    assert sorted(already) == [3, 7]

    # Merge survivors.
    scanned_with_survivors = [
        {"building_id": 3, "detected_survivors": [{"x": 1.0, "y": 2.0, "z": 3.0, "supplied": False}]}
    ]
    merged = await store.merge_survivor_state("test-sim-1", scanned_with_survivors)
    assert merged["scanned_buildings"] is not None
    b3 = next(b for b in merged["scanned_buildings"] if b["building_id"] == 3)
    assert len(b3["detected_survivors"]) == 1
