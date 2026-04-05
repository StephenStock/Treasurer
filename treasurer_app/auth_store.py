"""Auth tables, seeds, and user/token queries (SQLite)."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

# Role codes stored in DB (stable identifiers).
ROLE_DEFINITIONS: list[tuple[str, str, int]] = [
    ("SECRETARY", "Secretary", 10),
    ("TREASURER", "Treasurer", 20),
    ("AUDITOR", "Auditor", 30),
    ("ADMIN", "Admin", 40),
    ("CHARITY_STEWARD", "Charity Steward", 50),
    ("MASTER", "Master", 60),
]

# Per-user admin capabilities (Portal users screen). Not role-based at runtime.
# Forms and Settings remain open to all signed-in users (see login_config.user_can).
PERMISSION_DEFINITIONS: list[tuple[str, str]] = [
    ("admin_users", "Manage portal users"),
    ("admin_table_editor", "Edit raw database tables (dangerous)"),
]

USER_ADMIN_GRANT_CODES = frozenset(code for code, _desc in PERMISSION_DEFINITIONS)


def ensure_auth_tables(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS roles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL UNIQUE,
            description TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS role_permissions (
            role_id INTEGER NOT NULL,
            permission_id INTEGER NOT NULL,
            allowed INTEGER NOT NULL DEFAULT 1,
            PRIMARY KEY (role_id, permission_id),
            FOREIGN KEY (role_id) REFERENCES roles (id) ON DELETE CASCADE,
            FOREIGN KEY (permission_id) REFERENCES permissions (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role_id INTEGER NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            FOREIGN KEY (role_id) REFERENCES roles (id)
        );

        CREATE INDEX IF NOT EXISTS idx_users_role_id ON users (role_id);

        CREATE TABLE IF NOT EXISTS user_workspaces (
            user_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            office_code TEXT NOT NULL,
            PRIMARY KEY (user_id, body, office_code),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_user_workspaces_user ON user_workspaces (user_id);

        CREATE TABLE IF NOT EXISTS user_admin_grants (
            user_id INTEGER NOT NULL,
            permission_code TEXT NOT NULL,
            PRIMARY KEY (user_id, permission_code),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_user_admin_grants_user ON user_admin_grants (user_id);

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_password_reset_tokens_hash ON password_reset_tokens (token_hash);
        """
    )
    _ensure_unique_constraints(db)

    role_ids: dict[str, int] = {}
    for code, display_name, sort_order in ROLE_DEFINITIONS:
        db.execute(
            """
            INSERT INTO roles (code, display_name, sort_order)
            VALUES (?, ?, ?)
            ON CONFLICT (code) DO UPDATE SET
                display_name = excluded.display_name,
                sort_order = excluded.sort_order
            """,
            (code, display_name, sort_order),
        )
        row = db.execute("SELECT id FROM roles WHERE code = ?", (code,)).fetchone()
        if row:
            role_ids[code] = int(row["id"])

    perm_ids: dict[str, int] = {}
    for code, description in PERMISSION_DEFINITIONS:
        db.execute(
            """
            INSERT INTO permissions (code, description)
            VALUES (?, ?)
            ON CONFLICT (code) DO UPDATE SET description = excluded.description
            """,
            (code, description),
        )
        row = db.execute("SELECT id FROM permissions WHERE code = ?", (code,)).fetchone()
        if row:
            perm_ids[code] = int(row["id"])

    _prune_permissions_not_in_definitions(db, set(perm_ids.keys()))

    for role_code, rid in role_ids.items():
        for _perm_code, pid in perm_ids.items():
            allowed = 1 if role_code == "ADMIN" else 0
            db.execute(
                """
                INSERT INTO role_permissions (role_id, permission_id, allowed)
                VALUES (?, ?, ?)
                ON CONFLICT(role_id, permission_id) DO UPDATE SET allowed = excluded.allowed
                """,
                (rid, pid, allowed),
            )

    _migrate_legacy_user_access_from_roles(db)


