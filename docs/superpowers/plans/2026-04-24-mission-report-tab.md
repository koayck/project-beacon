# Mission Report Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a top-level "Mission Report" dashboard tab that shows a structured, human-readable view of each mission — summary card on top, full agent event timeline below — and fix the `result_summary` bug where the sentinel `"Report emitted."` clobbers real summaries.

**Architecture:** Three independently-shippable layers. Layer 1 (additive) persists every SSE agent event to a new `mission_run_events` SQLite table. Layer 2 replaces the "last text wins" rule in `MissionRunAccumulator` with a deterministic "best summary" picker that filters sentinels and prefers structured markers. Layer 3 is a pure-frontend tab that fetches per-run events and renders summary + timeline.

**Tech Stack:** Python 3.12, FastAPI, aiosqlite, pydantic, pytest, asyncio · Next.js 14 (SSG), React, TypeScript, Tailwind.

**Spec:** `docs/superpowers/specs/2026-04-24-mission-report-tab-design.md`

---

## File Structure

**Created:**
- `backend/db/models.py` — *modified*, add `MissionRunEvent` pydantic model
- `backend/db/schema.sql` — *modified*, add `mission_run_events` table
- `backend/db/repository.py` — *modified*, add `_MissionRunEventsRepository` and `mission_run_events_repo` singleton
- `backend/services/mission_summary.py` — *new*, pure `pick_best_summary()` function
- `backend/services/mission_runs.py` — *modified*, accumulator gains `record_event()` + event buffer; `build()` calls picker
- `backend/app.py` — *modified*, `/command/stream` calls `accumulator.record_event(...)`; new `GET /dashboard/runs/{id}/events`
- `tests/test_mission_summary_picker.py` — *new*, picker unit tests
- `tests/test_mission_run_events_repository.py` — *new*, repo round-trip tests
- `tests/test_mission_run_accumulator.py` — *modified*, add tests for event buffer + picker integration
- `frontend/src/lib/api.ts` — *modified*, add `MissionRunEvent` type + `fetchMissionEvents()`
- `frontend/src/app/dashboard/page.tsx` — *modified*, add tab strip + render Mission Report
- `frontend/src/components/dashboard/MissionReportTab.tsx` — *new*, run picker + content orchestration
- `frontend/src/components/dashboard/MissionReportSummary.tsx` — *new*, summary card
- `frontend/src/components/dashboard/MissionTimeline.tsx` — *new*, ordered list of events
- `frontend/src/components/dashboard/TimelineEvent.tsx` — *new*, one row, variant-switches on event_type

---

## Task 1: Add `mission_run_events` schema

**Files:**
- Modify: `backend/db/schema.sql` (append at end)

- [ ] **Step 1: Append the table to the schema**

Append exactly this to the end of `backend/db/schema.sql`:

```sql
CREATE TABLE IF NOT EXISTS mission_run_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      INTEGER NOT NULL,
    seq         INTEGER NOT NULL,
    ts          TEXT    NOT NULL,
    event_type  TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (run_id) REFERENCES mission_runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mission_run_events_run_seq
    ON mission_run_events(run_id, seq);
```

- [ ] **Step 2: Verify schema applies cleanly to a fresh DB**

Run: `BEACON_DB_PATH=/tmp/beacon-schema-check.db uv run python -c "import asyncio; from backend.db.repository import init_db; asyncio.run(init_db())"`
Expected: exits with code 0, no exception.

- [ ] **Step 3: Commit**

```bash
git add backend/db/schema.sql
git commit -m "feat(db): add mission_run_events table for agent event timeline"
```

---

## Task 2: Add `MissionRunEvent` model

**Files:**
- Modify: `backend/db/models.py`

- [ ] **Step 1: Append the model**

Append to `backend/db/models.py`:

```python
class MissionRunEvent(BaseModel):
    id: Optional[int] = None
    run_id: int
    seq: int
    ts: str
    event_type: Literal["tool_call", "tool_result", "thinking", "text", "final", "error"]
    payload: str  # JSON-encoded blob; the API layer parses it
    created_at: Optional[str] = None
```

- [ ] **Step 2: Type-check**

Run: `uv run python -c "from backend.db.models import MissionRunEvent; print(MissionRunEvent(run_id=1, seq=0, ts='2026-04-24T00:00:00Z', event_type='text', payload='{}'))"`
Expected: prints a populated model instance, no error.

- [ ] **Step 3: Commit**

```bash
git add backend/db/models.py
git commit -m "feat(db): add MissionRunEvent pydantic model"
```

---

## Task 3: Add events repository

