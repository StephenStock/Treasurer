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

# Permission keys for the role matrix (enforced on routes and nav; see login_config.permission_required).
PERMISSION_DEFINITIONS: list[tuple[str, str]] = [
    ("page_home", "Home / dashboard"),
    ("page_statement", "Statement"),
    ("page_members", "Members"),
    ("page_bank", "Bank"),
    ("page_cash", "Cash"),
    ("page_balances", "Sub accounts / balances"),
    ("page_auditors", "Auditors"),
    ("page_settings", "Settings"),
    ("page_help", "Help"),
    ("page_forms", "Forms"),
    ("page_meal_bookings", "Meal bookings (setup & responses)"),
    ("admin_users", "Manage portal users"),
    ("admin_role_permissions", "Manage role permissions"),
    ("admin_table_editor", "Edit raw database tables (dangerous)"),
]


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

    for rid in role_ids.values():
        for pid in perm_ids.values():
            db.execute(
                """
                INSERT INTO role_permissions (role_id, permission_id, allowed)
                VALUES (?, ?, 1)
                ON CONFLICT(role_id, permission_id) DO NOTHING
                """,
                (rid, pid),
            )


def _ensure_unique_constraints(db: sqlite3.Connection) -> None:
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_permissions_code ON permissions (code)")
    except sqlite3.OperationalError:
        pass
    try:
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_roles_code ON roles (code)")
    except sqlite3.OperationalError:
        pass


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


def role_permissions_matrix(db: sqlite3.Connection) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[list[bool]]]:
    roles = list_roles(db)
    perms = db.execute("SELECT id, code, description FROM permissions ORDER BY id").fetchall()
    perm_list = [dict(p) for p in perms]
    matrix: list[list[bool]] = []
    for role in roles:
        row_flags: list[bool] = []
        for p in perm_list:
            r = db.execute(
                """
                SELECT COALESCE(rp.allowed, 0) AS a
                FROM role_permissions rp
                WHERE rp.role_id = ? AND rp.permission_id = ?
                """,
                (role["id"], p["id"]),
            ).fetchone()
            row_flags.append(bool(r and r["a"]))
        matrix.append(row_flags)
    return roles, perm_list, matrix


def set_role_permission(db: sqlite3.Connection, role_id: int, permission_id: int, allowed: bool) -> None:
    db.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id, allowed)
        VALUES (?, ?, ?)
        ON CONFLICT(role_id, permission_id) DO UPDATE SET allowed = excluded.allowed
        """,
        (role_id, permission_id, 1 if allowed else 0),
    )


def permission_id_by_code(db: sqlite3.Connection, code: str) -> int | None:
    row = db.execute("SELECT id FROM permissions WHERE code = ?", (code,)).fetchone()
    return int(row["id"]) if row else None


def role_has_permission(db: sqlite3.Connection, role_id: int, permission_code: str) -> bool:
    """True if this role may access the permission (row must exist with allowed=1).

    The Admin role always has every permission regardless of stored matrix values
    (matrix checkboxes for Admin remain for reference and testing other roles' layout).
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