def _migrate_legacy_user_access_from_roles(db: sqlite3.Connection) -> None:
    """One-time fill user_workspaces / user_admin_grants from users.role_id when those tables are empty."""
    role_code_by_id = {
        int(r["id"]): str(r["code"]) for r in db.execute("SELECT id, code FROM roles").fetchall()
    }
    users = db.execute("SELECT id, role_id FROM users").fetchall()
    for u in users:
        uid = int(u["id"])
        rid = int(u["role_id"])
        rc = role_code_by_id.get(rid, "TREASURER")
        if db.execute("SELECT 1 FROM user_workspaces WHERE user_id = ? LIMIT 1", (uid,)).fetchone() is None:
            for item in _default_workspace_assignments_for_db_role(rc):
                db.execute(
                    """
                    INSERT OR IGNORE INTO user_workspaces (user_id, body, office_code)
                    VALUES (?, ?, ?)
                    """,
                    (uid, item["body"], item["role_code"]),
                )
        if db.execute("SELECT 1 FROM user_admin_grants WHERE user_id = ? LIMIT 1", (uid,)).fetchone() is None:
            for perm_code, _desc in PERMISSION_DEFINITIONS:
                if role_has_permission(db, rid, perm_code):
                    db.execute(
                        """
                        INSERT OR IGNORE INTO user_admin_grants (user_id, permission_code)
                        VALUES (?, ?)
                        """,
                        (uid, perm_code),
                    )


def _prune_permissions_not_in_definitions(db: sqlite3.Connection, keep_codes: set[str]) -> None:
    rows = db.execute("SELECT id, code FROM permissions").fetchall()
    for row in rows:
        code = str(row["code"])
        if code in keep_codes:
            continue
        pid = int(row["id"])
        db.execute("DELETE FROM role_permissions WHERE permission_id = ?", (pid,))
        db.execute("DELETE FROM permissions WHERE id = ?", (pid,))


def _ensure_unique_constraints(db: sqlite3.Connection) -> None:
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_permissions_code ON permissions (code)")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_roles_code ON roles (code)")
    except sqlite3.OperationalError:
        pass


def list_roles_for_signed_in_user(
    db: sqlite3.Connection | None,
    user: Any,
    *,
    dev_show_treasurer_when_anonymous: bool = False,
) -> list[dict[str, str]]:
    """Roles this account may pick in the UI. Today: one DB role per user; tests may fake Treasurer when LOGIN_DISABLED."""
    if dev_show_treasurer_when_anonymous:
        return [{"code": "TREASURER", "label": "Treasurer"}]
    if db is None:
        return []
    try:
        authed = bool(getattr(user, "is_authenticated", False))
    except Exception:
        authed = False
    if not authed:
        return []
    row = fetch_user_for_login(db, int(user.id))
    if not row:
        return []
    code = str(row["role_code"])
    r2 = db.execute("SELECT display_name FROM roles WHERE code = ?", (code,)).fetchone()
    label = str(r2["display_name"]) if r2 else code
    return [{"code": code, "label": label}]


def _workspace_assignment_label(body: str, office_code: str) -> str:
    prefix = "Chapter" if body == "chapter" else "Lodge"
    for code, display_name, _so in ROLE_DEFINITIONS:
        if code == office_code:
            return f"{prefix} · {display_name}"
    return f"{prefix} · {office_code.replace('_', ' ').title()}"


def _default_workspace_assignments_for_db_role(db_role: str) -> list[dict[str, str]]:
    """Template list used only for migrating legacy role_id → user_workspaces."""
    if db_role == "ADMIN":
        return [
            {"body": "lodge", "role_code": "ADMIN", "label": "Lodge · Admin"},
            {"body": "lodge", "role_code": "TREASURER", "label": "Lodge · Treasurer"},
            {"body": "lodge", "role_code": "SECRETARY", "label": "Lodge · Secretary"},
            {"body": "chapter", "role_code": "TREASURER", "label": "Chapter · Treasurer"},
            {"body": "chapter", "role_code": "SECRETARY", "label": "Chapter · Secretary"},
        ]
    if db_role == "TREASURER":
        return [{"body": "lodge", "role_code": "TREASURER", "label": "Lodge · Treasurer"}]
    if db_role == "SECRETARY":
        return [
            {"body": "lodge", "role_code": "SECRETARY", "label": "Lodge · Secretary"},
            {"body": "chapter", "role_code": "SECRETARY", "label": "Chapter · Secretary"},
        ]
    if db_role == "AUDITOR":
        return [{"body": "lodge", "role_code": "AUDITOR", "label": "Lodge · Auditor"}]
    if db_role == "CHARITY_STEWARD":
        return [
            {
                "body": "lodge",
                "role_code": "CHARITY_STEWARD",
                "label": "Lodge · Charity Steward",
            }
        ]
    if db_role == "MASTER":
        return [{"body": "lodge", "role_code": "MASTER", "label": "Lodge · Master"}]
    return []


