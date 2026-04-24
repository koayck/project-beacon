from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from backend.db.models import MissionRun
from backend.services.mission_summary import pick_best_summary


_INT_MAX = 2_147_483_647
_RESULT_SUMMARY_MAX_CHARS = 500
_TEXT_EVENT_TYPES: frozenset[str] = frozenset({"text", "final"})
_VALID_EVENT_TYPES: frozenset[str] = frozenset({
    "tool_call", "tool_result", "thinking", "text", "final", "error",
})


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


@dataclass
class BufferedEvent:
    """One agent stream event held in memory until the run is persisted.

    `payload` is the original dict; serialized to JSON only at flush time.
    """
    seq: int
    ts: str
    event_type: Literal["tool_call", "tool_result", "thinking", "text", "final", "error"]
    payload: dict[str, Any]


class MissionRunAccumulator:
    """Collects per-command metrics + event stream across a streaming command request.

    One instance per command stream. Updated as events flow (tool calls,
    detections, deliveries, text/thinking events) and finalised with `build()`
    at stream end.
    """

    def __init__(self, asset_id: str, prompt: str, simulation_id: str | None) -> None:
        self.asset_id = asset_id
        self.prompt = prompt
        self.simulation_id = simulation_id
        self.started_at = datetime.now(timezone.utc)
        self.tool_call_count = 0
        self._detected_keys: set[tuple[float, float, float]] = set()
        self._rescued_keys: set[tuple[float, float, float]] = set()
        self.events: list[BufferedEvent] = []

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

    def record_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Append one event to the in-memory buffer.

        Sequence numbers are assigned in arrival order. Timestamps captured at
        record-time. Unknown event types are silently dropped — keep the call
        site cheap for the SSE hot path.
        """
        if event_type not in _VALID_EVENT_TYPES:
            return
        self.events.append(
            BufferedEvent(
                seq=len(self.events),
                ts=datetime.now(timezone.utc).isoformat(),
                event_type=event_type,  # type: ignore[arg-type]
                payload=payload,
            )
        )

    def _derive_summary(self, fallback: str) -> str | None:
        text_candidates = [
            str(e.payload.get("text", ""))
            for e in self.events
            if e.event_type in _TEXT_EVENT_TYPES
        ]
        if not text_candidates and fallback:
            text_candidates = [fallback]
        return pick_best_summary(text_candidates)

    def build(
        self,
        *,
        status: str,
        ttft_ms: int | None,
        final_text: str,
        error: str | None = None,
        langfuse_trace_id: str | None = None,
    ) -> MissionRun:
        ended_at = datetime.now(timezone.utc)
        duration_ms_raw = int((ended_at - self.started_at).total_seconds() * 1000)
        duration_ms = max(0, min(duration_ms_raw, _INT_MAX))
        derived = self._derive_summary(final_text or "")
        summary = derived[:_RESULT_SUMMARY_MAX_CHARS] if derived else None
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
            langfuse_trace_id=langfuse_trace_id,
        )

    def serialise_events(self, run_id: int) -> list[dict[str, Any]]:
        """Return event rows ready for `mission_run_events_repo.insert_many`.

        Caller wraps each dict into MissionRunEvent — kept as a plain list of
        dicts here so this module avoids importing the model and stays cheap to
        import in test contexts.
        """
        return [
            {
                "run_id": run_id,
                "seq": e.seq,
                "ts": e.ts,
                "event_type": e.event_type,
                "payload": json.dumps(e.payload, default=str),
            }
            for e in self.events
        ]
