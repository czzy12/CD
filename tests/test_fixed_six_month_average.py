import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

from bankflow_v2.adjustment import AdjustmentConfig
from bankflow_v2.models import Transaction
from bankflow_v2.income_proof_export import build_income_proof_input, flow_block
from gui_v2 import _monthly_average_row, build_monthly_rows


class FixedSixMonthAverageTests(unittest.TestCase):
    def test_five_recognized_months_are_divided_by_six(self):
        transactions = [
            Transaction(datetime(2026, month, 1), income=Decimal("60000"))
            for month in range(1, 6)
        ]

        rows = build_monthly_rows(transactions)

        self.assertEqual(rows[-1][1], "月均")
        self.assertEqual(rows[-1][3], "5.00")

    def test_adjusted_monthly_row_keeps_the_fixed_six_divisor(self):
        total = SimpleNamespace(
            adjusted_income_sum=Decimal("300000"),
            adjusted_expense_sum=Decimal("120000"),
        )

        row = _monthly_average_row(total, 5, for_excel=False, adjusted=True)

        self.assertEqual(row[0], "月均")
        self.assertEqual(row[2], "5.00")
        self.assertEqual(row[-1], "识别5个月，固定按6个月平均")

        excel_row = _monthly_average_row(total, 5, for_excel=True, adjusted=True)
        self.assertEqual(excel_row[0], "月均(÷6)")

    def test_income_proof_export_uses_the_same_fixed_six_average(self):
        transactions = [
            Transaction(datetime(2026, month, 1), income=Decimal("60000"))
            for month in range(1, 6)
        ]
        result = SimpleNamespace(bank_id="test", transactions=transactions)

        block = flow_block([result], "个人")

        self.assertEqual(block["summary"]["income_monthly_avg_wan"], 5.0)

    def test_wechat_income_adjustment_rebalances_proof_expense(self):
        incomes = ["100000", "120000", "130000", "140000", "150000", "259600"]
        expenses = ["70000", "90000", "110000", "130000", "150000", "349200"]
        transactions = []
        for index, (income, expense) in enumerate(zip(incomes, expenses), start=1):
            income_tx = Transaction(
                datetime(2026, index, 1),
                income=Decimal(income),
                bank="微信流水",
            )
            income_tx.flow_type = "微信"
            expense_tx = Transaction(
                datetime(2026, index, 2),
                expense=Decimal(expense),
                bank="微信流水",
            )
            expense_tx.flow_type = "微信"
            transactions.extend([income_tx, expense_tx])
        result = SimpleNamespace(
            bank_id="wechat",
            bank_label="微信流水",
            bank_confidence=100,
            bank_reason="test",
            account_name="",
            account_no="",
            transactions=transactions,
        )
        configs = [
            AdjustmentConfig(
                enabled=True,
                amount_wan=Decimal("800"),
                start_month="2026-01",
                end_month="2026-06",
                balanced=False,
                label="收入调整（微信）",
                randomized=False,
            )
        ]

        data = build_income_proof_input([result], adjustment_configs=configs)
        summary = data["personal_flow"]["summary"]

        self.assertEqual(summary["income_amount_total_wan"], 889.96)
        self.assertGreater(summary["expense_amount_total_wan"], 800)


if __name__ == "__main__":
    unittest.main()
