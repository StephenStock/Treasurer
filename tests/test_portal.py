"""Portal landing and /home treasurer dashboard routes."""

import tempfile
import unittest
from pathlib import Path

from treasurer_app import create_app


class PortalRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.td = tempfile.TemporaryDirectory()
        root = Path(self.td.name)
        self.app = create_app(
            {
                "TESTING": True,
                "DATABASE": str(root / "live.db"),
                "BACKUP_DATABASE": str(root / "backup.db"),
                "SECRET_KEY": "test-secret-portal",
                "RUNTIME_LOCK_ENABLED": False,
                "LOGIN_DISABLED": True,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self) -> None:
        self.td.cleanup()

    def test_portal_at_root_ok(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"portal-landing", response.data)
        self.assertIn(b"Treasurer", response.data)

    def test_treasurer_home_at_slash_home(self) -> None:
        response = self.client.get("/home")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"dashboard-welcome", response.data)


if __name__ == "__main__":
    unittest.main()
