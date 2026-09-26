import unittest
from datetime import datetime
from decimal import Decimal

from bankflow_v2.boc import _mark_midnight_rollover_dates
from bankflow_v2.models import Transaction
from bankflow_v2.summary import summarize


def transaction(raw_time: str, amount: str, balance: str) -> Transaction:
    value = Decimal(amount)
    return Transaction(
        transaction_time=datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S"),
        income=max(value, Decimal("0.00")),
        expense=max(-value, Decimal("0.00")),
        balance=Decimal(balance),
        bank="中国银行个人",
        raw_time=raw_time,
        raw_amount=amount,
        raw_balance=balance,
    )


class BocTests(unittest.TestCase):
    def test_midnight_booking_rollover_keeps_raw_time_without_balance_warnings(self):
        rows = [
            transaction("2026-07-17 00:07:09", "-2103.00", "78036.01"),
            transaction("2026-07-16 10:15:25", "40912.00", "80139.01"),
            transaction("2026-07-16 00:01:54", "-3255.00", "39227.01"),
            transaction("2026-07-16 00:00:14", "-3525.00", "42482.01"),
            transaction("2026-07-16 23:59:28", "-2708.00", "46007.01"),
            transaction("2026-07-15 23:56:19", "-7744.00", "48715.01"),
        ]

        _mark_midnight_rollover_dates(rows)

        self.assertEqual(rows[4].transaction_time, datetime(2026, 7, 16, 23, 59, 28))
        self.assertTrue(all(getattr(row, "balance_optional", False) for row in rows[1:5]))
        self.assertEqual(summarize(rows).issues, [])


if __name__ == "__main__":
    unittest.main()
