import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from bankflow_v2.models import Transaction
from bankflow_v2.income_proof_export import flow_block
from gui_v2 import _monthly_average_row, build_monthly_rows


class FixedSixMonthAverageTests(unittest.TestCase):
    def test_five_recognized_months_are_divided_by_six(self):
        transactions = [
            Transaction(datetime(2026, month, 1), income=Decimal("60000"))
            for month in range(1, 6)
        ]

        rows = build_monthly_rows(transactions)

        self.assertEqual(rows[-1][1], "月均(÷6)")
        self.assertEqual(rows[-1][3], "5.00")

    def test_adjusted_monthly_row_keeps_the_fixed_six_divisor(self):
        total = SimpleNamespace(
            adjusted_income_sum=Decimal("300000"),
            adjusted_expense_sum=Decimal("120000"),
        )

        row = _monthly_average_row(total, 5, for_excel=False, adjusted=True)

        self.assertEqual(row[0], "月均(÷6)")
        self.assertEqual(row[2], "5.00")
        self.assertEqual(row[-1], "识别5个月，固定按6个月平均")

    def test_income_proof_export_uses_the_same_fixed_six_average(self):
        transactions = [
            Transaction(datetime(2026, month, 1), income=Decimal("60000"))
            for month in range(1, 6)
        ]
        result = SimpleNamespace(bank_id="test", transactions=transactions)

        block = flow_block([result], "个人")

        self.assertEqual(block["summary"]["income_monthly_avg_wan"], 5.0)


if __name__ == "__main__":
    unittest.main()
