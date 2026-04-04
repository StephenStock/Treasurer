import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask

from treasurer_app.db import (
    DatabaseHandle,
    ensure_financial_tables,
    init_db,
    list_virtual_account_transfers_for_account,
)
from treasurer_app.routes import main_bp


class VirtualTransfersSettingsTestCase(unittest.TestCase):
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
            BACKUP_DATABASE=str(project_root / "instance" / "test-backup.db"),
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

    def _reporting_period_id(self) -> int:
        row = self.connection.execute(
            "SELECT id FROM reporting_periods WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        return row["id"]

    def _account_ids(self) -> tuple[int, int]:
        main = self.connection.execute(
            "SELECT id FROM virtual_accounts WHERE code = 'MAIN'"
        ).fetchone()
        cent = self.connection.execute(
            "SELECT id FROM virtual_accounts WHERE code = 'CENTENARY'"
        ).fetchone()
        assert main is not None and cent is not None
        return int(main["id"]), int(cent["id"])

    def test_add_update_delete_transfer(self) -> None:
        period_id = self._reporting_period_id()
        main_id, cent_id = self._account_ids()

        r = self.client.post(
            "/balances/MAIN/transfers/add",
            data={
                "direction": "out",
                "other_account_code": "CENTENARY",
                "amount": "100.50",
                "transfer_date": "2026-04-01",
                "description": "Test move",
                "notes": "n1",
            },
            follow_redirects=False,
        )
        self.assertEqual(r.status_code, 302)
        rows = list_virtual_account_transfers_for_account(self.db, period_id, main_id)
        self.assertEqual(len(rows), 1)
        tid = int(rows[0]["id"])
        self.assertEqual(float(rows[0]["amount"]), 100.5)
        self.assertEqual(rows[0]["description"], "Test move")
        self.assertEqual(int(rows[0]["from_virtual_account_id"]), main_id)
        self.assertEqual(int(rows[0]["to_virtual_account_id"]), cent_id)

        r2 = self.client.post(
            f"/balances/MAIN/transfers/{tid}/update",
            data={
                "from_account_code": "CENTENARY",
                "to_account_code": "MAIN",
                "amount": "50.25",
                "transfer_date": "",
                "description": "Revised",
                "notes": "",
            },
        )
        self.assertEqual(r2.status_code, 302)
        rows2 = list_virtual_account_transfers_for_account(self.db, period_id, main_id)
        self.assertEqual(len(rows2), 1)
        self.assertEqual(float(rows2[0]["amount"]), 50.25)
        self.assertEqual(rows2[0]["description"], "Revised")
        self.assertIsNone(rows2[0]["transfer_date"])

        r3 = self.client.post(f"/balances/MAIN/transfers/{tid}/delete")
        self.assertEqual(r3.status_code, 302)
        rows3 = list_virtual_account_transfers_for_account(self.db, period_id, main_id)
        self.assertEqual(len(rows3), 0)

    def test_balance_page_includes_transfer_register(self) -> None:
        rv = self.client.get("/balances/MAIN")
        self.assertEqual(rv.status_code, 200)
        self.assertIn(b"sub-account-transfers", rv.data)
        self.assertIn(b"Transfer register", rv.data)


if __name__ == "__main__":
    unittest.main()
