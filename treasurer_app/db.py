from __future__ import annotations

import csv
import difflib
import io
import os
import re
import shutil
import sqlite3
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import current_app, g


WORKBOOK_BANK_SHEET = "Bank"
WORKBOOK_CASH_SHEET = "Cash"
WORKBOOK_MEMBERS_SHEET = "Members"
WORKBOOK_STATEMENT_SHEET = "Statement"
WORKBOOK_CANDIDATES = (
    "Accounts 2025-26.xlsx",
    "TreasurerAccounts_Template.xlsx",
)

MIGRATION_TABLE_ORDER = (
    "reporting_periods",
    "member_types",
    "members",
    "dues",
    "events",
    "messages",
    "subscription_charges",
    "dining_charges",
    "payments",
    "ledger_categories",
    "app_runtime_locks",
    "bank_transactions",
    "bank_transaction_allocations",
    "meetings",
    "cashbook_entries",
    "cash_settlements",
    "bookings",
)

APP_SETTING_BACKUP_DATABASE = "backup_database"
APP_SETTING_BACKUP_FOLDER = "backup_folder"
APP_RUNTIME_LOCK_NAME = "main"
APP_RUNTIME_LOCK_HEARTBEAT_SECONDS = 30
APP_RUNTIME_LOCK_STALE_SECONDS = 120
BACKUP_DATABASE_FILENAME = "Treasurer.backup.db"

BANK_CATEGORY_DEFINITIONS = [
    ("CASH", "Cash", "in", 10),
    ("PRE_SUBS", "Pre-Subs", "in", 20),
    ("PRE_DINING", "Pre-Dining", "in", 30),
    ("SUBS", "Subs", "in", 40),
    ("DINING", "Dining", "in", 50),
    ("VISITOR", "Visitor", "in", 60),
    ("INITIATION", "Initiation", "in", 70),
    ("SUMUP", "SumUp", "in", 80),
    ("GAVEL", "Gavel", "in", 90),
    ("DONATIONS_IN", "Donations", "in", 100),
    ("RAFFLE", "Raffle", "in", 105),
    ("COPPER_POT", "Copper Pot", "in", 107),
    ("CHAPTER_LOI", "Chapter LOI", "in", 110),
    ("LOI", "LOI", "in", 120),
    ("ALMONER", "Almoner", "out", 135),
    ("RELIEF", "Relief", "out", 130),
    ("DONATIONS_OUT", "Donations", "out", 140),
    ("TYLER", "Tyler", "out", 145),
    ("UGLE", "UGLE", "out", 150),
    ("PGLE", "PGLE", "out", 160),
    ("ORSETT", "Orsett", "out", 170),
    ("WOOLMKT", "WoolMkt", "out", 180),
    ("CATERER", "Caterer", "out", 190),
    ("BANK_CHARGES", "Bank Charges", "out", 200),
    ("WIDOWS", "Widows", "out", 210),
]

VIRTUAL_ACCOUNT_DEFINITIONS = [
    ("MAIN", "Main", 10),
    ("CHARITY", "Charity", 20),
    ("GLASGOW_FRANK", "Glasgow/Frank", 30),
    ("LOI", "LOI", 50),
    ("PRE_SUBS", "Pre-Paid Subs", 80),
    ("PRE_DINING", "Pre-Paid Dining", 90),
    ("BENEVOLENT", "Benevolent Fund", 100),
    ("CENTENARY", "Centenary Fund", 110),
]

DEFAULT_VIRTUAL_ACCOUNT_OPENING_BALANCES = {
    "MAIN": 5141.17,
    "CHARITY": 744.46,
    "GLASGOW_FRANK": 10689.79,
    "LOI": 335.65,
    "PRE_SUBS": 127.745,
    "PRE_DINING": 72.255,
    "BENEVOLENT": 772.17,
    "CENTENARY": 3170.48,
}

VIRTUAL_ACCOUNT_CATEGORY_MAP = {
    "MAIN": [
        "CASH",
        "INITIATION",
        "SUMUP",
        "SUBS",
        "DINING",
        "VISITOR",
        "CATERER",
        "BANK_CHARGES",
        "COPPER_POT",
        "CHAPTER_LOI",
        "TYLER",
        "UGLE",
        "PGLE",
        "ORSETT",
        "WOOLMKT",
    ],
    "CHARITY": ["GAVEL", "RAFFLE", "DONATIONS_IN", "DONATIONS_OUT", "RELIEF"],
    "GLASGOW_FRANK": [],
    "LOI": ["LOI"],
    "PRE_SUBS": ["PRE_SUBS"],
    "PRE_DINING": ["PRE_DINING"],
    "BENEVOLENT": ["WIDOWS", "ALMONER"],
    "CENTENARY": [],
}

CASH_COLUMN_CATEGORY_CODES = {
    "C": "SUBS",
    "D": "DINING",
    "E": "GAVEL",
    "F": "RAFFLE",
    "G": "COPPER_POT",
    "I": "DONATIONS_OUT",
    "J": "ALMONER",
    "K": "TYLER",
}

CASH_OUT_COLUMNS = {"J", "K"}

BANK_COLUMN_CATEGORY_CODES = {
    "L": "CASH",
    "M": "PRE_SUBS",
    "N": "PRE_DINING",
    "O": "SUBS",
    "P": "DINING",
    "Q": "VISITOR",
    "R": "INITIATION",
    "S": "SUMUP",
    "T": "GAVEL",
    "U": "DONATIONS_IN",
    "V": "CHAPTER_LOI",
    "W": "LOI",
    "Z": "RELIEF",
    "AA": "DONATIONS_OUT",
    "AB": "UGLE",
    "AC": "PGLE",
    "AD": "ORSETT",
    "AE": "WOOLMKT",
    "AF": "CATERER",
    "AG": "BANK_CHARGES",
    "AH": "WIDOWS",
}

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS = {"main": _MAIN_NS, "rel": _REL_NS, "pkgrel": _PKG_REL_NS}


def ensure_instance_path(app) -> None:
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)


def default_database_path() -> Path:
    configured = os.environ.get("TREASURER_DATABASE")
    if configured:
        return Path(configured)
    return Path("C:/TreasurerDB/Treasurer.db")


def default_backup_folder_path() -> Path:
    configured = os.environ.get("TREASURER_BACKUP_DATABASE")
    if configured:
        configured_path = Path(configured)
        if configured_path.suffix.lower() == ".db":
            return configured_path.parent
        return configured_path

    documents_dir = Path.home() / "Documents"
    if documents_dir.exists():
        return documents_dir / "Treasurer Backups"

    for env_name in ("OneDriveCommercial", "OneDriveConsumer", "OneDrive"):
        one_drive_root = os.environ.get(env_name)
        if one_drive_root:
            return Path(one_drive_root) / "Treasurer Backups"

    return Path.home() / "Treasurer Backups"


def backup_database_file_path(backup_folder_path: Path) -> Path:
    return backup_folder_path / BACKUP_DATABASE_FILENAME


def default_backup_database_path() -> Path:
    return backup_database_file_path(default_backup_folder_path())


def runtime_lock_identity() -> dict[str, object]:
    machine_name = os.environ.get("COMPUTERNAME") or os.environ.get("HOSTNAME") or "unknown-machine"
    owner_name = os.environ.get("USERNAME") or os.environ.get("USER") or "unknown-user"
    process_id = os.getpid()
    session_token = uuid.uuid4().hex
    return {
        "machine_name": machine_name,
        "owner_name": owner_name,
        "process_id": process_id,
        "session_token": session_token,
    }


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat()


def _parse_iso_datetime(raw_value: str | None) -> datetime | None:
    if not raw_value:
        return None
    try:
        return datetime.fromisoformat(str(raw_value))
    except ValueError:
        return None


def _runtime_lock_is_stale(row: sqlite3.Row | None, stale_seconds: int = APP_RUNTIME_LOCK_STALE_SECONDS) -> bool:
    if row is None:
        return True

    last_seen_at = _parse_iso_datetime(row["last_seen_at"] if "last_seen_at" in row.keys() else None)
    if last_seen_at is None:
        return True

    return datetime.utcnow() - last_seen_at > timedelta(seconds=stale_seconds)


def get_runtime_lock_status(db: DatabaseHandle, lock_name: str = APP_RUNTIME_LOCK_NAME) -> sqlite3.Row | None:
    if not table_exists(db, "app_runtime_locks"):
        return None

    row = db.execute(
        """
        SELECT *
        FROM app_runtime_locks
        WHERE lock_name = ?
        LIMIT 1
        """,
        (lock_name,),
    ).fetchone()
    if row is None or row["released_at"]:
        return None
    if _runtime_lock_is_stale(row):
        return None
    return row


def check_runtime_lock_available(db: DatabaseHandle, lock_name: str = APP_RUNTIME_LOCK_NAME) -> tuple[bool, sqlite3.Row | None]:
    lock_row = get_runtime_lock_status(db, lock_name)
    if lock_row is None:
        return True, None
    return False, lock_row


def claim_runtime_lock(
    db: DatabaseHandle,
    *,
    lock_name: str = APP_RUNTIME_LOCK_NAME,
    owner_name: str,
    machine_name: str,
    process_id: int,
    session_token: str,
) -> tuple[bool, sqlite3.Row | None]:
    if not table_exists(db, "app_runtime_locks"):
        return True, None

    active_lock = get_runtime_lock_status(db, lock_name)
    if active_lock is not None and active_lock["session_token"] != session_token:
        return False, active_lock

    now = _utc_now_iso()
    if active_lock is None:
        db.execute(
            """
            INSERT INTO app_runtime_locks (
                lock_name,
                owner_name,
                machine_name,
                process_id,
                session_token,
                locked_at,
                last_seen_at,
                released_at,
                release_reason
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(lock_name) DO UPDATE SET
                owner_name = excluded.owner_name,
                machine_name = excluded.machine_name,
                process_id = excluded.process_id,
                session_token = excluded.session_token,
                locked_at = excluded.locked_at,
                last_seen_at = excluded.last_seen_at,
                released_at = NULL,
                release_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                lock_name,
                owner_name,
                machine_name,
                process_id,
                session_token,
                now,
                now,
            ),
        )
    else:
        db.execute(
            """
            UPDATE app_runtime_locks
            SET
                owner_name = ?,
                machine_name = ?,
                process_id = ?,
                session_token = ?,
                last_seen_at = ?,
                released_at = NULL,
                release_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE lock_name = ?
            """,
            (
                owner_name,
                machine_name,
                process_id,
                session_token,
                now,
                lock_name,
            ),
        )

    refreshed = db.execute(
        """
        SELECT *
        FROM app_runtime_locks
        WHERE lock_name = ?
        LIMIT 1
        """,
        (lock_name,),
    ).fetchone()
    return True, refreshed


def refresh_runtime_lock(
    db: DatabaseHandle,
    session_token: str,
    *,
    lock_name: str = APP_RUNTIME_LOCK_NAME,
) -> bool:
    if not table_exists(db, "app_runtime_locks"):
        return False

    now = _utc_now_iso()
    cursor = db.execute(
        """
        UPDATE app_runtime_locks
        SET last_seen_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE lock_name = ? AND session_token = ? AND released_at IS NULL
        """,
        (now, lock_name, session_token),
    )
    return cursor.rowcount > 0


def release_runtime_lock(
    db: DatabaseHandle,
    session_token: str,
    *,
    lock_name: str = APP_RUNTIME_LOCK_NAME,
    release_reason: str = "released",
) -> bool:
    if not table_exists(db, "app_runtime_locks"):
        return False

    now = _utc_now_iso()
    cursor = db.execute(
        """
        UPDATE app_runtime_locks
        SET released_at = ?, release_reason = ?, last_seen_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE lock_name = ? AND session_token = ? AND released_at IS NULL
        """,
        (now, release_reason, now, lock_name, session_token),
    )
    return cursor.rowcount > 0


def force_release_runtime_lock(
    db: DatabaseHandle,
    *,
    lock_name: str = APP_RUNTIME_LOCK_NAME,
    release_reason: str = "manual unlock",
) -> bool:
    if not table_exists(db, "app_runtime_locks"):
        return False

    now = _utc_now_iso()
    cursor = db.execute(
        """
        UPDATE app_runtime_locks
        SET released_at = ?, release_reason = ?, last_seen_at = ?, updated_at = CURRENT_TIMESTAMP
        WHERE lock_name = ? AND released_at IS NULL
        """,
        (now, release_reason, now, lock_name),
    )
    return cursor.rowcount > 0


def _read_backup_setting(primary_database_path: Path | None = None) -> Path | None:
    if primary_database_path is None:
        return None

    try:
        if not primary_database_path.exists():
            return None
    except OSError:
        return None

    connection = None
    try:
        connection = sqlite3.connect(primary_database_path)
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            """
            SELECT setting_key, setting_value
            FROM app_settings
            WHERE setting_key IN (?, ?)
            ORDER BY CASE setting_key WHEN ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (
                APP_SETTING_BACKUP_FOLDER,
                APP_SETTING_BACKUP_DATABASE,
                APP_SETTING_BACKUP_FOLDER,
            ),
        ).fetchone()
        if not row or not row["setting_value"]:
            return None

        configured_path = Path(str(row["setting_value"]))
        if row["setting_key"] == APP_SETTING_BACKUP_DATABASE and configured_path.suffix.lower() == ".db":
            return configured_path.parent
        return configured_path
    except sqlite3.Error:
        return None
    finally:
        if connection is not None:
            connection.close()


