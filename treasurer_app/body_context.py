"""Session-backed Lodge vs Chapter URL context and role lens for the signed-in user."""

from __future__ import annotations

SESSION_KEY_APP_BODY = "app_body"
SESSION_KEY_FOCUS_ROLE = "focus_role_code"
SESSION_KEY_PICKED_WORKSPACE = "picked_workspace"
VALID_BODIES = frozenset({"lodge", "chapter"})

# Lodge bank/statement/settings UI: Treasurer plus Admin (bootstrap operator accounts).
LODGE_TREASURER_UI_ROLE_CODES = frozenset({"TREASURER", "ADMIN"})

# Only these body+role pairs use the implemented lodge treasurer app as their home.
IMPLEMENTED_WORKSPACE_PAIRS = frozenset({("lodge", "TREASURER"), ("lodge", "ADMIN")})


def get_active_body(session) -> str:
    raw = session.get(SESSION_KEY_APP_BODY, "lodge")
    return raw if raw in VALID_BODIES else "lodge"


def set_active_body(session, body: str) -> None:
    if body in VALID_BODIES:
        session[SESSION_KEY_APP_BODY] = body
        session.modified = True


def valid_role_codes() -> set[str]:
    from .auth_store import ROLE_DEFINITIONS

    return {r[0] for r in ROLE_DEFINITIONS}


def focus_allowed_role_codes_from_assignments(assignments: list[dict[str, str]]) -> frozenset[str]:
    """Union of role codes appearing in the user's workspace list (waffle)."""
    return frozenset(a["role_code"] for a in assignments if a.get("role_code"))


def picked_workspace_pair(session) -> tuple[str, str] | None:
    """Session workspace from the waffle: 'lodge:TREASURER' / 'chapter:SECRETARY', etc."""
    raw = session.get(SESSION_KEY_PICKED_WORKSPACE)
    if not raw or ":" not in raw:
        return None
    b, _, code = str(raw).partition(":")
    b = b.strip().lower()
    code = code.strip().upper()
    if b not in VALID_BODIES or code not in valid_role_codes():
        return None
    return b, code


def set_picked_workspace(session, body: str, role_code: str) -> None:
    if body in VALID_BODIES and role_code in valid_role_codes():
        session[SESSION_KEY_PICKED_WORKSPACE] = f"{body}:{role_code}"
        session.modified = True


def workspace_pair_is_implemented(body: str, role_code: str) -> bool:
    return (body, role_code) in IMPLEMENTED_WORKSPACE_PAIRS


def _default_focus_among_allowed(session, allowed: frozenset[str]) -> str:
    """Prefer session if valid, else Treasurer if allowed, else lowest sort_order in ROLE_DEFINITIONS."""
    from .auth_store import ROLE_DEFINITIONS

    raw = session.get(SESSION_KEY_FOCUS_ROLE)
    if raw in allowed:
        return raw
    if "TREASURER" in allowed:
        return "TREASURER"
    for code, _lbl, _so in sorted(ROLE_DEFINITIONS, key=lambda x: x[2]):
        if code in allowed:
            return code
    return sorted(allowed)[0]


def get_focus_role_code(session, current_user, allowed_codes: frozenset[str] | None = None) -> str:
    """Role shown in the header. If only one role is allowed for this user, always use it."""
    valid = valid_role_codes()
    if allowed_codes is not None and allowed_codes:
        allowed = frozenset(c for c in allowed_codes if c in valid)
        if not allowed:
            return "TREASURER"
        if len(allowed) == 1:
            return next(iter(allowed))
        return _default_focus_among_allowed(session, allowed)
    raw = session.get(SESSION_KEY_FOCUS_ROLE)
    if raw and raw in valid:
        return raw
    try:
        if current_user.is_authenticated:
            rc = getattr(current_user, "role_code", None) or "TREASURER"
            return rc if rc in valid else "TREASURER"
    except Exception:
        pass
    return "TREASURER"


def set_focus_role_code(session, code: str) -> None:
    if code in valid_role_codes():
        session[SESSION_KEY_FOCUS_ROLE] = code
        session.modified = True


def role_display_name(code: str) -> str:
    from .auth_store import ROLE_DEFINITIONS

    for c, label, _so in ROLE_DEFINITIONS:
        if c == code:
            return label
    return code.replace("_", " ").title()


def workspace_label_for_pair(body: str, role_code: str) -> str:
    prefix = "Chapter" if body == "chapter" else "Lodge"
    return f"{prefix} · {role_display_name(role_code)}"