def workspace_grant_catalog() -> list[dict[str, str]]:
    """Checkbox options on Portal users (value is lodge:SECRETARY, etc.)."""
    out: list[dict[str, str]] = []
    for body in ("lodge", "chapter"):
        prefix = "Lodge" if body == "lodge" else "Chapter"
        for code, display_name, _so in ROLE_DEFINITIONS:
            out.append(
                {
                    "body": body,
                    "role_code": code,
                    "value": f"{body}:{code}",
                    "label": f"{prefix} · {display_name}",
                }
            )
    return out


def parse_workspace_grant_form_values(raw_values: list[str]) -> list[tuple[str, str]]:
    valid_bodies = frozenset({"lodge", "chapter"})
    valid_codes = {r[0] for r in ROLE_DEFINITIONS}
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for raw in raw_values:
        if not raw or ":" not in raw:
            continue
        b, _, c = str(raw).partition(":")
        b, c = b.strip().lower(), c.strip().upper()
        if b not in valid_bodies or c not in valid_codes:
            continue
        key = (b, c)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def list_user_workspace_grant_keys(db: sqlite3.Connection, user_id: int) -> set[str]:
    rows = db.execute(
        "SELECT body, office_code FROM user_workspaces WHERE user_id = ? ORDER BY body, office_code",
        (user_id,),
    ).fetchall()
    return {f"{r['body']}:{r['office_code']}" for r in rows}


def replace_user_workspace_grants(db: sqlite3.Connection, user_id: int, pairs: list[tuple[str, str]]) -> None:
    db.execute("DELETE FROM user_workspaces WHERE user_id = ?", (user_id,))
    for body, office_code in pairs:
        db.execute(
            """
            INSERT INTO user_workspaces (user_id, body, office_code)
            VALUES (?, ?, ?)
            """,
            (user_id, body, office_code),
        )


def parse_admin_grant_form_values(raw_values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in raw_values:
        code = str(raw or "").strip()
        if code in USER_ADMIN_GRANT_CODES and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def replace_user_admin_grants(db: sqlite3.Connection, user_id: int, codes: list[str]) -> None:
    db.execute("DELETE FROM user_admin_grants WHERE user_id = ?", (user_id,))
    for code in codes:
        db.execute(
            """
            INSERT INTO user_admin_grants (user_id, permission_code)
            VALUES (?, ?)
            """,
            (user_id, code),
        )


def list_user_admin_grant_codes(db: sqlite3.Connection, user_id: int) -> set[str]:
    rows = db.execute(
        "SELECT permission_code FROM user_admin_grants WHERE user_id = ? ORDER BY permission_code",
        (user_id,),
    ).fetchall()
    return {str(r["permission_code"]) for r in rows}


def user_has_admin_grant(db: sqlite3.Connection, user_id: int, permission_code: str) -> bool:
    if permission_code not in USER_ADMIN_GRANT_CODES:
        return False
    row = db.execute(
        """
        SELECT 1 AS x FROM user_admin_grants
        WHERE user_id = ? AND permission_code = ?
        LIMIT 1
        """,
        (user_id, permission_code),
    ).fetchone()
    return row is not None


def admin_grant_catalog() -> list[dict[str, str]]:
    return [{"code": c, "description": d} for c, d in PERMISSION_DEFINITIONS]


def seed_bootstrap_user_access(db: sqlite3.Connection, user_id: int) -> None:
    """First install admin: full lodge+chapter menu + all admin grants."""
    pairs = [(a["body"], a["role_code"]) for a in _default_workspace_assignments_for_db_role("ADMIN")]
    replace_user_workspace_grants(db, user_id, pairs)
    replace_user_admin_grants(db, user_id, [c for c, _ in PERMISSION_DEFINITIONS])


def list_workspace_assignments(
    db: sqlite3.Connection | None,
    user: Any,
    *,
    dev_show_treasurer_when_anonymous: bool = False,
) -> list[dict[str, str]]:
    """Waffle entries from user_workspaces only (per person; configure under Portal users)."""
    if dev_show_treasurer_when_anonymous:
        return [
            {
                "body": "lodge",
                "role_code": "TREASURER",
                "label": "Lodge · Treasurer",
            }
        ]
    if db is None:
        return []
    try:
        authed = bool(getattr(user, "is_authenticated", False))
    except Exception:
        authed = False
    if not authed:
        return []
    row = fetch_user_for_login(db, int(user.id))
    if not row:
        return []
    uid = int(row["id"])
    rows = db.execute(
        "SELECT body, office_code FROM user_workspaces WHERE user_id = ? ORDER BY body, office_code",
        (uid,),
    ).fetchall()
    return [
        {
            "body": str(r["body"]),
            "role_code": str(r["office_code"]),
            "label": _workspace_assignment_label(str(r["body"]), str(r["office_code"])),
        }
        for r in rows
    ]


def workspace_assignment_is_allowed(assignments: list[dict[str, str]], body: str, role_code: str) -> bool:
    b = body.strip().lower()
    r = role_code.strip().upper()
    return any(a.get("body") == b and a.get("role_code") == r for a in assignments)


def fetch_user_for_login(db: sqlite3.Connection, user_id: int) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT u.id, u.email, u.password_hash, u.role_id, u.active, r.code AS role_code
        FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE u.id = ?
        """,
        (user_id,),
    ).fetchone()
    return dict(row) if row else None


def fetch_user_by_email(db: sqlite3.Connection, email: str) -> dict[str, Any] | None:
    row = db.execute(
        """
        SELECT u.id, u.email, u.password_hash, u.role_id, u.active, r.code AS role_code
        FROM users u
        JOIN roles r ON r.id = u.role_id
        WHERE LOWER(u.email) = LOWER(?)
        """,
        (email.strip(),),
    ).fetchone()
    return dict(row) if row else None


def count_users(db: sqlite3.Connection) -> int:
    return int(db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])


def list_users_with_roles(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT u.id, u.email, u.active, u.created_at, r.id AS role_id, r.code AS role_code, r.display_name AS role_display
        FROM users u
        JOIN roles r ON r.id = u.role_id
        ORDER BY LOWER(u.email)
        """
    ).fetchall()
    return [dict(r) for r in rows]