def resolve_backup_database_path(primary_database_path: Path | None = None) -> Path:
    backup_folder = _read_backup_setting(primary_database_path)
    if backup_folder is not None:
        if backup_folder.suffix.lower() == ".db":
            return backup_folder
        return backup_database_file_path(backup_folder)

    configured = os.environ.get("TREASURER_BACKUP_DATABASE")
    if configured:
        configured_path = Path(configured)
        if configured_path.suffix.lower() == ".db":
            return configured_path
        return backup_database_file_path(configured_path)

    return default_backup_database_path()


def resolve_backup_folder_path(primary_database_path: Path | None = None) -> Path:
    backup_path = _read_backup_setting(primary_database_path)
    if backup_path is not None:
        if backup_path.suffix.lower() == ".db":
            return backup_path.parent
        return backup_path

    configured = os.environ.get("TREASURER_BACKUP_DATABASE")
    if configured:
        configured_path = Path(configured)
        if configured_path.suffix.lower() == ".db":
            return configured_path.parent
        return configured_path

    return default_backup_folder_path()


def ensure_database_parent_path(database_path: Path) -> None:
    try:
        database_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        # Shared UNC paths can already exist or be managed outside this machine.
        pass


def _atomic_copy_file(source_path: Path, destination_path: Path) -> None:
    ensure_database_parent_path(destination_path)
    temp_path = destination_path.with_name(f"{destination_path.name}.tmp")
    if temp_path.exists():
        temp_path.unlink()
    shutil.copy2(source_path, temp_path)
    os.replace(temp_path, destination_path)


def sync_database_files(primary_path: Path, backup_path: Path) -> None:
    if primary_path.resolve() == backup_path.resolve():
        return

    primary_exists = primary_path.exists()
    backup_exists = backup_path.exists()

    if primary_exists and not backup_exists:
        _atomic_copy_file(primary_path, backup_path)
        return

    if backup_exists and not primary_exists:
        _atomic_copy_file(backup_path, primary_path)
        return

    if not primary_exists or not backup_exists:
        return

    primary_stat = primary_path.stat()
    backup_stat = backup_path.stat()
    primary_stamp = (primary_stat.st_mtime_ns, primary_stat.st_size)
    backup_stamp = (backup_stat.st_mtime_ns, backup_stat.st_size)

    if backup_stamp > primary_stamp:
        _atomic_copy_file(backup_path, primary_path)
    elif primary_stamp > backup_stamp:
        _atomic_copy_file(primary_path, backup_path)


def backup_database(db: DatabaseHandle, backup_path: Path) -> None:
    if db.backend != "sqlite":
        return

    ensure_database_parent_path(backup_path)
    temp_path = backup_path.with_name(f"{backup_path.name}.tmp")
    if temp_path.exists():
        temp_path.unlink()

    db.commit()
    destination = sqlite3.connect(temp_path)
    try:
        db.backup(destination)
        destination.commit()
    finally:
        destination.close()

    os.replace(temp_path, backup_path)


def restore_database_from_backup(primary_path: Path, backup_path: Path) -> None:
    if primary_path.resolve() == backup_path.resolve():
        return
    if not backup_path.exists():
        raise FileNotFoundError(backup_path)

    ensure_database_parent_path(primary_path)
    temp_path = primary_path.with_name(f"{primary_path.name}.restore.tmp")
    if temp_path.exists():
        temp_path.unlink()

    shutil.copy2(backup_path, temp_path)
    os.replace(temp_path, primary_path)


