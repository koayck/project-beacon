from __future__ import annotations

_SENTINELS: frozenset[str] = frozenset({"Report emitted."})
_STRUCTURED_MARKERS: tuple[str, ...] = ("═══", "COMPLETE", "TOTAL")


def pick_best_summary(candidates: list[str]) -> str | None:
    """Pick the most informative text from a run's text-bearing events.

    Filters known sentinels and whitespace-only strings, prefers candidates
    containing structured markers (visual dividers, completion banners,
    summary totals), and otherwise falls back to the longest remaining string.

    Args:
        candidates: All `text` and `final` event payloads collected during a
            mission run, in emission order.

    Returns:
        The best summary string, or None if no usable candidate exists.
    """
    cleaned = [c for c in candidates if c and c.strip() and c not in _SENTINELS]
    if not cleaned:
        return None
    structured = [c for c in cleaned if any(m in c for m in _STRUCTURED_MARKERS)]
    pool = structured if structured else cleaned
    return max(pool, key=len)
