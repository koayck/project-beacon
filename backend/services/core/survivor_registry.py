from __future__ import annotations

from collections.abc import Iterable

_detected_survivor_ids: set[int] = set()
_supplied_target_keys: set[str] = set()


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


def _target_key(target: dict) -> str | None:
    if not isinstance(target, dict):
        return None
    survivor_id = normalize_survivor_id(target.get("id"))
    if survivor_id is not None:
        return f"id:{survivor_id}"

    x = target.get("x")
    y = target.get("y")
    z = target.get("z")
    if not isinstance(x, (int, float)) or not isinstance(z, (int, float)):
        return None
    y_value = float(y) if isinstance(y, (int, float)) else 0.0
    return f"xyz:{float(x):.2f},{y_value:.2f},{float(z):.2f}"


def register_supplied_target(target: dict) -> bool:
    key = _target_key(target)
    if key is None:
        return False
    before = len(_supplied_target_keys)
    _supplied_target_keys.add(key)
    return len(_supplied_target_keys) > before


def register_supplied_targets(rows: Iterable[dict]) -> int:
    before = len(_supplied_target_keys)
    for row in rows:
        if isinstance(row, dict):
            register_supplied_target(row)
    return len(_supplied_target_keys) - before


def clear_supplied_targets() -> None:
    _supplied_target_keys.clear()


def get_supplied_target_keys() -> set[str]:
    return set(_supplied_target_keys)