def _schema_sql_for_sqlite(sql: str) -> str:
    sql = re.sub(r"CREATE TABLE (?!IF NOT EXISTS)", "CREATE TABLE IF NOT EXISTS ", sql)
    sql = sql.replace("INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    sql = sql.replace("CURRENT_TIMESTAMP::text", "CURRENT_TIMESTAMP")
    sql = re.sub(r"CREATE INDEX (?!IF NOT EXISTS)", "CREATE INDEX IF NOT EXISTS ", sql)
    return sql


class DatabaseHandle:
    def __init__(self, connection, backend: str):
        self._connection = connection
        self.backend = backend

    def execute(self, sql: str, params: tuple | list | None = None):
        if params is None:
            return self._connection.execute(sql)
        return self._connection.execute(sql, params)

    def executemany(self, sql: str, params_seq):
        return self._connection.executemany(sql, params_seq)

    def executescript(self, script: str):
        return self._connection.executescript(script)

    def commit(self) -> None:
        self._connection.commit()

    def close(self) -> None:
        self._connection.close()

    def __getattr__(self, name):
        return getattr(self._connection, name)


def get_db() -> DatabaseHandle:
    if "db" not in g:
        database_spec = current_app.config["DATABASE"]
        connection = sqlite3.connect(database_spec)
        connection.row_factory = sqlite3.Row
        g.db = DatabaseHandle(connection, "sqlite")
    return g.db


def table_exists(db: DatabaseHandle, table_name: str) -> bool:
    row = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_app_setting(db: DatabaseHandle, setting_key: str, default: str | None = None) -> str | None:
    if not table_exists(db, "app_settings"):
        return default

    row = db.execute(
        """
        SELECT setting_value
        FROM app_settings
        WHERE setting_key = ?
        """,
        (setting_key,),
    ).fetchone()
    if row is None:
        return default
    return row["setting_value"] or default


def set_app_setting(db: DatabaseHandle, setting_key: str, setting_value: str) -> None:
    db.execute(
        """
        INSERT INTO app_settings (setting_key, setting_value)
        VALUES (?, ?)
        ON CONFLICT(setting_key) DO UPDATE SET
            setting_value = excluded.setting_value,
            updated_at = CURRENT_TIMESTAMP
        """,
        (setting_key, setting_value),
    )


def delete_app_setting(db: DatabaseHandle, setting_key: str) -> None:
    if table_exists(db, "app_settings"):
        db.execute(
            "DELETE FROM app_settings WHERE setting_key = ?",
            (setting_key,),
        )


def close_db(_error=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _candidate_workbook_paths() -> list[Path]:
    root = _project_root()
    return [root / name for name in WORKBOOK_CANDIDATES]


def _find_existing_workbook() -> Path | None:
    for path in _candidate_workbook_paths():
        if path.exists():
            return path
    return None


def _candidate_statement_csv_paths() -> list[Path]:
    root = _project_root()
    return sorted(
        [
            path
            for path in root.glob("Transactions_Export*.csv")
            if path.is_file()
        ],
        key=lambda path: path.name.lower(),
    )


def _normalize_statement_text(raw_value: str | None) -> str:
    if raw_value is None:
        return ""
    return re.sub(r"\s+", " ", str(raw_value)).strip().upper()


def _tokenize_match_text(raw_value: str | None) -> set[str]:
    normalized = _normalize_statement_text(raw_value)
    return {token for token in re.split(r"[^A-Z0-9]+", normalized) if token}


def _parse_statement_date(raw_value: str | None) -> str | None:
    if not raw_value:
        return None

    value = str(raw_value).strip()
    for format_string in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, format_string).date().isoformat()
        except ValueError:
            continue
    return value


def _parse_statement_amount(raw_value: str | None) -> float:
    if raw_value in (None, ""):
        return 0.0
    return round(float(str(raw_value).replace(",", "").strip()), 2)


def _bank_transaction_match_query(
    db: sqlite3.Connection,
    transaction_date: str | None,
    details: str,
    transaction_type: str | None,
    money_in: float,
    money_out: float,
    running_balance: float | None,
) -> sqlite3.Row | None:
    if running_balance is None:
        balance_clause = "bt.running_balance IS NULL"
        balance_params: tuple[object, ...] = ()
    else:
        balance_clause = "ROUND(CAST(bt.running_balance AS numeric), 2) = ?"
        balance_params = (round(float(running_balance), 2),)

    query = f"""
        SELECT *
        FROM bank_transactions bt
        WHERE COALESCE(bt.transaction_date, '') = ?
          AND UPPER(TRIM(bt.details)) = ?
          AND COALESCE(UPPER(TRIM(bt.transaction_type)), '') = ?
          AND ROUND(CAST(bt.money_in AS numeric), 2) = ?
          AND ROUND(CAST(bt.money_out AS numeric), 2) = ?
          AND {balance_clause}
        ORDER BY bt.id ASC
        LIMIT 1
    """
    return db.execute(
        query,
        (
            transaction_date or "",
            _normalize_statement_text(details),
            _normalize_statement_text(transaction_type),
            round(money_in, 2),
            round(money_out, 2),
            *balance_params,
        ),
    ).fetchone()


def _score_bank_transaction_match(
    target_date: str | None,
    details: str,
    transaction_type: str | None,
    candidate: sqlite3.Row,
) -> float:
    score = 0.0
    target_details = _normalize_statement_text(details)
    candidate_details = _normalize_statement_text(candidate["details"])
    target_type = _normalize_statement_text(transaction_type)
    candidate_type = _normalize_statement_text(candidate["transaction_type"])

    if target_details and candidate_details:
        if target_details == candidate_details:
            score += 100.0
        else:
            ratio = difflib.SequenceMatcher(None, target_details, candidate_details).ratio()
            score += ratio * 60.0

        target_tokens = _tokenize_match_text(details)
        candidate_tokens = _tokenize_match_text(candidate["details"])
        if target_tokens and candidate_tokens:
            overlap = len(target_tokens & candidate_tokens) / len(target_tokens | candidate_tokens)
            score += overlap * 40.0

    if target_type and candidate_type:
        if target_type == candidate_type:
            score += 20.0
        else:
            score -= 10.0

    candidate_date = candidate["transaction_date"]
    if target_date and candidate_date:
        try:
            target_dt = datetime.strptime(target_date, "%Y-%m-%d").date()
            candidate_dt = datetime.strptime(str(candidate_date), "%Y-%m-%d").date()
            day_gap = abs((target_dt - candidate_dt).days)
            score += max(0.0, 15.0 - min(day_gap, 15))
        except ValueError:
            pass

    if candidate["money_in"] is not None and candidate["money_out"] is not None:
        target_money = float(candidate["money_in"] or 0) + float(candidate["money_out"] or 0)
        score += max(
            0.0,
            5.0
            - abs(target_money - (float(candidate["money_in"] or 0) + float(candidate["money_out"] or 0))),
        )

    return score


def _upsert_bank_transaction(
    db: sqlite3.Connection,
    reporting_period_id: int,
    *,
    source_workbook: str,
    source_sheet: str,
    source_row_number: int,
    transaction_date: str | None,
    details: str,
    transaction_type: str | None,
    money_in: float,
    money_out: float,
    running_balance: float | None,
    is_opening_balance: int = 0,
) -> str:
    existing = db.execute(
        """
        SELECT id
        FROM bank_transactions
        WHERE source_workbook = ?
          AND source_sheet = ?
          AND source_row_number = ?
        LIMIT 1
        """,
        (source_workbook, source_sheet, source_row_number),
    ).fetchone()

    if existing is None:
        existing = _bank_transaction_match_query(
            db,
            transaction_date,
            details,
            transaction_type,
            money_in,
            money_out,
            running_balance,
        )

    if existing is None:
        db.execute(
            """
            INSERT INTO bank_transactions (
                reporting_period_id,
                transaction_date,
                details,
                transaction_type,
                money_in,
                money_out,
                running_balance,
                is_opening_balance,
                source_workbook,
                source_sheet,
                source_row_number
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reporting_period_id,
                transaction_date,
                details,
                transaction_type,
                round(money_in, 2),
                round(money_out, 2),
                running_balance,
                is_opening_balance,
                source_workbook,
                source_sheet,
                source_row_number,
            ),
        )
        return "inserted"

    db.execute(
        """
        UPDATE bank_transactions
        SET
            reporting_period_id = ?,
            transaction_date = ?,
            details = ?,
            transaction_type = ?,
            money_in = ?,
            money_out = ?,
            running_balance = ?,
            is_opening_balance = ?,
            source_workbook = ?,
            source_sheet = ?,
            source_row_number = ?
        WHERE id = ?
        """,
        (
            reporting_period_id,
            transaction_date,
            details,
            transaction_type,
            round(money_in, 2),
            round(money_out, 2),
            running_balance,
            is_opening_balance,
            source_workbook,
            source_sheet,
            source_row_number,
            existing["id"],
        ),
    )
    return "updated"


def _import_bank_statement_csv(
    db: sqlite3.Connection,
    reporting_period_id: int,
    csv_path: Path,
) -> dict[str, int]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return _import_bank_statement_csv_handle(db, reporting_period_id, handle, csv_path.name)


def _import_bank_statement_csv_handle(
    db: sqlite3.Connection,
    reporting_period_id: int,
    handle,
    source_workbook: str,
) -> dict[str, int]:
    inserted = 0
    updated = 0

    reader = csv.DictReader(handle)
    for row_number, row in enumerate(reader, start=2):
        if not row:
            continue

        transaction_date = _parse_statement_date(row.get("Date"))
        details = (row.get("Details") or "").strip()
        transaction_type = (row.get("Transaction Type") or "").strip() or None
        money_in = _parse_statement_amount(row.get("In"))
        money_out = _parse_statement_amount(row.get("Out"))
        running_balance = _parse_statement_amount(row.get("Balance"))

        if (
            not transaction_date
            and not details
            and transaction_type is None
            and money_in == 0
            and money_out == 0
            and running_balance == 0
        ):
            continue

        action = _upsert_bank_transaction(
            db,
            reporting_period_id,
            source_workbook=source_workbook,
            source_sheet="CSV",
            source_row_number=row_number,
            transaction_date=transaction_date,
            details=details or "Imported statement row",
            transaction_type=transaction_type,
            money_in=money_in,
            money_out=money_out,
            running_balance=running_balance,
        )

        if action == "inserted":
            inserted += 1
        else:
            updated += 1

    return {"inserted": inserted, "updated": updated}


def import_bank_statement_uploads(
    db: sqlite3.Connection,
    reporting_period_id: int,
    uploaded_files,
) -> dict[str, int]:
    totals = {"files": 0, "inserted": 0, "updated": 0}

    for uploaded_file in uploaded_files:
        if uploaded_file is None or not getattr(uploaded_file, "filename", ""):
            continue

        raw_bytes = uploaded_file.read()
        if not raw_bytes:
            continue

        with io.StringIO(raw_bytes.decode("utf-8-sig")) as handle:
            file_totals = _import_bank_statement_csv_handle(
                db,
                reporting_period_id,
                handle,
                uploaded_file.filename,
            )

        totals["files"] += 1
        totals["inserted"] += file_totals["inserted"]
        totals["updated"] += file_totals["updated"]

    return totals


def import_bank_statement_exports(
    db: sqlite3.Connection,
    reporting_period_id: int = 1,
    statement_paths: list[Path] | None = None,
) -> dict[str, int]:
    paths = statement_paths if statement_paths is not None else _candidate_statement_csv_paths()
    totals = {"files": 0, "inserted": 0, "updated": 0}

    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        file_totals = _import_bank_statement_csv(db, reporting_period_id, path)
        totals["files"] += 1
        totals["inserted"] += file_totals["inserted"]
        totals["updated"] += file_totals["updated"]

    return totals


def _excel_serial_to_iso_date(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    serial = int(float(raw_value))
    return (date(1899, 12, 30) + timedelta(days=serial)).isoformat()


def _to_amount(raw_value: str | None) -> float:
    if raw_value in (None, ""):
        return 0.0
    return round(float(raw_value), 2)


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    shared_strings: list[str] = []
    path = "xl/sharedStrings.xml"
    if path not in archive.namelist():
        return shared_strings

    root = ET.fromstring(archive.read(path))
    for item in root.findall(f"{{{_MAIN_NS}}}si"):
        shared_strings.append("".join(node.text or "" for node in item.iter(f"{{{_MAIN_NS}}}t")))
    return shared_strings


def _get_cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")

    if cell_type == "inlineStr":
        text_node = cell.find(f"{{{_MAIN_NS}}}is")
        return "" if text_node is None else "".join(node.text or "" for node in text_node.iter(f"{{{_MAIN_NS}}}t"))

    value_node = cell.find(f"{{{_MAIN_NS}}}v")
    if value_node is None or value_node.text is None:
        return ""

    if cell_type == "s":
        return shared_strings[int(value_node.text)]

    return value_node.text


def _sheet_target_by_name(archive: zipfile.ZipFile, sheet_name: str) -> str | None:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    relationship_map = {
        relationship.attrib["Id"]: relationship.attrib["Target"]
        for relationship in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
    }

    sheets = workbook.find("main:sheets", _NS)
    if sheets is None:
        return None

    for sheet in sheets.findall("main:sheet", _NS):
        if sheet.attrib.get("name") == sheet_name:
            relationship_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
            if relationship_id:
                return relationship_map.get(relationship_id)
    return None


def _read_sheet_rows(workbook_path: Path, sheet_name: str) -> list[tuple[int, dict[str, str]]]:
    with zipfile.ZipFile(workbook_path) as archive:
        target = _sheet_target_by_name(archive, sheet_name)
        if target is None:
            return []

        shared_strings = _load_shared_strings(archive)
        sheet_xml = ET.fromstring(archive.read(f"xl/{target}"))
        sheet_data = sheet_xml.find(f"{{{_MAIN_NS}}}sheetData")
        if sheet_data is None:
            return []

        rows: list[tuple[int, dict[str, str]]] = []
        for row in sheet_data.findall(f"{{{_MAIN_NS}}}row"):
            row_number = int(row.attrib["r"])
            values: dict[str, str] = {}
            for cell in row.findall(f"{{{_MAIN_NS}}}c"):
                reference = cell.attrib.get("r", "")
                column = re.match(r"[A-Z]+", reference)
                if column is None:
                    continue
                values[column.group(0)] = _get_cell_value(cell, shared_strings)
            rows.append((row_number, values))
        return rows


def seed_ledger_categories(db: sqlite3.Connection) -> None:
    db.executemany(
        """
        INSERT INTO ledger_categories (code, display_name, direction, sort_order)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (code) DO NOTHING
        """,
        BANK_CATEGORY_DEFINITIONS,
    )


def seed_virtual_accounts(db: sqlite3.Connection) -> None:
    db.executemany(
        """
        INSERT INTO virtual_accounts (code, display_name, sort_order)
        VALUES (?, ?, ?)
        ON CONFLICT (code) DO UPDATE SET
            display_name = excluded.display_name,
            sort_order = excluded.sort_order
        """,
        VIRTUAL_ACCOUNT_DEFINITIONS,
    )


def _merge_removed_virtual_accounts_into_main(
    db: sqlite3.Connection,
    removed_codes: tuple[str, ...],
) -> None:
    if not removed_codes:
        return

    main_row = db.execute(
        "SELECT id FROM virtual_accounts WHERE code = ?",
        ("MAIN",),
    ).fetchone()
    if main_row is None:
        return
    main_id = main_row["id"]

    placeholders = ",".join(["?"] * len(removed_codes))
    removed_rows = db.execute(
        f"""
        SELECT id
        FROM virtual_accounts
        WHERE code IN ({placeholders})
        """,
        removed_codes,
    ).fetchall()
    if not removed_rows:
        return

    removed_ids = [row["id"] for row in removed_rows]
    removed_placeholders = ",".join(["?"] * len(removed_ids))

    balance_rows = db.execute(
        f"""
        SELECT reporting_period_id, COALESCE(SUM(opening_balance), 0) AS total_opening_balance
        FROM virtual_account_balances
        WHERE virtual_account_id IN ({removed_placeholders})
        GROUP BY reporting_period_id
        """,
        removed_ids,
    ).fetchall()

    existing_main_balances = {
        row["reporting_period_id"]: float(row["opening_balance"] or 0)
        for row in db.execute(
            "SELECT reporting_period_id, opening_balance FROM virtual_account_balances WHERE virtual_account_id = ?",
            (main_id,),
        ).fetchall()
    }

    for row in balance_rows:
        reporting_period_id = row["reporting_period_id"]
        total_opening_balance = existing_main_balances.get(reporting_period_id, 0.0) + float(
            row["total_opening_balance"] or 0
        )
        db.execute(
            """
            INSERT INTO virtual_account_balances (reporting_period_id, virtual_account_id, opening_balance)
            VALUES (?, ?, ?)
            ON CONFLICT (reporting_period_id, virtual_account_id) DO UPDATE SET opening_balance = excluded.opening_balance
            """,
            (reporting_period_id, main_id, total_opening_balance),
        )
        existing_main_balances[reporting_period_id] = total_opening_balance

    db.execute(
        f"""
        UPDATE virtual_account_category_map
        SET virtual_account_id = ?
        WHERE virtual_account_id IN ({removed_placeholders})
        """,
        (main_id, *removed_ids),
    )
    db.execute(
        f"""
        UPDATE virtual_account_transfers
        SET from_virtual_account_id = ?
        WHERE from_virtual_account_id IN ({removed_placeholders})
        """,
        (main_id, *removed_ids),
    )
    db.execute(
        f"""
        UPDATE virtual_account_transfers
        SET to_virtual_account_id = ?
        WHERE to_virtual_account_id IN ({removed_placeholders})
        """,
        (main_id, *removed_ids),
    )
    db.execute(
        f"""
        DELETE FROM virtual_account_balances
        WHERE virtual_account_id IN ({removed_placeholders})
        """,
        removed_ids,
    )
    db.execute(
        f"""
        DELETE FROM virtual_accounts
        WHERE id IN ({removed_placeholders})
        """,
        removed_ids,
    )


def consolidate_virtual_accounts(db: sqlite3.Connection) -> None:
    _merge_removed_virtual_accounts_into_main(db, ("SUBS", "DINING"))

    target = db.execute(
        "SELECT id FROM virtual_accounts WHERE code = ?",
        ("GLASGOW_FRANK",),
    ).fetchone()
    target_id = target["id"] if target else None

    legacy_rows = db.execute(
        """
        SELECT id, code
        FROM virtual_accounts
        WHERE code IN ('GLASGOW', 'FRANK')
        ORDER BY sort_order, code
        """,
    ).fetchall()
    if not legacy_rows and target_id is not None:
        if db.execute("SELECT COUNT(*) AS total FROM virtual_account_category_map").fetchone()["total"] == 0:
            seed_virtual_account_category_map(db)
        return

    if target_id is None:
        db.execute(
            """
            INSERT INTO virtual_accounts (code, display_name, sort_order)
            VALUES (?, ?, ?)
            """,
            ("GLASGOW_FRANK", "Glasgow/Frank", 30),
        )
        target_id = db.execute(
            "SELECT id FROM virtual_accounts WHERE code = ?",
            ("GLASGOW_FRANK",),
        ).fetchone()["id"]

    legacy_ids = [row["id"] for row in legacy_rows]
    if legacy_ids:
        balance_rows = db.execute(
            f"""
            SELECT reporting_period_id, COALESCE(SUM(opening_balance), 0) AS total_opening_balance
            FROM virtual_account_balances
            WHERE virtual_account_id IN ({", ".join(["?"] * len(legacy_ids))})
            GROUP BY reporting_period_id
            """,
            legacy_ids,
        ).fetchall()
        existing_target_balances = {
            row["reporting_period_id"]: float(row["opening_balance"] or 0)
            for row in db.execute(
                "SELECT reporting_period_id, opening_balance FROM virtual_account_balances WHERE virtual_account_id = ?",
                (target_id,),
            ).fetchall()
        }

        for row in balance_rows:
            reporting_period_id = row["reporting_period_id"]
            total_opening_balance = float(row["total_opening_balance"] or 0)
            if reporting_period_id in existing_target_balances:
                total_opening_balance += existing_target_balances[reporting_period_id]
            db.execute(
                """
                INSERT INTO virtual_account_balances (reporting_period_id, virtual_account_id, opening_balance)
                VALUES (?, ?, ?)
                ON CONFLICT (reporting_period_id, virtual_account_id) DO UPDATE SET opening_balance = excluded.opening_balance
                """,
                (reporting_period_id, target_id, total_opening_balance),
            )

        db.execute(
            f"""
            DELETE FROM virtual_account_balances
            WHERE virtual_account_id IN ({", ".join(["?"] * len(legacy_ids))})
            """,
            legacy_ids,
        )
        db.execute(
            f"""
            DELETE FROM virtual_accounts
            WHERE id IN ({", ".join(["?"] * len(legacy_ids))})
            """,
            legacy_ids,
        )

    if db.execute("SELECT COUNT(*) AS total FROM virtual_account_category_map").fetchone()["total"] == 0:
        seed_virtual_account_category_map(db)


def seed_virtual_account_category_map(db: sqlite3.Connection) -> None:
    account_ids = {
        row["code"]: row["id"]
        for row in db.execute("SELECT id, code FROM virtual_accounts").fetchall()
    }
    category_ids = {
        row["code"]: row["id"]
        for row in db.execute("SELECT id, code FROM ledger_categories").fetchall()
    }
    mappings: list[tuple[int, int]] = []
    for account_code, category_codes in VIRTUAL_ACCOUNT_CATEGORY_MAP.items():
        account_id = account_ids.get(account_code)
        if account_id is None:
            continue
        for category_code in category_codes:
            category_id = category_ids.get(category_code)
            if category_id is None:
                continue
            mappings.append((account_id, category_id))

    db.execute("DELETE FROM virtual_account_category_map")

    db.executemany(
        """
        INSERT INTO virtual_account_category_map (virtual_account_id, ledger_category_id)
        VALUES (?, ?)
        """,
        mappings,
    )


def virtual_account_category_mappings(db: sqlite3.Connection) -> list[dict[str, object]]:
    rows = db.execute(
        """
        SELECT
            lc.id AS ledger_category_id,
            lc.code AS ledger_category_code,
            lc.display_name AS ledger_category_name,
            COALESCE(va.code, 'MAIN') AS virtual_account_code,
            COALESCE(va.display_name, 'Main') AS virtual_account_name
        FROM ledger_categories lc
        LEFT JOIN virtual_account_category_map vacm ON vacm.ledger_category_id = lc.id
        LEFT JOIN virtual_accounts va ON va.id = vacm.virtual_account_id
        ORDER BY lc.direction, lc.sort_order, lc.display_name
        """,
    ).fetchall()
    return [
        {
            "ledger_category_id": row["ledger_category_id"],
            "ledger_category_code": row["ledger_category_code"],
            "ledger_category_name": row["ledger_category_name"],
            "virtual_account_code": row["virtual_account_code"],
            "virtual_account_name": row["virtual_account_name"],
        }
        for row in rows
    ]


def replace_virtual_account_category_map(
    db: sqlite3.Connection,
    mappings: list[tuple[int, int]],
) -> None:
    db.execute("DELETE FROM virtual_account_category_map")
    if mappings:
        db.executemany(
            """
            INSERT INTO virtual_account_category_map (virtual_account_id, ledger_category_id)
            VALUES (?, ?)
            """,
            mappings,
        )


def ensure_financial_tables(db: sqlite3.Connection) -> None:
    schema_sql = _schema_sql_for_sqlite(
        """
        CREATE TABLE IF NOT EXISTS ledger_categories (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            direction TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
        );

        CREATE TABLE IF NOT EXISTS app_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
        );

        CREATE TABLE IF NOT EXISTS app_runtime_locks (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            lock_name TEXT NOT NULL UNIQUE,
            owner_name TEXT NOT NULL,
            machine_name TEXT NOT NULL,
            process_id INTEGER NOT NULL,
            session_token TEXT NOT NULL UNIQUE,
            locked_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            released_at TEXT,
            release_reason TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
        );

        CREATE TABLE IF NOT EXISTS bank_transactions (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            reporting_period_id INTEGER NOT NULL,
            transaction_date TEXT,
            details TEXT NOT NULL,
            transaction_type TEXT,
            money_in REAL NOT NULL DEFAULT 0,
            money_out REAL NOT NULL DEFAULT 0,
            running_balance REAL,
            is_opening_balance INTEGER NOT NULL DEFAULT 0,
            source_workbook TEXT,
            source_sheet TEXT,
            source_row_number INTEGER,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            FOREIGN KEY (reporting_period_id) REFERENCES reporting_periods (id),
            UNIQUE (source_workbook, source_sheet, source_row_number)
        );

        CREATE TABLE IF NOT EXISTS bank_transaction_allocations (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            bank_transaction_id INTEGER NOT NULL,
            ledger_category_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            FOREIGN KEY (bank_transaction_id) REFERENCES bank_transactions (id) ON DELETE CASCADE,
            FOREIGN KEY (ledger_category_id) REFERENCES ledger_categories (id)
        );

        CREATE TABLE IF NOT EXISTS meetings (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            reporting_period_id INTEGER NOT NULL,
            meeting_key TEXT NOT NULL UNIQUE,
            meeting_name TEXT NOT NULL,
            meeting_date TEXT,
            meeting_type TEXT NOT NULL DEFAULT 'Regular',
            sort_order INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            FOREIGN KEY (reporting_period_id) REFERENCES reporting_periods (id)
        );

        CREATE TABLE IF NOT EXISTS cashbook_entries (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            reporting_period_id INTEGER NOT NULL,
            meeting_key TEXT NOT NULL CHECK (meeting_key IN ('SEPTEMBER', 'NOVEMBER', 'JANUARY', 'MARCH', 'MAY')),
            entry_type TEXT NOT NULL,
            entry_name TEXT NOT NULL,
            member_id INTEGER,
            ledger_category_id INTEGER,
            money_in REAL NOT NULL DEFAULT 0,
            money_out REAL NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            FOREIGN KEY (reporting_period_id) REFERENCES reporting_periods (id),
            FOREIGN KEY (member_id) REFERENCES members (id),
            FOREIGN KEY (ledger_category_id) REFERENCES ledger_categories (id)
        );

        CREATE TABLE IF NOT EXISTS cash_settlements (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            reporting_period_id INTEGER NOT NULL,
            meeting_key TEXT NOT NULL CHECK (meeting_key IN ('SEPTEMBER', 'NOVEMBER', 'JANUARY', 'MARCH', 'MAY')),
            settlement_date TEXT NOT NULL,
            net_amount REAL NOT NULL,
            bank_transaction_id INTEGER NOT NULL UNIQUE,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            FOREIGN KEY (reporting_period_id) REFERENCES reporting_periods (id),
            FOREIGN KEY (bank_transaction_id) REFERENCES bank_transactions (id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS virtual_accounts (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text
        );

        CREATE TABLE IF NOT EXISTS virtual_account_balances (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            reporting_period_id INTEGER NOT NULL,
            virtual_account_id INTEGER NOT NULL,
            opening_balance REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            FOREIGN KEY (reporting_period_id) REFERENCES reporting_periods (id),
            FOREIGN KEY (virtual_account_id) REFERENCES virtual_accounts (id),
            UNIQUE (reporting_period_id, virtual_account_id)
        );

        CREATE TABLE IF NOT EXISTS member_prepayments (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            member_id INTEGER NOT NULL,
            reporting_period_id INTEGER NOT NULL,
            subscription_prepayment REAL NOT NULL DEFAULT 0,
            dining_prepayment REAL NOT NULL DEFAULT 0,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            FOREIGN KEY (member_id) REFERENCES members (id),
            FOREIGN KEY (reporting_period_id) REFERENCES reporting_periods (id),
            UNIQUE (member_id, reporting_period_id)
        );

        CREATE TABLE IF NOT EXISTS virtual_account_category_map (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            virtual_account_id INTEGER NOT NULL,
            ledger_category_id INTEGER NOT NULL UNIQUE,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            FOREIGN KEY (virtual_account_id) REFERENCES virtual_accounts (id),
            FOREIGN KEY (ledger_category_id) REFERENCES ledger_categories (id)
        );

        CREATE TABLE IF NOT EXISTS virtual_account_transfers (
            id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            reporting_period_id INTEGER NOT NULL,
            from_virtual_account_id INTEGER,
            to_virtual_account_id INTEGER,
            amount REAL NOT NULL DEFAULT 0,
            transfer_date TEXT,
            description TEXT NOT NULL,
            notes TEXT,
            source_workbook TEXT,
            source_sheet TEXT,
            source_row_number INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP::text,
            FOREIGN KEY (reporting_period_id) REFERENCES reporting_periods (id),
            FOREIGN KEY (from_virtual_account_id) REFERENCES virtual_accounts (id),
            FOREIGN KEY (to_virtual_account_id) REFERENCES virtual_accounts (id),
            UNIQUE (source_workbook, source_sheet, source_row_number)
        );

        CREATE INDEX IF NOT EXISTS idx_bank_transactions_date ON bank_transactions (transaction_date);
        CREATE INDEX IF NOT EXISTS idx_bank_transactions_reporting_period_id ON bank_transactions (reporting_period_id);
        CREATE INDEX IF NOT EXISTS idx_app_settings_updated_at ON app_settings (updated_at);
        CREATE INDEX IF NOT EXISTS idx_app_runtime_locks_last_seen_at ON app_runtime_locks (last_seen_at);
        CREATE INDEX IF NOT EXISTS idx_bank_transaction_allocations_transaction_id ON bank_transaction_allocations (bank_transaction_id);
        CREATE INDEX IF NOT EXISTS idx_bank_transaction_allocations_category_id ON bank_transaction_allocations (ledger_category_id);
        CREATE INDEX IF NOT EXISTS idx_meetings_reporting_period_id ON meetings (reporting_period_id);
        CREATE INDEX IF NOT EXISTS idx_meetings_sort_order ON meetings (sort_order);
        CREATE INDEX IF NOT EXISTS idx_cashbook_entries_meeting_key ON cashbook_entries (meeting_key);
        CREATE INDEX IF NOT EXISTS idx_cash_settlements_meeting_key ON cash_settlements (meeting_key);
        CREATE INDEX IF NOT EXISTS idx_virtual_account_balances_reporting_period_id ON virtual_account_balances (reporting_period_id);
        CREATE INDEX IF NOT EXISTS idx_member_prepayments_reporting_period_id ON member_prepayments (reporting_period_id);
        CREATE INDEX IF NOT EXISTS idx_virtual_account_transfers_reporting_period_id ON virtual_account_transfers (reporting_period_id);
        """
    )
    db.executescript(
        schema_sql
    )
    _ensure_cash_settlement_migration(db)


def _ensure_cash_settlement_migration(db: DatabaseHandle) -> None:
    if not table_exists(db, "cash_settlements"):
        return

    schema_row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'cash_settlements'"
    ).fetchone()
    if schema_row and "UNIQUE (reporting_period_id, meeting_key)" in (schema_row[0] or ""):
        db.execute("PRAGMA foreign_keys = OFF")
        db.executescript(
            """
            CREATE TABLE cash_settlements_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reporting_period_id INTEGER NOT NULL,
                meeting_key TEXT NOT NULL CHECK (meeting_key IN ('SEPTEMBER', 'NOVEMBER', 'JANUARY', 'MARCH', 'MAY')),
                settlement_date TEXT NOT NULL,
                net_amount REAL NOT NULL,
                bank_transaction_id INTEGER NOT NULL UNIQUE,
                notes TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (reporting_period_id) REFERENCES reporting_periods (id),
                FOREIGN KEY (bank_transaction_id) REFERENCES bank_transactions (id) ON DELETE CASCADE
            );

            INSERT INTO cash_settlements_new (
                id, reporting_period_id, meeting_key, settlement_date,
                net_amount, bank_transaction_id, notes, created_at
            )
            SELECT
                id, reporting_period_id, meeting_key, settlement_date,
                net_amount, bank_transaction_id, notes, created_at
            FROM cash_settlements;

            DROP TABLE cash_settlements;
            ALTER TABLE cash_settlements_new RENAME TO cash_settlements;
            """
        )
        db.execute("PRAGMA foreign_keys = ON")


def _category_id_map(db: sqlite3.Connection) -> dict[str, int]:
    return {
        row["code"]: row["id"]
        for row in db.execute("SELECT id, code FROM ledger_categories").fetchall()
    }


def cash_settlement_map(
    db: sqlite3.Connection,
    reporting_period_id: int,
) -> dict[str, dict[str, object]]:
    rows = db.execute(
        """
        SELECT
            cs.id,
            cs.meeting_key,
            cs.settlement_date,
            cs.net_amount,
            cs.bank_transaction_id,
            cs.notes,
            bt.transaction_date AS bank_transaction_date,
            bt.details AS bank_details,
            bt.transaction_type AS bank_transaction_type
        FROM cash_settlements cs
        JOIN bank_transactions bt ON bt.id = cs.bank_transaction_id
        WHERE cs.reporting_period_id = ?
        ORDER BY cs.settlement_date, cs.id
        """,
        (reporting_period_id,),
    ).fetchall()

    settlement_map: dict[str, dict[str, object]] = {}
    for row in rows:
        bucket = settlement_map.setdefault(
            row["meeting_key"],
            {"settlements": [], "settled_total": 0.0},
        )
        settlement = {
            "id": row["id"],
            "meeting_key": row["meeting_key"],
            "settlement_date": row["settlement_date"],
            "net_amount": float(row["net_amount"] or 0),
            "bank_transaction_id": row["bank_transaction_id"],
            "notes": row["notes"],
            "bank_transaction_date": row["bank_transaction_date"],
            "bank_details": row["bank_details"],
            "bank_transaction_type": row["bank_transaction_type"],
        }
        bucket["settlements"].append(settlement)
        bucket["settled_total"] = float(bucket["settled_total"]) + float(row["net_amount"] or 0)
    return settlement_map


def _meeting_cash_totals(
    db: sqlite3.Connection,
    reporting_period_id: int,
    meeting_key: str,
) -> dict[str, float]:
    totals = db.execute(
        """
        SELECT
            COALESCE(SUM(money_in), 0) AS total_in,
            COALESCE(SUM(money_out), 0) AS total_out
        FROM cashbook_entries
        WHERE reporting_period_id = ? AND meeting_key = ?
        """,
        (reporting_period_id, meeting_key),
    ).fetchone()
    total_in = float(totals["total_in"] or 0)
    total_out = float(totals["total_out"] or 0)
    meeting_net = round(total_in - total_out, 2)

    settled_row = db.execute(
        """
        SELECT COALESCE(SUM(net_amount), 0) AS settled_total
        FROM cash_settlements
        WHERE reporting_period_id = ? AND meeting_key = ?
        """,
        (reporting_period_id, meeting_key),
    ).fetchone()
    settled_total = float(settled_row["settled_total"] or 0)
    remaining_to_settle = round(meeting_net - settled_total, 2)

    return {
        "total_in": total_in,
        "total_out": total_out,
        "meeting_net": meeting_net,
        "settled_total": settled_total,
        "remaining_to_settle": remaining_to_settle,
    }


def _insert_cash_settlement_row(
    db: sqlite3.Connection,
    reporting_period_id: int,
    meeting_key: str,
    meeting_name: str,
    settlement_date: str,
    net_amount: float,
    bank_transaction_id: int,
    notes: str | None,
    *,
    meeting_totals: dict[str, float] | None = None,
) -> dict[str, object]:
    totals = meeting_totals or _meeting_cash_totals(db, reporting_period_id, meeting_key)

    if totals["remaining_to_settle"] <= 0:
        raise ValueError("That meeting is already fully settled.")
    if net_amount <= 0:
        raise ValueError("There is no positive cash balance to settle for that meeting.")
    if net_amount > totals["remaining_to_settle"]:
        raise ValueError("That deposit is larger than the remaining cash to settle.")

    existing = db.execute(
        "SELECT id FROM cash_settlements WHERE bank_transaction_id = ?",
        (bank_transaction_id,),
    ).fetchone()
    if existing:
        raise ValueError("That bank transaction is already linked to a settlement.")

    inserted = db.execute(
        """
        INSERT INTO cash_settlements (
            reporting_period_id, meeting_key, settlement_date,
            net_amount, bank_transaction_id, notes
        )
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            reporting_period_id,
            meeting_key,
            settlement_date,
            net_amount,
            bank_transaction_id,
            notes,
        ),
    ).fetchone()

    return {
        "id": inserted["id"],
        "meeting_key": meeting_key,
        "meeting_name": meeting_name,
        "settlement_date": settlement_date,
        "net_amount": net_amount,
        "bank_transaction_id": bank_transaction_id,
        "settled_total": round(totals["settled_total"] + net_amount, 2),
        "remaining_to_settle": round(totals["remaining_to_settle"] - net_amount, 2),
        "notes": notes,
    }


