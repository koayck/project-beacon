# Mission Report Tab — Design

**Date:** 2026-04-24
**Status:** Draft (awaiting user review)
**Driver:** Hackathon finals pitch — judges need to visibly see that real AI agent reasoning is driving the swarm, not a scripted demo.

## Problem

Today the only places an operator (or judge) can see what the agent actually did are:
1. The terminal running `uv run python -m backend.app` (volatile, console-only).
2. The expanded row in `RunsTable` on the dashboard, which shows a single `result_summary` string plus the prompt/error.

This is inadequate for two reasons:

**a) Data loss.** The full agent stream (tool calls in order, tool results, thinking, intermediate text) is emitted live over SSE but never persisted. Once a mission ends, it's gone.

**b) `result_summary` is often wrong.** It captures the *last text* the agent emitted. When the scan agent follows its instruction at `backend/instructions/scan_agent_text.py:68` to output the sentinel `"Report emitted."` after a handoff, that string clobbers the real structured summary. Observed in production: row #2 of the current RunsTable reads `RESULT: Report emitted.` while the real scan report has vanished.

The pitch differentiator vs. Cesium/Gazebo competitors is AI orchestration. Judges must be able to see the agent's reasoning trail post-mission, not just final numbers.

## Goal

Add a new top-level tab on the dashboard — **Mission Report** — that renders a human-readable, structured view of a selected mission: headline metrics on top, agent timeline below. Persist the underlying event data so the view works for any mission, not just the one currently in memory.

## Non-goals

- Editing / replaying missions from the report view.
- Historical missions run before this feature shipped — they will show the summary card only (no timeline). No migration.
- Per-event cost / token attribution (run-level totals only, as today).
- Full-text search across missions.

## Architecture

Three changes, each independently shippable and ordered so item 1 is low-risk-additive, item 2 is a targeted bug fix, item 3 is pure frontend.

### 1. Persist the agent event stream (backend, additive)

**New table `mission_run_events`:**

```sql
CREATE TABLE IF NOT EXISTS mission_run_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    ts           TEXT    NOT NULL,
    event_type   TEXT    NOT NULL,  -- 'tool_call' | 'tool_result' | 'thinking' | 'text' | 'final' | 'error'
    payload      TEXT    NOT NULL,  -- JSON blob
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (run_id) REFERENCES mission_runs(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_mission_run_events_run_seq
    ON mission_run_events(run_id, seq);
```

`payload` is event-shape-specific JSON:
- `tool_call`: `{"name": str, "args": object, "call_id": str}`
- `tool_result`: `{"call_id": str, "result": any, "duration_ms": int}`
- `thinking`: `{"text": str}`
- `text`: `{"text": str}`
- `final`: `{"text": str}`
- `error`: `{"message": str, "trace": str | null}`

**Write path.** The SSE stream handler in `backend/app.py` (the `/command/stream` endpoint) already iterates the ADK runner's events and constructs a `MissionRunAccumulator` per request. We add a single in-memory event buffer **on the accumulator** (`accumulator.record_event(evt)`) — same object item 2 reads from. After the run completes and the `mission_runs` row is inserted (yielding `run_id`), the handler flushes the buffer with a single `INSERT ... VALUES (...)` multi-row write to `mission_run_events`. Single flush keeps the hot path unchanged.

**Failure handling.** The event flush is wrapped in `try/except` and logged — if it fails, the mission itself still records (old behavior). This makes the change strictly additive: any bug cannot break the live demo flow.

**Ordering.** The `mission_runs` insert must happen *before* `mission_run_events` flush because events need a `run_id`. If `mission_runs` insert fails, events are dropped (nothing to attach to). Today's code already inserts `mission_runs` at stream end; we piggyback on that moment.

### 2. Fix `result_summary` capture (backend, targeted bug fix)

Replace the "last `text` event wins" rule in `backend/services/mission_runs.py:88` with a deterministic "best summary" picker that runs over all `text` and `final` events collected during the run.

**Rule, in order:**

1. Filter out known sentinels: exact matches of `"Report emitted."`, empty strings, whitespace-only.
2. Among remaining candidates, prefer strings containing any structured marker: `═══`, `COMPLETE`, or `TOTAL`.
3. If no structured candidate exists, pick the longest remaining candidate.
4. If no candidate exists (e.g., the agent only emitted tool calls), fall back to `None`.

The picker is a pure function over a list of strings — trivial unit test surface.

**Coupling to item 1.** This fix requires knowing *all* text-bearing events, not just the last one. The accumulator `MissionRunAccumulator` in `backend/services/mission_runs.py` already exists and gains the event buffer from item 1. The picker reads from that same buffer, so items 1 and 2 share the in-memory state rather than duplicating it.

