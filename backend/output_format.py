"""
Output formatting helpers for command responses and streamed text events.
"""
from __future__ import annotations


def is_sweep_scan_prompt(prompt: str) -> bool:
    """
    True when the user command is asking for a sweep scan workflow.
    """
    lower = prompt.lower()
    return "sweep" in lower and "scan" in lower


def is_structured_sweep_report(text: str) -> bool:
    """
    True when text matches the canonical structured sweep report header.
    """
    return "SWEEP SCAN COMPLETE" in text.upper()


def prefer_structured_sweep_report(
    prompt: str,
    text_candidates: list[str],
    fallback_text: str,
) -> str:
    """
    For sweep scan prompts, prefer the structured sweep report if available.
    """
    if not is_sweep_scan_prompt(prompt):
        return fallback_text

    for text in text_candidates:
        if is_structured_sweep_report(text):
            return text
    return fallback_text
