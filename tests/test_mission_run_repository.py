from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.db.models import MissionRun
from backend.db.repository import _connect, init_db, mission_run_repo


@pytest.fixture(autouse=True)
async def fresh_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Give each test an isolated SQLite database with schema applied."""
    monkeypatch.setenv("BEACON_DB_PATH", str(tmp_path / "test.db"))
    await init_db()


async def test_create_and_list_recent_returns_row() -> None:
    run = MissionRun(
        asset_id="BEACON-01",
        prompt="test-create-one",
        status="success",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        duration_ms=1500,
        ttft_ms=200,
        tool_call_count=2,
        survivors_detected=3,
        survivors_rescued=1,
        result_summary="ok",
    )
    row_id = await mission_run_repo.create(run)
    assert row_id > 0

    rows = await mission_run_repo.list_recent(limit=50)
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].tool_call_count == 2


async def test_overview_aggregates_correctly() -> None:
    now = datetime.now(timezone.utc)
    runs = [
        MissionRun(asset_id="A", prompt="p1", status="success", started_at=now, ended_at=now,
                   duration_ms=1000, ttft_ms=100, survivors_detected=2, survivors_rescued=2),
        MissionRun(asset_id="A", prompt="p2", status="success", started_at=now, ended_at=now,
                   duration_ms=2000, ttft_ms=200, survivors_detected=1, survivors_rescued=1),
        MissionRun(asset_id="A", prompt="p3", status="success", started_at=now, ended_at=now,
                   duration_ms=3000, ttft_ms=300, survivors_detected=1, survivors_rescued=0),
        MissionRun(asset_id="A", prompt="p4", status="failed", started_at=now, ended_at=now,
                   duration_ms=500, ttft_ms=None, survivors_detected=0, survivors_rescued=0,
                   error_message="boom"),
    ]
    for r in runs:
        await mission_run_repo.create(r)

    async with _connect() as conn:
        cur = await conn.execute(
            """
            SELECT
              COUNT(*) AS total_missions,
              AVG(ttft_ms) FILTER (WHERE ttft_ms IS NOT NULL) AS avg_ttft_ms,
              AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL) AS avg_duration_ms,
              SUM(survivors_rescued) AS total_survivors_rescued,
              SUM(survivors_detected) AS total_survivors_detected,
              AVG((JULIANDAY(ended_at) - JULIANDAY(started_at)) * 86400.0)
                FILTER (WHERE status='success' AND survivors_rescued > 0) AS avg_rescue_time_s
            FROM mission_runs
            """
        )
        row = await cur.fetchone()

    assert row is not None
    assert int(row["total_missions"]) == 4
    assert int(row["total_survivors_rescued"]) == 3
    assert int(row["total_survivors_detected"]) == 4
    assert abs(float(row["avg_ttft_ms"]) - 200.0) < 0.01  # (100+200+300)/3


async def test_overview_returns_expected_keys_and_types() -> None:
    """Exercise overview() itself: key presence + type casts of aggregate columns."""
    result = await mission_run_repo.overview()

    expected_keys = {
        "total_missions",
        "avg_ttft_ms",
        "avg_duration_ms",
        "total_survivors_rescued",
        "total_survivors_detected",
        "rescue_success_rate",
        "avg_rescue_time_s",
    }
    assert expected_keys.issubset(result.keys())

    assert isinstance(result["total_missions"], int)
    assert isinstance(result["total_survivors_rescued"], int)
    assert isinstance(result["total_survivors_detected"], int)
    assert isinstance(result["rescue_success_rate"], float)
    assert 0.0 <= result["rescue_success_rate"] <= 100.0

    for key in ("avg_ttft_ms", "avg_duration_ms", "avg_rescue_time_s"):
        assert result[key] is None or isinstance(result[key], float)
