from backend.services.mission_summary import pick_best_summary


def test_returns_none_for_empty_input() -> None:
    assert pick_best_summary([]) is None


def test_filters_known_sentinels() -> None:
    assert pick_best_summary(["Report emitted.", "  ", ""]) is None


def test_prefers_structured_marker_over_longer_text() -> None:
    long_plain = "x" * 500
    structured = "═══ AREA SCAN COMPLETE ═══ short"
    assert pick_best_summary([long_plain, structured]) == structured


def test_picks_longest_when_no_structured_candidate() -> None:
    short = "ok"
    longer = "Mission completed without incident."
    assert pick_best_summary([short, longer]) == longer


def test_strips_sentinels_then_picks_longest() -> None:
    assert pick_best_summary(["Report emitted.", "actual result here"]) == "actual result here"


def test_recognizes_total_marker() -> None:
    assert pick_best_summary(["short", "TOTAL SUPPLY DISPATCHED: 1"]) == "TOTAL SUPPLY DISPATCHED: 1"


def test_recognizes_complete_marker() -> None:
    assert (
        pick_best_summary(["short", "AREA SCAN COMPLETE — 2 building(s)"])
        == "AREA SCAN COMPLETE — 2 building(s)"
    )


def test_among_multiple_structured_picks_longest() -> None:
    a = "═══ COMPLETE ═══"
    b = "═══ COMPLETE ═══ with details" * 3
    assert pick_best_summary([a, b]) == b
