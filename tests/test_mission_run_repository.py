from datetime import datetime, timezone

import pytest

from backend.db.models import MissionRun
from backend.db.repository import _connect, mission_run_repo


pytestmark = pytest.mark.asyncio


async def _cleanup(prefix: str) -> None:
    async with _connect() as conn:
        await conn.execute("DELETE FROM mission_runs WHERE prompt LIKE $1", f"{prefix}%")


async def test_create_and_list_recent_returns_row() -> None:
    prefix = "test-repo-a-"
    await _cleanup(prefix)
    run = MissionRun(
        asset_id="BEACON-01",
        prompt=f"{prefix}one",
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
    try:
        row_id = await mission_run_repo.create(run)
        assert row_id > 0

        rows = await mission_run_repo.list_recent(limit=50)
        matching = [r for r in rows if r.prompt == f"{prefix}one"]
        assert len(matching) == 1
        assert matching[0].status == "success"
        assert matching[0].tool_call_count == 2
    finally:
        await _cleanup(prefix)


async def test_overview_aggregates_correctly() -> None:
    prefix = "test-repo-b-"
    await _cleanup(prefix)
    now = datetime.now(timezone.utc)
    # 3 successful runs with rescues, 1 successful without rescue, 1 failed
    runs = [
        MissionRun(asset_id="A", prompt=f"{prefix}1", status="success", started_at=now, ended_at=now,
                   duration_ms=1000, ttft_ms=100, survivors_detected=2, survivors_rescued=2),
        MissionRun(asset_id="A", prompt=f"{prefix}2", status="success", started_at=now, ended_at=now,
                   duration_ms=2000, ttft_ms=200, survivors_detected=1, survivors_rescued=1),
        MissionRun(asset_id="A", prompt=f"{prefix}3", status="success", started_at=now, ended_at=now,
                   duration_ms=3000, ttft_ms=300, survivors_detected=1, survivors_rescued=0),
        MissionRun(asset_id="A", prompt=f"{prefix}4", status="failed", started_at=now, ended_at=now,
                   duration_ms=500, ttft_ms=None, survivors_detected=0, survivors_rescued=0,
                   error_message="boom"),
    ]
    try:
        for r in runs:
            await mission_run_repo.create(r)

        # Filter aggregates via a scoped query, not overview(), so other test data doesn't pollute.
        async with _connect() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  COUNT(*) AS total_missions,
                  AVG(ttft_ms) FILTER (WHERE ttft_ms IS NOT NULL) AS avg_ttft_ms,
                  AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL) AS avg_duration_ms,
                  SUM(survivors_rescued) AS total_survivors_rescued,
                  SUM(survivors_detected) AS total_survivors_detected,
                  AVG(EXTRACT(EPOCH FROM (ended_at - started_at)))
                    FILTER (WHERE status='success' AND survivors_rescued > 0) AS avg_rescue_time_s
                FROM mission_runs WHERE prompt LIKE $1
                """,
                f"{prefix}%",
            )
        assert row["total_missions"] == 4
        assert int(row["total_survivors_rescued"]) == 3
        assert int(row["total_survivors_detected"]) == 4
        assert abs(float(row["avg_ttft_ms"]) - 200.0) < 0.01  # (100+200+300)/3
    finally:
        await _cleanup(prefix)


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

    # Count/sum fields are always non-null ints (COALESCE-guarded in SQL).
    assert isinstance(result["total_missions"], int)
    assert isinstance(result["total_survivors_rescued"], int)
    assert isinstance(result["total_survivors_detected"], int)

    # rescue_success_rate is CASE-guarded, so it's always a float (0.0 when no detections).
    assert isinstance(result["rescue_success_rate"], float)
    assert 0.0 <= result["rescue_success_rate"] <= 100.0

    # Nullable float aggregates — either None or float, never Decimal.
    for key in ("avg_ttft_ms", "avg_duration_ms", "avg_rescue_time_s"):
        assert result[key] is None or isinstance(result[key], float)
