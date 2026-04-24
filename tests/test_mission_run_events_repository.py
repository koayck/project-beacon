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
