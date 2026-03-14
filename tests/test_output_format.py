"""Unit tests for command output formatting policy."""
from __future__ import annotations

from backend.output_format import (
    is_structured_sweep_report,
    is_sweep_scan_prompt,
    prefer_structured_sweep_report,
)


def test_is_sweep_scan_prompt_detects_sweep_scan_intent() -> None:
    assert is_sweep_scan_prompt("please sweep scan the target building") is True
    assert is_sweep_scan_prompt("scan building at -15,-20") is False


def test_is_structured_sweep_report_detects_header() -> None:
    assert is_structured_sweep_report("SWEEP SCAN COMPLETE — BEACON-01") is True
    assert is_structured_sweep_report("Sweep scan of building 0 complete.") is False


def test_prefer_structured_sweep_report_for_sweep_prompt() -> None:
    structured = (
        "SWEEP SCAN COMPLETE — BEACON-01\n"
        "  Building  : X [-19.0, -11.0] Z [-24.0, -16.0]"
    )
    paraphrase = "Sweep scan of building 0 complete."
    selected = prefer_structured_sweep_report(
        prompt="sweep scan around the building",
        text_candidates=[structured, paraphrase],
        fallback_text=paraphrase,
    )
    assert selected == structured


def test_prefer_structured_sweep_report_keeps_fallback_for_non_sweep() -> None:
    structured = "SWEEP SCAN COMPLETE — BEACON-01"
    fallback = "General movement completed."
    selected = prefer_structured_sweep_report(
        prompt="move beacon-01 to base",
        text_candidates=[structured],
        fallback_text=fallback,
    )
    assert selected == fallback