**Files:**
- Create: `tests/test_mission_run_events_repository.py`
- Modify: `backend/db/repository.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mission_run_events_repository.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.db.models import MissionRun, MissionRunEvent
from backend.db.repository import init_db, mission_run_events_repo, mission_run_repo


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BEACON_DB_PATH", str(tmp_path / "test.db"))
    await init_db()


async def _seed_run() -> int:
    run = MissionRun(
        asset_id="BEACON-01",
        prompt="p",
        status="success",
        started_at=datetime.now(timezone.utc),
    )
    return await mission_run_repo.create(run)


async def test_insert_many_and_list_returns_events_in_seq_order() -> None:
    run_id = await _seed_run()
    events = [
        MissionRunEvent(run_id=run_id, seq=2, ts="2026-04-24T00:00:02Z",
                        event_type="text", payload='{"text":"second"}'),
        MissionRunEvent(run_id=run_id, seq=0, ts="2026-04-24T00:00:00Z",
                        event_type="tool_call", payload='{"name":"scan"}'),
        MissionRunEvent(run_id=run_id, seq=1, ts="2026-04-24T00:00:01Z",
                        event_type="tool_result", payload='{"ok":true}'),
    ]
    await mission_run_events_repo.insert_many(events)

    rows = await mission_run_events_repo.list_for_run(run_id)
    assert [r.seq for r in rows] == [0, 1, 2]
    assert rows[0].event_type == "tool_call"


async def test_insert_many_empty_is_noop() -> None:
    run_id = await _seed_run()
    await mission_run_events_repo.insert_many([])
    rows = await mission_run_events_repo.list_for_run(run_id)
    assert rows == []


async def test_list_for_unknown_run_returns_empty() -> None:
    rows = await mission_run_events_repo.list_for_run(99999)
    assert rows == []
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest tests/test_mission_run_events_repository.py -v`
Expected: FAIL with `ImportError: cannot import name 'mission_run_events_repo'`.

- [ ] **Step 3: Add the repository**

In `backend/db/repository.py`:

a) Add `MissionRunEvent` to the existing import:

```python
from backend.db.models import Asset, MissionLog, LicenseRecord, MissionRun, MissionRunEvent
```

b) Add this section after the `_MissionRunRepository` class (just before `# ── Singletons ──`):

```python
# ── Mission Run Events ────────────────────────────────────────────────────────


class _MissionRunEventsRepository:
    async def insert_many(self, events: list[MissionRunEvent]) -> None:
        """Bulk-insert events for a mission run. No-op if the list is empty."""
        if not events:
            return
        query = """
            INSERT INTO mission_run_events (run_id, seq, ts, event_type, payload)
            VALUES (?, ?, ?, ?, ?)
        """
        rows = [
            (e.run_id, e.seq, e.ts, e.event_type, e.payload)
            for e in events
        ]
        async with _connect() as conn:
            await conn.executemany(query, rows)
            await conn.commit()

    async def list_for_run(self, run_id: int) -> list[MissionRunEvent]:
        """Return all events for one run, ordered by seq ascending."""
        query = """
            SELECT id, run_id, seq, ts, event_type, payload, created_at
            FROM mission_run_events
            WHERE run_id = ?
            ORDER BY seq ASC
        """
        async with _connect() as conn:
            cur = await conn.execute(query, (run_id,))
            rows = await cur.fetchall()
        return [MissionRunEvent(**_row_to_dict(row)) for row in rows]
```

c) Add the singleton at the bottom, next to the other singletons:

```python
mission_run_events_repo = _MissionRunEventsRepository()
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/test_mission_run_events_repository.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/db/repository.py backend/db/models.py tests/test_mission_run_events_repository.py
git commit -m "feat(db): add mission_run_events repository with bulk insert + ordered list"
```

---

## Task 4: Add `pick_best_summary()` pure function

**Files:**
- Create: `backend/services/mission_summary.py`
- Create: `tests/test_mission_summary_picker.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mission_summary_picker.py`:

```python
from backend.services.mission_summary import pick_best_summary


def test_returns_none_for_empty_input() -> None:
    assert pick_best_summary([]) is None


def test_filters_known_sentinels() -> None:
    assert pick_best_summary(["Report emitted.", "  ", ""]) is None


def test_prefers_structured_marker_over_longer_text() -> None:
    long_plain = "x" * 500
    structured = "═══ AREA SCAN COMPLETE ═══ short"
    assert pick_best_summary([long_plain, structured]) == structured


def test_picks_longest_when_no_structured_candidate() -> None:
    short = "ok"
    longer = "Mission completed without incident."
    assert pick_best_summary([short, longer]) == longer


def test_strips_sentinels_then_picks_longest() -> None:
    assert pick_best_summary(["Report emitted.", "actual result here"]) == "actual result here"


def test_recognizes_total_marker() -> None:
    assert pick_best_summary(["short", "TOTAL SUPPLY DISPATCHED: 1"]) == "TOTAL SUPPLY DISPATCHED: 1"


def test_recognizes_complete_marker() -> None:
    assert (
        pick_best_summary(["short", "AREA SCAN COMPLETE — 2 building(s)"])
        == "AREA SCAN COMPLETE — 2 building(s)"
    )


def test_among_multiple_structured_picks_longest() -> None:
    a = "═══ COMPLETE ═══"
    b = "═══ COMPLETE ═══ with details" * 3
    assert pick_best_summary([a, b]) == b
```

