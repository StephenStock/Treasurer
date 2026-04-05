import tempfile
import unittest
from pathlib import Path

from treasurer_app import create_app


class HealthzTests(unittest.TestCase):
    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(root / "live.db"),
                "BACKUP_DATABASE": str(root / "backup.db"),
                "SECRET_KEY": "test-secret",
                "RUNTIME_LOCK_ENABLED": False,
                "LOGIN_DISABLED": False,
            }
        )
        self.client = self.app.test_client()

    def test_healthz_returns_ok(self) -> None:
        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True).strip(), "ok")


if __name__ == "__main__":
    unittest.main()
