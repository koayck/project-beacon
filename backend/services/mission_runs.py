from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from backend.db.models import MissionRun


_INT_MAX = 2_147_483_647
_RESULT_SUMMARY_MAX_CHARS = 500


def _round_key(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _coord_key(payload: Any) -> tuple[float, float, float] | None:
    if not isinstance(payload, dict):
        return None
    x = _round_key(payload.get("x"))
    y = _round_key(payload.get("y"))
    z = _round_key(payload.get("z"))
    if x is None or y is None or z is None:
        return None
    return (x, y, z)


class MissionRunAccumulator:
    """Collects per-command metrics across a streaming command request.

    One instance per command stream. Updated as events flow (tool calls,
    detections, deliveries) and finalised with `build()` at stream end.
    """

    def __init__(self, asset_id: str, prompt: str, simulation_id: str | None) -> None:
        self.asset_id = asset_id
        self.prompt = prompt
        self.simulation_id = simulation_id
        self.started_at = datetime.now(timezone.utc)
        self.tool_call_count = 0
        self._detected_keys: set[tuple[float, float, float]] = set()
        self._rescued_keys: set[tuple[float, float, float]] = set()

    @property
    def survivors_detected(self) -> int:
        return len(self._detected_keys)

    @property
    def survivors_rescued(self) -> int:
        return len(self._rescued_keys)

    def record_tool_call(self) -> None:
        self.tool_call_count += 1

    def record_detections(self, survivors: list[Any]) -> None:
        if not isinstance(survivors, list):
            return
        for entry in survivors:
            key = _coord_key(entry)
            if key is not None:
                self._detected_keys.add(key)

    def record_deliveries(self, dispatches: list[Any]) -> None:
        if not isinstance(dispatches, list):
            return
        for entry in dispatches:
            if not isinstance(entry, dict):
                continue
            key = _coord_key(entry.get("survivor"))
            if key is not None:
                self._rescued_keys.add(key)

    def build(
        self,
        *,
        status: str,
        ttft_ms: int | None,
        final_text: str,
        error: str | None = None,
    ) -> MissionRun:
        ended_at = datetime.now(timezone.utc)
        duration_ms_raw = int((ended_at - self.started_at).total_seconds() * 1000)
        duration_ms = max(0, min(duration_ms_raw, _INT_MAX))
        summary = (final_text or "")[:_RESULT_SUMMARY_MAX_CHARS] or None
        return MissionRun(
            simulation_id=self.simulation_id,
            asset_id=self.asset_id,
            prompt=self.prompt,
            status=status,  # type: ignore[arg-type]
            started_at=self.started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            ttft_ms=ttft_ms,
            tool_call_count=self.tool_call_count,
            survivors_detected=self.survivors_detected,
            survivors_rescued=self.survivors_rescued,
            result_summary=summary,
            error_message=error,
        )
