from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from .db import (
    _dues_status,
    _find_existing_workbook,
    get_db,
    import_bank_statement_exports,
    import_bank_transactions_from_workbook,
    replace_bank_transaction_allocations,
    seed_meeting_schedule,
    seed_virtual_account_balances,
    seed_virtual_accounts,
    seed_virtual_account_category_map,
    virtual_account_report,
    table_exists,
)


main_bp = Blueprint("main", __name__)


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
    if db.backend == "postgres":
        allocation_summary_sql = """
            COALESCE(
                STRING_AGG(
                    lc.display_name || '|' || TO_CHAR(bta.amount, 'FM999999990.00'),
                    '||'
                    ORDER BY lc.display_name
                ),
                ''
            ) AS allocation_summary
        """
    else:
        allocation_summary_sql = """
            COALESCE(
                GROUP_CONCAT(
                    lc.display_name || '|' || printf('%.2f', bta.amount),
                    '||'
                ),
                ''
            ) AS allocation_summary
        """

    categories = db.execute(
        """
        SELECT id, code, display_name, direction
        FROM ledger_categories
        ORDER BY direction, sort_order, display_name
        """
    ).fetchall()

    transactions = db.execute(
        f"""
        SELECT
            bt.id,
            bt.transaction_date,
            bt.details,
            bt.transaction_type,
            bt.money_in,
            bt.money_out,
            bt.running_balance,
            bt.is_opening_balance,
            {allocation_summary_sql}
        FROM bank_transactions bt
        LEFT JOIN bank_transaction_allocations bta ON bta.bank_transaction_id = bt.id
        LEFT JOIN ledger_categories lc ON lc.id = bta.ledger_category_id
        GROUP BY
            bt.id,
            bt.transaction_date,
            bt.details,
            bt.transaction_type,
            bt.money_in,
            bt.money_out,
            bt.running_balance,
            bt.is_opening_balance
        ORDER BY
            bt.transaction_date DESC,
            bt.id DESC
        """
    ).fetchall()

    prepared_transactions = []
    for transaction in transactions:
        allocations = []
        summary = transaction["allocation_summary"] or ""
        if summary:
            for item in summary.split("||"):
                if not item:
                    continue
                label, amount = item.split("|", 1)
                allocations.append({"label": label, "amount": float(amount)})

        selected_category_id = db.execute(
            """
            SELECT bta.ledger_category_id
            FROM bank_transaction_allocations bta
            WHERE bta.bank_transaction_id = ?
            ORDER BY bta.id
            LIMIT 1
            """,
            (transaction["id"],),
        ).fetchone()

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
                "selected_category_id": (
                    selected_category_id["ledger_category_id"] if selected_category_id else None
                ),
                "needs_attention": not allocations and not transaction["is_opening_balance"],
                "net_amount": (
                    float(transaction["money_in"])
                    if transaction["money_in"] > 0
                    else float(transaction["money_out"])
                ),
            }
        )

    summary = db.execute(
        """
        SELECT
            COUNT(*) AS total_transactions,
            COALESCE(SUM(money_in), 0) AS total_money_in,
            COALESCE(SUM(money_out), 0) AS total_money_out,
            COALESCE(SUM(CASE WHEN bt.is_opening_balance = 0 AND allocation_counts.count_per_transaction IS NULL THEN 1 ELSE 0 END), 0)
                AS uncategorised_transactions
        FROM bank_transactions bt
        LEFT JOIN (
            SELECT bank_transaction_id, COUNT(*) AS count_per_transaction
            FROM bank_transaction_allocations
            GROUP BY bank_transaction_id
        ) allocation_counts ON allocation_counts.bank_transaction_id = bt.id
        """
    ).fetchone()

    return {
        "bank_transactions": prepared_transactions,
        "ledger_categories": categories,
        "bank_summary": summary,
    }