- [ ] **Step 2: Run tests — verify they fail**

Run: `uv run pytest tests/test_mission_summary_picker.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'backend.services.mission_summary'`.

- [ ] **Step 3: Implement the picker**

Create `backend/services/mission_summary.py`:

```python
from __future__ import annotations

_SENTINELS: frozenset[str] = frozenset({"Report emitted."})
_STRUCTURED_MARKERS: tuple[str, ...] = ("═══", "COMPLETE", "TOTAL")


def pick_best_summary(candidates: list[str]) -> str | None:
    """Pick the most informative text from a run's text-bearing events.

    Filters known sentinels and whitespace-only strings, prefers candidates
    containing structured markers (visual dividers, completion banners,
    summary totals), and otherwise falls back to the longest remaining string.

    Args:
        candidates: All `text` and `final` event payloads collected during a
            mission run, in emission order.

    Returns:
        The best summary string, or None if no usable candidate exists.
    """
    cleaned = [c for c in candidates if c and c.strip() and c not in _SENTINELS]
    if not cleaned:
        return None
    structured = [c for c in cleaned if any(m in c for m in _STRUCTURED_MARKERS)]
    pool = structured if structured else cleaned
    return max(pool, key=len)
```

- [ ] **Step 4: Run tests — verify they pass**

Run: `uv run pytest tests/test_mission_summary_picker.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/mission_summary.py tests/test_mission_summary_picker.py
git commit -m "feat(mission): add pick_best_summary() that filters sentinels and prefers structured markers"
```

---

## Task 5: Extend `MissionRunAccumulator` with event buffer + use picker in `build()`

**Files:**
- Modify: `backend/services/mission_runs.py`
- Modify: `tests/test_mission_run_accumulator.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mission_run_accumulator.py`:

```python
def test_record_event_buffers_in_order() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="p", simulation_id=None)
    acc.record_event("tool_call", {"name": "scan"})
    acc.record_event("text", {"text": "hello"})
    assert len(acc.events) == 2
    assert acc.events[0].event_type == "tool_call"
    assert acc.events[0].seq == 0
    assert acc.events[1].seq == 1
    assert acc.events[1].event_type == "text"


def test_build_uses_pick_best_summary_over_all_text_events() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="p", simulation_id=None)
    acc.record_event("text", {"text": "═══ AREA SCAN COMPLETE ═══ details"})
    acc.record_event("final", {"text": "Report emitted."})
    run = acc.build(status="success", ttft_ms=None, final_text="Report emitted.")
    assert run.result_summary == "═══ AREA SCAN COMPLETE ═══ details"


def test_build_falls_back_to_final_text_when_no_events_recorded() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="p", simulation_id=None)
    run = acc.build(status="success", ttft_ms=None, final_text="just this")
    assert run.result_summary == "just this"


def test_build_returns_none_summary_when_only_sentinels() -> None:
    acc = MissionRunAccumulator(asset_id="FLEET", prompt="p", simulation_id=None)
    acc.record_event("text", {"text": "Report emitted."})
    acc.record_event("final", {"text": "Report emitted."})
    run = acc.build(status="success", ttft_ms=None, final_text="Report emitted.")
    assert run.result_summary is None
```

- [ ] **Step 2: Run tests — verify the new ones fail**

Run: `uv run pytest tests/test_mission_run_accumulator.py -v`
Expected: 4 new tests FAIL (`AttributeError: 'MissionRunAccumulator' object has no attribute 'record_event'` and similar). Existing 8 tests still pass.

- [ ] **Step 3: Update the accumulator**

Replace the entire contents of `backend/services/mission_runs.py` with:

```python
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
        valid_types = {"tool_call", "tool_result", "thinking", "text", "final", "error"}
        if event_type not in valid_types:
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
```

- [ ] **Step 4: Run all accumulator tests — verify they pass**

Run: `uv run pytest tests/test_mission_run_accumulator.py -v`
Expected: 12 passed (8 original + 4 new).

- [ ] **Step 5: Commit**

```bash
git add backend/services/mission_runs.py tests/test_mission_run_accumulator.py
git commit -m "feat(mission): buffer agent events and derive summary from full text history"
```

---

## Task 6: Wire event recording into `/command/stream` SSE handler

**Files:**
- Modify: `backend/app.py`

- [ ] **Step 1: Add event recording calls inside the SSE generator**

