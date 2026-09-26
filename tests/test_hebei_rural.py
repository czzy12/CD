import unittest
from datetime import datetime
from decimal import Decimal

from bankflow_v2.hebei_rural import _order_daily_balance_chain
from bankflow_v2.models import Transaction
from bankflow_v2.summary import summarize


class HebeiRuralTests(unittest.TestCase):
    def test_restores_unordered_same_day_rows_without_changing_values(self):
        def tx(amount, balance):
            amount = Decimal(amount)
            return Transaction(datetime(2026, 7, 21), income=max(amount, Decimal(0)),
                               expense=max(-amount, Decimal(0)), balance=Decimal(balance),
                               raw_time="20260721")
        rows = [tx("-5", "115"), tx("10", "110"), tx("10", "120")]
        ordered = _order_daily_balance_chain(rows)
        self.assertEqual([row.balance for row in ordered], [Decimal("110"), Decimal("120"), Decimal("115")])
        summary = summarize(ordered)
        self.assertEqual(summary.opening_balance, Decimal("100.00"))
        self.assertEqual(summary.issues, [])

    def test_uncovered_balance_change_is_not_hidden(self):
        rows = [Transaction(datetime(2026, 7, day), income=Decimal("10"),
                            balance=Decimal(balance), raw_time=f"202607{day:02d}")
                for day, balance in [(1, "110"), (2, "150")]]
        summary = summarize(_order_daily_balance_chain(rows))
        self.assertTrue(any("余额不连续" in issue.message for issue in summary.issues))
