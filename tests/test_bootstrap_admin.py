"""Regression: first-run init_db() must still create bootstrap admin when env is set."""

import os
import tempfile
import unittest
from pathlib import Path

from treasurer_app import create_app
from treasurer_app.auth_store import count_users, fetch_user_by_email
from treasurer_app.db import get_db


class BootstrapAdminTests(unittest.TestCase):
    def test_bootstrap_runs_after_fresh_init_db(self) -> None:
        prev_email = os.environ.pop("TREASURER_BOOTSTRAP_ADMIN_EMAIL", None)
        prev_pw = os.environ.pop("TREASURER_BOOTSTRAP_ADMIN_PASSWORD", None)
        try:
            os.environ["TREASURER_BOOTSTRAP_ADMIN_EMAIL"] = "bootstrap-test@example.com"
            os.environ["TREASURER_BOOTSTRAP_ADMIN_PASSWORD"] = "bootstrap_pw_ok_12"

            with tempfile.TemporaryDirectory() as td:
                root = Path(td)
                app = create_app(
                    {
                        "DATABASE": str(root / "live.db"),
                        "BACKUP_DATABASE": str(root / "backup.db"),
                        "SECRET_KEY": "test-secret-bootstrap",
                        "RUNTIME_LOCK_ENABLED": False,
                        "LOGIN_DISABLED": False,
                    }
                )
                with app.app_context():
                    db = get_db()
                    self.assertEqual(count_users(db), 1)
                    row = fetch_user_by_email(db, "bootstrap-test@example.com")
                    self.assertIsNotNone(row)
                    self.assertEqual(row["email"], "bootstrap-test@example.com")
        finally:
            if prev_email is not None:
                os.environ["TREASURER_BOOTSTRAP_ADMIN_EMAIL"] = prev_email
            else:
                os.environ.pop("TREASURER_BOOTSTRAP_ADMIN_EMAIL", None)
            if prev_pw is not None:
                os.environ["TREASURER_BOOTSTRAP_ADMIN_PASSWORD"] = prev_pw
            else:
                os.environ.pop("TREASURER_BOOTSTRAP_ADMIN_PASSWORD", None)


if __name__ == "__main__":
    unittest.main()
