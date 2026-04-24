from __future__ import annotations

import os
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiosqlite

from backend.db.models import Asset, MissionLog, LicenseRecord, MissionRun

_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()


def _get_db_path() -> Path:
    return Path(os.environ.get("BEACON_DB_PATH", "./beacon.db")).expanduser().resolve()


async def init_db() -> None:
    """Create the SQLite database and apply the schema if tables do not exist."""
    path = _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(str(path)) as conn:
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.executescript(_SCHEMA_SQL)


@asynccontextmanager
async def _connect() -> AsyncIterator[aiosqlite.Connection]:
    """Open a temporary aiosqlite connection with row-factory and foreign-key support."""
    async with aiosqlite.connect(str(_get_db_path())) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys=ON")
        yield conn


def _row_to_dict(row: aiosqlite.Row) -> dict[str, Any]:
    """Convert an aiosqlite Row into a plain dictionary."""
    return dict(row)


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
            cur = await conn.execute(query)
            rows = await cur.fetchall()
        return [Asset(**_row_to_dict(row)) for row in rows]

    async def get(self, asset_id: str) -> Asset | None:
        """Return one asset by its external asset identifier."""
        query = """
            SELECT id, asset_id, asset_class, grpc_host, grpc_port, registered_at
            FROM assets
            WHERE asset_id = ?
        """
        async with _connect() as conn:
            cur = await conn.execute(query, (asset_id,))
            row = await cur.fetchone()
        return Asset(**_row_to_dict(row)) if row is not None else None

    async def upsert(self, asset: Asset) -> None:
        """Insert or update an asset row."""
        query = """
            INSERT INTO assets (asset_id, asset_class, grpc_host, grpc_port)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (asset_id) DO UPDATE SET
                asset_class = EXCLUDED.asset_class,
                grpc_host   = EXCLUDED.grpc_host,
                grpc_port   = EXCLUDED.grpc_port
        """
        async with _connect() as conn:
            await conn.execute(query, (asset.asset_id, asset.asset_class, asset.grpc_host, asset.grpc_port))
            await conn.commit()

    async def delete(self, asset_id: str) -> None:
        """Delete an asset row by asset identifier."""
        async with _connect() as conn:
            await conn.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
            await conn.commit()


# ── Mission Logs ──────────────────────────────────────────────────────────────


class _MissionLogRepository:
    async def create(self, log: MissionLog) -> None:
        """Persist one mission log entry."""
        query = """
            INSERT INTO mission_logs (asset_id, command, params, result)
            VALUES (?, ?, ?, ?)
        """
        async with _connect() as conn:
            await conn.execute(query, (log.asset_id, log.command, log.params, log.result))
            await conn.commit()

    async def list_for_asset(self, asset_id: str, limit: int = 50) -> list[MissionLog]:
        """Return recent mission logs for one asset."""
        query = """
            SELECT id, asset_id, command, params, result, created_at
            FROM mission_logs
            WHERE asset_id = ?
            ORDER BY id DESC
            LIMIT ?
        """
        async with _connect() as conn:
            cur = await conn.execute(query, (asset_id, limit))
            rows = await cur.fetchall()
        return [MissionLog(**_row_to_dict(row)) for row in rows]


# ── License ───────────────────────────────────────────────────────────────────


