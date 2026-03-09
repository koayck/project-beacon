"""Unit tests for the offline license validator."""
from __future__ import annotations

import hashlib
from datetime import date, timedelta

import pytest

from backend.licensing.validator import validate_format, check_expiry, _checksum


def _make_valid_key(g1: str = "ABCD", g2: str = "EF12", g3: str = "3456") -> str:
    checksum = _checksum(g1 + g2 + g3)
    return f"BEACON-{g1}-{g2}-{g3}-{checksum}"


# ── Format validation ─────────────────────────────────────────────────────────

def test_valid_key_passes():
    key = _make_valid_key()
    ok, err = validate_format(key)
    assert ok is True
    assert err == ""


def test_wrong_prefix_fails():
    ok, err = validate_format("NOTBEACON-ABCD-EF12-3456-XXXX")
    assert ok is False


def test_wrong_length_fails():
    ok, err = validate_format("BEACON-AB-EF12-3456-XXXX")
    assert ok is False


def test_bad_checksum_fails():
    ok, err = validate_format("BEACON-ABCD-EF12-3456-ZZZZ")
    assert ok is False
    assert "checksum" in err.lower()


def test_lowercase_accepted():
    key = _make_valid_key().lower()
    ok, _ = validate_format(key)
    assert ok is True  # validator normalises to uppercase


# ── Expiry check ──────────────────────────────────────────────────────────────

def test_future_expiry_is_valid():
    future = (date.today() + timedelta(days=30)).isoformat()
    valid, days = check_expiry(future)
    assert valid is True
    assert days == 30


def test_past_expiry_is_invalid():
    past = (date.today() - timedelta(days=5)).isoformat()
    valid, days = check_expiry(past)
    assert valid is False
    assert days == -5


def test_today_expiry_is_valid():
    today = date.today().isoformat()
    valid, days = check_expiry(today)
    assert valid is True
    assert days == 0
