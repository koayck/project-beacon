from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

import asyncpg

from backend.db.models import Asset, MissionLog, LicenseRecord, MissionRun


async def init_db() -> None:
    """Validate that the configured Supabase database is reachable."""
    async with _connect() as conn:
        await conn.execute("SELECT 1")


@asynccontextmanager
async def _connect() -> AsyncIterator[asyncpg.Connection]:
    """Open a temporary asyncpg connection to the configured Supabase database."""
    dsn = _normalize_dsn(os.environ.get("SUPABASE_DB_URL", "").strip())
    conn = await asyncpg.connect(dsn=dsn)
    try:
        yield conn
    finally:
        await conn.close()


def _normalize_dsn(db_url: str) -> str:
    """Convert SQLAlchemy-style Postgres URLs into asyncpg-compatible DSNs."""
    stripped = db_url.strip()
    if not stripped:
        raise RuntimeError("SUPABASE_DB_URL is required for database access")
    if stripped.startswith("postgresql+asyncpg://"):
        return "postgresql://" + stripped[len("postgresql+asyncpg://") :]
    return stripped


def _row_to_dict(row: asyncpg.Record) -> dict[str, Any]:
    """Convert an asyncpg record into a JSON-serialisable dictionary."""
    payload = dict(row)
    for key, value in payload.items():
        if isinstance(value, (date, datetime)):
            payload[key] = value.isoformat()
    return payload


# ── Assets ────────────────────────────────────────────────────────────────────


class _AssetRepository:
    async def list_all(self) -> list[Asset]:
        """Return all registered assets ordered by database row ID."""
        query = """
            SELECT id, asset_id, asset_class, grpc_host, grpc_port, registered_at
            FROM assets
            ORDER BY id
        """
        async with _connect() as conn:
            rows = await conn.fetch(query)
        return [Asset(**_row_to_dict(row)) for row in rows]

    async def get(self, asset_id: str) -> Asset | None:
        """Return one asset by its external asset identifier."""
        query = """
            SELECT id, asset_id, asset_class, grpc_host, grpc_port, registered_at
            FROM assets
            WHERE asset_id = $1
        """
        async with _connect() as conn:
            row = await conn.fetchrow(query, asset_id)
        return Asset(**_row_to_dict(row)) if row is not None else None

    async def upsert(self, asset: Asset) -> None:
        """Insert or update an asset row in Supabase."""
        query = """
            INSERT INTO assets (asset_id, asset_class, grpc_host, grpc_port)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (asset_id) DO UPDATE SET
                asset_class = EXCLUDED.asset_class,
                grpc_host = EXCLUDED.grpc_host,
                grpc_port = EXCLUDED.grpc_port
        """
        async with _connect() as conn:
            await conn.execute(
                query,
                asset.asset_id,
                asset.asset_class,
                asset.grpc_host,
                asset.grpc_port,
            )

    async def delete(self, asset_id: str) -> None:
        """Delete an asset row by asset identifier."""
        async with _connect() as conn:
            await conn.execute("DELETE FROM assets WHERE asset_id = $1", asset_id)


# ── Mission Logs ──────────────────────────────────────────────────────────────


class _MissionLogRepository:
    async def create(self, log: MissionLog) -> None:
        """Persist one mission log entry."""
        query = """
            INSERT INTO mission_logs (asset_id, command, params, result)
            VALUES ($1, $2, $3, $4)
        """
        async with _connect() as conn:
            await conn.execute(query, log.asset_id, log.command, log.params, log.result)

    async def list_for_asset(self, asset_id: str, limit: int = 50) -> list[MissionLog]:
        """Return recent mission logs for one asset."""
        query = """
            SELECT id, asset_id, command, params, result, created_at
            FROM mission_logs
            WHERE asset_id = $1
            ORDER BY id DESC
            LIMIT $2
        """
        async with _connect() as conn:
            rows = await conn.fetch(query, asset_id, limit)
        return [MissionLog(**_row_to_dict(row)) for row in rows]


# ── License ───────────────────────────────────────────────────────────────────