In `backend/app.py`, inside `send_command_stream`'s `generate()` function, find each `yield f"data: {json.dumps(payload)}\n\n"` line in the agent-event-handling loop and add `accumulator.record_event(payload["type"], payload)` immediately before each `yield`. The change is uniform:

Before:
```python
yield f"data: {json.dumps(payload)}\n\n"
```

After:
```python
accumulator.record_event(payload["type"], payload)
yield f"data: {json.dumps(payload)}\n\n"
```

Apply this to all six agent-event yield sites inside the per-event loop:
1. `thinking` payload (around line 1314)
2. `tool_call` payload (around line 1324)
3. `text` payload from sweep tool-result branch (around line 1350)
4. `tool_result` payload (around line 1362)
5. `text` payload from sweep structured-text branch (around line 1371)
6. `text` / `final` payload from plain-text branch (around line 1389)

Do NOT add it to the heartbeat, error, or done payloads — those are stream-control events, not agent events. Specifically: skip the `'heartbeat'` yield (~line 1296), the top-level `'error'` yield (~line 1302), and the final `'done'` yield (~line 1442).

The `error` event_type IS a valid agent event, but the SSE handler's `'error'` payload is emitted for stream-control failures (queue errors). For consistency, leave it out of the buffer — the run's `error_message` field already captures it.

- [ ] **Step 2: After the existing `mission_run_repo.create(run)` call, flush events**

Find this block (around lines 1408-1418 in the `finally:` clause of `generate()`):

```python
            try:
                run = accumulator.build(
                    status=final_status,
                    ttft_ms=ttft_ms_int,
                    final_text=final_text or "",
                    error=error_text,
                    langfuse_trace_id=langfuse_trace_id,
                )
                await mission_run_repo.create(run)
            except Exception as exc:
                logging.getLogger(__name__).exception("Failed to persist mission_run: %s", exc)
```

Replace with:

```python
            try:
                run = accumulator.build(
                    status=final_status,
                    ttft_ms=ttft_ms_int,
                    final_text=final_text or "",
                    error=error_text,
                    langfuse_trace_id=langfuse_trace_id,
                )
                run_id = await mission_run_repo.create(run)
                if run_id and accumulator.events:
                    try:
                        rows = [
                            MissionRunEvent(**row)
                            for row in accumulator.serialise_events(run_id)
                        ]
                        await mission_run_events_repo.insert_many(rows)
                    except Exception as exc:
                        logging.getLogger(__name__).exception(
                            "Failed to persist mission_run_events: %s", exc
                        )
            except Exception as exc:
                logging.getLogger(__name__).exception("Failed to persist mission_run: %s", exc)
```

- [ ] **Step 3: Update the existing imports at the top of `backend/app.py`**

Change:
```python
from backend.db.repository import init_db, asset_repo, mission_log_repo, mission_run_repo
from backend.db.models import Asset, MissionLog, MissionRun
```

To:
```python
from backend.db.repository import (
    init_db,
    asset_repo,
    mission_log_repo,
    mission_run_repo,
    mission_run_events_repo,
)
from backend.db.models import Asset, MissionLog, MissionRun, MissionRunEvent
```

- [ ] **Step 4: Smoke test — start the backend and confirm no startup error**

Run: `uv run python -c "from backend.app import app; print('app loaded:', app.title)"`
Expected: `app loaded: Project Beacon`. No import error.

- [ ] **Step 5: Commit**

```bash
git add backend/app.py
git commit -m "feat(stream): persist agent events to mission_run_events on stream completion"
```

---

## Task 7: Add `GET /dashboard/runs/{id}/events` endpoint

**Files:**
- Modify: `backend/app.py`

- [ ] **Step 1: Add the endpoint after the existing `/dashboard` route**

In `backend/app.py`, immediately after the `get_dashboard()` function (around line 870), add:

```python
@app.get("/dashboard/runs/{run_id}/events")
async def get_mission_run_events(run_id: int) -> dict:
    """Return the recorded agent event timeline for one mission run.

    Args:
        run_id: Database ID of the mission run.

    Returns:
        {"run_id": int, "events": [{"seq", "ts", "event_type", "payload"}, ...]}
        where `payload` is the parsed JSON object (or {"raw": str} if the stored
        blob fails to parse — never crash on malformed payloads).
    """
    rows = await mission_run_events_repo.list_for_run(run_id)
    out_events: list[dict] = []
    for row in rows:
        try:
            parsed = json.loads(row.payload)
        except (TypeError, ValueError):
            parsed = {"raw": row.payload}
        out_events.append({
            "seq": row.seq,
            "ts": row.ts,
            "event_type": row.event_type,
            "payload": parsed,
        })
    return {"run_id": run_id, "events": out_events}
```

- [ ] **Step 2: Smoke test the endpoint with an empty DB**

Start backend in one shell: `uv run python -m backend.app`