class _LicenseRepository:
    async def get_active(self) -> LicenseRecord | None:
        """Return the latest active license record, if one exists."""
        query = """
            SELECT id, license_key, org_name, expiry_date, seat_count, activated_at, is_active
            FROM licenses
            WHERE is_active = 1
            ORDER BY id DESC
            LIMIT 1
        """
        async with _connect() as conn:
            cur = await conn.execute(query)
            row = await cur.fetchone()
        return LicenseRecord(**_row_to_dict(row)) if row is not None else None

    async def get_by_key(self, key: str) -> LicenseRecord | None:
        """Return a license record by its activation key."""
        query = """
            SELECT id, license_key, org_name, expiry_date, seat_count, activated_at, is_active
            FROM licenses
            WHERE license_key = ?
        """
        async with _connect() as conn:
            cur = await conn.execute(query, (key,))
            row = await cur.fetchone()
        return LicenseRecord(**_row_to_dict(row)) if row is not None else None

    async def insert(self, record: LicenseRecord) -> None:
        """Insert a new license record."""
        activated_at = record.activated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        query = """
            INSERT INTO licenses (
                license_key, org_name, expiry_date, seat_count, activated_at, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """
        async with _connect() as conn:
            await conn.execute(
                query,
                (
                    record.license_key,
                    record.org_name,
                    record.expiry_date,
                    record.seat_count,
                    activated_at,
                    int(record.is_active),
                ),
            )
            await conn.commit()

    async def deactivate(self, key: str) -> None:
        """Mark a license as inactive."""
        async with _connect() as conn:
            await conn.execute("UPDATE licenses SET is_active = 0 WHERE license_key = ?", (key,))
            await conn.commit()


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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        async with _connect() as conn:
            cur = await conn.execute(
                query,
                (
                    run.simulation_id,
                    run.asset_id,
                    run.prompt,
                    run.status,
                    run.started_at.isoformat() if run.started_at else None,
                    run.ended_at.isoformat() if run.ended_at else None,
                    run.duration_ms,
                    run.ttft_ms,
                    run.tool_call_count,
                    run.survivors_detected,
                    run.survivors_rescued,
                    run.result_summary,
                    run.error_message,
                    run.langfuse_trace_id,
                ),
            )
            await conn.commit()
            return cur.lastrowid or 0

    async def list_recent(self, limit: int = 50) -> list[MissionRun]:
        """Return the most recent mission runs, newest first."""
        query = """
            SELECT id, simulation_id, asset_id, prompt, status,
                   started_at, ended_at, duration_ms, ttft_ms,
                   tool_call_count, survivors_detected, survivors_rescued,
                   result_summary, error_message, langfuse_trace_id, created_at
            FROM mission_runs
            ORDER BY id DESC
            LIMIT ?
        """
        async with _connect() as conn:
            cur = await conn.execute(query, (limit,))
            rows = await cur.fetchall()
        return [MissionRun(**_row_to_dict(row)) for row in rows]

    async def overview(self) -> dict[str, Any]:
        """Return dashboard overview aggregates in a single query."""
        query = """
            SELECT
              COUNT(*)                                                                AS total_missions,
              AVG(ttft_ms) FILTER (WHERE ttft_ms IS NOT NULL)                         AS avg_ttft_ms,
              AVG(duration_ms) FILTER (WHERE duration_ms IS NOT NULL)                 AS avg_duration_ms,
              COALESCE(SUM(survivors_rescued), 0)                                     AS total_survivors_rescued,
              COALESCE(SUM(survivors_detected), 0)                                    AS total_survivors_detected,
              COALESCE(SUM(tool_call_count), 0)                                       AS total_tool_calls,
              CASE WHEN COALESCE(SUM(survivors_detected), 0) > 0
                   THEN 100.0 * SUM(survivors_rescued) / SUM(survivors_detected)
                   ELSE 0 END                                                         AS rescue_success_rate,
              AVG((JULIANDAY(ended_at) - JULIANDAY(started_at)) * 86400.0)
                  FILTER (WHERE status='success' AND survivors_rescued > 0)           AS avg_rescue_time_s
            FROM mission_runs
        """
        async with _connect() as conn:
            cur = await conn.execute(query)
            row = await cur.fetchone()
        result = _row_to_dict(row) if row is not None else {}
        for key in ("avg_ttft_ms", "avg_duration_ms", "rescue_success_rate", "avg_rescue_time_s"):
            if result.get(key) is not None:
                result[key] = float(result[key])
        for key in ("total_missions", "total_survivors_rescued", "total_survivors_detected", "total_tool_calls"):
            if result.get(key) is not None:
                result[key] = int(result[key])
        return result


# ── Singletons ────────────────────────────────────────────────────────────────

asset_repo = _AssetRepository()
mission_log_repo = _MissionLogRepository()
license_repo = _LicenseRepository()
mission_run_repo = _MissionRunRepository()
