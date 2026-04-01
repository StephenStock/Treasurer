import os
import sqlite3
import threading
import tempfile
from datetime import date, datetime
from pathlib import Path

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from .db import (
    APP_SETTING_BACKUP_DATABASE,
    APP_SETTING_BACKUP_FOLDER,
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
    _insert_cash_settlement_row,
    replace_bank_transaction_allocations,
    replace_virtual_account_category_map,
    seed_meeting_schedule,
    seed_virtual_account_balances,
    consolidate_virtual_accounts,
    resolve_backup_folder_path,
    resolve_backup_database_path,
    restore_database_from_backup,
    release_runtime_lock,
    set_app_setting,
    virtual_account_report,
    table_exists,
    _normalize_member_name,
    virtual_account_category_mappings,
)


main_bp = Blueprint("main", __name__)


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
            bt.transaction_date DESC,
            bt.id DESC
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
        ORDER BY
            CASE WHEN transaction_date IS NULL OR transaction_date = '' THEN 1 ELSE 0 END,
            transaction_date DESC,
            id DESC
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
        ORDER BY transaction_date, id
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
        "income_total": round(
            general_income_total + charity_income_total + benevolent_income_total + loi_income_total,
            2,
        ),
        "expense_total": round(
            general_expense_total + charity_expense_total + benevolent_expense_total + loi_expense_total,
            2,
        ),
        "net_result": round(
            (
                general_income_total
                + charity_income_total
                + benevolent_income_total
                + loi_income_total
            )
            - (
                general_expense_total
                + charity_expense_total
                + benevolent_expense_total
                + loi_expense_total
            ),
            2,
        ),
        "latest_bank_balance": latest_balance["running_balance"] if latest_balance else None,
        "opening_bank_balance": opening_bank_balance["running_balance"] if opening_bank_balance else None,
        "bank_receipts_total": round(float(total_receipts or 0), 2),
        "bank_payments_total": round(float(total_payments or 0), 2),
        "uncategorised_transactions": uncategorised_transactions,
        "balance_rows": balance_rows,
        "balance_total": balance_total,
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
        ORDER BY m.full_name
        """,
        (reporting_period_id,),
    ).fetchall()

    members = []
    for row in member_rows:
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
                "subscription_outstanding": float(row["subscription_due"] or 0) - float(row["subscription_paid"] or 0),
                "dining_outstanding": float(row["dining_due"] or 0) - float(row["dining_paid"] or 0),
            }
        )

    return {
        "members": members,
        "reporting_period_id": reporting_period_id,
    }


def _backup_status_context():
    db = get_db()
    database_path = Path(current_app.config["DATABASE"])
    backup_path = Path(current_app.config.get("BACKUP_DATABASE") or resolve_backup_database_path(database_path))

    selected_folder = get_app_setting(db, APP_SETTING_BACKUP_FOLDER)
    selected_legacy_backup = get_app_setting(db, APP_SETTING_BACKUP_DATABASE)
    backup_folder_selected = bool(selected_folder or selected_legacy_backup)

    if selected_folder:
        backup_folder_path = Path(selected_folder)
    elif selected_legacy_backup:
        legacy_path = Path(selected_legacy_backup)
        backup_folder_path = legacy_path.parent if legacy_path.suffix.lower() == ".db" else legacy_path
    else:
        backup_folder_path = backup_path.parent

    backup_file_exists = backup_path.exists()
    last_backup_at = None
    if backup_file_exists:
        last_backup_at = datetime.fromtimestamp(backup_path.stat().st_mtime)

    if backup_folder_selected:
        if backup_file_exists and last_backup_at is not None:
            dashboard_summary = (
                f"Backup folder selected at {backup_folder_path}. Last backup {last_backup_at.strftime('%Y-%m-%d %H:%M')}."
            )
        elif backup_file_exists:
            dashboard_summary = f"Backup folder selected at {backup_folder_path}. Backup file is present."
        else:
            dashboard_summary = f"Backup folder selected at {backup_folder_path}. No backup file has been created yet."
    else:
        if backup_file_exists and last_backup_at is not None:
            dashboard_summary = (
                f"No backup folder selected yet. Using automatic backup location at {backup_folder_path}. "
                f"Last backup {last_backup_at.strftime('%Y-%m-%d %H:%M')}."
            )
        elif backup_file_exists:
            dashboard_summary = (
                f"No backup folder selected yet. Using automatic backup location at {backup_folder_path}. Backup file is present."
            )
        else:
            dashboard_summary = (
                f"No backup folder selected yet. Using automatic backup location at {backup_folder_path}. No backup file has been created yet."
            )

    return {
        "backup_folder_selected": backup_folder_selected,
        "backup_folder_path": backup_folder_path,
        "backup_file_path": backup_path,
        "backup_file_exists": backup_file_exists,
        "backup_last_backed_up": last_backup_at,
        "backup_dashboard_summary": dashboard_summary,
        "backup_selection_message": (
            "No backup folder has been selected yet. The app is using the automatic backup location."
            if not backup_folder_selected
            else "Backup folder selected in Settings."
        ),
    }


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

    stats = {
        "dues_outstanding": db.execute(
            """
            SELECT COALESCE(
                SUM((subscription_due - subscription_paid) + (dining_due - dining_paid)),
                0
            ) AS total
            FROM dues
            WHERE subscription_due > subscription_paid
               OR dining_due > dining_paid
            """
        ).fetchone()["total"],
    }

    arrears_rows = db.execute(
        """
        SELECT
            m.membership_number,
            m.full_name,
            mt.code AS member_type,
            m.status,
            d.subscription_due,
            d.subscription_paid,
            d.dining_due,
            d.dining_paid,
            (d.subscription_due - d.subscription_paid) AS subscription_outstanding,
            (d.dining_due - d.dining_paid) AS dining_outstanding
        FROM dues d
        JOIN members m ON m.id = d.member_id
        LEFT JOIN member_types mt ON mt.id = m.member_type_id
        WHERE (d.subscription_due - d.subscription_paid) > 0
           OR (d.dining_due - d.dining_paid) > 0
        ORDER BY
            (d.subscription_due - d.subscription_paid) + (d.dining_due - d.dining_paid) DESC,
            m.full_name
        """
    ).fetchall()

    arrears_members = [
        {
            "membership_number": row["membership_number"],
            "full_name": row["full_name"],
            "member_type": row["member_type"] or "-",
            "status": row["status"],
            "subscription_due": float(row["subscription_due"] or 0),
            "subscription_paid": float(row["subscription_paid"] or 0),
            "dining_due": float(row["dining_due"] or 0),
            "dining_paid": float(row["dining_paid"] or 0),
            "subscription_outstanding": float(row["subscription_outstanding"] or 0),
            "dining_outstanding": float(row["dining_outstanding"] or 0),
            "total_outstanding": float(
                (row["subscription_outstanding"] or 0) + (row["dining_outstanding"] or 0)
            ),
        }
        for row in arrears_rows
    ]

    stats["arrears_count"] = len(arrears_members)

    return render_template(
        "dashboard.html",
        active_page="home",
        stats=stats,
        arrears_members=arrears_members,
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
        backup_database(db, backup_path)
    except Exception:
        pass

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

    allocation_totals = {"transactions_matched": 0, "allocations_written": 0}
    if totals["files"] > 0:
        allocation_totals = backfill_bank_allocations_from_workbook(db, reporting_period_id)

    db.commit()
    if totals["inserted"] or totals["updated"]:
        source_label = "uploaded file(s)" if has_uploads else "CSV file(s)"
        if allocation_totals["transactions_matched"]:
            allocation_note = (
                f" Refreshed {allocation_totals['allocations_written']} allocations from the workbook."
            )
        else:
            allocation_note = ""
        flash(
            f"Imported {totals['inserted']} new and updated {totals['updated']} bank statement rows from {totals['files']} {source_label}.{allocation_note}",
            "success",
        )
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
        statement_lodge_name="Stanford-le-Hope Lodge No. 5217",
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

    audit_checks = [
        "Do the totals on this page add up to the printed statement?",
        "Does the closing bank balance match the bank statement?",
        "Are all cash settlements recorded and banked?",
        "Are there any unexplained or uncategorised rows?",
        "Do the opening and closing account balances look sensible?",
    ]

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
        "statement_lodge_name": "Stanford-le-Hope Lodge No. 5217",
        "statement_year_label": _statement_year_label(),
        "audit_sections": audit_sections,
        "audit_checks": audit_checks,
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
        "member_statuses": [
            {
                "membership_number": row["membership_number"],
                "full_name": row["full_name"],
                "member_type": row["member_type"] or "Unknown",
                "status": row["status"],
                "subscription_due": row["subscription_due"] or 0.0,
                "subscription_paid": row["subscription_paid"] or 0.0,
                "dining_due": row["dining_due"] or 0.0,
                "dining_paid": row["dining_paid"] or 0.0,
            }
            for row in db.execute(
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
        ]

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
    report = virtual_account_report(db)
    selected_account = next((row for row in report if row["code"] == account_code.upper()), None)
    if selected_account is None and report:
        selected_account = report[0]
    elif selected_account is None:
        selected_account = {
            "code": account_code.upper(),
            "display_name": account_code.title(),
            "opening_balance": 0.0,
            "total_in": 0.0,
            "total_out": 0.0,
            "closing_balance": 0.0,
            "entries": [],
        }

    return render_template(
        "balance_sheet.html",
        active_page="balances",
        accounts=report,
        selected_account=selected_account,
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
    suggested_backup_folder_path = str(resolve_backup_folder_path(Path(current_app.config["DATABASE"])))
    backup_folder_path = get_app_setting(db, APP_SETTING_BACKUP_FOLDER)
    if backup_folder_path is None:
        backup_folder_path = get_app_setting(db, APP_SETTING_BACKUP_DATABASE)
    if backup_folder_path is None:
        backup_folder_path = suggested_backup_folder_path
    elif backup_folder_path.endswith(".db"):
        backup_folder_path = str(Path(backup_folder_path).parent)

    current_app.config["BACKUP_DATABASE"] = str(resolve_backup_database_path(Path(current_app.config["DATABASE"])))
    seed_virtual_account_balances(db, reporting_period_id)
    consolidate_virtual_accounts(db)
    category_mappings = virtual_account_category_mappings(db)
    virtual_accounts = virtual_account_report(db)

    if request.method == "POST":
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
            backup_folder_path = str(resolve_backup_folder_path(Path(current_app.config["DATABASE"])))
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
        meeting_schedule=_meeting_schedule(),
        virtual_accounts=virtual_accounts,
        category_account_mappings=category_mappings,
    )


@main_bp.post("/__shutdown")
def shutdown_app():
    return _handle_app_exit()
