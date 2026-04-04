import unittest

from treasurer_app.db import _normalize_xlsx_rel_target


class XlsxRelTargetTests(unittest.TestCase):
    def test_normalizes_variants(self) -> None:
        self.assertEqual(_normalize_xlsx_rel_target("worksheets/sheet4.xml"), "xl/worksheets/sheet4.xml")
        self.assertEqual(_normalize_xlsx_rel_target("xl/worksheets/sheet4.xml"), "xl/worksheets/sheet4.xml")
        self.assertEqual(_normalize_xlsx_rel_target("/xl/worksheets/sheet4.xml"), "xl/worksheets/sheet4.xml")
        self.assertEqual(_normalize_xlsx_rel_target("\\xl\\worksheets\\sheet4.xml"), "xl/worksheets/sheet4.xml")

    def test_none_empty(self) -> None:
        self.assertIsNone(_normalize_xlsx_rel_target(None))
        self.assertIsNone(_normalize_xlsx_rel_target(""))


if __name__ == "__main__":
    unittest.main()
