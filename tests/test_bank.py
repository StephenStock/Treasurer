import platform
import sqlite3
import tempfile
import unittest
from io import BytesIO, StringIO
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from werkzeug.datastructures import FileStorage, MultiDict

from treasurer_app.db import (
    APP_SETTING_LODGE_DISPLAY_NAME,
    MAX_BANK_STATEMENT_FILE_BYTES,
    DatabaseHandle,
    _bank_transaction_import_fingerprint,
    _import_bank_statement_csv_handle,
    ensure_financial_tables,
    import_bank_statement_uploads,
    init_db,
    recompute_bank_running_balances,
    remove_legacy_visitor_member,
    set_app_setting,
)
from treasurer_app.routes import main_bp


class BankPageTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.db = DatabaseHandle(self.connection, "sqlite")

        project_root = Path(__file__).resolve().parent.parent
        self.app = Flask(
            __name__,
            template_folder=str(project_root / "templates"),
            static_folder=str(project_root / "static"),
        )
        self.app.config.update(
            TESTING=True,
            DATABASE=":memory:",
            BACKUP_DATABASE=str(Path(__file__).resolve().parent.parent / "instance" / "test-backup.db"),
            SECRET_KEY="test",
        )
        self.app.register_blueprint(main_bp)
        self.ctx = self.app.app_context()
        self.ctx.push()

        self.patcher_db = patch("treasurer_app.db.get_db", return_value=self.db)
        self.patcher_routes_db = patch("treasurer_app.routes.get_db", return_value=self.db)
        self.patcher_db.start()
        self.patcher_routes_db.start()

        init_db()
        ensure_financial_tables(self.db)
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.patcher_routes_db.stop()
        self.patcher_db.stop()
        self.ctx.pop()
        self.connection.close()

    def _db(self) -> sqlite3.Connection:
        return self.connection

    def _current_reporting_period_id(self) -> int:
        db = self._db()
        row = db.execute(
            "SELECT id FROM reporting_periods WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["id"]

    def _category_id(self, code: str) -> int:
        db = self._db()
        row = db.execute(
            "SELECT id FROM ledger_categories WHERE code = ?",
            (code,),
        ).fetchone()
        self.assertIsNotNone(row, f"Missing ledger category {code}")
        return row["id"]

    def _virtual_account_id(self, code: str) -> int:
        db = self._db()
        row = db.execute(
            "SELECT id FROM virtual_accounts WHERE code = ?",
            (code,),
        ).fetchone()
        self.assertIsNotNone(row, f"Missing virtual account {code}")
        return row["id"]

    def _insert_bank_transaction(self, *, details: str, money_in: float, money_out: float = 0.0) -> int:
        db = self._db()
        reporting_period_id = self._current_reporting_period_id()
        tx_type = "Inward Payment" if money_in > 0 else "Outward Payment"
        fp = _bank_transaction_import_fingerprint(
            reporting_period_id,
            "2026-03-29",
            details,
            tx_type,
            money_in,
            money_out,
        )
        row = db.execute(
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
                source_row_number,
                notes,
                import_fingerprint
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                reporting_period_id,
                "2026-03-29",
                details,
                tx_type,
                money_in,
                money_out,
                1000.0,
                0,
                "test-suite",
                "CSV",
                9001,
                "test row",
                fp,
            ),
        ).fetchone()
        db.commit()
        return row["id"]

    def test_bank_page_renders_split_editor(self) -> None:
        response = self.client.get("/bank")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="__split__"', response.data)
        self.assertIn(b"Split", response.data)
        self.assertIn(b"data-bank-split-add", response.data)
        self.assertNotIn(b"Use single category", response.data)
        self.assertNotIn(b">Save split<", response.data)

    def test_bank_assign_saves_multiple_allocations(self) -> None:
        transaction_id = self._insert_bank_transaction(details="Split sumup", money_in=100.0)
        cash_id = self._category_id("CASH")
        subs_id = self._category_id("SUBS")

        response = self.client.post(
            f"/bank/{transaction_id}/assign",
            data=MultiDict(
                [
                    ("allocation_category_id", str(cash_id)),
                    ("allocation_amount", "60.00"),
                    ("allocation_category_id", str(subs_id)),
                    ("allocation_amount", "40.00"),
                ]
            ),
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])

        db = self._db()
        rows = db.execute(
            """
            SELECT lc.code, bta.amount
            FROM bank_transaction_allocations bta
            JOIN ledger_categories lc ON lc.id = bta.ledger_category_id
            WHERE bta.bank_transaction_id = ?
            ORDER BY bta.id
            """,
            (transaction_id,),
        ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertEqual([row["code"] for row in rows], ["CASH", "SUBS"])
        self.assertEqual([round(float(row["amount"]), 2) for row in rows], [60.0, 40.0])

    def test_bank_assign_rejects_mismatched_totals(self) -> None:
        transaction_id = self._insert_bank_transaction(details="Bad split", money_in=100.0)
        cash_id = self._category_id("CASH")
        subs_id = self._category_id("SUBS")

        response = self.client.post(
            f"/bank/{transaction_id}/assign",
            data=MultiDict(
                [
                    ("allocation_category_id", str(cash_id)),
                    ("allocation_amount", "60.00"),
                    ("allocation_category_id", str(subs_id)),
                    ("allocation_amount", "30.00"),
                ]
            ),
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("Allocations must total", payload["message"])

    def test_bank_transaction_settle_requires_cash_allocation(self) -> None:
        transaction_id = self._insert_bank_transaction(details="Non cash row", money_in=50.0)
        subs_id = self._category_id("SUBS")

        db = self._db()
        db.execute(
            """
            INSERT INTO bank_transaction_allocations (
                bank_transaction_id, ledger_category_id, amount
            )
            VALUES (?, ?, ?)
            """,
            (transaction_id, subs_id, 50.0),
        )
        db.commit()

        response = self.client.post(
            f"/bank/{transaction_id}/settle",
            data={"meeting_key": "SEPTEMBER", "settlement_date": "2026-03-29"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.get_json()
        self.assertFalse(payload["ok"])
        self.assertIn("Only cash rows", payload["message"])

    def test_bank_transaction_settle_allows_cash_allocation(self) -> None:
        transaction_id = self._insert_bank_transaction(details="Cash row", money_in=50.0)
        cash_id = self._category_id("CASH")

        db = self._db()
        db.execute(
            """
            INSERT INTO bank_transaction_allocations (
                bank_transaction_id, ledger_category_id, amount
            )
            VALUES (?, ?, ?)
            """,
            (transaction_id, cash_id, 50.0),
        )
        db.commit()

        response = self.client.post(
            f"/bank/{transaction_id}/settle",
            data={"meeting_key": "SEPTEMBER", "settlement_date": "2026-03-29"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertIn("linked to meeting cash", payload["message"])

        settlement = db.execute(
            """
            SELECT meeting_key, bank_transaction_id, net_amount
            FROM cash_settlements
            WHERE bank_transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        self.assertIsNotNone(settlement)
        self.assertEqual(settlement["meeting_key"], "SEPTEMBER")
        self.assertEqual(settlement["bank_transaction_id"], transaction_id)
        self.assertEqual(round(float(settlement["net_amount"]), 2), 50.0)

        unlink_response = self.client.post(
            f"/bank/{transaction_id}/unsettle",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(unlink_response.status_code, 200)
        unlink_payload = unlink_response.get_json()
        self.assertTrue(unlink_payload["ok"])
        self.assertIn("unlinked", unlink_payload["message"])

        cleared = db.execute(
            """
            SELECT id
            FROM cash_settlements
            WHERE bank_transaction_id = ?
            """,
            (transaction_id,),
        ).fetchone()
        self.assertIsNone(cleared)

    def test_bank_rebuild_from_workbook_clears_existing_rows(self) -> None:
        transaction_id = self._insert_bank_transaction(details="Old row", money_in=25.0)
        cash_id = self._category_id("CASH")
        db = self._db()
        db.execute(
            """
            INSERT INTO bank_transaction_allocations (
                bank_transaction_id, ledger_category_id, amount
            )
            VALUES (?, ?, ?)
            """,
            (transaction_id, cash_id, 25.0),
        )
        db.execute(
            """
            INSERT INTO cash_settlements (
                reporting_period_id, meeting_key, settlement_date,
                net_amount, bank_transaction_id, notes
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (self._current_reporting_period_id(), "SEPTEMBER", "2026-03-29", 25.0, transaction_id, "linked"),
        )
        db.commit()

        with (
            patch("treasurer_app.routes._find_existing_workbook", return_value=Path("Accounts 2025-26.xlsx")),
            patch("treasurer_app.routes.import_bank_transactions_from_workbook", return_value=1),
        ):
            response = self.client.post(
                "/bank/rebuild",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            db.execute("SELECT COUNT(*) AS total FROM bank_transactions").fetchone()["total"],
            0,
        )
        self.assertEqual(
            db.execute("SELECT COUNT(*) AS total FROM bank_transaction_allocations").fetchone()["total"],
            0,
        )
        self.assertEqual(
            db.execute("SELECT COUNT(*) AS total FROM cash_settlements").fetchone()["total"],
            0,
        )

    def test_bank_csv_reimport_dedupes_when_details_whitespace_differs(self) -> None:
        rid = self._current_reporting_period_id()
        count = lambda: self._db().execute("SELECT COUNT(*) AS c FROM bank_transactions").fetchone()["c"]
        before = count()
        csv_a = (
            "Date,Details,Transaction Type,In,Out,Balance\n"
            "01/03/2026,ACME  PAYMENT,FPI,100.00,,500.00\n"
        )
        _import_bank_statement_csv_handle(self.connection, rid, StringIO(csv_a), "March.csv")
        after_first = count()

        csv_b = (
            "Date,Details,Transaction Type,In,Out,Balance\n"
            "01/03/2026,ACME    PAYMENT,FPI,100.00,,500.00\n"
        )
        _import_bank_statement_csv_handle(self.connection, rid, StringIO(csv_b), "March_copy.csv")
        after_second = count()

        self.assertEqual(after_first, after_second, "re-import must update the same row, not insert a duplicate")
        self.assertGreaterEqual(after_first, before)

    def test_bank_csv_merges_legacy_placeholder_details_with_empty_csv_cell(self) -> None:
        rid = self._current_reporting_period_id()
        count = lambda: self._db().execute("SELECT COUNT(*) AS c FROM bank_transactions").fetchone()["c"]
        legacy_date_iso = "2099-06-15"
        legacy_fp = _bank_transaction_import_fingerprint(
            rid,
            legacy_date_iso,
            "Imported transaction",
            "Account Maintenance Fee",
            0.0,
            7.77,
        )
        self._db().execute(
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
                source_row_number,
                import_fingerprint
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, 'legacy.xlsx', 'Bank', 99, ?)
            """,
            (
                rid,
                legacy_date_iso,
                "Imported transaction",
                "Account Maintenance Fee",
                0.0,
                7.77,
                1000.0,
                legacy_fp,
            ),
        )
        before = count()
        csv_row = (
            "Date,Details,Transaction Type,In,Out,Balance\n"
            "15/06/2099,,Account Maintenance Fee,,7.77,1000.00\n"
        )
        _import_bank_statement_csv_handle(self.connection, rid, StringIO(csv_row), "stmt.csv")
        self.assertEqual(count(), before)

        row = self._db().execute(
            """
            SELECT details, source_workbook, source_sheet
            FROM bank_transactions
            WHERE transaction_date = ? AND ROUND(money_out, 2) = 7.77
            """,
            (legacy_date_iso,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["details"], "")
        self.assertEqual(row["source_workbook"], "stmt.csv")
        self.assertEqual(row["source_sheet"], "CSV")

    def test_bank_running_balances_use_statement_line_order_not_row_id(self) -> None:
        """CSV is newest-first: lower source_row = newer line; recompute walks oldest-first."""
        rid = self._current_reporting_period_id()
        db = self._db()
        opening_fp = "test-opening-balance-fp-unique-001"
        loi_fp = "test-loi-fp-unique-002"
        chq_fp = "test-chq-fp-unique-003"
        db.execute(
            """
            INSERT INTO bank_transactions (
                reporting_period_id, transaction_date, details, transaction_type,
                money_in, money_out, running_balance, is_opening_balance,
                source_workbook, source_sheet, source_row_number, import_fingerprint
            )
            VALUES (?, '2026-04-01', 'Opening Balance', NULL, 0, 0, 1000.0, 1,
                    'seed', 'Bank', 1, ?)
            """,
            (rid, opening_fp),
        )
        db.execute(
            """
            INSERT INTO bank_transactions (
                reporting_period_id, transaction_date, details, transaction_type,
                money_in, money_out, running_balance, is_opening_balance,
                source_workbook, source_sheet, source_row_number, import_fingerprint
            )
            VALUES (?, '2026-04-02', 'LOI payment', 'Inward Payment', 10.17, 0, 999.0, 0,
                    'stmt.csv', 'CSV', 10, ?)
            """,
            (rid, loi_fp),
        )
        db.execute(
            """
            INSERT INTO bank_transactions (
                reporting_period_id, transaction_date, details, transaction_type,
                money_in, money_out, running_balance, is_opening_balance,
                source_workbook, source_sheet, source_row_number, import_fingerprint
            )
            VALUES (?, '2026-04-02', 'Cheque 800037', 'Cheque', 0, 127.0, 888.0, 0,
                    'stmt.csv', 'CSV', 11, ?)
            """,
            (rid, chq_fp),
        )
        db.commit()

        recompute_bank_running_balances(db, rid)
        db.commit()

        loi_row = db.execute(
            "SELECT running_balance FROM bank_transactions WHERE import_fingerprint = ?",
            (loi_fp,),
        ).fetchone()
        chq_row = db.execute(
            "SELECT running_balance FROM bank_transactions WHERE import_fingerprint = ?",
            (chq_fp,),
        ).fetchone()
        self.assertIsNotNone(loi_row)
        self.assertIsNotNone(chq_row)
        self.assertEqual(float(chq_row["running_balance"]), 873.0)
        self.assertEqual(float(loi_row["running_balance"]), 883.17)

    def test_bank_csv_reimport_dedupes_when_balance_column_changes(self) -> None:
        rid = self._current_reporting_period_id()
        count = lambda: self._db().execute("SELECT COUNT(*) AS c FROM bank_transactions").fetchone()["c"]
        before = count()
        csv_with_balance = (
            "Date,Details,Transaction Type,In,Out,Balance\n"
            "02/03/2026,CAFE LTD,DEB,,15.50,884.25\n"
        )
        _import_bank_statement_csv_handle(self.connection, rid, StringIO(csv_with_balance), "stmt1.csv")
        after_first = count()

        csv_no_balance = (
            "Date,Details,Transaction Type,In,Out,Balance\n"
            "02/03/2026,CAFE LTD,DEB,,15.50,\n"
        )
        _import_bank_statement_csv_handle(self.connection, rid, StringIO(csv_no_balance), "stmt2.csv")
        after_second = count()

        self.assertEqual(after_first, after_second, "re-import without balance must update, not duplicate")
        self.assertGreaterEqual(after_first, before)

    def test_bank_import_does_not_backfill_allocations_from_workbook(self) -> None:
        with (
            patch(
                "treasurer_app.routes.import_bank_statement_uploads",
                return_value={"files": 1, "inserted": 1, "updated": 0, "errors": []},
            ) as import_uploads,
            patch("treasurer_app.routes.backfill_bank_allocations_from_workbook") as backfill,
        ):
            response = self.client.post(
                "/bank/import",
                data={
                    "statement_files": (
                        BytesIO(b"Date,Details,In,Out,Balance\n"),
                        "statement.csv",
                    )
                },
                headers={"X-Requested-With": "XMLHttpRequest"},
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        import_uploads.assert_called_once()
        backfill.assert_not_called()

    def test_statement_shows_lodge_name_from_settings(self) -> None:
        set_app_setting(self.db, APP_SETTING_LODGE_DISPLAY_NAME, "Test Lodge Alpha")
        rv = self.client.get("/statement")
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b"Test Lodge Alpha", rv.data)
        self.assertNotIn(b"Stanford-le-Hope Lodge No. 5217", rv.data)

    def test_bank_upload_non_utf8_reports_error(self) -> None:
        rid = self._current_reporting_period_id()
        fs = FileStorage(stream=BytesIO(b"\xff\x00\x80 not valid utf-8"), filename="bad.csv", content_type="text/csv")
        totals = import_bank_statement_uploads(self.db, rid, [fs])
        self.assertEqual(totals["files"], 0)
        self.assertTrue(totals["errors"])
        self.assertTrue(any("UTF-8" in e for e in totals["errors"]))

    def test_bank_upload_rejects_oversized_file(self) -> None:
        rid = self._current_reporting_period_id()
        raw = b"x" * (MAX_BANK_STATEMENT_FILE_BYTES + 1)
        fs = FileStorage(stream=BytesIO(raw), filename="huge.csv", content_type="text/csv")
        totals = import_bank_statement_uploads(self.db, rid, [fs])
        self.assertEqual(totals["files"], 0)
        self.assertTrue(any("MB" in e for e in totals["errors"]))

    def test_member_dues_post_updates_amounts(self) -> None:
        row = self._db().execute("SELECT id FROM members ORDER BY id LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        member_id = row["id"]
        response = self.client.post(
            f"/members/{member_id}/dues",
            data={"subscription_due": "333.5", "dining_due": "111.25"},
        )
        self.assertEqual(response.status_code, 302)
        dues = self._db().execute(
            """
            SELECT subscription_due, dining_due
            FROM dues
            WHERE member_id = ? AND reporting_period_id = ?
            """,
            (member_id, self._current_reporting_period_id()),
        ).fetchone()
        self.assertIsNotNone(dues)
        self.assertEqual(float(dues["subscription_due"]), 333.5)
        self.assertEqual(float(dues["dining_due"]), 111.25)

    def test_backup_run_writes_mirrored_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            backup_path = Path(td) / "Treasurer.backup.db"
            self.app.config["BACKUP_DATABASE"] = str(backup_path)
            response = self.client.post("/backup/run")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers.get("Location"), "/settings")
            self.assertTrue(backup_path.is_file())

    def test_open_backup_folder_redirects_and_launches_file_manager(self) -> None:
        opener = {"Windows": "explorer", "Darwin": "open"}.get(platform.system(), "xdg-open")
        with patch("treasurer_app.routes.subprocess.Popen") as popen:
            response = self.client.get("/backup/open-folder", headers={"Referer": "/settings"})
            self.assertEqual(response.status_code, 302)
            launches = [
                c
                for c in popen.call_args_list
                if c.args and isinstance(c.args[0], list) and c.args[0][:1] == [opener]
            ]
            self.assertEqual(len(launches), 1)

    def test_settings_can_update_virtual_account_mapping(self) -> None:
        sumup_category_id = self._category_id("SUMUP")
        charity_account_id = self._virtual_account_id("CHARITY")

        response = self.client.post(
            "/settings",
            data={
                f"category_{sumup_category_id}_virtual_account": "CHARITY",
            },
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        self.assertEqual(response.status_code, 302)

        row = self._db().execute(
            """
            SELECT va.code AS virtual_account_code
            FROM virtual_account_category_map vacm
            JOIN virtual_accounts va ON va.id = vacm.virtual_account_id
            WHERE vacm.ledger_category_id = ?
            """,
            (sumup_category_id,),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["virtual_account_code"], "CHARITY")
        self.assertEqual(charity_account_id, self._virtual_account_id("CHARITY"))

    def test_virtual_account_defaults_do_not_include_subs_or_dining_accounts(self) -> None:
        db = self._db()
        codes = {
            row["code"]
            for row in db.execute(
                "SELECT code FROM virtual_accounts ORDER BY sort_order, code"
            ).fetchall()
        }
        self.assertNotIn("SUBS", codes)
        self.assertNotIn("DINING", codes)

        mappings = {
            row["category_code"]: row["virtual_account_code"]
            for row in db.execute(
                """
                SELECT
                    lc.code AS category_code,
                    COALESCE(va.code, 'MAIN') AS virtual_account_code
                FROM ledger_categories lc
                LEFT JOIN virtual_account_category_map vacm ON vacm.ledger_category_id = lc.id
                LEFT JOIN virtual_accounts va ON va.id = vacm.virtual_account_id
                """
            ).fetchall()
        }
        self.assertEqual(mappings["SUBS"], "MAIN")
        self.assertEqual(mappings["DINING"], "MAIN")

    def test_legacy_visitor_member_is_removed_from_existing_data(self) -> None:
        db = self._db()
        visitor_type_id = db.execute(
            "SELECT id FROM member_types WHERE code = ?",
            ("VISITOR",),
        ).fetchone()["id"]
        member_id = db.execute(
            """
            INSERT INTO members (
                membership_number, full_name, member_type_id, email, phone, status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("M999", "*Visitor", visitor_type_id, None, None, "visitor", ""),
        ).lastrowid
        db.execute(
            """
            INSERT INTO dues (
                member_id, reporting_period_id, year,
                subscription_due, subscription_paid, dining_due, dining_paid, status, notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (member_id, self._current_reporting_period_id(), 2026, 0.0, 0.0, 0.0, 0.0, "unpaid", ""),
        )

        removed = remove_legacy_visitor_member(db)

        self.assertEqual(removed, 1)
        self.assertIsNone(
            db.execute("SELECT 1 FROM members WHERE full_name = ?", ("*Visitor",)).fetchone()
        )
        self.assertIsNone(
            db.execute("SELECT 1 FROM dues WHERE member_id = ?", (member_id,)).fetchone()
        )


if __name__ == "__main__":
    unittest.main()
