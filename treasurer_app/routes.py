import os
import platform
import sqlite3
import subprocess
import threading
import tempfile
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .backup_mirror_health import clear_failure as clear_backup_mirror_failure
from .backup_mirror_health import record_failure as record_backup_mirror_failure
from .db import (
    APP_SETTING_BACKUP_DATABASE,
    APP_SETTING_BACKUP_FOLDER,
    APP_SETTING_LODGE_DISPLAY_NAME,
    DEFAULT_LODGE_DISPLAY_NAME,
    _dues_status,
    _find_existing_workbook,
    backup_database,
    cash_settlement_map,
    close_db,
    delete_app_setting,
    create_cash_settlement,
    backfill_bank_allocations_from_workbook,
    get_app_setting,
    get_db,
    get_runtime_lock_status,
    import_bank_statement_exports,
    import_bank_statement_uploads,
    import_bank_transactions_from_workbook,
    delete_virtual_account_transfer,
    _insert_cash_settlement_row,
    insert_manual_virtual_account_transfer,
    list_virtual_account_transfers_for_account,
    replace_bank_transaction_allocations,
    replace_virtual_account_category_map,
    seed_meeting_schedule,
    seed_virtual_account_balances,
    consolidate_virtual_accounts,
    resolve_backup_folder_path,
    resolve_backup_database_path,
    resolve_mirror_backup_file_path,
    restore_database_from_backup,
    release_runtime_lock,
    set_app_setting,
    virtual_account_report,
    table_exists,
    update_virtual_account_transfer,
    virtual_account_transfer_involves_account,
    _normalize_member_name,
    virtual_account_category_mappings,
)


main_bp = Blueprint("main", __name__)


@main_bp.route("/healthz")
def healthz():
    """Lightweight liveness probe for reverse proxies and deploy scripts (no DB access)."""
    return ("ok", 200, {"Content-Type": "text/plain; charset=utf-8"})


def _launcher_exit_signal_path() -> Path:
    return Path(os.environ.get("TEMP") or tempfile.gettempdir()) / "treasurer.exit"


def _signal_launcher_exit() -> None:
    try:
        _launcher_exit_signal_path().write_text(datetime.utcnow().isoformat(), encoding="utf-8")
    except Exception:
        pass


@main_bp.app_context_processor
def inject_balance_nav_accounts():
    try:
        db = get_db()
        if not table_exists(db, "virtual_accounts"):
            return {"balance_nav_accounts": []}
        return {"balance_nav_accounts": virtual_account_report(db)}
    except Exception:
        return {"balance_nav_accounts": []}


@main_bp.app_context_processor
def inject_backup_mirror_health():
    from flask import current_app

    return {
        "backup_mirror_error": current_app.config.get("BACKUP_LAST_ERROR"),
        "backup_mirror_error_at": current_app.config.get("BACKUP_LAST_ERROR_AT"),
    }


def _lodge_display_name(db: sqlite3.Connection) -> str:
    name = get_app_setting(db, APP_SETTING_LODGE_DISPLAY_NAME)
    if name and str(name).strip():
        return str(name).strip()
    return DEFAULT_LODGE_DISPLAY_NAME


def _bank_page_context():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    schedule = _meeting_schedule()

    categories = db.execute(
        """
        SELECT id, code, display_name, direction
        FROM ledger_categories
        ORDER BY direction, sort_order, display_name
        """
    ).fetchall()

    transactions = db.execute(
        """
        SELECT
            bt.id,
            bt.transaction_date,
            bt.details,
            bt.transaction_type,
            bt.money_in,
            bt.money_out,
            bt.running_balance,
            bt.is_opening_balance,
            cs.id AS settlement_id,
            cs.meeting_key AS settlement_meeting_key,
            meeting.meeting_name AS settlement_meeting_name,
            cs.settlement_date AS settlement_date,
            cs.net_amount AS settlement_net_amount
        FROM bank_transactions bt
        LEFT JOIN cash_settlements cs ON cs.bank_transaction_id = bt.id
        LEFT JOIN meetings meeting
          ON meeting.reporting_period_id = bt.reporting_period_id
         AND meeting.meeting_key = cs.meeting_key
        WHERE bt.reporting_period_id = ?
        ORDER BY
            CASE WHEN bt.transaction_date IS NULL OR bt.transaction_date = '' THEN 1 ELSE 0 END,
            bt.transaction_date ASC,
            COALESCE(bt.source_workbook, '') ASC,
            CASE WHEN bt.is_opening_balance = 1 THEN 0 ELSE 1 END,
            CASE
                WHEN bt.source_sheet = 'CSV' THEN -COALESCE(bt.source_row_number, bt.id)
                ELSE COALESCE(bt.source_row_number, bt.id)
            END ASC,
            bt.id ASC
        """,
        (reporting_period_id,),
    ).fetchall()

    transaction_ids = [transaction["id"] for transaction in transactions]
    allocations_by_transaction: dict[int, list[dict[str, object]]] = {}
    if transaction_ids:
        placeholders = ",".join(["?"] * len(transaction_ids))
        allocation_rows = db.execute(
            f"""
            SELECT
                bta.bank_transaction_id,
                bta.ledger_category_id,
                bta.amount,
                lc.code AS ledger_category_code,
                lc.display_name AS ledger_category_name
            FROM bank_transaction_allocations bta
            JOIN ledger_categories lc ON lc.id = bta.ledger_category_id
            WHERE bta.bank_transaction_id IN ({placeholders})
            ORDER BY bta.bank_transaction_id, bta.id
            """,
            transaction_ids,
        ).fetchall()

        for row in allocation_rows:
            allocations_by_transaction.setdefault(row["bank_transaction_id"], []).append(
                {
                    "ledger_category_id": row["ledger_category_id"],
                    "ledger_category_code": row["ledger_category_code"],
                    "ledger_category_name": row["ledger_category_name"],
                    "amount": float(row["amount"] or 0),
                }
            )

    prepared_transactions = []
    for transaction in transactions:
        transaction_allocations = allocations_by_transaction.get(transaction["id"], [])
        has_cash_allocation = any(
            allocation["ledger_category_code"] == "CASH" for allocation in transaction_allocations
        )
        allocations = transaction_allocations

        prepared_transactions.append(
            {
                "id": transaction["id"],
                "transaction_date": transaction["transaction_date"],
                "details": transaction["details"],
                "transaction_type": transaction["transaction_type"],
                "money_in": transaction["money_in"],
                "money_out": transaction["money_out"],
                "running_balance": transaction["running_balance"],
                "is_opening_balance": transaction["is_opening_balance"],
                "allocations": allocations,
                "is_cash_category": has_cash_allocation,
                "allocation_total": round(
                    sum(float(allocation["amount"] or 0) for allocation in transaction_allocations),
                    2,
                ),
                "needs_attention": (
                    not transaction_allocations and not transaction["is_opening_balance"]
                ),
                "net_amount": (
                    float(transaction["money_in"])
                    if transaction["money_in"] > 0
                    else float(transaction["money_out"])
                ),
                "settlement_id": transaction["settlement_id"],
                "settlement_meeting_key": transaction["settlement_meeting_key"],
                "settlement_meeting_name": transaction["settlement_meeting_name"],
                "settlement_date": transaction["settlement_date"],
                "settlement_amount": float(transaction["settlement_net_amount"] or 0),
            }
        )

    summary = db.execute(
        """
        SELECT
            COUNT(*) AS total_transactions,
            COALESCE(SUM(money_in), 0) AS total_money_in,
            COALESCE(SUM(money_out), 0) AS total_money_out,
            COALESCE(
                SUM(
                    CASE
                        WHEN bt.is_opening_balance = 0 AND allocation_counts.count_per_transaction IS NULL
                        THEN 1
                        ELSE 0
                    END
                ),
                0
            ) AS uncategorised_transactions
        FROM bank_transactions bt
        LEFT JOIN (
            SELECT bank_transaction_id, COUNT(*) AS count_per_transaction
            FROM bank_transaction_allocations
            GROUP BY bank_transaction_id
        ) allocation_counts ON allocation_counts.bank_transaction_id = bt.id
        WHERE bt.reporting_period_id = ?
        """,
        (reporting_period_id,),
    ).fetchone()

    meeting_summaries = _cash_meeting_summaries(
        db,
        reporting_period_id,
        meeting_schedule=schedule,
    )

    return {
        "bank_transactions": prepared_transactions,
        "ledger_categories": categories,
        "bank_summary": summary,
        "meeting_summaries": meeting_summaries,
    }


