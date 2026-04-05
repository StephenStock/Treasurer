"""Minimum password length (portal users, login reset, bootstrap, table admin)."""

from __future__ import annotations

import os


def min_password_length_from_environ() -> int:
    """Read ``TREASURER_PASSWORD_MIN_LENGTH`` (default 10). Clamped to 6–128."""
    raw = os.environ.get("TREASURER_PASSWORD_MIN_LENGTH", "10").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 10
    return max(6, min(128, n))
