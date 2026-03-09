from __future__ import annotations

import hashlib
import re
from datetime import date

# Key format: BEACON-XXXX-XXXX-XXXX-CHKK
# Groups 1-3 are payload; group 4 is a 4-char checksum.
_KEY_RE = re.compile(
    r"^BEACON-([A-Z0-9]{4})-([A-Z0-9]{4})-([A-Z0-9]{4})-([A-Z0-9]{4})$"
)


def validate_format(key: str) -> tuple[bool, str]:
    """
    Returns (is_valid, error_message).
    Checks prefix, character set, length, and checksum.
    """
    key = key.strip().upper()
    m = _KEY_RE.match(key)
    if not m:
        return False, "Invalid key format. Expected BEACON-XXXX-XXXX-XXXX-XXXX"

    g1, g2, g3, checksum = m.groups()
    expected = _checksum(g1 + g2 + g3)
    if checksum != expected:
        return False, "Invalid key (checksum mismatch — check for typos)"

    return True, ""


def check_expiry(expiry_date: str) -> tuple[bool, int]:
    """
    Returns (is_valid, days_remaining).
    Negative days_remaining means already expired.
    """
    expiry = date.fromisoformat(expiry_date)
    today = date.today()
    delta = (expiry - today).days
    return delta >= 0, delta


def _checksum(payload: str) -> str:
    """Deterministic 4-char hex checksum derived from payload."""
    digest = hashlib.sha256(payload.encode()).hexdigest()
    return digest[:4].upper()
