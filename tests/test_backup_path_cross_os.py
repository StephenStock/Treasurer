"""Backup path handling when app_settings contain paths from another OS (e.g. DB uploaded from Windows to Linux)."""

import unittest
from unittest.mock import patch

from treasurer_app.db import backup_folder_setting_unusable_on_this_runtime


class BackupPathCrossOsTests(unittest.TestCase):
    def test_windows_paths_flagged_on_posix(self) -> None:
        with patch("os.name", "posix"):
            self.assertTrue(backup_folder_setting_unusable_on_this_runtime(r"C:\Users\steve\Documents\Treasurer Backups"))
            self.assertTrue(backup_folder_setting_unusable_on_this_runtime(r"\\server\share\backups"))
            self.assertFalse(backup_folder_setting_unusable_on_this_runtime("/data/backups"))
            self.assertFalse(backup_folder_setting_unusable_on_this_runtime(""))

    def test_windows_paths_allowed_on_nt(self) -> None:
        with patch("os.name", "nt"):
            self.assertFalse(backup_folder_setting_unusable_on_this_runtime(r"C:\Users\steve\Documents\Treasurer Backups"))


if __name__ == "__main__":
    unittest.main()