def _statement_page_context():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()

    bank_totals = {
        row["code"]: float(row["total_amount"] or 0)
        for row in db.execute(
            """
            SELECT
                lc.code,
                COALESCE(SUM(bta.amount), 0) AS total_amount
            FROM ledger_categories lc
            LEFT JOIN bank_transaction_allocations bta ON bta.ledger_category_id = lc.id
            LEFT JOIN bank_transactions bt
              ON bt.id = bta.bank_transaction_id
             AND bt.reporting_period_id = ?
            WHERE bt.reporting_period_id = ? OR bt.id IS NULL
            GROUP BY lc.code
            """,
            (reporting_period_id, reporting_period_id),
        ).fetchall()
    }

    cash_totals = {
        row["code"]: {
            "money_in": float(row["money_in"] or 0),
            "money_out": float(row["money_out"] or 0),
        }
        for row in db.execute(
            """
            SELECT
                lc.code,
                COALESCE(SUM(c.money_in), 0) AS money_in,
                COALESCE(SUM(c.money_out), 0) AS money_out
            FROM cashbook_entries c
            LEFT JOIN ledger_categories lc ON lc.id = c.ledger_category_id
            WHERE c.reporting_period_id = ?
            GROUP BY lc.code
            """,
            (reporting_period_id,),
        ).fetchall()
    }

    def bank(code: str) -> float:
        return round(bank_totals.get(code, 0.0), 2)

    def cash_in(code: str) -> float:
        return round(cash_totals.get(code, {}).get("money_in", 0.0), 2)

    def cash_out(code: str) -> float:
        return round(cash_totals.get(code, {}).get("money_out", 0.0), 2)

    def rows_with_total(definitions: list[tuple[str, float]]) -> tuple[list[dict[str, float | str]], float]:
        rows = [{"label": label, "amount": round(amount, 2)} for label, amount in definitions]
        return rows, round(sum(row["amount"] for row in rows), 2)

    general_income_rows, general_income_total = rows_with_total(
        [
            ("Dining Fees", bank("DINING") + bank("VISITOR") + cash_in("DINING")),
            ("Subscriptions", bank("SUBS") + cash_in("SUBS")),
            ("Initiation Fees", bank("INITIATION")),
            ("Chapter C of I Rent", bank("CHAPTER_LOI")),
            ("SumUp", bank("SUMUP")),
        ]
    )
    general_expense_rows, general_expense_total = rows_with_total(
        [
            ("Catering", bank("CATERER")),
            ("UGLE", bank("UGLE")),
            ("PGLE", bank("PGLE")),
            ("Orsett Masonic Hall rent", bank("ORSETT")),
            ("L of I Rent Woolmarket", bank("WOOLMKT")),
            ("Tyler's Fee", cash_out("TYLER")),
            ("Bank Charges", bank("BANK_CHARGES")),
        ]
    )

    charity_income_rows, charity_income_total = rows_with_total(
        [
            ("Gavels", bank("GAVEL") + cash_in("GAVEL")),
            ("Raffles", bank("RAFFLE") + cash_in("RAFFLE")),
            ("Charity Donations", bank("DONATIONS_IN")),
        ]
    )
    charity_expense_rows, charity_expense_total = rows_with_total(
        [
            ("Relief Chest", bank("RELIEF")),
            ("Charity donations from Lodge Funds", bank("DONATIONS_OUT") + cash_out("DONATIONS_OUT")),
        ]
    )

    benevolent_income_rows, benevolent_income_total = rows_with_total([])
    benevolent_expense_rows, benevolent_expense_total = rows_with_total(
        [
            ("Widows Christmas gifts", bank("WIDOWS")),
            ("Almoner's expenses", cash_out("ALMONER")),
        ]
    )

    loi_income_rows, loi_income_total = rows_with_total(
        [
            ("Collections", bank("LOI")),
        ]
    )
    loi_expense_rows, loi_expense_total = rows_with_total([])

    latest_balance = db.execute(
        """
        SELECT running_balance
        FROM bank_transactions
        WHERE reporting_period_id = ?
          AND running_balance IS NOT NULL
          AND is_opening_balance = 0
        ORDER BY
            CASE WHEN transaction_date IS NULL OR transaction_date = '' THEN 1 ELSE 0 END,
            transaction_date DESC,
            CASE
                WHEN source_sheet = 'CSV' THEN COALESCE(source_row_number, id)
                ELSE -COALESCE(source_row_number, id)
            END ASC,
            id ASC
        LIMIT 1
        """,
        (reporting_period_id,),
    ).fetchone()

    opening_bank_balance = db.execute(
        """
        SELECT running_balance
        FROM bank_transactions
        WHERE reporting_period_id = ?
          AND is_opening_balance = 1
        ORDER BY
            CASE WHEN transaction_date IS NULL OR transaction_date = '' THEN 1 ELSE 0 END,
            transaction_date ASC,
            COALESCE(source_workbook, '') ASC,
            COALESCE(source_row_number, id) ASC,
            id ASC
        LIMIT 1
        """,
        (reporting_period_id,),
    ).fetchone()

    total_receipts = db.execute(
        """
        SELECT COALESCE(SUM(money_in), 0) AS total
        FROM bank_transactions
        WHERE reporting_period_id = ?
          AND is_opening_balance = 0
        """,
        (reporting_period_id,),
    ).fetchone()["total"]

    total_payments = db.execute(
        """
        SELECT COALESCE(SUM(money_out), 0) AS total
        FROM bank_transactions
        WHERE reporting_period_id = ?
          AND is_opening_balance = 0
        """,
        (reporting_period_id,),
    ).fetchone()["total"]

    uncategorised_transactions = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM bank_transactions bt
        LEFT JOIN bank_transaction_allocations bta ON bta.bank_transaction_id = bt.id
        WHERE bt.is_opening_balance = 0
          AND bt.reporting_period_id = ?
          AND bta.id IS NULL
        """,
        (reporting_period_id,),
    ).fetchone()["total"]

    opening_balances = {
        row["code"]: float(row["opening_balance"] or 0)
        for row in db.execute(
            """
            SELECT va.code, vab.opening_balance
            FROM virtual_account_balances vab
            JOIN virtual_accounts va ON va.id = vab.virtual_account_id
            WHERE vab.reporting_period_id = ?
            """,
            (reporting_period_id,),
        ).fetchall()
    }

    prepayment_totals = db.execute(
        """
        SELECT
            COALESCE(SUM(subscription_prepayment), 0) AS subscription_total,
            COALESCE(SUM(dining_prepayment), 0) AS dining_total
        FROM member_prepayments
        WHERE reporting_period_id = ?
        """,
        (reporting_period_id,),
    ).fetchone()
    prepayment_subs_total = float(prepayment_totals["subscription_total"] or 0)
    prepayment_dining_total = float(prepayment_totals["dining_total"] or 0)

    centenary_transfer_total = db.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM virtual_account_transfers vat
        JOIN virtual_accounts to_account ON to_account.id = vat.to_virtual_account_id
        WHERE vat.reporting_period_id = ?
          AND to_account.code = 'CENTENARY'
        """,
        (reporting_period_id,),
    ).fetchone()["total"]

    balance_rows = []
    for code, label, total_in, total_out, transfer_in, transfer_out in [
        ("MAIN", "Main Account", general_income_total, general_expense_total, prepayment_subs_total + prepayment_dining_total, 0.0),
        ("CHARITY", "Charity Account", charity_income_total, charity_expense_total, 0.0, 0.0),
        ("GLASGOW_FRANK", "Glasgow/Frank", 0.0, 0.0, 0.0, float(centenary_transfer_total or 0)),
        ("LOI", "Lodge of Instruction", loi_income_total, loi_expense_total, 0.0, 0.0),
        ("PRE_SUBS", "Pre-Paid Subs", bank("PRE_SUBS"), 0.0, 0.0, prepayment_subs_total),
        ("PRE_DINING", "Pre-Paid Dining", bank("PRE_DINING"), 0.0, 0.0, prepayment_dining_total),
        ("BENEVOLENT", "Benevolent Fund", benevolent_income_total, benevolent_expense_total, 0.0, 0.0),
        ("CENTENARY", "Centenary Fund", 0.0, 0.0, float(centenary_transfer_total or 0), 0.0),
    ]:
        opening = float(opening_balances.get(code, 0))
        closing = round(opening + total_in - total_out + transfer_in - transfer_out, 2)
        balance_rows.append(
            {
                "code": code,
                "display_name": label,
                "opening_balance": opening,
                "total_in": round(total_in, 2),
                "total_out": round(total_out, 2),
                "transfer_in": round(transfer_in, 2),
                "transfer_out": round(transfer_out, 2),
                "closing_balance": closing,
            }
        )

    balance_total = round(sum(float(row["closing_balance"] or 0) for row in balance_rows), 2)

    # Lodge returns (General, Charity, Benevolent): L.O.I. is tracked separately—not part of the lodge’s
    # formal accounts or Grand Lodge reporting; collections are informational through the shared bank account.
    statement_income_total = round(
        general_income_total + charity_income_total + benevolent_income_total,
        2,
    )
    statement_expense_total = round(
        general_expense_total + charity_expense_total + benevolent_expense_total,
        2,
    )
    statement_net_result = round(statement_income_total - statement_expense_total, 2)
    loi_statement_net = round(loi_income_total - loi_expense_total, 2)

    return {
        "statement_sections": [
            {
                "title": "General Fund Accounts",
                "income_rows": general_income_rows,
                "expense_rows": general_expense_rows,
                "income_total": general_income_total,
                "expense_total": general_expense_total,
            },
            {
                "title": "Charity Account",
                "income_rows": charity_income_rows,
                "expense_rows": charity_expense_rows,
                "income_total": charity_income_total,
                "expense_total": charity_expense_total,
            },
            {
                "title": "Benevolent Fund",
                "income_rows": benevolent_income_rows,
                "expense_rows": benevolent_expense_rows,
                "income_total": benevolent_income_total,
                "expense_total": benevolent_expense_total,
            },
            {
                "title": "Lodge of Instruction",
                "income_rows": loi_income_rows,
                "expense_rows": loi_expense_rows,
                "income_total": loi_income_total,
                "expense_total": loi_expense_total,
            },
        ],
        "income_total": statement_income_total,
        "expense_total": statement_expense_total,
        # Always income_total − expense_total (Statement strip, Auditors header, summary table footer).
        "net_result": statement_net_result,
        "loi_income_total": round(loi_income_total, 2),
        "loi_expense_total": round(loi_expense_total, 2),
        "loi_net_result": loi_statement_net,
        "latest_bank_balance": latest_balance["running_balance"] if latest_balance else None,
        "opening_bank_balance": opening_bank_balance["running_balance"] if opening_bank_balance else None,
        "bank_receipts_total": round(float(total_receipts or 0), 2),
        "bank_payments_total": round(float(total_payments or 0), 2),
        "uncategorised_transactions": uncategorised_transactions,
        "balance_rows": balance_rows,
        "balance_total": balance_total,
        "statement_lodge_name": _lodge_display_name(db),
    }


