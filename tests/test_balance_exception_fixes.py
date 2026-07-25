from decimal import Decimal
import unittest
from unittest.mock import patch

from bankflow_v2.ccb_corp import extract_ccb_corp
from bankflow_v2.cib import _has_confirmed_strong_watermark, extract_cib
from bankflow_v2.summary import summarize


class _Page:
    def __init__(self, text="", tables=None):
        self._text = text
        self._tables = tables or []

    def extract_text(self):
        return self._text

    def extract_tables(self):
        return self._tables


class _Pdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class BalanceExceptionFixTests(unittest.TestCase):
    def test_ccb_corp_negative_debit_is_income_for_summary(self):
        table = [
            ["header"] * 5,
            ["", "20251113 14:40:02", "-3548.00", "0.00", "44764.47"],
            ["", "20251113 14:40:03", "0.00", "-20.00", "44744.47"],
        ]
        with patch("bankflow_v2.ccb_corp.pdfplumber.open", return_value=_Pdf([_Page(tables=[table])])):
            transactions = extract_ccb_corp("sample.pdf")

        self.assertEqual(transactions[0].income, Decimal("3548.00"))
        self.assertEqual(transactions[0].expense, Decimal("0.00"))
        self.assertEqual(transactions[1].income, Decimal("0.00"))
        self.assertEqual(transactions[1].expense, Decimal("20.00"))
        self.assertEqual(summarize(transactions).income_sum, Decimal("3548.00"))
        self.assertEqual(summarize(transactions).expense_sum, Decimal("20.00"))

    def test_cib_confirmed_watermark_layout_marks_balances_as_reference(self):
        watermark_text = (
            "说明：交易明细涉及您的个人隐私，请妥善处理，"
            "交易明细内容仅供个人参考。"
        )
        table = [
            ["header"] * 9,
            ["2026-05-18 16:00:00", "20260518", "快捷支付", "支", "-15.00", "57,302.92", "", "", ""],
            ["2026-05-18 16:01:00", "20260518", "快捷支付", "支", "-20.00", "57,282.92", "", "", ""],
        ]
        with patch("bankflow_v2.cib.pdfplumber.open", return_value=_Pdf([_Page(watermark_text, [table])])):
            transactions = extract_cib("sample.pdf")

        self.assertTrue(all(tx.balance is None and tx.balance_optional for tx in transactions))
        self.assertTrue(all(tx.raw_balance.startswith("参考余额:") for tx in transactions))
        self.assertEqual(summarize(transactions).issues, [])

    def test_cib_confirmed_watermark_marker_allows_known_text_fragmentation(self):
        text = "说 2026 明 交 易 明 细 涉 及 您的个人 隐 私。交易 明 细 内 容 仅 供个人参考。"

        self.assertTrue(_has_confirmed_strong_watermark(text))


if __name__ == "__main__":
    unittest.main()
