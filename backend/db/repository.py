from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import aiosqlite

from backend.db.models import Asset, MissionLog, LicenseRecord

DB_PATH = os.environ.get("BEACON_DB", str(Path(__file__).parent.parent.parent / "beacon.db"))
_SCHEMA = Path(__file__).parent / "schema.sql"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(_SCHEMA.read_text())
        await db.commit()


# ── Assets ────────────────────────────────────────────────────────────────────

class _AssetRepository:
    async def list_all(self) -> list[Asset]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM assets ORDER BY id") as cur:
                rows = await cur.fetchall()
        return [Asset(**dict(r)) for r in rows]

    async def get(self, asset_id: str) -> Optional[Asset]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM assets WHERE asset_id = ?", (asset_id,)
            ) as cur:
                row = await cur.fetchone()
        return Asset(**dict(row)) if row else None

    async def upsert(self, asset: Asset) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO assets (asset_id, asset_class, grpc_host, grpc_port)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(asset_id) DO UPDATE SET
                    grpc_host = excluded.grpc_host,
                    grpc_port = excluded.grpc_port
                """,
                (asset.asset_id, asset.asset_class, asset.grpc_host, asset.grpc_port),
            )
            await db.commit()

    async def delete(self, asset_id: str) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM assets WHERE asset_id = ?", (asset_id,))
            await db.commit()


# ── Mission Logs ──────────────────────────────────────────────────────────────

class _MissionLogRepository:
    async def create(self, log: MissionLog) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO mission_logs (asset_id, command, params, result) VALUES (?, ?, ?, ?)",
                (log.asset_id, log.command, log.params, log.result),
            )
            await db.commit()

    async def list_for_asset(self, asset_id: str, limit: int = 50) -> list[MissionLog]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM mission_logs WHERE asset_id = ? ORDER BY id DESC LIMIT ?",
                (asset_id, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [MissionLog(**dict(r)) for r in rows]


# ── License ───────────────────────────────────────────────────────────────────

class _LicenseRepository:
    async def get_active(self) -> Optional[LicenseRecord]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM licenses WHERE is_active = 1 ORDER BY id DESC LIMIT 1"
            ) as cur:
                row = await cur.fetchone()
        return LicenseRecord(**dict(row)) if row else None

    async def get_by_key(self, key: str) -> Optional[LicenseRecord]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM licenses WHERE license_key = ?", (key,)
            ) as cur:
                row = await cur.fetchone()
        return LicenseRecord(**dict(row)) if row else None

    async def insert(self, record: LicenseRecord) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                INSERT INTO licenses (license_key, org_name, expiry_date, seat_count)
                VALUES (?, ?, ?, ?)
                """,
                (record.license_key, record.org_name, record.expiry_date, record.seat_count),
            )
            await db.commit()

    async def deactivate(self, key: str) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE licenses SET is_active = 0 WHERE license_key = ?", (key,)
            )
            await db.commit()


# ── Singletons ────────────────────────────────────────────────────────────────

asset_repo = _AssetRepository()
mission_log_repo = _MissionLogRepository()
license_repo = _LicenseRepository()