In another shell: `curl -s http://127.0.0.1:8000/dashboard/runs/99999/events`
Expected: `{"run_id":99999,"events":[]}`

Stop the backend (Ctrl+C).

- [ ] **Step 3: Commit**

```bash
git add backend/app.py
git commit -m "feat(api): add /dashboard/runs/{id}/events endpoint"
```

---

## Task 8: Add frontend type + API client

**Files:**
- Modify: `frontend/src/lib/api.ts`

- [ ] **Step 1: Add the type after `DashboardPayload`**

In `frontend/src/lib/api.ts`, after the `DashboardPayload` interface (around line 169), add:

```typescript
export type MissionRunEventType =
  | 'tool_call'
  | 'tool_result'
  | 'thinking'
  | 'text'
  | 'final'
  | 'error'

export interface MissionRunEvent {
  seq: number
  ts: string
  event_type: MissionRunEventType
  payload: Record<string, unknown>
}

export interface MissionRunEventsResponse {
  run_id: number
  events: MissionRunEvent[]
}
```

- [ ] **Step 2: Add the fetch function after `fetchDashboard()`**

At the end of `frontend/src/lib/api.ts`, after `fetchDashboard`, add:

```typescript
export async function fetchMissionEvents(runId: number): Promise<MissionRunEventsResponse> {
  const res = await fetch(`${BASE}/dashboard/runs/${runId}/events`)
  if (!res.ok) throw new Error(`Mission events fetch failed: ${res.status}`)
  return res.json()
}
```

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0, no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api.ts
git commit -m "feat(api): add MissionRunEvent type and fetchMissionEvents client"
```

---

## Task 9: Build `TimelineEvent` component

**Files:**
- Create: `frontend/src/components/dashboard/TimelineEvent.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/dashboard/TimelineEvent.tsx`:

```typescript
'use client'

import { useState } from 'react'
import type { MissionRunEvent } from '@/lib/api'

const TYPE_STYLES: Record<MissionRunEvent['event_type'], { label: string; color: string }> = {
  tool_call:   { label: 'TOOL CALL',   color: 'text-[#88ccee]' },
  tool_result: { label: 'TOOL RESULT', color: 'text-[#44dd88]' },
  thinking:    { label: 'THINKING',    color: 'text-[#cc88ff]' },
  text:        { label: 'TEXT',        color: 'text-[#cde]' },
  final:       { label: 'FINAL',       color: 'text-[#ffaa55]' },
  error:       { label: 'ERROR',       color: 'text-[#ff5555]' },
}

const SENTINEL_TEXTS = new Set(['Report emitted.'])

function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleTimeString('en-US', { hour12: false }) +
    `.${String(d.getMilliseconds()).padStart(3, '0')}`
}

function eventBody(event: MissionRunEvent): string {
  const p = event.payload
  if (event.event_type === 'tool_call') {
    const name = String(p.name ?? '?')
    const args = JSON.stringify(p.args ?? {}, null, 2)
    return `${name}(${args})`
  }
  if (event.event_type === 'tool_result') {
    const name = String(p.name ?? '?')
    const result = typeof p.result === 'string'
      ? p.result
      : JSON.stringify(p.result, null, 2)
    return `${name} →\n${result}`
  }
  if (event.event_type === 'error') {
    return String(p.text ?? p.message ?? '(no detail)')
  }
  return String(p.text ?? '')
}

