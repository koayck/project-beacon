"""Unit tests for post-mission recall (schedule_mission_complete_recall).

Covers the grace-skip logic (new command during grace), home-pad short-circuit,
success + failure event emission, and the empty/invalid asset_ids guards.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.services.mission_recall import schedule_mission_complete_recall


@pytest.mark.asyncio
async def test_schedule_recall_emits_start_and_completion_events() -> None:
    events: list[dict] = []
    get_status = AsyncMock(
        return_value={
            "asset_id": "BEACON-01",
            "x": 10.0, "y": 5.0, "z": -15.0,  # not at home
            "battery": 42.0,
            "status": "IDLE",
        }
    )
    return_to_base = AsyncMock(return_value={"success": True})

    tasks = schedule_mission_complete_recall(
        ["BEACON-01"],
        get_status=get_status,
        return_to_base_fn=return_to_base,
        publish_event=events.append,
        grace_seconds=0.0,
        trigger_reason="scan_mission_complete",
    )
    await asyncio.gather(*tasks)

    event_names = [e.get("event") for e in events]
    assert event_names == ["auto_recall_started", "auto_recall_completed"]
    started = events[0]
    assert started["asset_id"] == "BEACON-01"
    assert started["battery"] == 42.0
    assert started["reason"] == "scan_mission_complete"
    assert "charging" in started["message"].lower()
    return_to_base.assert_awaited_once_with("BEACON-01")


@pytest.mark.asyncio
async def test_schedule_recall_skips_when_drone_not_idle_after_grace() -> None:
    """If a new command starts the drone moving during the grace window,
    the recall must not preempt it — no events, no return_to_base call."""
    events: list[dict] = []
    # Status reads MOVING by the time grace elapses (simulating operator follow-up).
    get_status = AsyncMock(
        return_value={
            "asset_id": "BEACON-01",
            "x": 0.0, "y": 5.0, "z": 0.0,
            "battery": 60.0,
            "status": "MOVING",
        }
    )
    return_to_base = AsyncMock()

    tasks = schedule_mission_complete_recall(
        ["BEACON-01"],
        get_status=get_status,
        return_to_base_fn=return_to_base,
        publish_event=events.append,
        grace_seconds=0.0,
    )
    await asyncio.gather(*tasks)

    return_to_base.assert_not_awaited()
    assert events == []


@pytest.mark.asyncio
async def test_schedule_recall_skips_when_drone_already_at_home() -> None:
    events: list[dict] = []
    get_status = AsyncMock(
        return_value={
            "asset_id": "BEACON-01",
            "x": 0.0, "y": 2.0, "z": 0.0,  # on the pad
            "battery": 88.0,
            "status": "IDLE",
        }
    )
    return_to_base = AsyncMock()

    tasks = schedule_mission_complete_recall(
        ["BEACON-01"],
        get_status=get_status,
        return_to_base_fn=return_to_base,
        publish_event=events.append,
        grace_seconds=0.0,
    )
    await asyncio.gather(*tasks)

    return_to_base.assert_not_awaited()
    assert events == []


@pytest.mark.asyncio
async def test_schedule_recall_emits_failure_event_when_rtb_raises() -> None:
    events: list[dict] = []
    get_status = AsyncMock(
        return_value={
            "asset_id": "BEACON-02",
            "x": 15.0, "y": 5.0, "z": 20.0,
            "battery": 35.0,
            "status": "IDLE",
        }
    )
    return_to_base = AsyncMock(side_effect=RuntimeError("grpc channel closed"))

    tasks = schedule_mission_complete_recall(
        ["BEACON-02"],
        get_status=get_status,
        return_to_base_fn=return_to_base,
        publish_event=events.append,
        grace_seconds=0.0,
    )
    await asyncio.gather(*tasks)

    event_names = [e.get("event") for e in events]
    assert event_names == ["auto_recall_started", "auto_recall_failed"]
    failed = events[-1]
    assert "grpc channel closed" in failed["error"]


@pytest.mark.asyncio
async def test_schedule_recall_deduplicates_and_ignores_empty_ids() -> None:
    events: list[dict] = []
    get_status = AsyncMock(
        return_value={
            "asset_id": "BEACON-01",
            "x": 10.0, "y": 5.0, "z": 10.0,
            "battery": 50.0,
            "status": "IDLE",
        }
    )
    return_to_base = AsyncMock(return_value={"success": True})

    tasks = schedule_mission_complete_recall(
        ["BEACON-01", "BEACON-01", "", None, "BEACON-02"],  # type: ignore[list-item]
        get_status=get_status,
        return_to_base_fn=return_to_base,
        publish_event=events.append,
        grace_seconds=0.0,
    )
    assert len(tasks) == 2  # BEACON-01 (deduped) and BEACON-02

    # No running loop → empty list.
    unique_names = {t.get_name() for t in tasks}
    assert any("BEACON-01" in n for n in unique_names)
    assert any("BEACON-02" in n for n in unique_names)

    await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_schedule_recall_publisher_exception_does_not_block_rtb() -> None:
    """A flaky publish_event must not prevent return_to_base from running."""
    def _flaky(_payload: dict) -> None:
        raise RuntimeError("publisher boom")

    get_status = AsyncMock(
        return_value={
            "asset_id": "BEACON-03",
            "x": 5.0, "y": 5.0, "z": 5.0,
            "battery": 25.0,
            "status": "IDLE",
        }
    )
    return_to_base = AsyncMock(return_value={"success": True})

    tasks = schedule_mission_complete_recall(
        ["BEACON-03"],
        get_status=get_status,
        return_to_base_fn=return_to_base,
        publish_event=_flaky,
        grace_seconds=0.0,
    )
    await asyncio.gather(*tasks)

    return_to_base.assert_awaited_once_with("BEACON-03")


@pytest.mark.asyncio
async def test_schedule_recall_grace_can_be_cancelled_cleanly() -> None:
    """Cancelling a scheduled task before grace elapses must not run recall."""
    get_status = AsyncMock()
    return_to_base = AsyncMock()

    tasks = schedule_mission_complete_recall(
        ["BEACON-04"],
        get_status=get_status,
        return_to_base_fn=return_to_base,
        publish_event=None,
        grace_seconds=5.0,
    )
    for task in tasks:
        task.cancel()

    # Await cancellation to clean up.
    await asyncio.gather(*tasks, return_exceptions=True)

    get_status.assert_not_awaited()
    return_to_base.assert_not_awaited()