def create_cash_settlement(
    db: sqlite3.Connection,
    reporting_period_id: int,
    *,
    meeting_key: str,
    settlement_date: str,
    details: str,
    deposit_amount: float | None = None,
    notes: str | None = None,
) -> dict[str, object]:
    meeting_totals = _meeting_cash_totals(db, reporting_period_id, meeting_key)
    total_in = meeting_totals["total_in"]
    total_out = meeting_totals["total_out"]
    meeting_net = meeting_totals["meeting_net"]
    remaining_to_settle = meeting_totals["remaining_to_settle"]
    if remaining_to_settle <= 0:
        raise ValueError("That meeting is already fully settled.")

    if deposit_amount is None:
        net_amount = remaining_to_settle
    else:
        net_amount = round(float(deposit_amount), 2)
    if net_amount <= 0:
        raise ValueError("There is no positive cash balance to settle for that meeting.")
    if net_amount > remaining_to_settle:
        raise ValueError("That deposit is larger than the remaining cash to settle.")

    category_id_row = db.execute(
        "SELECT id FROM ledger_categories WHERE code = ?",
        ("CASH",),
    ).fetchone()
    if category_id_row is None:
        raise RuntimeError("The CASH ledger category is missing.")

    meeting_row = db.execute(
        """
        SELECT meeting_name, sort_order
        FROM meetings
        WHERE reporting_period_id = ? AND meeting_key = ?
        """,
        (reporting_period_id, meeting_key),
    ).fetchone()
    if meeting_row is None:
        raise ValueError("That meeting could not be found.")

    settlement_index_row = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM cash_settlements
        WHERE reporting_period_id = ? AND meeting_key = ?
        """,
        (reporting_period_id, meeting_key),
    ).fetchone()
    settlement_index = int(settlement_index_row["total"] or 0) + 1
    source_row_number = reporting_period_id * 100000 + int(meeting_row["sort_order"] or 0) * 100 + settlement_index

    bank_transaction = db.execute(
        """
        INSERT INTO bank_transactions (
            reporting_period_id,
            transaction_date,
            details,
            transaction_type,
            money_in,
            money_out,
            source_workbook,
            source_sheet,
            source_row_number,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            reporting_period_id,
            settlement_date,
            details,
            "Cash deposit",
            net_amount,
            0.0,
            "system",
            "cash_settlement",
            source_row_number,
            notes,
        ),
    ).fetchone()

    bank_transaction_id = bank_transaction["id"]
    db.execute(
        """
        INSERT INTO bank_transaction_allocations (
            bank_transaction_id, ledger_category_id, amount
        )
        VALUES (?, ?, ?)
        """,
        (bank_transaction_id, category_id_row["id"], net_amount),
    )

    settlement = _insert_cash_settlement_row(
        db,
        reporting_period_id,
        meeting_key,
        meeting_row["meeting_name"],
        settlement_date,
        net_amount,
        bank_transaction_id,
        notes,
        meeting_totals=meeting_totals,
    )

    return {
        "id": bank_transaction_id,
        "meeting_name": meeting_row["meeting_name"],
        "meeting_key": meeting_key,
        "settlement_date": settlement_date,
        "net_amount": net_amount,
        "total_in": total_in,
        "total_out": total_out,
        "settled_total": settlement["settled_total"],
        "remaining_to_settle": settlement["remaining_to_settle"],
    }


