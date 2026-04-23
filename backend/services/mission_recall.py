"""Dispatch return-to-base for drones after a mission's task queue drains.

The battery-driven ``AutoRecallMonitor`` handles emergency recalls; this module
handles the routine post-mission housekeeping requested in the case-study
booklet (drones return for charging once the area scan / supply dispatch
completes). A short idle-grace window lets the operator chain follow-up
commands ("scan area, then supply survivors") without fighting a premature
recall mid-sequence.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_DEFAULT_GRACE_SECONDS = 10.0
# Home pad at (0, 2, 0); treat drones within ~2m of the pad footprint as already home.
_HOME_XZ_RADIUS_SQ_M = 4.0
_HOME_Y_TOLERANCE_M = 2.0


def _safe_emit(publish_event: Callable[[dict], None] | None, payload: dict) -> None:
    if publish_event is None:
        return
    try:
        publish_event(payload)
    except Exception:  # noqa: BLE001
        logger.exception("publish_event callback raised in mission_recall")


async def _grace_then_recall(
    asset_id: str,
    *,
    grace_seconds: float,
    get_status: Callable[[str], Awaitable[dict]],
    return_to_base_fn: Callable[[str], Awaitable[dict]],
    publish_event: Callable[[dict], None] | None,
    trigger_reason: str,
) -> None:
    """Wait out the grace window, then recall iff the drone is still idle.

    Skips the recall when:
      - Grace-window sleep is cancelled (caller aborted).
      - Drone moved to a non-IDLE state during grace (operator issued a new
        command; don't preempt it).
      - Drone is already within the home-pad footprint.
    """
    try:
        await asyncio.sleep(max(grace_seconds, 0.0))
    except asyncio.CancelledError:
        raise

    try:
        status = await get_status(asset_id)
    except Exception:  # noqa: BLE001
        logger.exception(
            "mission_recall: failed to read status for %s; skipping recall", asset_id,
        )
        return

    current_status = str(status.get("status", "")).upper()
    if current_status != "IDLE":
        logger.debug(
            "mission_recall skipped for %s — status=%s (new command during grace)",
            asset_id,
            current_status,
        )
        return

    try:
        x = float(status.get("x", 0.0))
        z = float(status.get("z", 0.0))
        y = float(status.get("y", 0.0))
    except (TypeError, ValueError):
        x, y, z = 0.0, 0.0, 0.0

    if (x * x + z * z) < _HOME_XZ_RADIUS_SQ_M and abs(y - 2.0) < _HOME_Y_TOLERANCE_M:
        logger.debug("mission_recall skipped for %s — already at base", asset_id)
        return

    battery_raw = status.get("battery")
    try:
        battery_value: float | None = float(battery_raw) if battery_raw is not None else None
    except (TypeError, ValueError):
        battery_value = None

    battery_text = f" ({battery_value:.1f}%)" if battery_value is not None else ""
    _safe_emit(
        publish_event,
        {
            "type": "system_event",
            "event": "auto_recall_started",
            "asset_id": asset_id,
            "battery": battery_value,
            "reason": trigger_reason,
            "message": f"{asset_id} mission complete{battery_text} — returning to base for charging",
        },
    )

    try:
        await return_to_base_fn(asset_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("mission_recall: return_to_base failed for %s", asset_id)
        _safe_emit(
            publish_event,
            {
                "type": "system_event",
                "event": "auto_recall_failed",
                "asset_id": asset_id,
                "battery": battery_value,
                "reason": trigger_reason,
                "error": f"{type(exc).__name__}: {exc}",
                "message": f"{asset_id} mission-complete recall failed",
            },
        )
        return

    _safe_emit(
        publish_event,
        {
            "type": "system_event",
            "event": "auto_recall_completed",
            "asset_id": asset_id,
            "battery": battery_value,
            "reason": trigger_reason,
            "message": f"{asset_id} returning to base for charging",
        },
    )


def schedule_mission_complete_recall(
    asset_ids: list[str],
    *,
    get_status: Callable[[str], Awaitable[dict]],
    return_to_base_fn: Callable[[str], Awaitable[dict]],
    publish_event: Callable[[dict], None] | None = None,
    grace_seconds: float = _DEFAULT_GRACE_SECONDS,
    trigger_reason: str = "mission_complete",
) -> list[asyncio.Task]:
    """Dispatch a per-drone grace-then-recall coroutine for each asset_id.

    Returns the created ``asyncio.Task`` handles. Duplicate asset_ids in the
    input are collapsed (order-preserving). When no running event loop exists
    (e.g. the caller is a sync tool invoked outside of the agent loop), an
    empty list is returned and a warning is logged — the mission still
    completes normally, just without automated recall.
    """
    unique_assets = [aid for aid in dict.fromkeys(asset_ids) if aid]
    if not unique_assets:
        return []

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning(
            "mission_recall: no running event loop; cannot schedule recall for %s",
            unique_assets,
        )
        return []

    tasks: list[asyncio.Task] = []
    for asset_id in unique_assets:
        task = loop.create_task(
            _grace_then_recall(
                asset_id,
                grace_seconds=grace_seconds,
                get_status=get_status,
                return_to_base_fn=return_to_base_fn,
                publish_event=publish_event,
                trigger_reason=trigger_reason,
            ),
            name=f"mission_recall:{asset_id}:{trigger_reason}",
        )
        tasks.append(task)
    return tasks
