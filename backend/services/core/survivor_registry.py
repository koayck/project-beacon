from __future__ import annotations

from collections.abc import Iterable

_detected_survivor_ids: set[int] = set()
_supplied_target_keys: set[str] = set()


def normalize_survivor_id(value: object) -> int | None:
    try:
        value_float = float(value)
    except (TypeError, ValueError):
        value_float = None
    if value_float is not None and value_float.is_integer():
        return int(value_float)
    try:
        raw = value.strip()
    except AttributeError:
        return None
    if raw.isdigit():
        return int(raw)
    return None


def register_detected_survivors(rows: Iterable[dict]) -> int:
    before = len(_detected_survivor_ids)
    for row in rows:
        try:
            row_get = row.get
        except AttributeError:
            continue
        survivor_id = normalize_survivor_id(row_get("id"))
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
    try:
        target_get = target.get
    except AttributeError:
        return None
    survivor_id = normalize_survivor_id(target_get("id"))
    if survivor_id is not None:
        return f"id:{survivor_id}"

    try:
        x = float(target_get("x"))
        z = float(target_get("z"))
    except (TypeError, ValueError):
        return None
    try:
        y_value = float(target_get("y"))
    except (TypeError, ValueError):
        y_value = 0.0
    return f"xyz:{x:.2f},{y_value:.2f},{z:.2f}"


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
        try:
            row.get
        except AttributeError:
            continue
        register_supplied_target(row)
    return len(_supplied_target_keys) - before


def clear_supplied_targets() -> None:
    _supplied_target_keys.clear()


def get_supplied_target_keys() -> set[str]:
    return set(_supplied_target_keys)