def _current_reporting_period_id() -> int:
    db = get_db()
    row = db.execute(
        "SELECT id FROM reporting_periods WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["id"] if row else 1


def _current_reporting_period_label() -> str:
    db = get_db()
    row = db.execute(
        "SELECT label FROM reporting_periods WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return row["label"] if row and row["label"] else "2025-26"


def _statement_year_label() -> str:
    label = _current_reporting_period_label()
    if "-" in label:
        parts = label.split("-", 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            if len(parts[0]) == 4 and len(parts[1]) == 2:
                return f"{parts[0]}-{parts[0][:2]}{parts[1]}"
            return f"{parts[0]}-{parts[1]}"
    return label


def _meeting_schedule():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    return db.execute(
        """
        SELECT meeting_key, meeting_name, meeting_date, meeting_type, sort_order, notes
        FROM meetings
        WHERE reporting_period_id = ?
        ORDER BY sort_order, meeting_key
        """,
        (reporting_period_id,),
    ).fetchall()


def _cash_meeting_summaries(
    db: sqlite3.Connection,
    reporting_period_id: int,
    meeting_schedule: list[dict[str, object]] | None = None,
) -> list[dict[str, object]]:
    settlement_map = cash_settlement_map(db, reporting_period_id)
    entry_totals = db.execute(
        """
        SELECT
            meeting_key,
            COALESCE(SUM(money_in), 0) AS total_in,
            COALESCE(SUM(money_out), 0) AS total_out
        FROM cashbook_entries
        WHERE reporting_period_id = ?
        GROUP BY meeting_key
        """,
        (reporting_period_id,),
    ).fetchall()
    totals_map = {row["meeting_key"]: row for row in entry_totals}
    schedule = meeting_schedule or _meeting_schedule()
    summaries = []
    for meeting in schedule:
        meeting_key = meeting["meeting_key"]
        totals = totals_map.get(meeting_key)
        total_in = float(totals["total_in"] or 0) if totals else 0.0
        total_out = float(totals["total_out"] or 0) if totals else 0.0
        meeting_net = round(total_in - total_out, 2)
        settled_total = float(settlement_map.get(meeting_key, {}).get("settled_total", 0))
        remaining_to_bank = round(meeting_net - settled_total, 2)
        summaries.append(
            {
                "meeting_key": meeting_key,
                "meeting_name": meeting["meeting_name"],
                "meeting_date": meeting["meeting_date"],
                "meeting_type": meeting["meeting_type"],
                "net_to_bank": meeting_net,
                "settled_total": settled_total,
                "remaining_to_bank": remaining_to_bank,
            }
        )
    return summaries


def _cash_page_context():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    schedule = _meeting_schedule()
    settlements = cash_settlement_map(db, reporting_period_id)
    today = date.today().isoformat()
    categories = db.execute(
        """
        SELECT id, code, display_name, direction
        FROM ledger_categories
        ORDER BY direction, sort_order, display_name
        """
    ).fetchall()

    member_rows = db.execute(
        """
        SELECT id, full_name
        FROM members
        ORDER BY full_name
        """
    ).fetchall()
    members = [
        {"id": row["id"], "full_name": row["full_name"]}
        for row in member_rows
    ]
    member_lookup = {
        _normalize_member_name(member["full_name"]): member["id"]
        for member in members
    }

    entry_rows = db.execute(
        """
        SELECT
            c.id,
            c.meeting_key,
            c.entry_type,
            c.entry_name,
            c.member_id,
            c.ledger_category_id,
            c.money_in,
            c.money_out,
            c.notes,
            lc.display_name AS category_name,
            m.meeting_name,
            m.meeting_date,
            m.meeting_type,
            m.sort_order
        FROM cashbook_entries c
        LEFT JOIN meetings m
          ON m.meeting_key = c.meeting_key
         AND m.reporting_period_id = c.reporting_period_id
        LEFT JOIN ledger_categories lc ON lc.id = c.ledger_category_id
        WHERE c.reporting_period_id = ?
        ORDER BY m.sort_order, c.id
        """,
        (reporting_period_id,),
    ).fetchall()

    blocks = []
    for meeting in schedule:
        meeting_entries = []
        for row in entry_rows:
            if row["meeting_key"] != meeting["meeting_key"]:
                continue
            normalized_entry_type = (row["entry_type"] or "").strip().lower()
            resolved_member_id = row["member_id"]
            if not resolved_member_id and normalized_entry_type == "member":
                resolved_member_id = member_lookup.get(_normalize_member_name(row["entry_name"]))
            meeting_entries.append(
                {
                    "id": row["id"],
                    "entry_type": row["entry_type"],
                    "entry_name": row["entry_name"],
                    "member_id": resolved_member_id,
                    "ledger_category_id": row["ledger_category_id"],
                    "category_name": row["category_name"],
                    "money_in": row["money_in"],
                    "money_out": row["money_out"],
                    "notes": row["notes"],
                }
            )
        blocks.append(
            {
                "meeting_key": meeting["meeting_key"],
                "meeting_name": meeting["meeting_name"],
                "meeting_date": meeting["meeting_date"],
                "meeting_type": meeting["meeting_type"],
                "entries": meeting_entries,
                "total_in": round(sum(float(row["money_in"] or 0) for row in meeting_entries), 2),
                "total_out": round(sum(float(row["money_out"] or 0) for row in meeting_entries), 2),
                "settlement": settlements.get(meeting["meeting_key"], {"settlements": [], "settled_total": 0.0}),
                "settlement_date_default": meeting["meeting_date"] or today,
            }
        )
    for block in blocks:
        block["net_to_bank"] = round(float(block["total_in"]) - float(block["total_out"]), 2)
        block["settled_total"] = round(float(block["settlement"]["settled_total"]), 2)
        block["remaining_to_bank"] = round(block["net_to_bank"] - block["settled_total"], 2)
        block["settlement_count"] = len(block["settlement"]["settlements"])

    return {
        "meeting_blocks": blocks,
        "meeting_schedule": schedule,
        "ledger_categories": categories,
        "members": members,
    }


def _members_page_context():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    member_rows = db.execute(
        """
        SELECT
            m.id,
            m.membership_number,
            m.full_name,
            m.status,
            m.notes,
            mt.code AS member_type,
            d.id AS dues_id,
            d.year,
            d.subscription_due,
            d.subscription_paid,
            d.dining_due,
            d.dining_paid,
            d.status AS dues_status,
            d.notes AS dues_notes
        FROM members m
        LEFT JOIN member_types mt ON mt.id = m.member_type_id
        LEFT JOIN dues d
          ON d.member_id = m.id
         AND d.reporting_period_id = ?
        WHERE m.full_name <> ?
          AND COALESCE(mt.code, '') <> ?
        ORDER BY m.full_name
        """,
        (reporting_period_id, "*Visitor", "VISITOR"),
    ).fetchall()

    members = []
    for row in member_rows:
        sd = float(row["subscription_due"] or 0)
        sp = float(row["subscription_paid"] or 0)
        dd = float(row["dining_due"] or 0)
        dp = float(row["dining_paid"] or 0)
        subs_out = max(0.0, round(sd - sp, 2))
        dining_out = max(0.0, round(dd - dp, 2))
        members.append(
            {
                "id": row["id"],
                "membership_number": row["membership_number"],
                "full_name": row["full_name"],
                "member_type": row["member_type"],
                "status": row["status"],
                "notes": row["notes"],
                "dues_id": row["dues_id"],
                "year": row["year"],
                "subscription_due": row["subscription_due"],
                "subscription_paid": row["subscription_paid"],
                "dining_due": row["dining_due"],
                "dining_paid": row["dining_paid"],
                "dues_status": row["dues_status"],
                "dues_notes": row["dues_notes"],
                "subscription_outstanding": subs_out,
                "dining_outstanding": dining_out,
                "has_payment_shortfall": subs_out > 0 or dining_out > 0,
            }
        )

    return {
        "members": members,
        "reporting_period_id": reporting_period_id,
    }


def _backup_status_context():
    db = get_db()
    database_path = Path(current_app.config["DATABASE"])
    backup_file = resolve_backup_database_path(database_path)
    current_app.config["BACKUP_DATABASE"] = str(backup_file)

    selected_folder = get_app_setting(db, APP_SETTING_BACKUP_FOLDER)
    selected_legacy_backup = get_app_setting(db, APP_SETTING_BACKUP_DATABASE)
    backup_folder_selected = bool(selected_folder or selected_legacy_backup)

    backup_folder_effective = backup_file.parent
    backup_file_effective = backup_file

    backup_file_exists = backup_file_effective.exists()
    last_backup_at = None
    if backup_file_exists:
        last_backup_at = datetime.fromtimestamp(backup_file_effective.stat().st_mtime)

    folder_label = str(backup_folder_effective)
    if backup_folder_selected:
        if backup_file_exists and last_backup_at is not None:
            dashboard_summary = (
                f"Backup folder selected. Files are written under {folder_label}. "
                f"Last backup {last_backup_at.strftime('%Y-%m-%d %H:%M')}."
            )
        elif backup_file_exists:
            dashboard_summary = (
                f"Backup folder selected. Files are written under {folder_label}. Backup file is present."
            )
        else:
            dashboard_summary = (
                f"Backup folder selected. Files are written under {folder_label}. No backup file has been created yet."
            )
    else:
        if backup_file_exists and last_backup_at is not None:
            dashboard_summary = (
                f"No backup folder selected yet. Using automatic location {folder_label}. "
                f"Last backup {last_backup_at.strftime('%Y-%m-%d %H:%M')}."
            )
        elif backup_file_exists:
            dashboard_summary = (
                f"No backup folder selected yet. Using automatic location {folder_label}. Backup file is present."
            )
        else:
            dashboard_summary = (
                f"No backup folder selected yet. Using automatic location {folder_label}. No backup file has been created yet."
            )

    return {
        "backup_folder_selected": backup_folder_selected,
        "backup_folder_effective": backup_folder_effective,
        "backup_file_effective": backup_file_effective,
        "backup_file_exists": backup_file_exists,
        "backup_last_backed_up": last_backup_at,
        "backup_dashboard_summary": dashboard_summary,
        "backup_selection_message": (
            "No backup folder has been selected yet. The app is using the automatic backup location."
            if not backup_folder_selected
            else "Backup folder selected in Settings."
        ),
    }


def _backup_folder_form_value(db) -> str:
    """Raw folder path from Settings (may be relative); empty if using automatic location."""
    raw = get_app_setting(db, APP_SETTING_BACKUP_FOLDER)
    if raw is None:
        raw = get_app_setting(db, APP_SETTING_BACKUP_DATABASE)
    if not raw:
        return ""
    raw = str(raw).strip()
    if raw.lower().endswith(".db"):
        return str(Path(raw).parent)
    return raw


def _runtime_lock_context():
    db = get_db()
    lock = get_runtime_lock_status(db)
    if lock is None:
        return {
            "runtime_lock_active": False,
            "runtime_lock_holder": None,
        }

    return {
        "runtime_lock_active": True,
        "runtime_lock_holder": lock,
    }


@main_bp.route("/")
def dashboard():
    db = get_db()
    backup_status = _backup_status_context()
    runtime_lock_status = _runtime_lock_context()

    return render_template(
        "dashboard.html",
        active_page="home",
        lodge_display_name=_lodge_display_name(db),
        **backup_status,
        **runtime_lock_status,
    )


def _handle_app_exit():
    db = get_db()
    backup_path = Path(current_app.config.get("BACKUP_DATABASE") or resolve_backup_database_path(Path(current_app.config["DATABASE"])))

    try:
        current_app.config["RUNTIME_LOCK_STOP_EVENT"].set()
        release_runtime_lock(
            db,
            current_app.config.get("RUNTIME_LOCK_TOKEN", ""),
            lock_name=current_app.config.get("RUNTIME_LOCK_NAME", "main"),
            release_reason="app exit",
        )
        db.commit()
    except Exception:
        pass

    try:
        backup_database(db, backup_path, primary_path=Path(current_app.config["DATABASE"]))
    except Exception as exc:
        record_backup_mirror_failure(current_app, exc, detail="Final backup when exiting failed.")

    try:
        db.commit()
    finally:
        close_db()
        _signal_launcher_exit()

    shutdown = request.environ.get("werkzeug.server.shutdown")
    if shutdown is not None:
        shutdown()

    threading.Timer(2.0, lambda: os._exit(0)).start()

    return {"ok": True, "message": "Treasurer is stopping. You can close this tab now."}


@main_bp.post("/app/exit")
def exit_app():
    return _handle_app_exit()


@main_bp.post("/backup/run")
def run_backup_now():
    db = get_db()
    database_path = Path(current_app.config["DATABASE"])
    backup_raw = current_app.config.get("BACKUP_DATABASE") or ""
    backup_file = (
        resolve_mirror_backup_file_path(Path(backup_raw), database_path)
        if backup_raw
        else resolve_backup_database_path(database_path)
    )
    try:
        backup_database(db, backup_file, primary_path=database_path)
        db.commit()
        clear_backup_mirror_failure(current_app)
        current_app.config["BACKUP_DATABASE"] = str(backup_file)
        flash(
            f"Mirrored backup saved: {backup_file.name} in {backup_file.parent}",
            "success",
        )
    except ValueError as exc:
        record_backup_mirror_failure(current_app, exc, detail="Manual backup from Settings failed.")
        flash(str(exc), "error")
    except Exception as exc:
        record_backup_mirror_failure(current_app, exc, detail="Manual backup from Settings failed.")
        flash(
            "The backup could not be written. Check the red warning above, your backup folder path, and disk space.",
            "error",
        )
    return redirect(url_for("main.settings"))


@main_bp.get("/backup/open-folder")
def open_backup_folder():
    """Open the resolved mirrored-backup folder in the system file manager (local use)."""
    database_path = Path(current_app.config["DATABASE"])
    folder = resolve_backup_database_path(database_path).parent.resolve()
    folder_str = str(folder)
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(  # noqa: S603 — fixed argv, local folder only
                ["explorer", folder_str],
                close_fds=True,
            )
        elif system == "Darwin":
            subprocess.Popen(["open", folder_str], close_fds=True)  # noqa: S603
        else:
            subprocess.Popen(["xdg-open", folder_str], close_fds=True)  # noqa: S603
    except OSError:
        flash(f"Could not open the file manager. Backup folder: {folder_str}", "error")
        return redirect(request.referrer or url_for("main.settings"))
    return redirect(request.referrer or url_for("main.settings"))


@main_bp.post("/backup/restore")
def restore_backup():
    db = get_db()
    database_path = Path(current_app.config["DATABASE"])
    backup_path = Path(current_app.config.get("BACKUP_DATABASE") or resolve_backup_database_path(database_path))

    if not backup_path.exists():
        flash("No backup file was found to restore from.", "error")
        return redirect(url_for("main.dashboard"))

    db.commit()
    close_db()

    try:
        restore_database_from_backup(database_path, backup_path)
        current_app.config["BACKUP_DATABASE"] = str(resolve_backup_database_path(database_path))
    except Exception:
        flash("The backup could not be restored.", "error")
        return redirect(url_for("main.dashboard"))

    flash("Local database restored from the mirrored backup.", "success")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/bank")
def bank():
    return render_template("bank.html", active_page="bank", **_bank_page_context())


@main_bp.post("/bank/import")
def bank_import():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    uploaded_files = request.files.getlist("statement_files")
    has_uploads = any(uploaded_file and uploaded_file.filename for uploaded_file in uploaded_files)

    if has_uploads:
        totals = import_bank_statement_uploads(db, reporting_period_id, uploaded_files)
    else:
        totals = import_bank_statement_exports(db, reporting_period_id=reporting_period_id)
        totals = {**totals, "errors": []}

    for err in totals.get("errors", []):
        flash(err, "error")

    if totals["files"] == 0 and not has_uploads:
        workbook_path = _find_existing_workbook()
        if workbook_path is not None:
            imported = import_bank_transactions_from_workbook(db, reporting_period_id, workbook_path)
            db.commit()
            if imported:
                flash(f"Imported {imported} bank transactions from the workbook.", "success")
            else:
                flash("No bank statement rows needed importing.", "info")
            return redirect(url_for("main.bank"))

    db.commit()
    if totals["inserted"] or totals["updated"]:
        source_label = "uploaded file(s)" if has_uploads else "CSV file(s)"
        flash(
            f"Imported {totals['inserted']} new and updated {totals['updated']} bank statement rows from {totals['files']} {source_label}.",
            "success",
        )
    elif has_uploads and totals.get("errors"):
        flash("No new bank rows were imported from your upload(s).", "error")
    elif has_uploads:
        flash("No bank statement rows needed importing from the uploaded file(s).", "info")
    else:
        flash("No bank statement rows needed importing.", "info")
    return redirect(url_for("main.bank"))


@main_bp.post("/bank/rebuild")
def bank_rebuild_from_workbook():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    workbook_path = _find_existing_workbook()

    if workbook_path is None:
        flash("No workbook was found to rebuild the bank ledger from.", "error")
        return redirect(url_for("main.bank"))

    db.execute(
        "DELETE FROM cash_settlements WHERE reporting_period_id = ?",
        (reporting_period_id,),
    )
    db.execute(
        """
        DELETE FROM bank_transaction_allocations
        WHERE bank_transaction_id IN (
            SELECT id
            FROM bank_transactions
            WHERE reporting_period_id = ?
        )
        """,
        (reporting_period_id,),
    )
    db.execute(
        "DELETE FROM bank_transactions WHERE reporting_period_id = ?",
        (reporting_period_id,),
    )

    imported = import_bank_transactions_from_workbook(db, reporting_period_id, workbook_path)
    db.commit()
    flash(
        f"Rebuilt {imported} bank transactions from the workbook.",
        "success" if imported else "info",
    )
    return redirect(url_for("main.bank"))


@main_bp.post("/bank/<int:transaction_id>/assign")
def bank_assign(transaction_id: int):
    db = get_db()
    category_ids = request.form.getlist("allocation_category_id")
    allocation_amounts = request.form.getlist("allocation_amount")
    if not category_ids and request.form.get("ledger_category_id") is not None:
        category_ids = [request.form.get("ledger_category_id", "")]  # Backward compatibility.
        allocation_amounts = [request.form.get("amount", "")]
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _reply(message: str, status_code: int = 200):
        if is_ajax:
            return {"ok": status_code < 400, "message": message}, status_code
        flash(message, "success" if status_code < 400 else "error")
        return redirect(url_for("main.bank"))

    transaction = db.execute(
        """
        SELECT id, money_in, money_out
        FROM bank_transactions
        WHERE id = ?
        """,
        (transaction_id,),
    ).fetchone()

    if transaction is None:
        return _reply("That bank transaction could not be found.", 404)

    max_amount = float(transaction["money_in"] or transaction["money_out"] or 0)
    if max_amount <= 0:
        return _reply("That row cannot be assigned a category.", 400)

    allocations: list[tuple[int, float]] = []
    for index, category_id_raw in enumerate(category_ids):
        allocation_amount_raw = allocation_amounts[index] if index < len(allocation_amounts) else ""
        category_id_raw = str(category_id_raw).strip()
        if not category_id_raw:
            continue
        try:
            category_id = int(category_id_raw)
        except ValueError:
            return _reply("Choose a valid category.", 400)

        try:
            allocation_amount = round(float(str(allocation_amount_raw).replace(",", "").strip()), 2)
        except ValueError:
            return _reply("Enter a valid allocation amount.", 400)

        if allocation_amount <= 0:
            continue
        allocations.append((category_id, allocation_amount))

    if not allocations:
        return _reply("Add at least one allocation.", 400)

    allocation_total = round(sum(amount for _category_id, amount in allocations), 2)
    if abs(allocation_total - round(max_amount, 2)) > 0.01:
        return _reply(
            f"Allocations must total £{max_amount:.2f} for this transaction.",
            400,
        )

    replace_bank_transaction_allocations(db, transaction_id, allocations)
    db.commit()
    return _reply("Bank transaction allocations saved.")


@main_bp.post("/bank/<int:transaction_id>/settle")
def bank_transaction_settle(transaction_id: int):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    meeting_key = request.form.get("meeting_key", "").strip().upper()
    settlement_date = request.form.get("settlement_date", "").strip()
    notes = request.form.get("notes", "").strip() or None
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _reply(message: str, status_code: int = 200, payload: dict | None = None):
        if is_ajax:
            body: dict[str, object] = {"ok": status_code < 400, "message": message}
            if payload:
                body.update(payload)
            return body, status_code
        flash(message, "success" if status_code < 400 else "error")
        return redirect(url_for("main.bank"))

    if not meeting_key:
        return _reply("Choose a meeting to settle.", 400)

    meeting_row = db.execute(
        """
        SELECT meeting_name, meeting_date
        FROM meetings
        WHERE reporting_period_id = ? AND meeting_key = ?
        """,
        (reporting_period_id, meeting_key),
    ).fetchone()
    if meeting_row is None:
        return _reply("That meeting could not be found.", 404)

    transaction = db.execute(
        """
        SELECT id, money_in, money_out, transaction_date
        FROM bank_transactions
        WHERE id = ? AND reporting_period_id = ?
        """,
        (transaction_id, reporting_period_id),
    ).fetchone()
    if transaction is None:
        return _reply("That bank transaction could not be found.", 404)

    net_amount = float(transaction["money_in"] or 0)
    if net_amount <= 0:
        return _reply("Only deposit rows can be linked to a meeting.", 400)

    cash_allocation = db.execute(
        """
        SELECT 1
        FROM bank_transaction_allocations bta
        JOIN ledger_categories lc ON lc.id = bta.ledger_category_id
        WHERE bta.bank_transaction_id = ? AND lc.code = 'CASH'
        LIMIT 1
        """,
        (transaction_id,),
    ).fetchone()
    if cash_allocation is None:
        return _reply("Only cash rows can be linked to a meeting.", 400)

    settlement_date_value = settlement_date or transaction["transaction_date"] or date.today().isoformat()

    try:
        settlement = _insert_cash_settlement_row(
            db,
            reporting_period_id,
            meeting_key,
            meeting_row["meeting_name"],
            settlement_date_value,
            net_amount,
            transaction_id,
            notes,
        )
    except ValueError as exc:
        return _reply(str(exc), 400)
    except RuntimeError as exc:
        return _reply(str(exc), 500)

    db.commit()
    return _reply(
        "Bank transaction linked to meeting cash.",
        payload={
            "settlement": settlement,
            "meeting": {
                "meeting_key": meeting_key,
                "meeting_name": meeting_row["meeting_name"],
                "meeting_date": meeting_row["meeting_date"],
                "remaining_to_bank": settlement["remaining_to_settle"],
            },
            "transaction_id": transaction_id,
        },
    )


@main_bp.post("/bank/<int:transaction_id>/unsettle")
def bank_transaction_unsettle(transaction_id: int):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _reply(message: str, status_code: int = 200, payload: dict | None = None):
        if is_ajax:
            body: dict[str, object] = {"ok": status_code < 400, "message": message}
            if payload:
                body.update(payload)
            return body, status_code
        flash(message, "success" if status_code < 400 else "error")
        return redirect(url_for("main.bank"))

    settlement = db.execute(
        """
        SELECT id, meeting_key, settlement_date, net_amount
        FROM cash_settlements
        WHERE bank_transaction_id = ? AND reporting_period_id = ?
        """,
        (transaction_id, reporting_period_id),
    ).fetchone()
    if settlement is None:
        return _reply("That settlement could not be found.", 404)

    db.execute(
        "DELETE FROM cash_settlements WHERE id = ?",
        (settlement["id"],),
    )
    db.commit()
    return _reply(
        "Bank settlement unlinked.",
        payload={
            "transaction_id": transaction_id,
            "meeting_key": settlement["meeting_key"],
        },
    )


@main_bp.route("/statement")
def statement():
    return render_template(
        "statement.html",
        active_page="statement",
        statement_year_label=_statement_year_label(),
        **_statement_page_context(),
    )


def _auditors_page_context():
    db = get_db()
    statement_context = _statement_page_context()
    account_histories = virtual_account_report(db)
    audit_sections = []
    for section in statement_context["statement_sections"]:
        audit_sections.append(
            {
                "title": section["title"],
                "income_total": section["income_total"],
                "expense_total": section["expense_total"],
                "net_total": round(section["income_total"] - section["expense_total"], 2),
            }
        )

    reporting_period_id = _current_reporting_period_id()
    cash_rows = db.execute(
        """
        SELECT
            m.meeting_name,
            m.meeting_date,
            COALESCE(SUM(c.money_in), 0) AS money_in,
            COALESCE(SUM(c.money_out), 0) AS money_out
        FROM meetings m
        LEFT JOIN cashbook_entries c
            ON c.meeting_key = m.meeting_key
            AND c.reporting_period_id = m.reporting_period_id
        WHERE m.reporting_period_id = ?
        GROUP BY m.meeting_name, m.meeting_date, m.sort_order
        ORDER BY m.sort_order
        """,
        (reporting_period_id,),
    ).fetchall()

    cash_detail_rows = db.execute(
        """
        SELECT
            c.id AS cash_entry_id,
            m.sort_order,
            m.meeting_date,
            m.meeting_name,
            COALESCE(c.money_in, 0) AS money_in,
            COALESCE(c.money_out, 0) AS money_out,
            c.entry_type,
            c.entry_name,
            lc.code AS ledger_category_code,
            lc.display_name AS ledger_category_name
        FROM cashbook_entries c
        LEFT JOIN meetings m
          ON c.meeting_key = m.meeting_key
         AND c.reporting_period_id = m.reporting_period_id
        LEFT JOIN ledger_categories lc ON lc.id = c.ledger_category_id
        WHERE c.reporting_period_id = ?
        ORDER BY m.sort_order, c.id
        """,
        (reporting_period_id,),
    ).fetchall()
    cash_book_details = []
    running_balance = 0.0
    for row in cash_detail_rows:
        income = float(row["money_in"] or 0)
        expense = float(row["money_out"] or 0)
        delta = income - expense
        running_balance += delta
        cash_book_details.append(
            {
                "meeting_name": row["meeting_name"] or "Cash",
                "meeting_date": row["meeting_date"],
                "entry_type": row["entry_type"],
                "entry_name": row["entry_name"],
                "category_name": row["ledger_category_name"] or row["ledger_category_code"] or "Unassigned",
                "income": income,
                "expense": expense,
                "running": running_balance,
            }
        )

    return {
        **statement_context,
        "statement_year_label": _statement_year_label(),
        "audit_sections": audit_sections,
        "account_histories": account_histories,
        "cash_statements": [
            {
                "meeting": row["meeting_name"],
                "date": row["meeting_date"],
                "money_in": float(row["money_in"] or 0),
                "money_out": float(row["money_out"] or 0),
                "net": float((row["money_in"] or 0) - (row["money_out"] or 0)),
            }
            for row in cash_rows
        ],
        "cash_book_details": cash_book_details,
        **(_auditors_member_payment_block(db, reporting_period_id)),
    }


def _auditors_member_payment_block(db, reporting_period_id: int) -> dict:
    """Member dues rows plus unpaid summary (due minus paid, floored at zero)."""
    rows = db.execute(
        """
        SELECT
            m.membership_number,
            m.full_name,
            mt.code AS member_type,
            m.status,
            d.subscription_due,
            d.subscription_paid,
            d.dining_due,
            d.dining_paid
        FROM members m
        LEFT JOIN member_types mt ON mt.id = m.member_type_id
        LEFT JOIN dues d
            ON d.member_id = m.id
           AND d.reporting_period_id = ?
        ORDER BY m.membership_number
        """,
        (reporting_period_id,),
    ).fetchall()

    member_statuses = []
    total_subs_out = 0.0
    total_dining_out = 0.0
    members_with_shortfall = 0

    for row in rows:
        sd = float(row["subscription_due"] or 0)
        sp = float(row["subscription_paid"] or 0)
        dd = float(row["dining_due"] or 0)
        dp = float(row["dining_paid"] or 0)
        subs_out = max(0.0, round(sd - sp, 2))
        dining_out = max(0.0, round(dd - dp, 2))
        has_shortfall = subs_out > 0 or dining_out > 0
        if has_shortfall:
            members_with_shortfall += 1
        total_subs_out += subs_out
        total_dining_out += dining_out
        member_statuses.append(
            {
                "membership_number": row["membership_number"],
                "full_name": row["full_name"],
                "member_type": row["member_type"] or "Unknown",
                "status": row["status"],
                "subscription_due": sd,
                "subscription_paid": sp,
                "dining_due": dd,
                "dining_paid": dp,
                "subscription_outstanding": subs_out,
                "dining_outstanding": dining_out,
                "has_payment_shortfall": has_shortfall,
            }
        )

    combined = round(total_subs_out + total_dining_out, 2)
    member_arrears_summary = {
        "members_with_shortfall": members_with_shortfall,
        "total_subscription_outstanding": round(total_subs_out, 2),
        "total_dining_outstanding": round(total_dining_out, 2),
        "combined_outstanding": combined,
    }

    return {
        "member_statuses": member_statuses,
        "member_arrears_summary": member_arrears_summary,
    }


@main_bp.route("/auditors")
def auditors():
    return render_template(
        "auditors.html",
        active_page="auditors",
        **_auditors_page_context(),
    )


@main_bp.route("/balances/")
def balances_index():
    db = get_db()
    accounts = virtual_account_report(db)
    first_account = accounts[0]["code"] if accounts else "MAIN"
    return redirect(url_for("main.balance_sheet", account_code=first_account))


@main_bp.route("/balances/<account_code>")
def balance_sheet(account_code: str):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    report = virtual_account_report(db)
    selected_account = next((row for row in report if row["code"] == account_code.upper()), None)
    if selected_account is None and report:
        selected_account = report[0]
    elif selected_account is None:
        aid = _virtual_account_id_for_code(db, account_code)
        selected_account = {
            "id": aid,
            "code": account_code.upper(),
            "display_name": account_code.title(),
            "opening_balance": 0.0,
            "total_in": 0.0,
            "total_out": 0.0,
            "transfer_in": 0.0,
            "transfer_out": 0.0,
            "closing_balance": 0.0,
            "entries": [],
        }

    account_transfers: list = []
    sub_account_id = selected_account.get("id") if selected_account else None
    if sub_account_id is not None:
        account_transfers = list_virtual_account_transfers_for_account(
            db,
            reporting_period_id,
            int(sub_account_id),
        )

    return render_template(
        "balance_sheet.html",
        active_page="balances",
        accounts=report,
        selected_account=selected_account,
        account_transfers=account_transfers,
    )


@main_bp.route("/cash")
def cash():
    return render_template("cash.html", active_page="cash", **_cash_page_context())


@main_bp.post("/cash/settle")
def cash_settle():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    meeting_key = request.form.get("meeting_key", "").strip().upper()
    settlement_date = request.form.get("settlement_date", "").strip()
    deposit_amount = request.form.get("deposit_amount", type=float)
    notes = request.form.get("notes", "").strip() or None
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _reply(message: str, status_code: int = 200, payload: dict | None = None):
        if is_ajax:
            body = {"ok": status_code < 400, "message": message}
            if payload:
                body.update(payload)
            return body, status_code
        flash(message, "success" if status_code < 400 else "error")
        return redirect(url_for("main.cash"))

    if meeting_key not in {"SEPTEMBER", "NOVEMBER", "JANUARY", "MARCH", "MAY"}:
        return _reply("Choose a valid meeting block.", 400)
    if not settlement_date:
        return _reply("Choose a settlement date.", 400)

    meeting_row = db.execute(
        """
        SELECT meeting_name
        FROM meetings
        WHERE reporting_period_id = ? AND meeting_key = ?
        """,
        (reporting_period_id, meeting_key),
    ).fetchone()
    if meeting_row is None:
        return _reply("That meeting could not be found.", 404)

    details = f"Cash deposit for {meeting_row['meeting_name']}"

    try:
        settlement = create_cash_settlement(
            db,
            reporting_period_id,
            meeting_key=meeting_key,
            settlement_date=settlement_date,
            details=details,
            deposit_amount=deposit_amount,
            notes=notes,
        )
    except ValueError as exc:
        return _reply(str(exc), 400)
    except RuntimeError as exc:
        return _reply(str(exc), 500)

    db.commit()
    return _reply(
        "Cash deposit linked.",
        payload={
            "settlement": settlement,
            "meeting": {
                "meeting_key": meeting_key,
                "total_in": settlement["total_in"],
                "total_out": settlement["total_out"],
                "net_to_bank": round(settlement["settled_total"] + settlement["remaining_to_settle"], 2),
                "settled_total": settlement["settled_total"],
                "remaining_to_bank": settlement["remaining_to_settle"],
            },
        },
    )


@main_bp.post("/cash/entries/add")
def cash_entry_add():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    meeting_key = request.form.get("meeting_key", "").strip().upper()
    entry_type = request.form.get("entry_type", "").strip()
    entry_name = request.form.get("entry_name", "").strip()
    member_id = request.form.get("member_id", type=int)
    category_id = request.form.get("ledger_category_id", type=int)
    money_in = request.form.get("money_in", type=float) or 0.0
    money_out = request.form.get("money_out", type=float) or 0.0
    notes = request.form.get("notes", "").strip() or None
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _reply(message: str, status_code: int = 200, payload: dict | None = None):
        if is_ajax:
            body = {"ok": status_code < 400, "message": message}
            if payload:
                body.update(payload)
            return body, status_code
        flash(message, "success" if status_code < 400 else "error")
        return redirect(url_for("main.cash"))

    if meeting_key not in {"SEPTEMBER", "NOVEMBER", "JANUARY", "MARCH", "MAY"}:
        return _reply("Choose a valid meeting block.", 400)
    if not entry_type or not entry_name or category_id is None:
        return _reply("Please complete the cash entry details.", 400)
    if money_in <= 0 and money_out <= 0:
        return _reply("Enter either an amount in or an amount out.", 400)

    inserted = db.execute(
        """
        INSERT INTO cashbook_entries (
            reporting_period_id, meeting_key, entry_type, entry_name,
            ledger_category_id, money_in, money_out, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            reporting_period_id,
            meeting_key,
            entry_type,
            entry_name,
            category_id,
            money_in,
            money_out,
            notes,
        ),
    ).fetchone()
    db.commit()
    if is_ajax:
        return _reply("Cash entry added.", payload={"entry_id": inserted["id"]})
    flash("Cash entry added.", "success")
    return redirect(url_for("main.cash"))


@main_bp.post("/cash/entries/<int:entry_id>/update")
def cash_entry_update(entry_id: int):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    meeting_key = request.form.get("meeting_key", "").strip().upper()
    entry_type = request.form.get("entry_type", "").strip()
    entry_name = request.form.get("entry_name", "").strip()
    member_id = request.form.get("member_id", type=int)
    category_id = request.form.get("ledger_category_id", type=int)
    money_in = request.form.get("money_in", type=float) or 0.0
    money_out = request.form.get("money_out", type=float) or 0.0
    notes = request.form.get("notes", "").strip() or None
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    def _reply(message: str, status_code: int = 200, payload: dict | None = None):
        if is_ajax:
            body = {"ok": status_code < 400, "message": message}
            if payload:
                body.update(payload)
            return body, status_code
        flash(message, "success" if status_code < 400 else "error")
        return redirect(url_for("main.cash"))

    entry_type_normalized = entry_type.lower()
    if entry_type_normalized == "member" and member_id is not None:
        member_row = db.execute(
            "SELECT full_name FROM members WHERE id = ?",
            (member_id,),
        ).fetchone()
        if member_row:
            entry_name = member_row["full_name"]
        else:
            member_id = None

    if meeting_key not in {"SEPTEMBER", "NOVEMBER", "JANUARY", "MARCH", "MAY"}:
        return _reply("Choose a valid meeting block.", 400)
    if not entry_type or not entry_name or category_id is None:
        return _reply("Please complete the cash entry details.", 400)
    if money_in <= 0 and money_out <= 0:
        return _reply("Enter either an amount in or an amount out.", 400)

    updated = db.execute(
        """
        UPDATE cashbook_entries
        SET meeting_key = ?, entry_type = ?, entry_name = ?, member_id = ?, ledger_category_id = ?,
            money_in = ?, money_out = ?, notes = ?
        WHERE id = ? AND reporting_period_id = ?
        """,
        (
            meeting_key,
            entry_type,
            entry_name,
            member_id,
            category_id,
            money_in,
            money_out,
            notes,
            entry_id,
            reporting_period_id,
        ),
    )
    db.commit()
    if updated.rowcount:
        if is_ajax:
            category_name = db.execute(
                "SELECT display_name FROM ledger_categories WHERE id = ?",
                (category_id,),
            ).fetchone()
            return _reply(
                "Cash entry updated.",
                payload={
                    "entry": {
                        "id": entry_id,
                        "meeting_key": meeting_key,
                        "entry_type": entry_type,
                        "entry_name": entry_name,
                        "category_id": category_id,
                        "category_name": category_name["display_name"] if category_name else None,
                        "member_id": member_id,
                        "money_in": money_in,
                        "money_out": money_out,
                        "notes": notes,
                    }
                },
            )
        flash("Cash entry updated.", "success")
    else:
        return _reply("That cash entry could not be found.", 404)
    return redirect(url_for("main.cash"))


@main_bp.post("/cash/entries/<int:entry_id>/delete")
def cash_entry_delete(entry_id: int):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    deleted = db.execute(
        "DELETE FROM cashbook_entries WHERE id = ? AND reporting_period_id = ?",
        (entry_id, reporting_period_id),
    )
    db.commit()
    if deleted.rowcount:
        if is_ajax:
            return {"ok": True, "message": "Cash entry deleted.", "entry_id": entry_id}
        flash("Cash entry deleted.", "success")
    else:
        if is_ajax:
            return {"ok": False, "message": "That cash entry could not be found."}, 404
        flash("That cash entry could not be found.", "error")
    return redirect(url_for("main.cash"))


@main_bp.route("/members")
def members():
    return render_template("members.html", active_page="members", **_members_page_context())


@main_bp.post("/members/<int:member_id>/dues")
def update_member_dues(member_id: int):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    subscription_due = request.form.get("subscription_due", type=float)
    dining_due = request.form.get("dining_due", type=float)

    member = db.execute(
        """
        SELECT m.id, mt.code AS member_code
        FROM members m
        LEFT JOIN member_types mt ON mt.id = m.member_type_id
        WHERE m.id = ?
        """,
        (member_id,),
    ).fetchone()

    if member is None:
        flash("That member could not be found.", "error")
        return redirect(url_for("main.members"))

    if subscription_due is None or dining_due is None or subscription_due < 0 or dining_due < 0:
        flash("Please enter valid dues amounts.", "error")
        return redirect(url_for("main.members"))

    dues_row = db.execute(
        """
        SELECT id, subscription_paid, dining_paid
        FROM dues
        WHERE member_id = ? AND reporting_period_id = ?
        """,
        (member_id, reporting_period_id),
    ).fetchone()

    if dues_row is None:
        db.execute(
            """
            INSERT INTO dues (
                member_id, reporting_period_id, year,
                subscription_due, subscription_paid, dining_due, dining_paid, status
            )
            VALUES (?, ?, ?, ?, 0, ?, 0, ?)
            """,
            (
                member_id,
                reporting_period_id,
                2026,
                subscription_due,
                dining_due,
                _dues_status(subscription_due, 0, dining_due, 0, member["member_code"] or "FULL"),
            ),
        )
    else:
        db.execute(
            """
            UPDATE dues
            SET subscription_due = ?, dining_due = ?, status = ?
            WHERE id = ?
            """,
            (
                subscription_due,
                dining_due,
                _dues_status(
                    subscription_due,
                    float(dues_row["subscription_paid"] or 0),
                    dining_due,
                    float(dues_row["dining_paid"] or 0),
                    member["member_code"] or "FULL",
                ),
                dues_row["id"],
            ),
        )

    db.commit()
    flash("Member dues updated.", "success")
    return redirect(url_for("main.members"))


@main_bp.route("/help")
def help_page():
    return render_template(
        "placeholder.html",
        active_page="help",
        title="Help",
        intro="Handover notes, process guidance, and category definitions can live here.",
    )


@main_bp.route("/forms")
def forms():
    return render_template(
        "placeholder.html",
        active_page="forms",
        title="Public Forms",
        intro="This will become the public-facing forms area for lodge requests and member workflows.",
    )


@main_bp.route("/settings", methods=["GET", "POST"])
def settings():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    backup_status = _backup_status_context()
    database_path = Path(current_app.config["DATABASE"])
    suggested_backup_folder_path = str(resolve_backup_folder_path(database_path))
    backup_folder_input_value = _backup_folder_form_value(db)
    seed_virtual_account_balances(db, reporting_period_id)
    consolidate_virtual_accounts(db)
    category_mappings = virtual_account_category_mappings(db)
    virtual_accounts = virtual_account_report(db)

    if request.method == "POST":
        lodge_display_name = request.form.get("lodge_display_name", "").strip()
        if lodge_display_name:
            set_app_setting(db, APP_SETTING_LODGE_DISPLAY_NAME, lodge_display_name)
        else:
            delete_app_setting(db, APP_SETTING_LODGE_DISPLAY_NAME)

        backup_folder_path = request.form.get("backup_folder_path", "").strip()
        if backup_folder_path:
            set_app_setting(db, APP_SETTING_BACKUP_FOLDER, backup_folder_path)
            delete_app_setting(db, APP_SETTING_BACKUP_DATABASE)
            current_app.config["BACKUP_DATABASE"] = str(
                resolve_backup_database_path(Path(current_app.config["DATABASE"]))
            )
        else:
            delete_app_setting(db, APP_SETTING_BACKUP_FOLDER)
            delete_app_setting(db, APP_SETTING_BACKUP_DATABASE)
            current_app.config["BACKUP_DATABASE"] = str(
                resolve_backup_database_path(Path(current_app.config["DATABASE"]))
            )

        for meeting in _meeting_schedule():
            meeting_key = meeting["meeting_key"]
            meeting_date = request.form.get(f"{meeting_key}_date") or None
            meeting_name = request.form.get(f"{meeting_key}_name", "").strip() or meeting["meeting_name"]
            meeting_type = request.form.get(f"{meeting_key}_type", "").strip() or meeting["meeting_type"]
            notes = request.form.get(f"{meeting_key}_notes", "").strip()

            db.execute(
                """
                UPDATE meetings
                SET meeting_date = ?, meeting_name = ?, meeting_type = ?, notes = ?
                WHERE reporting_period_id = ? AND meeting_key = ?
                """,
                (meeting_date, meeting_name, meeting_type, notes, reporting_period_id, meeting_key),
            )

        for account in virtual_account_report(db, reporting_period_id):
            balance_value = request.form.get(f"{account['code']}_opening_balance", type=float)
            if balance_value is None:
                balance_value = float(account["opening_balance"] or 0)
            db.execute(
                """
                UPDATE virtual_account_balances
                SET opening_balance = ?
                WHERE reporting_period_id = ? AND virtual_account_id = (
                    SELECT id FROM virtual_accounts WHERE code = ?
                )
                """,
                (balance_value, reporting_period_id, account["code"]),
            )

        account_lookup = {
            account["code"]: account["id"]
            for account in db.execute(
                "SELECT id, code FROM virtual_accounts ORDER BY sort_order, display_name"
            ).fetchall()
        }
        category_rows = db.execute(
            """
            SELECT id, code
            FROM ledger_categories
            ORDER BY direction, sort_order, display_name
            """
        ).fetchall()
        category_account_pairs: list[tuple[int, int]] = []
        for category in category_rows:
            selected_code = request.form.get(f"category_{category['id']}_virtual_account", "MAIN").strip().upper()
            account_id = account_lookup.get(selected_code)
            if account_id is None:
                account_id = account_lookup.get("MAIN")
            if account_id is None:
                continue
            category_account_pairs.append((account_id, category["id"]))

        replace_virtual_account_category_map(db, category_account_pairs)

        db.commit()
        flash("Settings updated.", "success")
        return redirect(url_for("main.settings"))

    return render_template(
        "settings.html",
        active_page="settings",
        **backup_status,
        backup_folder_input_value=backup_folder_input_value,
        suggested_backup_folder_path=suggested_backup_folder_path,
        lodge_display_name=_lodge_display_name(db),
        default_lodge_display_name=DEFAULT_LODGE_DISPLAY_NAME,
        meeting_schedule=_meeting_schedule(),
        virtual_accounts=virtual_accounts,
        category_account_mappings=category_mappings,
    )


def _virtual_account_id_for_code(db: sqlite3.Connection, code: str) -> int | None:
    row = db.execute(
        "SELECT id FROM virtual_accounts WHERE UPPER(TRIM(code)) = UPPER(TRIM(?))",
        (code,),
    ).fetchone()
    return int(row["id"]) if row else None


def _balance_subaccount_transfers_redirect(account_code: str) -> str:
    return url_for("main.balance_sheet", account_code=account_code.upper()) + "#sub-account-transfers"


@main_bp.post("/balances/<account_code>/transfers/add")
def balance_transfer_add(account_code: str):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    ac = account_code.upper()
    current_id = _virtual_account_id_for_code(db, ac)
    if current_id is None:
        flash("Unknown sub-account.", "error")
        return redirect(url_for("main.balances_index"))

    direction = (request.form.get("direction") or "").strip().lower()
    other_code = (request.form.get("other_account_code") or "").strip()
    other_id = _virtual_account_id_for_code(db, other_code)
    amount_raw = (request.form.get("amount") or "").strip()
    transfer_date = (request.form.get("transfer_date") or "").strip() or None
    description = (request.form.get("description") or "").strip()
    notes = (request.form.get("notes") or "").strip() or None

    if other_id is None:
        flash("Choose the other sub-account.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))
    if other_id == current_id:
        flash("Pick a different sub-account to transfer with.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    if direction == "out":
        from_id, to_id = current_id, other_id
    elif direction == "in":
        from_id, to_id = other_id, current_id
    else:
        flash("Choose whether money is coming in or going out of this sub-account.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    try:
        amount = float(amount_raw.replace(",", ""))
    except ValueError:
        flash("Enter a valid amount.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    try:
        insert_manual_virtual_account_transfer(
            db,
            reporting_period_id=reporting_period_id,
            from_virtual_account_id=from_id,
            to_virtual_account_id=to_id,
            amount=amount,
            transfer_date=transfer_date,
            description=description,
            notes=notes,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    db.commit()
    flash("Transfer added for this sub-account.", "success")
    return redirect(_balance_subaccount_transfers_redirect(ac))


@main_bp.post("/balances/<account_code>/transfers/<int:transfer_id>/update")
def balance_transfer_update(account_code: str, transfer_id: int):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    ac = account_code.upper()
    current_id = _virtual_account_id_for_code(db, ac)
    if current_id is None:
        flash("Unknown sub-account.", "error")
        return redirect(url_for("main.balances_index"))

    if not virtual_account_transfer_involves_account(
        db,
        transfer_id=transfer_id,
        reporting_period_id=reporting_period_id,
        virtual_account_id=current_id,
    ):
        flash("That transfer is not part of this sub-account's register.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    from_code = (request.form.get("from_account_code") or "").strip()
    to_code = (request.form.get("to_account_code") or "").strip()
    amount_raw = (request.form.get("amount") or "").strip()
    transfer_date = (request.form.get("transfer_date") or "").strip() or None
    description = (request.form.get("description") or "").strip()
    notes = (request.form.get("notes") or "").strip() or None

    from_id = _virtual_account_id_for_code(db, from_code)
    to_id = _virtual_account_id_for_code(db, to_code)
    if from_id is None or to_id is None:
        flash("Choose valid from and to sub-accounts.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    try:
        amount = float(amount_raw.replace(",", ""))
    except ValueError:
        flash("Enter a valid amount.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    try:
        updated = update_virtual_account_transfer(
            db,
            transfer_id=transfer_id,
            reporting_period_id=reporting_period_id,
            from_virtual_account_id=from_id,
            to_virtual_account_id=to_id,
            amount=amount,
            transfer_date=transfer_date,
            description=description,
            notes=notes,
        )
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    if not updated:
        flash("That transfer was not found for this reporting period.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    db.commit()
    flash("Transfer updated.", "success")
    return redirect(_balance_subaccount_transfers_redirect(ac))


@main_bp.post("/balances/<account_code>/transfers/<int:transfer_id>/delete")
def balance_transfer_delete(account_code: str, transfer_id: int):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    ac = account_code.upper()
    current_id = _virtual_account_id_for_code(db, ac)
    if current_id is None:
        flash("Unknown sub-account.", "error")
        return redirect(url_for("main.balances_index"))

    if not virtual_account_transfer_involves_account(
        db,
        transfer_id=transfer_id,
        reporting_period_id=reporting_period_id,
        virtual_account_id=current_id,
    ):
        flash("That transfer is not part of this sub-account's register.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))

    if not delete_virtual_account_transfer(
        db,
        transfer_id=transfer_id,
        reporting_period_id=reporting_period_id,
    ):
        flash("That transfer was not found for this reporting period.", "error")
        return redirect(_balance_subaccount_transfers_redirect(ac))
    db.commit()
    flash("Transfer removed.", "success")
    return redirect(_balance_subaccount_transfers_redirect(ac))


@main_bp.post("/__shutdown")
def shutdown_app():
    return _handle_app_exit()