def list_roles(db: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id, code, display_name, sort_order FROM roles ORDER BY sort_order, display_name"
    ).fetchall()
    return [dict(r) for r in rows]


def create_user_row(
    db: sqlite3.Connection,
    email: str,
    password_hash: str,
    role_id: int,
) -> int:
    cur = db.execute(
        """
        INSERT INTO users (email, password_hash, role_id, active, updated_at)
        VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)
        """,
        (email.strip().lower(), password_hash, role_id),
    )
    return int(cur.lastrowid)


def update_user_password(db: sqlite3.Connection, user_id: int, password_hash: str) -> None:
    db.execute(
        "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (password_hash, user_id),
    )


def update_user_role(db: sqlite3.Connection, user_id: int, role_id: int) -> None:
    db.execute(
        "UPDATE users SET role_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (role_id, user_id),
    )


def set_user_active(db: sqlite3.Connection, user_id: int, active: bool) -> None:
    db.execute(
        "UPDATE users SET active = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (1 if active else 0, user_id),
    )


def hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def store_reset_token(db: sqlite3.Connection, user_id: int, raw_token: str, hours: int = 2) -> None:
    db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user_id,))
    expires = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    db.execute(
        """
        INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
        VALUES (?, ?, ?)
        """,
        (user_id, hash_reset_token(raw_token), expires),
    )


def consume_reset_token(db: sqlite3.Connection, raw_token: str) -> int | None:
    th = hash_reset_token(raw_token)
    row = db.execute(
        """
        SELECT id, user_id, expires_at
        FROM password_reset_tokens
        WHERE token_hash = ?
        """,
        (th,),
    ).fetchone()
    if row is None:
        return None
    try:
        exp = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        if exp < datetime.now(timezone.utc):
            db.execute("DELETE FROM password_reset_tokens WHERE id = ?", (row["id"],))
            return None
    except (ValueError, TypeError):
        return None
    uid = int(row["user_id"])
    db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (uid,))
    return uid


def permission_id_by_code(db: sqlite3.Connection, code: str) -> int | None:
    row = db.execute("SELECT id FROM permissions WHERE code = ?", (code,)).fetchone()
    return int(row["id"]) if row else None


def role_has_permission(db: sqlite3.Connection, role_id: int, permission_code: str) -> bool:
    """True if this role may access the permission (row must exist with allowed=1).

    Used for legacy migration seeding only; runtime admin checks use user_admin_grants.
    The Admin role always has every permission regardless of stored matrix values.
    """
    code_row = db.execute("SELECT code FROM roles WHERE id = ?", (role_id,)).fetchone()
    if code_row and code_row["code"] == "ADMIN":
        return True
    row = db.execute(
        """
        SELECT rp.allowed
        FROM role_permissions rp
        JOIN permissions p ON p.id = rp.permission_id
        WHERE rp.role_id = ? AND p.code = ?
        """,
        (role_id, permission_code),
    ).fetchone()
    if row is None:
        return False
    return bool(row["allowed"])
