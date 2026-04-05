"""Allowlisted raw SQLite table editing for administrators (dangerous — use with care)."""

from __future__ import annotations

import sqlite3
from typing import Any

from .db import DatabaseHandle

# Only these tables may be accessed via table admin (exact names).
TABLE_ADMIN_ALLOWLIST: frozenset[str] = frozenset({"bank_transactions", "members", "users"})

TABLE_LABELS: dict[str, str] = {
    "bank_transactions": "Bank transactions",
    "members": "Members",
    "users": "Users",
}

TABLE_ADMIN_ORDER: tuple[str, ...] = ("bank_transactions", "members", "users")

TABLE_PAGE_SIZE: dict[str, int] = {
    "bank_transactions": 75,
    "members": 500,
    "users": 200,
}

TABLE_ORDER_SQL: dict[str, str] = {
    "bank_transactions": "id DESC",
    "members": "id",
    "users": "id",
}

# Prefer textarea for long / hash fields.
TEXTAREA_COLUMNS: dict[str, frozenset[str]] = {
    "bank_transactions": frozenset({"details", "notes"}),
    "members": frozenset({"notes"}),
    "users": frozenset({"password_hash"}),
}

def assert_table_allowed(table: str) -> str:
    if table not in TABLE_ADMIN_ALLOWLIST:
        raise ValueError("Invalid table.")
    return table


def fetch_column_info(db: DatabaseHandle, table: str) -> list[dict[str, Any]]:
    assert_table_allowed(table)
    rows = db.execute(f'PRAGMA table_info("{table}")').fetchall()
    return [dict(r) for r in rows]


def _coerce_value(col: dict[str, Any], raw: str | None) -> Any:
    if raw is None:
        raw = ""
    raw_stripped = raw.strip()
    if raw_stripped == "":
        return None
    typ = (col.get("type") or "").upper()
    if "INT" in typ:
        return int(raw_stripped)
    if "REAL" in typ or "FLOA" in typ or "DOUB" in typ:
        return float(raw_stripped)
    return raw


def row_values_from_form(
    cols: list[dict[str, Any]],
    form: Any,
    prefix: str,
    *,
    for_insert: bool,
) -> dict[str, Any]:
    """Read `prefix + colname` from form into a dict of column -> Python value."""
    out: dict[str, Any] = {}
    pk_name = _single_pk_name(cols)
    for col in cols:
        name = col["name"]
        if for_insert and pk_name and name == pk_name:
            continue
        key = f"{prefix}{name}"
        raw = form.get(key, "")
        if not isinstance(raw, str):
            raw = str(raw) if raw is not None else ""
        out[name] = _coerce_value(col, raw)
    return out


def _single_pk_name(cols: list[dict[str, Any]]) -> str | None:
    pks = [c["name"] for c in cols if c.get("pk")]
    if len(pks) == 1:
        return str(pks[0])
    return None


def insert_omit_sql_defaults(cols: list[dict[str, Any]], values: dict[str, Any]) -> dict[str, Any]:
    """Drop keys that are None when the column has a DB default so SQLite applies DEFAULT."""
    out = dict(values)
    for col in cols:
        name = col["name"]
        if name not in out:
            continue
        if out[name] is None and col.get("dflt_value") is not None:
            del out[name]
    return out


def validate_required_for_insert(cols: list[dict[str, Any]], values: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    pk_name = _single_pk_name(cols)
    for col in cols:
        name = col["name"]
        if pk_name and name == pk_name:
            continue
        if not col.get("notnull"):
            continue
        if col.get("dflt_value") is not None:
            continue
        if name not in values or values[name] is None:
            errors.append(f"Column “{name}” is required.")
    return errors


def insert_row(
    db: DatabaseHandle,
    table: str,
    cols: list[dict[str, Any]],
    values: dict[str, Any],
) -> None:
    assert_table_allowed(table)
    pk_name = _single_pk_name(cols)
    insert_cols = [c["name"] for c in cols if not (pk_name and c["name"] == pk_name)]
    insert_cols = [c for c in insert_cols if c in values]
    placeholders = ", ".join(["?"] * len(insert_cols))
    col_sql = ", ".join(f'"{c}"' for c in insert_cols)
    params = [values[c] for c in insert_cols]
    db.execute(f'INSERT INTO "{table}" ({col_sql}) VALUES ({placeholders})', params)


def update_row_by_pk(
    db: DatabaseHandle,
    table: str,
    cols: list[dict[str, Any]],
    pk_value: int,
    values: dict[str, Any],
) -> None:
    assert_table_allowed(table)
    pk_name = _single_pk_name(cols)
    if not pk_name:
        raise ValueError("Table has no single-column primary key.")
    set_parts: list[str] = []
    params: list[Any] = []
    for col in cols:
        name = col["name"]
        if name == pk_name:
            continue
        if name not in values:
            continue
        set_parts.append(f'"{name}" = ?')
        params.append(values[name])
    if not set_parts:
        return
    params.append(pk_value)
    sql = f'UPDATE "{table}" SET {", ".join(set_parts)} WHERE "{pk_name}" = ?'
    db.execute(sql, params)


def delete_row_by_pk(db: DatabaseHandle, table: str, cols: list[dict[str, Any]], pk_value: int) -> None:
    assert_table_allowed(table)
    pk_name = _single_pk_name(cols)
    if not pk_name:
        raise ValueError("Table has no single-column primary key.")
    db.execute(f'DELETE FROM "{table}" WHERE "{pk_name}" = ?', (pk_value,))


def count_rows(db: DatabaseHandle, table: str) -> int:
    assert_table_allowed(table)
    return int(db.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"])


def fetch_page(
    db: DatabaseHandle,
    table: str,
    *,
    limit: int,
    offset: int,
) -> list[sqlite3.Row]:
    assert_table_allowed(table)
    order = TABLE_ORDER_SQL.get(table, "id")
    return db.execute(
        f'SELECT * FROM "{table}" ORDER BY {order} LIMIT ? OFFSET ?',
        (limit, offset),
    ).fetchall()
