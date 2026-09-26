import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bankflow_v2.chengdu_corp import HEADERS, extract_chengdu_corp
from bankflow_v2.summary import summarize


class ChengduCorpTests(unittest.TestCase):
    def test_continuation_page_without_header_and_reverse_daily_order(self):
        row1 = ["IB1", "2026-09-01", "", "2.50", "107.50", "", "", "", "费用支取"]
        row2 = ["IB1", "2026-09-01", "10.00", "", "110.00", "", "", "", "货款"]
        first = SimpleNamespace(
            extract_text=lambda: "账号：1234567890 户名：公司\n汇总笔数：2 收入总计：10.00 支出总计：2.50",
            extract_tables=lambda: [[HEADERS, row1]],
        )
        second = SimpleNamespace(extract_text=lambda: "", extract_tables=lambda: [[row2]])
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = [first, second]
        with patch("bankflow_v2.chengdu_corp.pdfplumber.open", return_value=pdf):
            tx = extract_chengdu_corp("sample.pdf")
        summary = summarize(tx)
        self.assertEqual(summary.count, 2)
        self.assertEqual(summary.opening_balance, Decimal("100.00"))
        self.assertEqual(summary.closing_balance, Decimal("107.50"))
        self.assertEqual(summary.issues, [])
