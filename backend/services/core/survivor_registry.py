from __future__ import annotations

from collections.abc import Iterable

_detected_survivor_ids: set[int] = set()


def normalize_survivor_id(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        raw = value.strip()
        if raw.isdigit():
            return int(raw)
    return None


def register_detected_survivors(rows: Iterable[dict]) -> int:
    before = len(_detected_survivor_ids)
    for row in rows:
        if not isinstance(row, dict):
            continue
        survivor_id = normalize_survivor_id(row.get("id"))
        if survivor_id is None:
            continue
        _detected_survivor_ids.add(survivor_id)
    return len(_detected_survivor_ids) - before


def clear_detected_survivors() -> None:
    _detected_survivor_ids.clear()


def get_detected_survivor_ids() -> set[int]:
    # Return a copy to prevent accidental mutation from callers.
    return set(_detected_survivor_ids)
