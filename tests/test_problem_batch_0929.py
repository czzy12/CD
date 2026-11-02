import unittest
from datetime import datetime
from decimal import Decimal

from bankflow_v2.cib import _has_strong_watermark_layout
from bankflow_v2.huishang_corp import _restore_amounts_from_balance
from bankflow_v2.icbc_corp import _header_index, _parse_format_d
from bankflow_v2.models import Transaction
from bankflow_v2.qilu_corp import _resolve_rows
from bankflow_v2.shanxi_rural_corp import _normalize_order_and_duplicates
from bankflow_v2.summary import summarize


class _Page:
    def __init__(self, tables):
        self._tables = tables

    def extract_tables(self):
        return self._tables


class ProblemBatch0929Tests(unittest.TestCase):
    def test_icbc_format_without_balance_is_explicitly_optional(self):
        header = ["交易时间", "转出金额", "转入金额"]
        tx = _parse_format_d(
            ["2026-09-01 10:00:00", "10.00", "0.00"],
            _header_index(header),
            1,
            1,
        )
        self.assertTrue(tx.balance_optional)
        self.assertIsNone(tx.balance)
        self.assertEqual(tx.expense, Decimal("10.00"))
        self.assertEqual(summarize([tx]).issues, [])

    def test_qilu_watermark_amounts_are_recovered_from_balance_chain(self):
        rows = [
            ("100.00", "0.00", "1,100.00"),
            ("20,0000.00|2|6", "40.00|8|4", "1,300.00|9"),
            ("0.00", "-50.00", "1,350.00"),
        ]
        resolved = _resolve_rows(rows)
        self.assertEqual(resolved[1][:3], (Decimal("200.00"), Decimal("0.00"), Decimal("1300.00")))
        self.assertEqual(resolved[2][:3], (Decimal("0.00"), Decimal("-50.00"), Decimal("1350.00")))

    def test_huishang_missing_amount_uses_balance_and_keeps_signed_expense(self):
        rows = [
            Transaction(datetime(2026, 1, 1, 10, 0, 0), expense=Decimal("10.00"), balance=Decimal("100.00"), page_no=1, row_no=1),
            Transaction(datetime(2026, 1, 1, 10, 1, 0), expense=Decimal("-10.00"), balance=Decimal("110.00"), page_no=1, row_no=2),
            Transaction(datetime(2026, 1, 1, 10, 2, 0), balance=Decimal("115.00"), page_no=1, row_no=3),
        ]
        for tx in rows:
            tx.preserve_signed_columns = True
        _restore_amounts_from_balance(rows)
        ordered = sorted(rows, key=lambda tx: tx.transaction_time)
        self.assertEqual(ordered[1].expense, Decimal("-10.00"))
        self.assertEqual(ordered[2].income, Decimal("5.00"))
        self.assertEqual(summarize(rows).issues, [])

    def test_shanxi_rural_discards_redundant_unchanged_balance_row(self):
        rows = [
            Transaction(datetime(2026, 1, 1, 10), balance=Decimal("100.00"), page_no=1, row_no=1),
            Transaction(datetime(2026, 1, 1, 11), expense=Decimal("10.00"), balance=Decimal("100.00"), page_no=1, row_no=2),
            Transaction(datetime(2026, 1, 1, 12), expense=Decimal("10.00"), balance=Decimal("90.00"), page_no=1, row_no=3),
        ]
        normalized = _normalize_order_and_duplicates(rows)
        self.assertEqual(len(normalized), 2)
        self.assertEqual(normalized[-1].balance, Decimal("90.00"))

    def test_cib_strong_watermark_layout_is_detected_from_english_headers(self):
        header = [
            "交易时间\nTransaction Time",
            "记账日期\nA c c o u n t i n g Date 29",
            "摘要\nT r a n s a c t i o n Type",
            "支/收\nExpenditure / Income",
            "交易金额\nTransaction Amount",
            "账户余额\nAccount Balance",
        ]
        self.assertTrue(_has_strong_watermark_layout(_Page([[header]])))


if __name__ == "__main__":
    unittest.main()
