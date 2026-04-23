from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import asyncpg


@dataclass(frozen=True)
class ParsedScanTargets:
    """Structured targets parsed from a scan command prompt.

    Attributes:
        building_ids: Normalized building IDs inferred from coordinate mentions.
        has_scan_intent: True when the prompt is a scan intent; False otherwise.
    """

    building_ids: list[int]
    has_scan_intent: bool


class SimulationStore:
    """Supabase-backed simulation state store.

    The store persists simulation snapshots keyed by a stable simulation ID so
    frontend refreshes and backend command loops can share mission intel.
    """

    _COORD_TRIPLE_PATTERN = re.compile(
        r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)",
        re.IGNORECASE,
    )
    _COORD_TRIPLE_INLINE_PATTERN = re.compile(
        r"(?:^|[^\d.-])(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)(?:$|[^\d.-])",
        re.IGNORECASE,
    )

    def __init__(self, db_url: str) -> None:
        """Initialize the simulation store.

        Args:
            db_url: SQLAlchemy-style or plain Postgres DSN.
        """
        self._dsn = self._normalize_dsn(db_url)
        self._pool: asyncpg.Pool | None = None

    async def start(self) -> None:
        """Open the asyncpg pool and ensure schema objects exist."""
        if self._pool is not None:
            return
        self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=1, max_size=4)

    async def stop(self) -> None:
        """Close the asyncpg pool if it is active."""
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None

    async def create(self, simulation_id: str | None = None) -> str:
        """Create a simulation row if missing and return its ID.

        Args:
            simulation_id: Optional caller-supplied stable ID.

        Returns:
            Simulation ID persisted in the table.
        """
        sim_id = simulation_id.strip() if isinstance(simulation_id, str) and simulation_id.strip() else str(uuid4())
        pool = self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO simulation (id, scanned_buildings)
                VALUES ($1, '[]'::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                sim_id,
            )
        return sim_id

    async def get(self, simulation_id: str) -> dict[str, Any] | None:
        """Fetch one simulation snapshot.

        Args:
            simulation_id: Stable simulation ID.

        Returns:
            Simulation payload with JSON-decoded scanned buildings, or None.
        """
        pool = self._require_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, scanned_buildings, created_at, updated_at
                FROM simulation
                WHERE id = $1
                """,
                simulation_id,
            )
        if row is None:
            return None
        scanned_buildings = self._decode_json(row["scanned_buildings"], fallback=[])
        return {
            "id": row["id"],
            "scanned_buildings": scanned_buildings,
            "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
        }

    async def mark_buildings_scanned(self, simulation_id: str, building_ids: Iterable[int]) -> None:
        """Mark one or more building IDs as scanned in this simulation.

        Args:
            simulation_id: Stable simulation ID.
            building_ids: Building IDs inferred from scan prompts.
        """
        if not building_ids:
            return
        await self.create(simulation_id)
        snapshot = await self.get(simulation_id)
        if snapshot is None:
            return

        rows = self._to_building_map(snapshot.get("scanned_buildings", []))
        for building_id in building_ids:
            key = str(int(building_id))
            if key not in rows:
                rows[key] = {
                    "building_id": int(building_id),
                    "detected_survivors": [],
                }

        await self._write_scanned_buildings(simulation_id, list(rows.values()))

    async def get_already_scanned_buildings(self, simulation_id: str, building_ids: Iterable[int]) -> list[int]:
        """Return the subset of building IDs already scanned in this simulation.

        Args:
            simulation_id: Stable simulation ID.
            building_ids: Candidate building IDs to check.

        Returns:
            Sorted deduplicated list of already scanned building IDs.
        """
        snapshot = await self.get(simulation_id)
        if snapshot is None:
            return []
        rows = self._to_building_map(snapshot.get("scanned_buildings", []))
        already = {int(bid) for bid in building_ids if str(int(bid)) in rows}
        return sorted(already)

    async def merge_survivor_state(self, simulation_id: str, scanned_buildings: list[dict[str, Any]]) -> dict[str, Any]:
        """Merge frontend survivor state into persisted scanned building intel.

        Args:
            simulation_id: Stable simulation ID.
            scanned_buildings: Building rows with detected survivor lists.

        Returns:
            Updated simulation snapshot.
        """
        await self.create(simulation_id)
        existing = await self.get(simulation_id)
        if existing is None:
            existing_rows: dict[str, dict[str, Any]] = {}
        else:
            existing_rows = self._to_building_map(existing.get("scanned_buildings", []))

        for candidate in scanned_buildings:
            building_id = self._safe_int(candidate.get("building_id"))
            if building_id is None:
                continue
            key = str(building_id)
            current = existing_rows.get(
                key,
                {"building_id": building_id, "detected_survivors": []},
            )
            current_survivors = self._to_survivor_map(current.get("detected_survivors", []))
            for survivor in candidate.get("detected_survivors", []):
                survivor_dict = self._sanitize_survivor(survivor)
                if survivor_dict is None:
                    continue
                s_key = self._survivor_key(survivor_dict)
                prior = current_survivors.get(s_key)
                if prior is None:
                    current_survivors[s_key] = survivor_dict
                    continue
                # Preserve supplied=true once observed.
                current_survivors[s_key] = {
                    **survivor_dict,
                    "supplied": bool(prior.get("supplied", False) or survivor_dict.get("supplied", False)),
                }
            current["detected_survivors"] = list(current_survivors.values())
            existing_rows[key] = current

        merged_rows = list(existing_rows.values())
        await self._write_scanned_buildings(simulation_id, merged_rows)
        snapshot = await self.get(simulation_id)
        return snapshot if snapshot is not None else {"id": simulation_id, "scanned_buildings": merged_rows}

    @staticmethod
    def parse_scan_targets(prompt: str, known_buildings: Iterable[dict[str, Any]]) -> ParsedScanTargets:
        """Parse scan target building IDs from command prompt text.

        Args:
            prompt: Raw user mission text.
            known_buildings: Iterable of building dicts containing id/cx/cz.

        Returns:
            Parsed scan targets with scan-intent flag.
        """
        text = prompt.strip().lower()
        has_scan_intent = "scan" in text
        if not has_scan_intent:
            return ParsedScanTargets(building_ids=[], has_scan_intent=False)

        coords = SimulationStore._extract_prompt_coords(prompt)

        if not coords:
            return ParsedScanTargets(building_ids=[], has_scan_intent=True)

        resolved: set[int] = set()
        for x, z in coords:
            building_id = SimulationStore._resolve_building_id(x, z, known_buildings)
            if building_id is not None:
                resolved.add(building_id)

        return ParsedScanTargets(building_ids=sorted(resolved), has_scan_intent=True)

    @staticmethod
    def _extract_prompt_coords(prompt: str) -> list[tuple[float, float]]:
        """Extract candidate X/Z scan coordinates from free-form prompt text.

        Args:
            prompt: Raw user prompt text.

        Returns:
            Ordered list of unique ``(x, z)`` coordinate pairs inferred from 3D
            coordinate triples, supporting both parenthesized and inline forms.
        """
        coords: list[tuple[float, float]] = []
        seen: set[tuple[float, float]] = set()

        for match in SimulationStore._COORD_TRIPLE_PATTERN.finditer(prompt):
            x = float(match.group(1))
            z = float(match.group(3))
            key = (round(x, 3), round(z, 3))
            if key in seen:
                continue
            seen.add(key)
            coords.append((x, z))

        for match in SimulationStore._COORD_TRIPLE_INLINE_PATTERN.finditer(prompt):
            x = float(match.group(1))
            z = float(match.group(3))
            key = (round(x, 3), round(z, 3))
            if key in seen:
                continue
            seen.add(key)
            coords.append((x, z))

        return coords

    async def _write_scanned_buildings(self, simulation_id: str, scanned_buildings: list[dict[str, Any]]) -> None:
        """Persist scanned building JSON payload for one simulation.

        Args:
            simulation_id: Stable simulation ID.
            scanned_buildings: Validated building rows to store.
        """
        pool = self._require_pool()
        payload = json.dumps(scanned_buildings)
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE simulation
                SET scanned_buildings = $2::jsonb,
                    updated_at = NOW()
                WHERE id = $1
                """,
                simulation_id,
                payload,
            )

    def _require_pool(self) -> asyncpg.Pool:
        """Return active pool or raise when store is not initialized."""
        if self._pool is None:
            raise RuntimeError("SimulationStore is not started")
        return self._pool

    @staticmethod
    def _normalize_dsn(db_url: str) -> str:
        """Normalize SQLAlchemy-style Postgres DSN into asyncpg-compatible DSN.

        Args:
            db_url: Raw DSN from environment.

        Returns:
            asyncpg-compatible Postgres DSN.
        """
        stripped = db_url.strip()
        if stripped.startswith("postgresql+asyncpg://"):
            return "postgresql://" + stripped[len("postgresql+asyncpg://") :]
        return stripped

    @staticmethod
    def _decode_json(value: Any, fallback: Any) -> Any:
        """Decode JSON from asyncpg value safely.

        Args:
            value: JSON/JSONB value from asyncpg row.
            fallback: Value returned for invalid payloads.

        Returns:
            Decoded JSON structure or fallback.
        """
        if value is None:
            return fallback
        if isinstance(value, (list, dict)):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return fallback
        return fallback

    @staticmethod
    def _to_building_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Convert scanned building list into normalized keyed map.

        Args:
            rows: Raw scanned building rows.

        Returns:
            Mapping keyed by normalized building_id string.
        """
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_dict = row if isinstance(row, dict) else None
            if row_dict is None:
                continue
            building_id = SimulationStore._safe_int(row_dict.get("building_id"))
            if building_id is None:
                continue
            key = str(building_id)
            out[key] = {
                "building_id": building_id,
                "detected_survivors": [
                    survivor
                    for survivor in row_dict.get("detected_survivors", [])
                    if SimulationStore._sanitize_survivor(survivor) is not None
                ],
            }
        return out

    @staticmethod
    def _to_survivor_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Convert survivor list into a key-indexed map.

        Args:
            rows: Survivor rows.

        Returns:
            Survivor mapping keyed by rounded XYZ coordinates.
        """
        out: dict[str, dict[str, Any]] = {}
        for survivor in rows:
            clean = SimulationStore._sanitize_survivor(survivor)
            if clean is None:
                continue
            out[SimulationStore._survivor_key(clean)] = clean
        return out

    @staticmethod
    def _sanitize_survivor(value: Any) -> dict[str, Any] | None:
        """Validate and normalize one survivor payload.

        Args:
            value: Candidate survivor payload.

        Returns:
            Normalized survivor dict or None when invalid.
        """
        candidate = value if isinstance(value, dict) else None
        if candidate is None:
            return None
        x = SimulationStore._safe_float(candidate.get("x"))
        y = SimulationStore._safe_float(candidate.get("y"))
        z = SimulationStore._safe_float(candidate.get("z"))
        if x is None or y is None or z is None:
            return None
        return {
            "x": round(x, 3),
            "y": round(y, 3),
            "z": round(z, 3),
            "supplied": bool(candidate.get("supplied", False)),
        }

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        """Convert arbitrary numeric value to float safely.

        Args:
            value: Candidate numeric value.

        Returns:
            Converted float or None when invalid.
        """
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        return number

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        """Convert arbitrary numeric value to int safely.

        Args:
            value: Candidate integer value.

        Returns:
            Converted int or None when invalid.
        """
        try:
            number = int(value)
        except (TypeError, ValueError):
            return None
        return number

    @staticmethod
    def _survivor_key(survivor: dict[str, Any]) -> str:
        """Build a stable survivor key from rounded coordinates.

        Args:
            survivor: Survivor payload with x/y/z.

        Returns:
            Stable survivor key string.
        """
        return f"{survivor['x']:.3f}|{survivor['y']:.3f}|{survivor['z']:.3f}"

    @staticmethod
    def _resolve_building_id(x: float, z: float, known_buildings: Iterable[dict[str, Any]]) -> int | None:
        """Resolve nearest building ID for a prompt coordinate pair.

        Args:
            x: Prompt X coordinate.
            z: Prompt Z coordinate.
            known_buildings: Building dictionaries with id/cx/cz fields.

        Returns:
            Building ID when a nearby building is found, otherwise None.
        """
        # Exact footprint match takes precedence when bounds are available.
        for row in known_buildings:
            if not isinstance(row, dict):
                continue
            building_id = SimulationStore._safe_int(row.get("id"))
            min_x = SimulationStore._safe_float(row.get("min_x"))
            max_x = SimulationStore._safe_float(row.get("max_x"))
            min_z = SimulationStore._safe_float(row.get("min_z"))
            max_z = SimulationStore._safe_float(row.get("max_z"))
            if (
                building_id is None
                or min_x is None
                or max_x is None
                or min_z is None
                or max_z is None
            ):
                continue
            if min_x <= x <= max_x and min_z <= z <= max_z:
                return building_id

        best_id: int | None = None
        best_dist = float("inf")
        for row in known_buildings:
            if not isinstance(row, dict):
                continue
            building_id = SimulationStore._safe_int(row.get("id"))
            cx = SimulationStore._safe_float(row.get("cx"))
            cz = SimulationStore._safe_float(row.get("cz"))
            if building_id is None or cx is None or cz is None:
                continue
            dist = math.hypot(cx - x, cz - z)
            if dist < best_dist:
                best_dist = dist
                best_id = building_id
        if best_id is None:
            return None
        # For free-form coordinates, allow a loose nearest-center fallback.
        return best_id if best_dist <= 12.0 else None