### 3. Mission Report tab (frontend, pure UI)

**Tab navigation.** Add a simple tab strip directly below the existing header in `dashboard/page.tsx`:

```
[ PERFORMANCE ] [ MISSION REPORT ]
```

Performance tab = current view (`CurrentMissionStrip` + `OverviewCards` + `Charts` + `RunsTable`), unchanged. Mission Report tab = the new view. Tab state is local to the page component (`useState<'performance' | 'report'>('performance')`) — no routing change.

**Mission Report layout:**

```
┌────────────────────────────────────────────────────────────────────┐
│ [run picker: dropdown or left rail list of recent runs]            │
├────────────────────────────────────────────────────────────────────┤
│ SUMMARY CARD                                                       │
│  Status · Prompt · Duration · TTFT · Tokens · Cost · Detect/Rescue│
├────────────────────────────────────────────────────────────────────┤
│ AGENT TIMELINE                                                     │
│  ▶ [ts] thinking: …                                                │
│  ▶ [ts] tool_call: scan_area({...})                                │
│    └─ tool_result (842ms): { survivors: [...] }                    │
│  ▶ [ts] text: "Report emitted."   (dimmed, sentinel)               │
│  ▶ [ts] final: ═══ AREA SCAN COMPLETE ═══ (rendered monospace)     │
└────────────────────────────────────────────────────────────────────┘
```

**Component breakdown** (mirrors existing `components/dashboard/` style):

- `MissionReportTab.tsx` — orchestrates run selection + fetch
- `MissionReportSummary.tsx` — the top card (reuses formatting helpers from `RunsTable.tsx`)
- `MissionTimeline.tsx` — renders the event list
- `TimelineEvent.tsx` — one row; variant-switches on `event_type`
- Tab-strip component inlined in `dashboard/page.tsx` (simple — two buttons + state)

**Data fetch.** New API function `fetchMissionEvents(runId)` → `GET /dashboard/runs/{id}/events` → returns `{run: DashboardRun, events: MissionRunEvent[]}`. Events come pre-sorted by `seq`. Render is read-only.

**Rendering choices:**
- Preserve monospace formatting in `final` / long `text` events (the `═══` dividers are part of the demo aesthetic).
- Collapse `thinking` events by default; expand on click. Judges can drill in but it doesn't clutter.
- Tool call/result pairs render as a single grouped block with the result indented under the call.
- Sentinel texts (`"Report emitted."`) render dimmed with a small tag so it's clear what they are — useful for judges who ask about it.

## Data flow

```
Live mission:
  operator → /command/stream → ADK runner
    → events yielded out via SSE (unchanged — frontend scene panel still consumes)
    → MissionRunAccumulator.record_event(evt) for each event
    → stream completes → insert mission_runs → flush mission_run_events

Viewing report:
  dashboard → Mission Report tab → run picker (from /dashboard payload)
    → select run → GET /dashboard/runs/{id}/events
    → render summary + timeline
```

## Error handling

- **Event flush fails mid-write** — caught in the SSE handler's finalization block, logged, run remains viewable (summary card only). No cascade.
- **Fetch events for a run with no persisted events** (pre-feature missions) — endpoint returns `{run, events: []}`. UI renders summary card + "No detailed timeline available for this run" placeholder.
- **Malformed `payload` JSON** — endpoint returns the raw event with `payload_raw` field; UI shows it as an "unrecognized event" row rather than crashing.

## Testing

**Unit (new):**
- `tests/test_mission_runs_summary.py` — `pick_best_summary([...])` cases: sentinel-only, structured-marker-present, multiple candidates, empty.
- `tests/test_mission_run_events_repo.py` — insert + read-back round-trip, sequence ordering, cascade delete.

**Integration (new):**
- `tests/test_command_stream_persists_events.py` — drive a mocked ADK runner that emits a known event sequence, assert `mission_run_events` rows match.

**Manual (pre-pitch):**
- Run one scan mission live, switch to Mission Report tab, confirm timeline shows in correct order with correct summary.
- Run one mission that triggers the `"Report emitted."` sentinel path, confirm `result_summary` picks the real scan report, not the sentinel.

## Rollout ordering (for demo-day safety)

1. Ship item 1 (events table + write path) behind a `try/except` so it cannot break existing flows. Verify in dev.
2. Ship item 2 (summary picker) once item 1's event buffer exists to derive from. Unit-tested in isolation.
3. Ship item 3 (frontend tab). Pure read path — can't affect live mission execution.

Each item is a separate commit. If time pressure hits, items 1+3 alone deliver the pitch story (timeline view); item 2 is a correctness bonus.

## Open questions

None at time of spec write — all decisions resolved during brainstorming.
