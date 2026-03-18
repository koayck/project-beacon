from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from backend.services.auto_recall import AutoRecallMonitor


@pytest.mark.asyncio
async def test_auto_recall_triggers_for_low_battery_idle_drone() -> None:
    recall = AsyncMock(return_value={"success": True, "message": "Returned"})
    log_create = AsyncMock()
    monitor = AutoRecallMonitor(
        enabled=True,
        battery_threshold=10.0,
        cooldown_seconds=60.0,
        recall_fn=recall,
        registered_asset_ids_fn=lambda: ["BEACON-01"],
        log_create_fn=log_create,
    )
    monitor.start()

    monitor.handle_telemetry(
        {
            "asset_id": "beacon-01",
            "battery": 9.5,
            "status": "IDLE",
            "timestamp_ms": 1234567890,
        }
    )

    await asyncio.sleep(0.01)
    await monitor.stop()

    recall.assert_awaited_once_with("BEACON-01")
    log_create.assert_awaited_once()
    log_entry = log_create.await_args.args[0]
    assert log_entry.command == "auto_recall"
    assert log_entry.asset_id == "BEACON-01"
    reason = json.loads(log_entry.params or "{}")
    assert reason["trigger"] == "battery_low_idle"
    assert reason["battery"] == 9.5


@pytest.mark.asyncio
async def test_auto_recall_skips_non_idle_or_healthy_drones() -> None:
    recall = AsyncMock()
    log_create = AsyncMock()
    monitor = AutoRecallMonitor(
        enabled=True,
        battery_threshold=10.0,
        cooldown_seconds=60.0,
        recall_fn=recall,
        registered_asset_ids_fn=lambda: ["BEACON-01"],
        log_create_fn=log_create,
    )
    monitor.start()

    monitor.handle_telemetry({"asset_id": "BEACON-01", "battery": 5.0, "status": "MOVING"})
    monitor.handle_telemetry({"asset_id": "BEACON-01", "battery": 55.0, "status": "IDLE"})
    monitor.handle_telemetry({"asset_id": "BEACON-02", "battery": 5.0, "status": "IDLE"})

    await asyncio.sleep(0.01)
    await monitor.stop()

    recall.assert_not_awaited()
    log_create.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_recall_deduplicates_within_cooldown() -> None:
    recall = AsyncMock(return_value={"success": True})
    log_create = AsyncMock()
    monitor = AutoRecallMonitor(
        enabled=True,
        battery_threshold=10.0,
        cooldown_seconds=300.0,
        recall_fn=recall,
        registered_asset_ids_fn=lambda: ["BEACON-01"],
        log_create_fn=log_create,
    )
    monitor.start()

    payload = {"asset_id": "BEACON-01", "battery": 8.0, "status": "IDLE"}
    monitor.handle_telemetry(payload)
    monitor.handle_telemetry(payload)

    await asyncio.sleep(0.01)
    await monitor.stop()

    assert recall.await_count == 1
    assert log_create.await_count == 1
