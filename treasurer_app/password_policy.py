"""Minimum password length (portal users, login reset, bootstrap, table admin)."""

from __future__ import annotations

import os


def min_password_length_from_environ() -> int:
    """Read ``TREASURER_PASSWORD_MIN_LENGTH`` (default 8 so the shared initial login ``password`` is valid). Clamped to 6–128."""
    raw = os.environ.get("TREASURER_PASSWORD_MIN_LENGTH", "8").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 8
    return max(6, min(128, n))


def default_portal_initial_password(min_len: int) -> str:
    """Pre-filled value for Portal users → Add user → Initial password.

    Uses ``TREASURER_DEFAULT_INITIAL_PASSWORD`` if set, otherwise ``password``.
    If the result is shorter than ``min_len``, it is right-padded with ``0`` so it
    still meets the minimum (only when ``TREASURER_PASSWORD_MIN_LENGTH`` is raised above 8).
    """
    custom = os.environ.get("TREASURER_DEFAULT_INITIAL_PASSWORD", "").strip()
    core = custom if custom else "password"
    if len(core) < min_len:
        core = core + ("0" * (min_len - len(core)))
    return core[:128]
