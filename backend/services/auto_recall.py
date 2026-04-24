from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable

from backend.db.models import MissionLog
from backend.db.repository import mission_log_repo
from backend.runtime import grpc_client
from backend.services.api import return_to_base

logger = logging.getLogger(__name__)


class AutoRecallMonitor:
    """Telemetry-driven monitor that auto-recalls low-battery idle drones.

    When configured with a ``publish_event`` callback, each recall emits
    structured ``system_event`` payloads (started / completed / failed) that
    the broadcaster relays to the frontend activity feed. Without the hook
    the monitor behaves identically to before — the DB mission_log row is
    still written either way.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        battery_threshold: float = 25.0,
        cooldown_seconds: float = 60.0,
        recall_fn: Callable[[str], Awaitable[dict]] = return_to_base,
        registered_asset_ids_fn: Callable[[], list[str]] = grpc_client.registered_asset_ids,
        log_create_fn: Callable[[MissionLog], Awaitable[None]] = mission_log_repo.create,
        publish_event: Callable[[dict], None] | None = None,
    ) -> None:
        self._enabled = enabled
        self._battery_threshold = battery_threshold
        self._cooldown_seconds = cooldown_seconds
        self._recall_fn = recall_fn
        self._registered_asset_ids_fn = registered_asset_ids_fn
        self._log_create_fn = log_create_fn
        self._publish_event = publish_event

        self._running = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._inflight: set[str] = set()
        self._last_triggered: dict[str, float] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    def _emit(self, payload: dict) -> None:
        """Safely invoke the publish_event hook; never let it kill the monitor."""
        if self._publish_event is None:
            return
        try:
            self._publish_event(payload)
        except Exception:  # noqa: BLE001
            logger.exception("publish_event callback raised; continuing")

    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._running = True

    async def stop(self) -> None:
        self._running = False
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._inflight.clear()

    def handle_telemetry(self, payload: dict) -> None:
        if not self._running or not self._enabled:
            return

        asset_id = payload.get("asset_id")
        try:
            asset_id = asset_id.strip()
        except AttributeError:
            return
        if not asset_id:
            return
        asset_id = asset_id.upper()

        status = payload.get("status")
        try:
            is_idle = status == "IDLE"
        except Exception:
            return
        if not is_idle:
            return

        battery_raw = payload.get("battery")
        try:
            battery = float(battery_raw)
        except (TypeError, ValueError):
            return
        if battery > self._battery_threshold:
            return

        registered = {aid.upper() for aid in self._registered_asset_ids_fn()}
        if asset_id not in registered:
            return

        now = time.monotonic()
        if asset_id in self._inflight:
            return
        last = self._last_triggered.get(asset_id)
        if last is not None and now - last < self._cooldown_seconds:
            return

        self._last_triggered[asset_id] = now
        self._inflight.add(asset_id)
        reason = {
            "trigger": "battery_low_idle",
            "battery": battery,
            "status": status,
            "threshold": self._battery_threshold,
            "timestamp_ms": payload.get("timestamp_ms"),
        }
        task = (self._loop or asyncio.get_running_loop()).create_task(
            self._execute_auto_recall(asset_id, reason)
        )
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)

    def _on_task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.exception("Auto recall task failed", exc_info=exc)

    async def _execute_auto_recall(self, asset_id: str, reason: dict) -> None:
        battery = reason.get("battery")
        self._emit(
            {
                "type": "system_event",
                "event": "auto_recall_started",
                "asset_id": asset_id,
                "battery": battery,
                "threshold": self._battery_threshold,
                "reason": "battery_low",
                "message": (
                    f"{asset_id} battery {battery:.1f}% — auto-recalling for charging"
                    if isinstance(battery, (int, float))
                    else f"{asset_id} — auto-recalling for charging"
                ),
            }
        )
        try:
            result = await self._recall_fn(asset_id)
            await self._log_create_fn(
                MissionLog(
                    asset_id=asset_id,
                    command="auto_recall",
                    params=json.dumps(reason),
                    result=json.dumps(result),
                )
            )
            self._emit(
                {
                    "type": "system_event",
                    "event": "auto_recall_completed",
                    "asset_id": asset_id,
                    "battery": battery,
                    "message": f"{asset_id} returning to base for charging",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Auto recall failed for %s", asset_id)
            try:
                await self._log_create_fn(
                    MissionLog(
                        asset_id=asset_id,
                        command="auto_recall",
                        params=json.dumps(reason),
                        result=json.dumps(
                            {"success": False, "error": f"{type(exc).__name__}: {exc}"}
                        ),
                    )
                )
            except Exception:  # noqa: BLE001
                logger.exception("Failed to persist auto recall failure for %s", asset_id)
            self._emit(
                {
                    "type": "system_event",
                    "event": "auto_recall_failed",
                    "asset_id": asset_id,
                    "battery": battery,
                    "error": f"{type(exc).__name__}: {exc}",
                    "message": f"{asset_id} auto-recall failed",
                }
            )
        finally:
            self._inflight.discard(asset_id)
