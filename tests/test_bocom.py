import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from bankflow_v2.bocom import _amounts_from_direction, extract_bocom
from bankflow_v2.summary import summarize


class BocomTests(unittest.TestCase):
    def test_cd_flags_with_exported_tab(self):
        self.assertEqual(_amounts_from_direction("C&#x9;", Decimal("10")), (Decimal("10"), Decimal("0.00"), []))
        self.assertEqual(_amounts_from_direction("D\t", Decimal("10")), (Decimal("0.00"), Decimal("10"), []))

    def test_date_only_table_with_physical_empty_columns(self):
        rows = [
            ["2026-04-07", "平台", None, "收入", "C", None, "10.00", None, "110.00"],
            ["2026-04-07", "平台", None, "消费", "D", None, "2.00", None, "108.00"],
        ]
        page = MagicMock()
        page.extract_tables.return_value = [rows]
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = [page]
        with patch("bankflow_v2.bocom.pdfplumber.open", return_value=pdf):
            summary = summarize(extract_bocom("sample.pdf"))
        self.assertEqual(summary.count, 2)
        self.assertEqual(summary.income_sum, Decimal("10.00"))
        self.assertEqual(summary.expense_sum, Decimal("2.00"))
        self.assertEqual(summary.opening_balance, Decimal("100.00"))
        self.assertEqual(summary.closing_balance, Decimal("108.00"))
        self.assertEqual(summary.issues, [])
