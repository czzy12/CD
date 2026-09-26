import unittest
from datetime import datetime
from decimal import Decimal

from bankflow_v2.chaoyang_corp import extract_chaoyang_rows
from bankflow_v2.summary import summarize


class ChaoyangCorpTests(unittest.TestCase):
    def test_extracts_signed_income_and_expense_rows(self):
        transactions = extract_chaoyang_rows(
            "\n".join([
                "2026-09-12 14:00:57 支出 -38,251.00 162,508.41 加油站 06830501040004296",
                "2026-09-11 15:45:49 收入 +200,000.00 200,759.41 工程公司 21001720303059221206",
            ])
        )

        self.assertEqual(len(transactions), 2)
        self.assertEqual(transactions[0].transaction_time, datetime(2026, 9, 12, 14, 0, 57))
        self.assertEqual(transactions[0].expense, Decimal("38251.00"))
        self.assertEqual(transactions[1].income, Decimal("200000.00"))
        self.assertEqual(transactions[1].bank, "朝阳银行对公")
        self.assertEqual(transactions[1].merge_key, "2026-09-11 15:45:49|200000.00|0.00|200759.41")

    def test_orders_same_second_principal_before_fee_for_balance_check(self):
        transactions = extract_chaoyang_rows(
            "\n".join([
                "2026-03-25 11:12:22 支出 -15.00 8,071.24 手续费",
                "2026-03-25 11:12:22 支出 -110,000.00 8,086.24 转账",
            ])
        )

        summary = summarize(transactions, "同秒交易")

        self.assertEqual(summary.opening_balance, Decimal("118086.24"))
        self.assertEqual(summary.closing_balance, Decimal("8071.24"))
        self.assertEqual(summary.issues, [])


if __name__ == "__main__":
    unittest.main()