class _LicenseRepository:
    async def get_active(self) -> LicenseRecord | None:
        """Return the latest active license record, if one exists."""
        query = """
            SELECT id, license_key, org_name, expiry_date, seat_count, activated_at, is_active
            FROM licenses
            WHERE is_active = TRUE
            ORDER BY id DESC
            LIMIT 1
        """
        async with _connect() as conn:
            row = await conn.fetchrow(query)
        return LicenseRecord(**_row_to_dict(row)) if row is not None else None

    async def get_by_key(self, key: str) -> LicenseRecord | None:
        """Return a license record by its activation key."""
        query = """
            SELECT id, license_key, org_name, expiry_date, seat_count, activated_at, is_active
            FROM licenses
            WHERE license_key = $1
        """
        async with _connect() as conn:
            row = await conn.fetchrow(query, key)
        return LicenseRecord(**_row_to_dict(row)) if row is not None else None

    async def insert(self, record: LicenseRecord) -> None:
        """Insert a new license record into Supabase."""
        query = """
            INSERT INTO licenses (
                license_key,
                org_name,
                expiry_date,
                seat_count,
                activated_at,
                is_active
            )
            VALUES ($1, $2, $3::date, $4, COALESCE($5::timestamptz, NOW()), $6)
        """
        async with _connect() as conn:
            await conn.execute(
                query,
                record.license_key,
                record.org_name,
                record.expiry_date,
                record.seat_count,
                record.activated_at,
                record.is_active,
            )

    async def deactivate(self, key: str) -> None:
        """Mark a license as inactive."""
        async with _connect() as conn:
            await conn.execute(
                "UPDATE licenses SET is_active = FALSE WHERE license_key = $1", key
            )


# ── Mission Runs ──────────────────────────────────────────────────────────────


class _MissionRunRepository:
    async def create(self, run: MissionRun) -> int:
        """Insert one mission run row and return its ID."""
        query = """
            INSERT INTO mission_runs (
                simulation_id, asset_id, prompt, status,
                started_at, ended_at, duration_ms, ttft_ms,
                tool_call_count, survivors_detected, survivors_rescued,
                result_summary, error_message, langfuse_trace_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
            RETURNING id
        """
        async with _connect() as conn:
            row = await conn.fetchrow(
                query,
                run.simulation_id,
                run.asset_id,
                run.prompt,
                run.status,
                run.started_at,
                run.ended_at,
                run.duration_ms,
                run.ttft_ms,
                run.tool_call_count,
                run.survivors_detected,
                run.survivors_rescued,
                run.result_summary,
                run.error_message,
                run.langfuse_trace_id,
            )
        return int(row["id"])

    async def list_recent(self, limit: int = 50) -> list[MissionRun]:
        """Return the most recent mission runs, newest first."""
        query = """
            SELECT id, simulation_id, asset_id, prompt, status,
                   started_at, ended_at, duration_ms, ttft_ms,
                   tool_call_count, survivors_detected, survivors_rescued,
                   result_summary, error_message, langfuse_trace_id, created_at
            FROM mission_runs
            ORDER BY id DESC
            LIMIT $1
        """
        async with _connect() as conn:
            rows = await conn.fetch(query, limit)
        return [MissionRun(**_row_to_dict(row)) for row in rows]

    async def overview(self) -> dict[str, Any]:
        """Return dashboard overview aggregates in a single query."""
        query = """
            SELECT
              COUNT(*)                                                        AS total_missions,
              AVG(ttft_ms) FILTER (WHERE ttft_ms IS NOT NULL)                 AS avg_ttft_ms,
              AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL)         AS avg_duration_ms,
              COALESCE(SUM(survivors_rescued), 0)                             AS total_survivors_rescued,
              COALESCE(SUM(survivors_detected), 0)                            AS total_survivors_detected,
              COALESCE(SUM(tool_call_count), 0)                               AS total_tool_calls,
              CASE WHEN COALESCE(SUM(survivors_detected), 0) > 0
                   THEN 100.0 * SUM(survivors_rescued) / SUM(survivors_detected)
                   ELSE 0 END                                                 AS rescue_success_rate,
              AVG(EXTRACT(EPOCH FROM (ended_at - started_at)))
                  FILTER (WHERE status='success' AND survivors_rescued > 0)   AS avg_rescue_time_s
            FROM mission_runs
        """
        async with _connect() as conn:
            row = await conn.fetchrow(query)
        result = _row_to_dict(row) if row is not None else {}
        # Cast Decimal/numeric types to float for JSON serialisation.
        for key in (
            "avg_ttft_ms",
            "avg_duration_ms",
            "rescue_success_rate",
            "avg_rescue_time_s",
        ):
            if result.get(key) is not None:
                result[key] = float(result[key])
        for key in (
            "total_missions",
            "total_survivors_rescued",
            "total_survivors_detected",
            "total_tool_calls",
        ):
            if result.get(key) is not None:
                result[key] = int(result[key])
        return result


# ── Singletons ────────────────────────────────────────────────────────────────

asset_repo = _AssetRepository()
mission_log_repo = _MissionLogRepository()
license_repo = _LicenseRepository()
mission_run_repo = _MissionRunRepository()
