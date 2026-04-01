import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from werkzeug.datastructures import MultiDict

from treasurer_app.db import DatabaseHandle, init_db
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
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                reporting_period_id,
                "2026-03-29",
                details,
                "Inward Payment" if money_in > 0 else "Outward Payment",
                money_in,
                money_out,
                1000.0,
                0,
                "test-suite",
                "CSV",
                9001,
                "test row",
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


if __name__ == "__main__":
    unittest.main()