def _dues_status(
    subscription_due: float,
    subscription_paid: float,
    dining_due: float,
    dining_paid: float,
    member_code: str,
) -> str:
    outstanding = (subscription_due - subscription_paid) + (dining_due - dining_paid)
    if member_code in {"EXCLUDE", "DECEASED"}:
        return "written-off"
    if member_code == "RESIGNED" and outstanding > 0:
        return "written-off"
    if outstanding <= 0:
        return "paid"
    if subscription_paid > 0 or dining_paid > 0:
        return "part-paid"
    return "unpaid"


def seed_meeting_schedule(db: sqlite3.Connection, reporting_period_id: int = 1) -> None:
    meeting_rows = [
        ("SEPTEMBER", "September Meeting", "2025-09-15", "Regular", 1, ""),
        ("NOVEMBER", "November Meeting", "2025-11-17", "Regular", 2, ""),
        ("JANUARY", "January Meeting", "2026-01-19", "Regular", 3, ""),
        ("MARCH", "March Meeting", "2026-03-16", "Regular", 4, ""),
        ("MAY", "Installation Meeting", "2026-05-18", "Installation", 5, ""),
    ]

    db.executemany(
        """
        INSERT INTO meetings (
            reporting_period_id, meeting_key, meeting_name, meeting_date, meeting_type, sort_order, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (meeting_key) DO NOTHING
        """,
        [
            (reporting_period_id, key, name, meeting_date, meeting_type, sort_order, notes)
            for key, name, meeting_date, meeting_type, sort_order, notes in meeting_rows
        ],
    )


def seed_virtual_account_balances(db: sqlite3.Connection, reporting_period_id: int = 1) -> None:
    virtual_accounts = db.execute("SELECT id, code FROM virtual_accounts").fetchall()
    if not virtual_accounts:
        return

    existing_balances = {
        row["virtual_account_id"]: float(row["opening_balance"] or 0)
        for row in db.execute(
            """
            SELECT virtual_account_id, opening_balance
            FROM virtual_account_balances
            WHERE reporting_period_id = ?
            """,
            (reporting_period_id,),
        ).fetchall()
    }

    for row in virtual_accounts:
        default_balance = DEFAULT_VIRTUAL_ACCOUNT_OPENING_BALANCES.get(row["code"], 0.0)
        current_balance = existing_balances.get(row["id"])
        if current_balance is not None and current_balance != 0:
            continue
        db.execute(
            """
            INSERT INTO virtual_account_balances (reporting_period_id, virtual_account_id, opening_balance)
            VALUES (?, ?, ?)
            ON CONFLICT (reporting_period_id, virtual_account_id) DO UPDATE SET opening_balance = excluded.opening_balance
            """,
            (reporting_period_id, row["id"], default_balance),
        )


