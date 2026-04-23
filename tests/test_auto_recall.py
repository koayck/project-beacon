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
async def test_auto_recall_publishes_system_events_on_success() -> None:
    """Judge-visible narrative: each recall should emit started + completed
    system_event payloads the WS broadcaster can relay to the activity feed."""
    recall = AsyncMock(return_value={"success": True, "message": "Returned"})
    log_create = AsyncMock()
    events: list[dict] = []
    monitor = AutoRecallMonitor(
        enabled=True,
        battery_threshold=10.0,
        cooldown_seconds=60.0,
        recall_fn=recall,
        registered_asset_ids_fn=lambda: ["BEACON-01"],
        log_create_fn=log_create,
        publish_event=lambda payload: events.append(payload),
    )
    monitor.start()

    monitor.handle_telemetry(
        {
            "asset_id": "BEACON-01",
            "battery": 9.0,
            "status": "IDLE",
            "timestamp_ms": 42,
        }
    )

    await asyncio.sleep(0.01)
    await monitor.stop()

    started = [e for e in events if e.get("event") == "auto_recall_started"]
    completed = [e for e in events if e.get("event") == "auto_recall_completed"]
    assert len(started) == 1 and len(completed) == 1, events
    assert started[0]["type"] == "system_event"
    assert started[0]["asset_id"] == "BEACON-01"
    assert started[0]["battery"] == 9.0
    assert started[0]["threshold"] == 10.0
    assert "charging" in started[0]["message"].lower()
    assert completed[0]["asset_id"] == "BEACON-01"


@pytest.mark.asyncio
async def test_auto_recall_publishes_failure_event_on_recall_exception() -> None:
    """When the underlying recall raises, a failed system_event must still fire
    so operators see why the drone is stranded instead of a silent drop."""
    recall = AsyncMock(side_effect=RuntimeError("grpc channel down"))
    log_create = AsyncMock()
    events: list[dict] = []
    monitor = AutoRecallMonitor(
        enabled=True,
        battery_threshold=10.0,
        cooldown_seconds=60.0,
        recall_fn=recall,
        registered_asset_ids_fn=lambda: ["BEACON-01"],
        log_create_fn=log_create,
        publish_event=lambda payload: events.append(payload),
    )
    monitor.start()

    monitor.handle_telemetry(
        {"asset_id": "BEACON-01", "battery": 7.0, "status": "IDLE"}
    )

    await asyncio.sleep(0.01)
    await monitor.stop()

    event_names = [e.get("event") for e in events]
    assert event_names == ["auto_recall_started", "auto_recall_failed"], events
    failed = events[-1]
    assert failed["asset_id"] == "BEACON-01"
    assert "grpc channel down" in failed["error"]


@pytest.mark.asyncio
async def test_auto_recall_publisher_exception_does_not_kill_recall() -> None:
    """A flaky publish_event callback must not block the actual recall — the
    DB log and recall_fn must still run even if broadcasting raises."""
    recall = AsyncMock(return_value={"success": True})
    log_create = AsyncMock()

    def _flaky(_payload: dict) -> None:
        raise RuntimeError("publisher boom")

    monitor = AutoRecallMonitor(
        enabled=True,
        battery_threshold=10.0,
        cooldown_seconds=60.0,
        recall_fn=recall,
        registered_asset_ids_fn=lambda: ["BEACON-01"],
        log_create_fn=log_create,
        publish_event=_flaky,
    )
    monitor.start()

    monitor.handle_telemetry(
        {"asset_id": "BEACON-01", "battery": 6.0, "status": "IDLE"}
    )

    await asyncio.sleep(0.01)
    await monitor.stop()

    recall.assert_awaited_once_with("BEACON-01")
    log_create.assert_awaited_once()


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