def _statement_page_context():
    db = get_db()
    category_rows = db.execute(
        """
        SELECT
            lc.id,
            lc.code,
            lc.display_name,
            lc.direction,
            lc.sort_order,
            COALESCE(SUM(bta.amount), 0) AS total_amount,
            COUNT(DISTINCT bta.bank_transaction_id) AS transaction_count
        FROM ledger_categories lc
        LEFT JOIN bank_transaction_allocations bta ON bta.ledger_category_id = lc.id
        LEFT JOIN bank_transactions bt ON bt.id = bta.bank_transaction_id
        GROUP BY lc.id, lc.code, lc.display_name, lc.direction, lc.sort_order
        ORDER BY lc.direction, lc.sort_order, lc.display_name
        """
    ).fetchall()

    income_rows = []
    expense_rows = []
    income_total = 0.0
    expense_total = 0.0

    for row in category_rows:
        item = {
            "code": row["code"],
            "display_name": row["display_name"],
            "direction": row["direction"],
            "total_amount": float(row["total_amount"] or 0),
            "transaction_count": row["transaction_count"],
        }
        if row["direction"] == "in":
            income_rows.append(item)
            income_total += item["total_amount"]
        else:
            expense_rows.append(item)
            expense_total += item["total_amount"]

    latest_balance = db.execute(
        """
        SELECT running_balance
        FROM bank_transactions
        WHERE running_balance IS NOT NULL
        ORDER BY
            CASE WHEN transaction_date IS NULL OR transaction_date = '' THEN 1 ELSE 0 END,
            transaction_date DESC,
            id DESC
        LIMIT 1
        """
    ).fetchone()

    uncategorised_transactions = db.execute(
        """
        SELECT COUNT(*) AS total
        FROM bank_transactions bt
        LEFT JOIN bank_transaction_allocations bta ON bta.bank_transaction_id = bt.id
        WHERE bt.is_opening_balance = 0
          AND bta.id IS NULL
        """
    ).fetchone()["total"]

    balance_rows = virtual_account_report(db)
    balance_total = sum(float(row["closing_balance"] or 0) for row in balance_rows)

    return {
        "income_rows": income_rows,
        "expense_rows": expense_rows,
        "income_total": income_total,
        "expense_total": expense_total,
        "net_result": income_total - expense_total,
        "latest_bank_balance": latest_balance["running_balance"] if latest_balance else None,
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


def _cash_page_context():
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
        meeting_entries = [
            {
                "id": row["id"],
                "entry_type": row["entry_type"],
                "entry_name": row["entry_name"],
                "member_id": row["member_id"],
                "ledger_category_id": row["ledger_category_id"],
                "category_name": row["category_name"],
                "money_in": row["money_in"],
                "money_out": row["money_out"],
                "notes": row["notes"],
            }
            for row in entry_rows
            if row["meeting_key"] == meeting["meeting_key"]
        ]
        blocks.append(
            {
                "meeting_key": meeting["meeting_key"],
                "meeting_name": meeting["meeting_name"],
                "meeting_date": meeting["meeting_date"],
                "meeting_type": meeting["meeting_type"],
                "entries": meeting_entries,
                "total_in": sum(float(row["money_in"] or 0) for row in meeting_entries),
                "total_out": sum(float(row["money_out"] or 0) for row in meeting_entries),
            }
        )

    return {
        "meeting_blocks": blocks,
        "meeting_schedule": schedule,
        "ledger_categories": categories,
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


@main_bp.route("/")
def dashboard():
    if g.get("current_user") is None:
        return render_template(
            "home_public.html",
            active_page="home",
        )

    db = get_db()

    stats = {
        "members": db.execute("SELECT COUNT(*) AS total FROM members").fetchone()["total"],
        "events": db.execute("SELECT COUNT(*) AS total FROM events").fetchone()["total"],
        "open_messages": db.execute(
            "SELECT COUNT(*) AS total FROM messages WHERE status = 'open'"
        ).fetchone()["total"],
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

    recent_members = db.execute(
        """
        SELECT m.membership_number, m.full_name, mt.code AS member_type, m.email, m.status
        FROM members m
        LEFT JOIN member_types mt ON mt.id = m.member_type_id
        ORDER BY full_name
        LIMIT 5
        """
    ).fetchall()

    dues = db.execute(
        """
        SELECT
            m.full_name,
            d.year,
            d.subscription_due,
            d.subscription_paid,
            d.dining_due,
            d.dining_paid,
            (d.subscription_due - d.subscription_paid) AS subscription_outstanding,
            (d.dining_due - d.dining_paid) AS dining_outstanding,
            d.status
        FROM dues d
        JOIN members m ON m.id = d.member_id
        ORDER BY d.status DESC, m.full_name
        """
    ).fetchall()

    upcoming_events = db.execute(
        """
        SELECT id, title, event_date, meal_name, meal_price, booking_deadline, notes
        FROM events
        ORDER BY event_date
        """
    ).fetchall()

    bookings = db.execute(
        """
        SELECT e.title, m.full_name, b.seats, b.dietary_notes, b.status
        FROM bookings b
        JOIN events e ON e.id = b.event_id
        JOIN members m ON m.id = b.member_id
        ORDER BY e.event_date, m.full_name
        """
    ).fetchall()

    messages = db.execute(
        """
        SELECT sender_name, sender_role, subject, body, status, created_at
        FROM messages
        ORDER BY created_at DESC
        """
    ).fetchall()

    return render_template(
        "dashboard.html",
        active_page="home",
        stats=stats,
        recent_members=recent_members,
        dues=dues,
        upcoming_events=upcoming_events,
        bookings=bookings,
        messages=messages,
    )


@main_bp.route("/bank")
def bank():
    return render_template("bank.html", active_page="bank", **_bank_page_context())


@main_bp.post("/bank/import")
def bank_import():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    totals = import_bank_statement_exports(db, reporting_period_id=reporting_period_id)
    if totals["files"] == 0:
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
        flash(
            f"Imported {totals['inserted']} new and updated {totals['updated']} bank statement rows from {totals['files']} CSV file(s).",
            "success",
        )
    else:
        flash("No bank statement rows needed importing.", "info")
    return redirect(url_for("main.bank"))


@main_bp.post("/bank/<int:transaction_id>/assign")
def bank_assign(transaction_id: int):
    db = get_db()
    category_id = request.form.get("ledger_category_id", type=int)
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

    if category_id is None:
        return _reply("Choose a category.", 400)

    if transaction is None:
        return _reply("That bank transaction could not be found.", 404)

    max_amount = float(transaction["money_in"] or transaction["money_out"] or 0)
    if max_amount <= 0:
        return _reply("That row cannot be assigned a category.", 400)

    replace_bank_transaction_allocations(db, transaction_id, [(category_id, max_amount)])
    db.commit()
    return _reply("Bank transaction category saved.")


@main_bp.route("/statement")
def statement():
    return render_template("statement.html", active_page="statement", **_statement_page_context())


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


@main_bp.post("/cash/entries/add")
def cash_entry_add():
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    meeting_key = request.form.get("meeting_key", "").strip().upper()
    entry_type = request.form.get("entry_type", "").strip()
    entry_name = request.form.get("entry_name", "").strip()
    category_id = request.form.get("ledger_category_id", type=int)
    money_in = request.form.get("money_in", type=float) or 0.0
    money_out = request.form.get("money_out", type=float) or 0.0
    notes = request.form.get("notes", "").strip() or None

    if meeting_key not in {"SEPTEMBER", "NOVEMBER", "JANUARY", "MARCH", "MAY"}:
        flash("Choose a valid meeting block.", "error")
        return redirect(url_for("main.cash"))
    if not entry_type or not entry_name or category_id is None:
        flash("Please complete the cash entry details.", "error")
        return redirect(url_for("main.cash"))
    if money_in <= 0 and money_out <= 0:
        flash("Enter either an amount in or an amount out.", "error")
        return redirect(url_for("main.cash"))

    db.execute(
        """
        INSERT INTO cashbook_entries (
            reporting_period_id, meeting_key, entry_type, entry_name,
            ledger_category_id, money_in, money_out, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
    )
    db.commit()
    flash("Cash entry added.", "success")
    return redirect(url_for("main.cash"))


@main_bp.post("/cash/entries/<int:entry_id>/update")
def cash_entry_update(entry_id: int):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    meeting_key = request.form.get("meeting_key", "").strip().upper()
    entry_type = request.form.get("entry_type", "").strip()
    entry_name = request.form.get("entry_name", "").strip()
    category_id = request.form.get("ledger_category_id", type=int)
    money_in = request.form.get("money_in", type=float) or 0.0
    money_out = request.form.get("money_out", type=float) or 0.0
    notes = request.form.get("notes", "").strip() or None

    if meeting_key not in {"SEPTEMBER", "NOVEMBER", "JANUARY", "MARCH", "MAY"}:
        flash("Choose a valid meeting block.", "error")
        return redirect(url_for("main.cash"))
    if not entry_type or not entry_name or category_id is None:
        flash("Please complete the cash entry details.", "error")
        return redirect(url_for("main.cash"))
    if money_in <= 0 and money_out <= 0:
        flash("Enter either an amount in or an amount out.", "error")
        return redirect(url_for("main.cash"))

    updated = db.execute(
        """
        UPDATE cashbook_entries
        SET meeting_key = ?, entry_type = ?, entry_name = ?, ledger_category_id = ?,
            money_in = ?, money_out = ?, notes = ?
        WHERE id = ? AND reporting_period_id = ?
        """,
        (
            meeting_key,
            entry_type,
            entry_name,
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
        flash("Cash entry updated.", "success")
    else:
        flash("That cash entry could not be found.", "error")
    return redirect(url_for("main.cash"))


@main_bp.post("/cash/entries/<int:entry_id>/delete")
def cash_entry_delete(entry_id: int):
    db = get_db()
    reporting_period_id = _current_reporting_period_id()
    deleted = db.execute(
        "DELETE FROM cashbook_entries WHERE id = ? AND reporting_period_id = ?",
        (entry_id, reporting_period_id),
    )
    db.commit()
    if deleted.rowcount:
        flash("Cash entry deleted.", "success")
    else:
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
    seed_virtual_account_balances(db, reporting_period_id)

    if request.method == "POST":
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

        db.commit()
        flash("Settings updated.", "success")
        return redirect(url_for("main.settings"))

    return render_template(
        "settings.html",
        active_page="settings",
        meeting_schedule=_meeting_schedule(),
        virtual_accounts=virtual_account_report(db),
    )