def import_bank_transactions_from_workbook(
    db: sqlite3.Connection,
    reporting_period_id: int,
    workbook_path: Path,
) -> int:
    rows = _read_sheet_rows(workbook_path, WORKBOOK_BANK_SHEET)
    if not rows:
        return 0

    category_ids = _category_id_map(db)
    imported = 0

    for row_number, row in rows[1:]:
        row_label = row.get("A", "").strip()
        details = row.get("B", "").strip()
        transaction_type = row.get("C", "").strip()

        if row_label == "TOTALS" or details == "TOTALS":
            break

        if not details and not transaction_type and not row.get("D") and not row.get("E"):
            continue

        transaction_date = _excel_serial_to_iso_date(row.get("A"))
        money_in = _to_amount(row.get("D"))
        money_out = _to_amount(row.get("E"))
        running_balance = row.get("F")

        action = _upsert_bank_transaction(
            db,
            reporting_period_id,
            source_workbook=workbook_path.name,
            source_sheet=WORKBOOK_BANK_SHEET,
            source_row_number=row_number,
            transaction_date=transaction_date,
            details=details or "Imported transaction",
            transaction_type=transaction_type or None,
            money_in=money_in,
            money_out=money_out,
            running_balance=float(running_balance) if running_balance not in (None, "") else None,
            is_opening_balance=1 if details == "Opening Balance" else 0,
        )

        if action == "inserted":
            bank_transaction = db.execute(
                """
                SELECT id
                FROM bank_transactions
                WHERE source_workbook = ? AND source_sheet = ? AND source_row_number = ?
                LIMIT 1
                """,
                (workbook_path.name, WORKBOOK_BANK_SHEET, row_number),
            ).fetchone()
            bank_transaction_id = bank_transaction["id"] if bank_transaction else None
            if bank_transaction_id is not None:
                for column, category_code in BANK_COLUMN_CATEGORY_CODES.items():
                    amount = _to_amount(row.get(column))
                    if amount == 0:
                        continue
                    db.execute(
                        """
                        INSERT INTO bank_transaction_allocations (
                            bank_transaction_id, ledger_category_id, amount
                        )
                        VALUES (?, ?, ?)
                        """,
                        (bank_transaction_id, category_ids[category_code], amount),
                    )
            imported += 1

    return imported


def import_cash_entries_from_workbook(
    db: sqlite3.Connection,
    reporting_period_id: int,
    workbook_path: Path,
    *,
    replace: bool = True,
) -> int:
    rows = _read_sheet_rows(workbook_path, WORKBOOK_CASH_SHEET)
    if not rows:
        return 0

    if replace:
        db.execute("DELETE FROM cashbook_entries WHERE reporting_period_id = ?", (reporting_period_id,))
        db.execute("DELETE FROM cash_settlements WHERE reporting_period_id = ?", (reporting_period_id,))

    category_ids = _category_id_map(db)
    meeting_rows = db.execute(
        """
        SELECT meeting_key
        FROM meetings
        WHERE reporting_period_id = ?
        ORDER BY sort_order, meeting_key
        """,
        (reporting_period_id,),
    ).fetchall()
    meeting_keys = [row["meeting_key"] for row in meeting_rows]

    imported = 0
    meeting_index = -1
    current_meeting_key: str | None = None

    for row_number, row in rows:
        row_label = row.get("A", "").strip()
        row_name = row.get("B", "").strip()

        if row_label == "TOTALS" or row_name == "TOTALS":
            break

        if row_label and row_label.upper().endswith("MEETING"):
            meeting_index += 1
            current_meeting_key = meeting_keys[meeting_index] if meeting_index < len(meeting_keys) else None
            continue

        if row_label == "Item" or row_name == "Name":
            continue

        if current_meeting_key is None:
            continue

        entry_type = row_label or "Collection"
        entry_name = row_name or "Imported cash line"

        for column, category_code in CASH_COLUMN_CATEGORY_CODES.items():
            raw_amount = row.get(column)
            amount = _to_amount(raw_amount)
            if amount == 0:
                continue

            if column in CASH_OUT_COLUMNS:
                money_in = 0.0
                money_out = amount
            else:
                money_in = amount
                money_out = 0.0

            category_id = category_ids.get(category_code)
            notes_parts = [f"Imported from {workbook_path.name} Cash!{column}{row_number}"]
            notes_parts.append(f"Workbook label: {entry_type} / {entry_name}")
            if raw_amount is not None and str(raw_amount).strip().startswith("-"):
                notes_parts.append("Negative correction in workbook")

            db.execute(
                """
                INSERT INTO cashbook_entries (
                    reporting_period_id, meeting_key, entry_type, entry_name,
                    member_id, ledger_category_id, money_in, money_out, notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reporting_period_id,
                    current_meeting_key,
                    entry_type,
                    entry_name,
                    None,
                    category_id,
                    money_in,
                    money_out,
                    "; ".join(notes_parts),
                ),
            )
            imported += 1

    return imported


def replace_bank_transaction_allocations(
    db: sqlite3.Connection,
    bank_transaction_id: int,
    allocations: list[tuple[int, float]],
) -> None:
    db.execute(
        "DELETE FROM bank_transaction_allocations WHERE bank_transaction_id = ?",
        (bank_transaction_id,),
    )
    db.executemany(
        """
        INSERT INTO bank_transaction_allocations (bank_transaction_id, ledger_category_id, amount)
        VALUES (?, ?, ?)
        """,
        [
            (bank_transaction_id, ledger_category_id, amount)
            for ledger_category_id, amount in allocations
        ],
    )


def import_bank_transactions(db: sqlite3.Connection, reporting_period_id: int = 1) -> int:
    ensure_financial_tables(db)
    seed_ledger_categories(db)
    workbook_path = _find_existing_workbook()
    if workbook_path is None:
        return 0
    return import_bank_transactions_from_workbook(db, reporting_period_id, workbook_path)


def seed_bank_transactions_from_payments(
    db: sqlite3.Connection,
    reporting_period_id: int,
) -> int:
    category_ids = _category_id_map(db)
    payment_rows = db.execute(
        """
        SELECT
            p.id,
            p.payment_date,
            p.payment_method,
            p.reference,
            p.total_amount,
            p.subscription_amount,
            p.dining_amount,
            m.full_name
        FROM payments p
        JOIN members m ON m.id = p.member_id
        WHERE p.reporting_period_id = ?
        ORDER BY p.payment_date, p.id
        """,
        (reporting_period_id,),
    ).fetchall()

    for payment in payment_rows:
        bank_transaction = db.execute(
            """
            INSERT INTO bank_transactions (
                reporting_period_id,
                transaction_date,
                details,
                transaction_type,
                money_in,
                money_out,
                source_workbook,
                source_sheet,
                source_row_number,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                reporting_period_id,
                payment["payment_date"],
                f'{payment["full_name"]} payment',
                payment["payment_method"],
                float(payment["total_amount"]),
                0.0,
                "system",
                "payments",
                int(payment["id"]),
                payment["reference"],
            ),
        ).fetchone()
        bank_transaction_id = bank_transaction["id"]

        if payment["subscription_amount"] > 0:
            db.execute(
                """
                INSERT INTO bank_transaction_allocations (
                    bank_transaction_id, ledger_category_id, amount
                )
                VALUES (?, ?, ?)
                """,
                (bank_transaction_id, category_ids["SUBS"], float(payment["subscription_amount"])),
            )
        if payment["dining_amount"] > 0:
            db.execute(
                """
                INSERT INTO bank_transaction_allocations (
                    bank_transaction_id, ledger_category_id, amount
                )
                VALUES (?, ?, ?)
                """,
                (bank_transaction_id, category_ids["DINING"], float(payment["dining_amount"])),
            )

    return len(payment_rows)


def seed_bank_ledger(db: sqlite3.Connection, reporting_period_id: int = 1) -> int:
    if db.execute("SELECT COUNT(*) AS total FROM bank_transactions").fetchone()["total"] > 0:
        return 0

    csv_totals = import_bank_statement_exports(db, reporting_period_id)
    if csv_totals["inserted"] > 0 or csv_totals["updated"] > 0:
        return csv_totals["inserted"] + csv_totals["updated"]

    workbook_path = _find_existing_workbook()
    if workbook_path is not None:
        imported = import_bank_transactions_from_workbook(db, reporting_period_id, workbook_path)
        if imported > 0:
            return imported

    return seed_bank_transactions_from_payments(db, reporting_period_id)


def seed_cashbook_from_workbook(db: sqlite3.Connection, reporting_period_id: int = 1) -> int:
    existing_total = db.execute(
        "SELECT COUNT(*) AS total FROM cashbook_entries WHERE reporting_period_id = ?",
        (reporting_period_id,),
    ).fetchone()["total"]
    if existing_total > 0:
        return 0

    workbook_path = _find_existing_workbook()
    if workbook_path is None:
        return 0

    return import_cash_entries_from_workbook(db, reporting_period_id, workbook_path, replace=True)


