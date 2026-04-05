"""Root URL and /home treasurer dashboard routes."""

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

    def test_root_redirects_to_treasurer_home(self) -> None:
        response = self.client.get("/", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"dashboard-welcome", response.data)

    def test_treasurer_home_at_slash_home(self) -> None:
        response = self.client.get("/home")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"dashboard-welcome", response.data)

    def test_chapter_home_renders(self) -> None:
        response = self.client.get("/chapter")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"chapter-landing", response.data)
        self.assertIn(b"body-context-chapter", response.data)

    def test_chapter_coming_soon_placeholder(self) -> None:
        response = self.client.get("/chapter/coming/meetings")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Coming soon", response.data)


if __name__ == "__main__":
    unittest.main()