export function TimelineEvent({ event }: { event: MissionRunEvent }) {
  const style = TYPE_STYLES[event.event_type]
  const isThinking = event.event_type === 'thinking'
  const [open, setOpen] = useState(!isThinking)

  const body = eventBody(event)
  const isSentinel =
    (event.event_type === 'text' || event.event_type === 'final') &&
    SENTINEL_TEXTS.has(body.trim())

  return (
    <div className="border-l-2 border-[rgba(40,140,180,0.25)] pl-4 py-2">
      <button
        type="button"
        className="flex w-full items-baseline gap-3 text-left"
        onClick={() => setOpen(!open)}
      >
        <span className={`text-[10px] font-bold tracking-[1.5px] ${style.color}`}>
          {style.label}
        </span>
        <span className="text-[10px] text-[#556677] tabular-nums">
          {formatTime(event.ts)}
        </span>
        {isSentinel && (
          <span className="rounded bg-[rgba(85,102,119,0.2)] px-1.5 py-0.5 text-[9px] tracking-[1px] text-[#667788]">
            SENTINEL
          </span>
        )}
        <span className="ml-auto text-[10px] text-[#556677]">{open ? '▾' : '▸'}</span>
      </button>
      {open && (
        <pre className={`mt-2 whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed ${
          isSentinel ? 'text-[#667788]' : 'text-[#cde]'
        }`}>
          {body || '(empty)'}
        </pre>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/TimelineEvent.tsx
git commit -m "feat(dashboard): add TimelineEvent component"
```

---

## Task 10: Build `MissionTimeline` component

**Files:**
- Create: `frontend/src/components/dashboard/MissionTimeline.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/dashboard/MissionTimeline.tsx`:

```typescript
'use client'

import type { MissionRunEvent } from '@/lib/api'
import { TimelineEvent } from './TimelineEvent'

export function MissionTimeline({ events }: { events: MissionRunEvent[] }) {
  if (events.length === 0) {
    return (
      <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-6 text-[13px] text-[#556677]">
        No detailed timeline available for this run. (Mission predates the
        timeline-capture feature, or events failed to persist.)
      </section>
    )
  }
  return (
    <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-5">
      <h3 className="mb-4 text-[11px] font-bold tracking-[1.5px] text-[#556677]">
        AGENT TIMELINE — {events.length} EVENT{events.length === 1 ? '' : 'S'}
      </h3>
      <div className="space-y-1">
        {events.map(e => <TimelineEvent key={e.seq} event={e} />)}
      </div>
    </section>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/MissionTimeline.tsx
git commit -m "feat(dashboard): add MissionTimeline list component"
```

---

## Task 11: Build `MissionReportSummary` component

**Files:**
- Create: `frontend/src/components/dashboard/MissionReportSummary.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/dashboard/MissionReportSummary.tsx`:

```typescript
'use client'

import type { DashboardRun } from '@/lib/api'

function fmtMs(ms: number | null): string {
  if (ms === null) return '--'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function fmtCost(usd: number | null | undefined): string {
  if (usd === null || usd === undefined) return '--'
  if (usd < 0.001) return '<$0.001'
  if (usd < 1) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function fmtTokens(n: number | null | undefined): string {
  if (n === null || n === undefined) return '--'
  if (n < 1000) return String(n)
  return `${(n / 1000).toFixed(1)}k`
}

function StatusBadge({ status }: { status: DashboardRun['status'] }) {
  const style =
    status === 'success' ? 'bg-[rgba(68,221,136,0.15)] text-[#44dd88] border-[rgba(68,221,136,0.3)]' :
    status === 'failed'  ? 'bg-[rgba(255,85,85,0.15)] text-[#ff5555] border-[rgba(255,85,85,0.3)]' :
                            'bg-[rgba(255,170,51,0.15)] text-[#ffaa33] border-[rgba(255,170,51,0.3)]'
  return (
    <span className={`inline-block rounded border px-2.5 py-1 text-[11px] font-bold tracking-[1px] ${style}`}>
      {status.toUpperCase()}
    </span>
  )
}

function Field({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div>
      <div className="text-[10px] font-bold tracking-[1.5px] text-[#556677]">{label}</div>
      <div className={`mt-1 text-[18px] font-bold tabular-nums ${accent ?? 'text-[#cde]'}`}>{value}</div>
    </div>
  )
}

export function MissionReportSummary({ run }: { run: DashboardRun }) {
  return (
    <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-5">
      <header className="mb-4 flex items-center justify-between">
        <h3 className="text-[11px] font-bold tracking-[1.5px] text-[#556677]">
          MISSION #{run.id} · {run.asset_id}
        </h3>
        <StatusBadge status={run.status} />
      </header>

      <div className="mb-5 rounded border border-[rgba(40,140,180,0.15)] bg-[rgba(4,6,14,0.6)] p-3 text-[13px] text-[#cde]">
        <div className="mb-1 text-[10px] font-bold tracking-[1.5px] text-[#556677]">PROMPT</div>
        {run.prompt}
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-6">
        <Field label="DURATION" value={fmtMs(run.duration_ms)} accent="text-[#55aaff]" />
        <Field label="TTFT" value={fmtMs(run.ttft_ms)} accent="text-[#cc88ff]" />
        <Field label="DETECTED" value={String(run.survivors_detected)} accent="text-[#44ff66]" />
        <Field label="RESCUED" value={String(run.survivors_rescued)} accent="text-[#44dd88]" />
        <Field label="TOKENS" value={fmtTokens(run.total_tokens)} />
        <Field label="COST" value={fmtCost(run.cost_usd)} accent="text-[#ffaa55]" />
      </div>

      {run.result_summary && (
        <div className="mt-5 rounded border border-[rgba(40,140,180,0.15)] bg-[rgba(4,6,14,0.6)] p-3">
          <div className="mb-2 text-[10px] font-bold tracking-[1.5px] text-[#556677]">RESULT</div>
          <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-[#cde]">
            {run.result_summary}
          </pre>
        </div>
      )}

      {run.error_message && (
        <div className="mt-5 rounded border border-[rgba(255,85,85,0.3)] bg-[rgba(255,85,85,0.08)] p-3">
          <div className="mb-2 text-[10px] font-bold tracking-[1.5px] text-[#ff5555]">ERROR</div>
          <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed text-[#ff8888]">
            {run.error_message}
          </pre>
        </div>
      )}
    </section>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/MissionReportSummary.tsx
git commit -m "feat(dashboard): add MissionReportSummary card"
```

---

## Task 12: Build `MissionReportTab` orchestrator

**Files:**
- Create: `frontend/src/components/dashboard/MissionReportTab.tsx`

- [ ] **Step 1: Create the component**

Create `frontend/src/components/dashboard/MissionReportTab.tsx`:

```typescript
'use client'

import { useEffect, useMemo, useState } from 'react'
import { fetchMissionEvents, type DashboardRun, type MissionRunEvent } from '@/lib/api'
import { MissionReportSummary } from './MissionReportSummary'
import { MissionTimeline } from './MissionTimeline'

export function MissionReportTab({ runs }: { runs: DashboardRun[] }) {
  const [selectedId, setSelectedId] = useState<number | null>(runs[0]?.id ?? null)
  const [events, setEvents] = useState<MissionRunEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectedRun = useMemo(
    () => runs.find(r => r.id === selectedId) ?? null,
    [runs, selectedId],
  )

  useEffect(() => {
    if (selectedId === null) {
      setEvents([])
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    fetchMissionEvents(selectedId)
      .then(res => { if (!cancelled) setEvents(res.events) })
      .catch(e => { if (!cancelled) setError(String(e)) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [selectedId])

  if (runs.length === 0) {
    return (
      <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-6 text-center text-[#556677]">
        No missions yet — run a command from the scene to populate.
      </section>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-5 lg:grid-cols-[280px_1fr]">
      <aside className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-3">
        <div className="mb-3 px-2 text-[11px] font-bold tracking-[1.5px] text-[#556677]">
          RECENT MISSIONS
        </div>
        <ul className="space-y-1">
          {runs.map(run => {
            const active = run.id === selectedId
            return (
              <li key={run.id}>
                <button
                  type="button"
                  onClick={() => setSelectedId(run.id)}
                  className={`w-full rounded px-3 py-2 text-left text-[12px] transition ${
                    active
                      ? 'bg-[rgba(40,140,180,0.18)] text-[#cde]'
                      : 'text-[#8899bb] hover:bg-[rgba(40,140,180,0.08)]'
                  }`}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-bold tabular-nums">#{run.id}</span>
                    <span className="text-[10px] uppercase tracking-[1px] text-[#556677]">
                      {run.status}
                    </span>
                  </div>
                  <div className="mt-1 line-clamp-2 text-[11px] text-[#667788]">
                    {run.prompt}
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      </aside>

      <div className="space-y-5">
        {selectedRun && <MissionReportSummary run={selectedRun} />}
        {loading && (
          <section className="rounded-lg border border-[rgba(40,140,180,0.2)] bg-[rgba(6,8,16,0.7)] p-5 text-[13px] text-[#556677]">
            Loading timeline…
          </section>
        )}
        {error && (
          <section className="rounded-lg border border-[rgba(255,85,85,0.3)] bg-[rgba(255,85,85,0.08)] p-5 text-[13px] text-[#ff8888]">
            Failed to load events: {error}
          </section>
        )}
        {!loading && !error && selectedRun && <MissionTimeline events={events} />}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/MissionReportTab.tsx
git commit -m "feat(dashboard): add MissionReportTab orchestrator with run picker"
```

---

## Task 13: Add tab strip to dashboard page

**Files:**
- Modify: `frontend/src/app/dashboard/page.tsx`

- [ ] **Step 1: Replace the dashboard page contents**

Replace the entire contents of `frontend/src/app/dashboard/page.tsx` with:

```typescript
'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { fetchDashboard, type DashboardPayload } from '@/lib/api'
import { OverviewCards } from '@/components/dashboard/OverviewCards'
import { RunsTable } from '@/components/dashboard/RunsTable'
import { CurrentMissionStrip } from '@/components/dashboard/CurrentMissionStrip'
import { Charts } from '@/components/dashboard/Charts'
import { MissionReportTab } from '@/components/dashboard/MissionReportTab'

type TabKey = 'performance' | 'report'

function TabButton({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-5 py-2 text-[12px] font-bold tracking-[1.5px] transition ${
        active
          ? 'border-b-2 border-[#5599bb] text-[#88ccee]'
          : 'border-b-2 border-transparent text-[#556677] hover:text-[#8899bb]'
      }`}
    >
      {children}
    </button>
  )
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<TabKey>('performance')

  useEffect(() => {
    fetchDashboard().then(setData).catch(e => setError(String(e)))
  }, [])

  if (error) {
    return (
      <main className="h-screen overflow-y-auto bg-[#040612] p-6 font-mono text-[#ff8888]">
        Failed to load dashboard: {error}
      </main>
    )
  }
  if (!data) {
    return (
      <main className="h-screen overflow-y-auto bg-[#040612] p-6 font-mono text-[#667788]">
        Loading…
      </main>
    )
  }

  return (
    <main className="h-screen overflow-y-auto bg-[#040612] px-8 py-6 font-mono text-[#cde]">
      <header className="mb-5 flex items-end justify-between border-b border-[rgba(40,140,180,0.15)] pb-5">
        <div>
          <h1 className="text-[28px] font-bold leading-none tracking-[3px] text-[#5599bb] drop-shadow-[0_0_24px_rgba(85,153,187,0.35)]">
            PROJECT BEACON — PERFORMANCE
          </h1>
          <p className="mt-3 text-[13px] tracking-[1px] text-[#556677]">
            Historical mission telemetry · {data.runs.length} recent runs
          </p>
        </div>
        <Link
          href="/"
          className="rounded-md border border-[rgba(50,136,204,0.4)] bg-[rgba(40,140,180,0.06)] px-4 py-2 text-[12px] font-bold tracking-[1.5px] text-[#88ccee] hover:bg-[rgba(40,140,180,0.15)]"
        >
          ← BACK TO SCENE
        </Link>
      </header>

      <nav className="mb-6 flex gap-2 border-b border-[rgba(40,140,180,0.15)]">
        <TabButton active={tab === 'performance'} onClick={() => setTab('performance')}>
          PERFORMANCE
        </TabButton>
        <TabButton active={tab === 'report'} onClick={() => setTab('report')}>
          MISSION REPORT
        </TabButton>
      </nav>

      {tab === 'performance' && (
        <>
          {data.currentMission && <CurrentMissionStrip mission={data.currentMission} />}
          <OverviewCards overview={data.overview} />
          <Charts runs={data.runs} />
          <RunsTable runs={data.runs} />
        </>
      )}

      {tab === 'report' && <MissionReportTab runs={data.runs} />}
    </main>
  )
}
```

- [ ] **Step 2: Type-check**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0, no errors.

- [ ] **Step 3: Manual smoke test (UI verification)**

Start the backend in one shell: `uv run python -m backend.app`
Start the frontend in another shell: `cd frontend && npm run dev`

In the browser:
1. Open `http://localhost:3000/dashboard`. Verify two tabs visible: PERFORMANCE (active) and MISSION REPORT.
2. Click PERFORMANCE — confirm OverviewCards, Charts, and RunsTable all render exactly as before.
3. Click MISSION REPORT — confirm a run picker on the left, summary card on the right, and either an empty-timeline message or a populated timeline depending on whether any runs in the DB were created with events.
4. Run a fresh mission from the scene (`http://localhost:3000`), then return to dashboard → MISSION REPORT → select the new run. Verify the timeline shows tool_call → tool_result → text/final events in order.
5. Locate a historical mission whose `result_summary` was previously `"Report emitted."` (or run a sweep scan that triggers the sentinel) and verify after reload it now shows the real structured report.

Stop both processes (Ctrl+C in each shell).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/dashboard/page.tsx
git commit -m "feat(dashboard): add Performance/Mission Report tab strip"
```

---

## Final verification

- [ ] **Run the full backend test suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass. New test files (`test_mission_summary_picker.py`, `test_mission_run_events_repository.py`, `test_mission_run_accumulator.py`) all green; no regressions in pre-existing tests.

**Note on integration testing:** The spec mentioned a `tests/test_command_stream_persists_events.py` integration test that mocks the ADK runner. Building a faithful ADK-runner mock is significant scope and risks brittle tests. For the hackathon-day delivery, the manual smoke test in Task 13 step 3 (run a real mission end-to-end and verify the timeline appears) is the integration check. Add the formal integration test in a follow-up if the team wants it post-pitch.

- [ ] **Type-check the full frontend**

Run: `cd frontend && npx tsc --noEmit`
Expected: exits 0, no errors.

- [ ] **Update ARCHITECTURE.md** (per CLAUDE.md guideline)

If `ARCHITECTURE.md` exists at the repo root, append a paragraph under the dashboard / observability section:

> **Mission Report tab.** The dashboard exposes a per-run timeline view backed by the `mission_run_events` table. Every event yielded by the ADK runner during `/command/stream` is buffered in `MissionRunAccumulator` and bulk-inserted alongside the `mission_runs` row at stream end. The `pick_best_summary()` helper in `backend/services/mission_summary.py` derives `result_summary` from the full text-event history, filtering known sentinels like `"Report emitted."` and preferring strings containing structured markers.

If the file does not exist, skip this step.

Commit if updated:

```bash
git add ARCHITECTURE.md
git commit -m "docs(architecture): describe mission report tab and event capture"
```