def _current_reporting_period_id(db: sqlite3.Connection) -> int:
    row = db.execute(
        "SELECT id FROM reporting_periods WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else 1


def _normalize_member_name(raw_value: str | None) -> str:
    if raw_value is None:
        return ""
    normalized = str(raw_value).replace("’", "'")
    return re.sub(r"[^A-Z0-9]+", "", normalized.upper())


def import_member_prepayments_from_workbook(
    db: sqlite3.Connection,
    reporting_period_id: int,
    workbook_path: Path,
    *,
    replace: bool = True,
) -> int:
    rows = _read_sheet_rows(workbook_path, WORKBOOK_MEMBERS_SHEET)
    if not rows:
        return 0

    if replace:
        db.execute("DELETE FROM member_prepayments WHERE reporting_period_id = ?", (reporting_period_id,))

    member_lookup = {
        _normalize_member_name(row["full_name"]): row["id"]
        for row in db.execute("SELECT id, full_name FROM members").fetchall()
    }

    imported = 0
    for row_number, row in rows[1:]:
        name = (row.get("A") or "").strip()
        if not name or name in {"SUBSCRIBING MEMBERS", "FULL Members"}:
            continue

        member_id = member_lookup.get(_normalize_member_name(name))
        if member_id is None:
            continue

        subscription_prepayment = _to_amount(row.get("C"))
        dining_prepayment = _to_amount(row.get("D"))
        if subscription_prepayment == 0 and dining_prepayment == 0:
            continue

        notes = row.get("K", "").strip() or None
        db.execute(
            """
            INSERT INTO member_prepayments (
                member_id, reporting_period_id, subscription_prepayment, dining_prepayment, notes
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (member_id, reporting_period_id) DO UPDATE SET
                subscription_prepayment = excluded.subscription_prepayment,
                dining_prepayment = excluded.dining_prepayment,
                notes = excluded.notes
            """,
            (
                member_id,
                reporting_period_id,
                subscription_prepayment,
                dining_prepayment,
                notes,
            ),
        )
        imported += 1

    return imported


def seed_member_prepayments_from_workbook(db: sqlite3.Connection, reporting_period_id: int = 1) -> int:
    existing_total = db.execute(
        "SELECT COUNT(*) AS total FROM member_prepayments WHERE reporting_period_id = ?",
        (reporting_period_id,),
    ).fetchone()["total"]
    if existing_total > 0:
        return 0

    workbook_path = _find_existing_workbook()
    if workbook_path is None:
        return 0

    return import_member_prepayments_from_workbook(db, reporting_period_id, workbook_path, replace=True)


def import_virtual_account_transfers_from_workbook(
    db: sqlite3.Connection,
    reporting_period_id: int,
    workbook_path: Path,
    *,
    replace: bool = True,
) -> int:
    rows = _read_sheet_rows(workbook_path, WORKBOOK_STATEMENT_SHEET)
    if not rows:
        return 0

    if replace:
        db.execute("DELETE FROM virtual_account_transfers WHERE reporting_period_id = ?", (reporting_period_id,))

    account_ids = {
        row["code"]: row["id"]
        for row in db.execute("SELECT id, code FROM virtual_accounts").fetchall()
    }

    row_lookup = {row_number: row for row_number, row in rows}
    transfer_amount = _to_amount((row_lookup.get(48) or {}).get("F")) or _to_amount((row_lookup.get(43) or {}).get("G"))
    if transfer_amount <= 0:
        return 0

    db.execute(
        """
        INSERT INTO virtual_account_transfers (
            reporting_period_id, from_virtual_account_id, to_virtual_account_id,
            amount, transfer_date, description, source_workbook, source_sheet, source_row_number
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source_workbook, source_sheet, source_row_number) DO UPDATE SET
            from_virtual_account_id = excluded.from_virtual_account_id,
            to_virtual_account_id = excluded.to_virtual_account_id,
            amount = excluded.amount,
            transfer_date = excluded.transfer_date,
            description = excluded.description
        """,
        (
            reporting_period_id,
            account_ids.get("GLASGOW_FRANK"),
            account_ids.get("CENTENARY"),
            transfer_amount,
            None,
            "Workbook opening transfer from Glasgow/Frank to Centenary",
            workbook_path.name,
            WORKBOOK_STATEMENT_SHEET,
            48,
        ),
    )

    return 1


def seed_virtual_account_transfers_from_workbook(
    db: sqlite3.Connection,
    reporting_period_id: int = 1,
) -> int:
    existing_total = db.execute(
        "SELECT COUNT(*) AS total FROM virtual_account_transfers WHERE reporting_period_id = ?",
        (reporting_period_id,),
    ).fetchone()["total"]
    if existing_total > 0:
        return 0

    workbook_path = _find_existing_workbook()
    if workbook_path is None:
        return 0

    return import_virtual_account_transfers_from_workbook(
        db,
        reporting_period_id,
        workbook_path,
        replace=True,
    )


def virtual_account_report(db: sqlite3.Connection, reporting_period_id: int | None = None) -> list[dict[str, object]]:
    reporting_period_id = reporting_period_id or _current_reporting_period_id(db)
    account_rows = db.execute(
        """
        SELECT
            va.id,
            va.code,
            va.display_name,
            va.sort_order,
            COALESCE(vab.opening_balance, 0) AS opening_balance
        FROM virtual_accounts va
        LEFT JOIN virtual_account_balances vab
          ON vab.virtual_account_id = va.id
         AND vab.reporting_period_id = ?
        ORDER BY va.sort_order, va.display_name
        """,
        (reporting_period_id,),
    ).fetchall()

    category_map = {
        row["ledger_category_id"]: row["virtual_account_code"]
        for row in db.execute(
            """
            SELECT vacm.ledger_category_id, va.code AS virtual_account_code
            FROM virtual_account_category_map vacm
            JOIN virtual_accounts va ON va.id = vacm.virtual_account_id
            """
        ).fetchall()
    }

    account_index = {
        row["code"]: {
            "code": row["code"],
            "display_name": row["display_name"],
            "sort_order": row["sort_order"],
            "opening_balance": float(row["opening_balance"] or 0),
            "total_in": 0.0,
            "total_out": 0.0,
            "transfer_in": 0.0,
            "transfer_out": 0.0,
            "closing_balance": float(row["opening_balance"] or 0),
            "entries": [],
            "running_total": float(row["opening_balance"] or 0),
        }
        for row in account_rows
    }

    if "MAIN" not in account_index:
        account_index["MAIN"] = {
            "code": "MAIN",
            "display_name": "Main",
            "sort_order": 10,
            "opening_balance": 0.0,
            "total_in": 0.0,
            "total_out": 0.0,
            "transfer_in": 0.0,
            "transfer_out": 0.0,
            "closing_balance": 0.0,
            "running_total": 0.0,
            "entries": [],
        }

    entry_rows = db.execute(
        """
        SELECT
            bt.id AS bank_transaction_id,
            bt.transaction_date,
            bt.details,
            bt.transaction_type,
            lc.id AS ledger_category_id,
            lc.code AS ledger_category_code,
            lc.display_name AS ledger_category_name,
            lc.direction,
            bta.amount
        FROM bank_transaction_allocations bta
        JOIN bank_transactions bt ON bt.id = bta.bank_transaction_id
        JOIN ledger_categories lc ON lc.id = bta.ledger_category_id
        WHERE bt.reporting_period_id = ?
        ORDER BY
            CASE WHEN bt.transaction_date IS NULL OR bt.transaction_date = '' THEN 1 ELSE 0 END,
            bt.transaction_date,
            bt.id,
            bta.id
        """,
        (reporting_period_id,),
    ).fetchall()

    for row in entry_rows:
        account_code = category_map.get(row["ledger_category_id"], "MAIN")
        if account_code not in account_index:
            account_index[account_code] = {
                "code": account_code,
                "display_name": account_code.title(),
                "sort_order": 999,
                "opening_balance": 0.0,
                "total_in": 0.0,
                "total_out": 0.0,
                "transfer_in": 0.0,
                "transfer_out": 0.0,
                "closing_balance": 0.0,
                "entries": [],
                "running_total": 0.0,
            }
        amount = float(row["amount"] or 0)
        is_income = row["direction"] == "in"
        account = account_index[account_code]
        if is_income:
            account["total_in"] += amount
            account["running_total"] += amount
        else:
            account["total_out"] += amount
            account["running_total"] -= amount
        running = account["running_total"]
        account["entries"].append(
            {
                "bank_transaction_id": row["bank_transaction_id"],
                "transaction_date": row["transaction_date"],
                "details": row["details"],
                "transaction_type": row["transaction_type"],
                "category_code": row["ledger_category_code"],
                "category_name": row["ledger_category_name"],
                "direction": row["direction"],
                "amount": amount,
                "running_total": account["running_total"],
            }
        )

    cash_entry_rows = db.execute(
        """
        SELECT
            c.id AS cash_entry_id,
            c.meeting_key,
            c.entry_type,
            c.entry_name,
            c.ledger_category_id,
            c.money_in,
            c.money_out,
            lc.code AS ledger_category_code,
            lc.display_name AS ledger_category_name,
            lc.direction,
            m.meeting_date,
            m.meeting_name
        FROM cashbook_entries c
        LEFT JOIN ledger_categories lc ON lc.id = c.ledger_category_id
        LEFT JOIN meetings m
          ON m.meeting_key = c.meeting_key
         AND m.reporting_period_id = c.reporting_period_id
        WHERE c.reporting_period_id = ?
        ORDER BY m.sort_order, c.id
        """,
        (reporting_period_id,),
    ).fetchall()

    for row in cash_entry_rows:
        account_code = category_map.get(row["ledger_category_id"], "MAIN")
        if account_code not in account_index:
            account_index[account_code] = {
                "code": account_code,
                "display_name": account_code.title(),
                "sort_order": 999,
                "opening_balance": 0.0,
                "total_in": 0.0,
                "total_out": 0.0,
                "transfer_in": 0.0,
                "transfer_out": 0.0,
                "closing_balance": 0.0,
                "entries": [],
                "running_total": 0.0,
            }

        amount = float(row["money_in"] or row["money_out"] or 0)
        is_income = float(row["money_in"] or 0) > 0
        account = account_index[account_code]
        if is_income:
            account["total_in"] += amount
            account["running_total"] += amount
        else:
            account["total_out"] += amount
            account["running_total"] -= amount

        meeting_name = row["meeting_name"] or row["meeting_key"] or "Cash"
        entry_running = account["running_total"]
        account["entries"].append(
            {
                "bank_transaction_id": None,
                "transaction_date": row["meeting_date"],
                "details": f"{meeting_name}: {row['entry_type']} / {row['entry_name']}",
                "transaction_type": "Cash",
                "category_code": row["ledger_category_code"],
                "category_name": row["ledger_category_name"] or "Unassigned",
                "direction": "in" if is_income else "out",
                "amount": amount,
                "running_total": entry_running,
            }
        )

    prepayment_rows = db.execute(
        """
        SELECT
            m.full_name,
            mp.subscription_prepayment,
            mp.dining_prepayment
        FROM member_prepayments mp
        JOIN members m ON m.id = mp.member_id
        WHERE mp.reporting_period_id = ?
        ORDER BY m.full_name
        """,
        (reporting_period_id,),
    ).fetchall()

    for row in prepayment_rows:
        subscription_amount = float(row["subscription_prepayment"] or 0)
        dining_amount = float(row["dining_prepayment"] or 0)

        if subscription_amount > 0:
            account_index["PRE_SUBS"]["transfer_out"] += subscription_amount
            account_index["MAIN"]["transfer_in"] += subscription_amount
            pre_subs_running = account_index["PRE_SUBS"].get(
                "running_total", account_index["PRE_SUBS"]["opening_balance"]
            )
            account_index["PRE_SUBS"]["entries"].append(
                {
                    "bank_transaction_id": None,
                    "transaction_date": None,
                    "details": f"Pre-paid subs applied for {row['full_name']}",
                    "transaction_type": "Transfer",
                    "category_code": "PRE_SUBS",
                    "category_name": "Pre-Paid Subs",
                    "direction": "transfer_out",
                    "amount": subscription_amount,
                    "running_total": pre_subs_running,
                }
            )

        if dining_amount > 0:
            account_index["PRE_DINING"]["transfer_out"] += dining_amount
            account_index["MAIN"]["transfer_in"] += dining_amount
            pre_dining_running = account_index["PRE_DINING"].get(
                "running_total", account_index["PRE_DINING"]["opening_balance"]
            )
            account_index["PRE_DINING"]["entries"].append(
                {
                    "bank_transaction_id": None,
                    "transaction_date": None,
                    "details": f"Pre-paid dining applied for {row['full_name']}",
                    "transaction_type": "Transfer",
                    "category_code": "PRE_DINING",
                    "category_name": "Pre-Paid Dining",
                    "direction": "transfer_out",
                    "amount": dining_amount,
                    "running_total": pre_dining_running,
                }
            )

    transfer_rows = db.execute(
        """
        SELECT
            vat.amount,
            vat.transfer_date,
            vat.description,
            from_account.code AS from_account_code,
            to_account.code AS to_account_code
        FROM virtual_account_transfers vat
        LEFT JOIN virtual_accounts from_account ON from_account.id = vat.from_virtual_account_id
        LEFT JOIN virtual_accounts to_account ON to_account.id = vat.to_virtual_account_id
        WHERE vat.reporting_period_id = ?
        ORDER BY vat.transfer_date, vat.id
        """,
        (reporting_period_id,),
    ).fetchall()

    for row in transfer_rows:
        amount = float(row["amount"] or 0)
        from_code = row["from_account_code"]
        to_code = row["to_account_code"]
        if from_code and from_code in account_index:
            account_index[from_code]["transfer_out"] += amount
        if to_code and to_code in account_index:
            account_index[to_code]["transfer_in"] += amount

    for account in account_index.values():
        account["closing_balance"] = (
            account["opening_balance"]
            + account["total_in"]
            - account["total_out"]
            + account["transfer_in"]
            - account["transfer_out"]
        )

    return sorted(account_index.values(), key=lambda item: (item["sort_order"], item["display_name"]))


def backfill_bank_allocations_from_workbook(
    db: sqlite3.Connection,
    reporting_period_id: int = 1,
    workbook_path: Path | None = None,
) -> dict[str, int]:
    workbook_path = workbook_path or _find_existing_workbook()
    if workbook_path is None:
        return {"rows_seen": 0, "transactions_matched": 0, "allocations_written": 0}

    rows = _read_sheet_rows(workbook_path, WORKBOOK_BANK_SHEET)
    if not rows:
        return {"rows_seen": 0, "transactions_matched": 0, "allocations_written": 0}

    db.execute("DELETE FROM bank_transaction_allocations")
    category_ids = _category_id_map(db)
    rows_seen = 0
    transactions_matched = 0
    allocations_written = 0

    for row_number, row in rows[1:]:
        row_label = row.get("A", "").strip()
        details = row.get("B", "").strip()
        transaction_type = row.get("C", "").strip()

        if row_label == "TOTALS" or details == "TOTALS":
            break

        transaction_date = _excel_serial_to_iso_date(row.get("A"))
        money_in = _to_amount(row.get("D"))
        money_out = _to_amount(row.get("E"))
        running_balance = row.get("F")

        if money_in > 0:
            candidate_rows = db.execute(
                """
                SELECT id, transaction_date, details, transaction_type, money_in, money_out, running_balance
                FROM bank_transactions
                WHERE ROUND(CAST(money_in AS numeric), 2) = ?
                ORDER BY id
                """,
                (money_in,),
            ).fetchall()
        else:
            candidate_rows = db.execute(
                """
                SELECT id, transaction_date, details, transaction_type, money_in, money_out, running_balance
                FROM bank_transactions
                WHERE ROUND(CAST(money_out AS numeric), 2) = ?
                ORDER BY id
                """,
                (money_out,),
            ).fetchall()

        if transaction_type:
            filtered_candidates = [
                candidate
                for candidate in candidate_rows
                if _normalize_statement_text(candidate["transaction_type"])
                == _normalize_statement_text(transaction_type)
            ]
            if filtered_candidates:
                candidate_rows = filtered_candidates

        best_candidate = None
        best_score = 0.0
        for candidate in candidate_rows:
            score = _score_bank_transaction_match(
                transaction_date,
                details or "Imported transaction",
                transaction_type or None,
                candidate,
            )
            if score > best_score:
                best_score = score
                best_candidate = candidate

        matched_transaction = best_candidate if best_score >= 35.0 else None
        rows_seen += 1

        if matched_transaction is None:
            continue

        allocations: list[tuple[int, float]] = []
        for column, category_code in BANK_COLUMN_CATEGORY_CODES.items():
            amount = _to_amount(row.get(column))
            if amount == 0:
                continue
            allocations.append((category_ids[category_code], amount))

        if allocations:
            replace_bank_transaction_allocations(db, matched_transaction["id"], allocations)
            allocations_written += len(allocations)
        transactions_matched += 1

    return {
        "rows_seen": rows_seen,
        "transactions_matched": transactions_matched,
        "allocations_written": allocations_written,
    }


def init_db() -> None:
    db = get_db()
    if table_exists(db, "reporting_periods"):
        return

    schema_path = Path(__file__).with_name("schema.sql")
    db.executescript(_schema_sql_for_sqlite(schema_path.read_text(encoding="utf-8")))

    db.execute(
        """
        INSERT INTO reporting_periods (label, start_date, end_date, is_current)
        VALUES (?, ?, ?, ?)
        """,
        ("2025-26", "2025-09-01", "2026-08-31", 1),
    )

    seed_meeting_schedule(db, reporting_period_id=1)

    db.executemany(
        """
        INSERT INTO member_types (
            code, description, subscription_rule, dining_rule,
            default_subscription_amount, default_dining_amount
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("FULL", "Full member", "standard", "annual_package", 200.00, 125.00),
            ("ND", "Non-diner", "standard", "none", 200.00, 0.00),
            ("PAYG", "Pay as you go dining", "standard", "payg", 200.00, 0.00),
            ("SEC", "Secretary", "exempt", "annual_package", 0.00, 125.00),
            ("EXCLUDE", "Excluded or unrecoverable", "manual", "manual", 200.00, 0.00),
            ("RESIGNED", "Resigned member", "manual", "manual", 200.00, 0.00),
            ("DECEASED", "Deceased member", "manual", "none", 200.00, 0.00),
            ("VISITOR", "Visitor", "none", "payg", 0.00, 0.00),
        ],
    )

    member_rows = [
        ("*Visitor", "VISITOR", None, 0.00, 0.00, 0.00, 0.00, ""),
        ("Awcock,David", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Bradley Brown", "FULL", None, 120.00, 120.00, 75.00, 75.00, ""),
        ("Chipperfield,David", "ND", None, 200.00, 200.00, 0.00, 0.00, ""),
        ("Coleridge,Ashley", "SEC", None, 0.00, 0.00, 0.00, 0.00, ""),
        ("Coleridge-Humphries,Connor", "ND", None, 200.00, 200.00, 150.00, 150.00, ""),
        ("Connolly,P.J", "EXCLUDE", None, 200.00, 0.00, 0.00, 0.00, "Spoke to his son, he has dementia, so this money is lost"),
        ("Featherstone,Allen", "ND", None, 200.00, 200.00, 0.00, 0.00, ""),
        ("Fulford,Len", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Gillam,Mark", "PAYG", None, 200.00, 200.00, 0.00, 0.00, ""),
        ("Higgins, Nicolas", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Holloway,Ian", "RESIGNED", None, 200.00, 0.00, 0.00, 0.00, "Resigned"),
        ("James,Ian", "PAYG", None, 400.00, 300.00, 0.00, 0.00, ""),
        ("Jess, Matthew", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Marshall,Arthur", "ND", None, 200.00, 200.00, 0.00, 0.00, ""),
        ("Matondo, Herve", "RESIGNED", None, 200.00, 0.00, 0.00, 0.00, "Resigning - write off"),
        ("Moss,Peter", "FULL", None, 149.40, 149.40, 93.60, 93.60, ""),
        ("Mullender,Ray", "PAYG", None, 200.00, 200.00, 0.00, 0.00, ""),
        ("O'Brien,Keith", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Pavey, Shaun", "FULL", None, 240.00, 0.00, 0.00, 0.00, "Reminder sent 4th Jan"),
        ("Peacock,Steve", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Petchey,Ken", "ND", None, 200.00, 0.00, 0.00, 0.00, "Reminder sent 4th Jan"),
        ("Phillips,Andrew", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Porter,John", "RESIGNED", None, 200.00, 200.00, 125.00, 125.00, "Arrears from last year, nothing owing now"),
        ("South,Ray", "DECEASED", None, 200.00, 0.00, 0.00, 0.00, "Write off of course"),
        ("Stock,Stephen", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Stribling,Martyn", "ND", None, 200.00, 200.00, 0.00, 0.00, ""),
        ("Walden,Connor", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Walden,Mark", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
        ("Withey, Graham", "FULL", None, 200.00, 200.00, 125.00, 125.00, ""),
    ]

    member_type_ids = {
        row["code"]: row["id"]
        for row in db.execute("SELECT id, code FROM member_types").fetchall()
    }

    db.executemany(
        """
        INSERT INTO members (
            membership_number, full_name, member_type_id, email, phone, status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                f"M{index:03d}",
                name,
                member_type_ids[member_code],
                None,
                None,
                (
                    "visitor" if member_code == "VISITOR"
                    else "excluded" if member_code == "EXCLUDE"
                    else "resigned" if member_code == "RESIGNED"
                    else "deceased" if member_code == "DECEASED"
                    else "active"
                ),
                notes,
            )
            for index, (name, member_code, _pp_subs, subs_due, subs_paid, dining_due, dining_paid, notes)
            in enumerate(member_rows, start=1)
        ],
    )

    db.executemany(
        """
        INSERT INTO dues (
            member_id, reporting_period_id, year,
            subscription_due, subscription_paid, dining_due, dining_paid, status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                index,
                1,
                2026,
                subs_due,
                subs_paid,
                dining_due,
                dining_paid,
                _dues_status(subs_due, subs_paid, dining_due, dining_paid, member_code),
                notes,
            )
            for index, (_name, member_code, _pp_subs, subs_due, subs_paid, dining_due, dining_paid, notes)
            in enumerate(member_rows, start=1)
        ],
    )

    db.executemany(
        """
        INSERT INTO subscription_charges (
            member_id, reporting_period_id, charge_type, description, amount, due_date, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                index,
                1,
                "annual",
                "Annual lodge subscription",
                subs_due,
                "2025-10-01",
                notes,
            )
            for index, (_name, member_code, _pp_subs, subs_due, _subs_paid, _dining_due, _dining_paid, notes)
            in enumerate(member_rows, start=1)
            if member_code != "VISITOR" and subs_due > 0
        ],
    )

    db.execute(
        """
        INSERT INTO events (title, event_date, meal_name, meal_price, booking_deadline, notes)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "April Meeting Dinner",
            "2026-04-21",
            "Three-course festive board",
            22.50,
            "2026-04-17",
            "Members can book meals and note dietary requirements.",
        ),
    )

    db.executemany(
        """
        INSERT INTO dining_charges (
            member_id, event_id, reporting_period_id, description, amount, status, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                index,
                1,
                1,
                "Annual dining balance",
                dining_due,
                "paid" if dining_due <= dining_paid else ("part-paid" if dining_paid > 0 else "due"),
                notes,
            )
            for index, (_name, member_code, _pp_subs, _subs_due, _subs_paid, dining_due, dining_paid, notes)
            in enumerate(member_rows, start=1)
            if member_code != "VISITOR" and dining_due > 0
        ],
    )

    db.executemany(
        """
        INSERT INTO bookings (event_id, member_id, seats, dietary_notes, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (1, 2, 1, "", "confirmed"),
            (1, 10, 1, "", "confirmed"),
        ],
    )

    db.executemany(
        """
        INSERT INTO payments (
            member_id, reporting_period_id, payment_date, payment_method, reference,
            total_amount, subscription_amount, dining_amount, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                index,
                1,
                "2025-09-10",
                "bank",
                f"IMPORT-{index:03d}",
                subs_paid + dining_paid,
                subs_paid,
                dining_paid,
                notes,
            )
            for index, (_name, member_code, _pp_subs, _subs_due, subs_paid, _dining_due, dining_paid, notes)
            in enumerate(member_rows, start=1)
            if member_code != "VISITOR" and (subs_paid + dining_paid) > 0
        ],
    )

    db.execute(
        """
        INSERT INTO messages (sender_name, sender_role, subject, body, status)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "Secretary",
            "secretary",
            "Agenda reminder",
            "Please confirm the dues report is ready for the next committee meeting.",
            "open",
        ),
    )

    ensure_financial_tables(db)
    seed_ledger_categories(db)
    seed_virtual_accounts(db)
    consolidate_virtual_accounts(db)
    seed_virtual_account_balances(db, reporting_period_id=1)
    seed_bank_ledger(db, reporting_period_id=1)
    seed_cashbook_from_workbook(db, reporting_period_id=1)
    seed_member_prepayments_from_workbook(db, reporting_period_id=1)
    seed_virtual_account_transfers_from_workbook(db, reporting_period_id=1)

    db.commit()


def init_app(app) -> None:
    @app.cli.command("init-db")
    def init_db_command() -> None:
        init_db()
        print("Initialized the database.")

    @app.cli.command("backfill-bank-allocations")
    def backfill_bank_allocations_command() -> None:
        db = get_db()
        totals = backfill_bank_allocations_from_workbook(db)
        db.commit()
        print(
            f"Matched {totals['transactions_matched']} bank rows and wrote {totals['allocations_written']} allocations."
        )

    @app.cli.command("import-bank-statements")
    def import_bank_statements_command() -> None:
        db = get_db()
        reporting_period_id = 1
        totals = import_bank_statement_exports(db, reporting_period_id=reporting_period_id)
        if totals["files"] == 0:
            workbook_path = _find_existing_workbook()
            if workbook_path is not None:
                imported = import_bank_transactions_from_workbook(db, reporting_period_id, workbook_path)
                db.commit()
                print(f"Imported {imported} bank transactions from the workbook.")
                return
        allocation_totals = backfill_bank_allocations_from_workbook(db, reporting_period_id)
        db.commit()
        print(
            "Imported "
            f"{totals['inserted']} new and updated {totals['updated']} bank statement rows "
            f"from {totals['files']} CSV file(s). "
            f"Refreshed {allocation_totals['allocations_written']} allocations from the workbook."
        )

    @app.cli.command("import-cashbook")
    def import_cashbook_command() -> None:
        db = get_db()
        reporting_period_id = 1
        workbook_path = _find_existing_workbook()
        if workbook_path is None:
            raise RuntimeError("No workbook was found to import cash rows from.")

        imported = import_cash_entries_from_workbook(db, reporting_period_id, workbook_path, replace=True)
        db.commit()
        print(f"Imported {imported} cash entries from the workbook.")

    @app.cli.command("check-runtime-lock")
    def check_runtime_lock_command() -> None:
        db = get_db()
        lock_row = get_runtime_lock_status(db)
        if lock_row is None:
            print("Runtime lock is available.")
            return

        print(
            "Treasurer is already running on "
            f"{lock_row['machine_name']} as {lock_row['owner_name']} "
            f"since {lock_row['locked_at']}."
        )
        raise SystemExit(1)

    @app.cli.command("unlock-runtime-lock")
    def unlock_runtime_lock_command() -> None:
        db = get_db()
        if force_release_runtime_lock(db):
            db.commit()
            print("Runtime lock cleared.")
            return

        print("No active runtime lock was found.")
