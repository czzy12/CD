import json
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from bankflow_v2.models import StatementMetadata, Transaction, TransactionList
from bankflow_v2.result_export import build_bankflow_result, write_bankflow_json


def transaction() -> Transaction:
    return Transaction(
        transaction_time=datetime(2026, 7, 26, 10, 30),
        income=Decimal("100.00"),
        balance=Decimal("100.00"),
        bank="测试银行",
        page_no=2,
        row_no=5,
        raw_time="2026-07-26 10:30:00",
        raw_amount="100.00",
        raw_balance="100.00",
        raw_headers=["摘要"],
        raw_fields=["测试入账"],
        source_file="statement.pdf",
        source_file_id="sha256:source",
        evidence_locator="page=2;row=5",
        transaction_id="tx:source:transaction",
    )


class ResultExportTests(unittest.TestCase):
    def test_exports_only_original_transactions_with_evidence(self):
        row = transaction()
        transactions = TransactionList([row], metadata=StatementMetadata(account_name="张三", account_number="6222"))

        result = build_bankflow_result(transactions)
        exported = result["result"]["original_transactions"][0]

        self.assertEqual(result["schema_version"], "1.2")
        self.assertEqual(result["module"], "bankflow")
        self.assertEqual(result["analysis_source"], "original_transactions")
        self.assertEqual(result["statement_metadata"]["account_name"], "张三")
        self.assertEqual(result["source_files"], [{"source_file_id": "sha256:source", "source_file": "statement.pdf", "transaction_count": 1}])
        self.assertEqual(exported["transaction_id"], "tx:source:transaction")
        self.assertEqual(exported["evidence_locator"], "page=2;row=5")
        self.assertEqual(exported["original"]["raw_fields"], ["测试入账"])
        self.assertEqual(exported["income"], "100.00")
        for indicator in result["result"]["indicators"]:
            self.assertTrue(
                {
                    "indicator_type",
                    "value",
                    "parameters",
                    "evidence_transaction_ids",
                    "field_coverage",
                }.issubset(indicator)
            )
        self.assertEqual(
            result["result"]["facts"],
            [
                {"fact_type": "transaction_count", "value": 1, "evidence_transaction_ids": ["tx:source:transaction"]},
                {"fact_type": "income_total", "value": "100.00", "evidence_transaction_ids": ["tx:source:transaction"]},
                {"fact_type": "expense_total", "value": "0.00", "evidence_transaction_ids": []},
                {"fact_type": "net_amount", "value": "100.00", "evidence_transaction_ids": ["tx:source:transaction"]},
                {"fact_type": "period_start", "value": "2026-07-26T10:30:00", "evidence_transaction_ids": ["tx:source:transaction"]},
                {"fact_type": "period_end", "value": "2026-07-26T10:30:00", "evidence_transaction_ids": ["tx:source:transaction"]},
                {"fact_type": "opening_balance", "value": "0.00", "evidence_transaction_ids": ["tx:source:transaction"]},
                {"fact_type": "closing_balance", "value": "100.00", "evidence_transaction_ids": ["tx:source:transaction"]},
            ],
        )
        self.assertFalse(result["manual_review"]["required"])

    def test_time_proximity_windows_are_inclusive_and_link_evidence(self):
        first = transaction()
        first.transaction_time = datetime(2026, 7, 1, 8, 0)
        first.transaction_id = "tx:income"

        at_one_day = transaction()
        at_one_day.transaction_time = first.transaction_time + timedelta(days=1)
        at_one_day.transaction_id = "tx:expense-1d"
        at_one_day.income = Decimal("0.00")
        at_one_day.expense = Decimal("20.00")

        after_one_day = transaction()
        after_one_day.transaction_time = first.transaction_time + timedelta(days=1, seconds=1)
        after_one_day.transaction_id = "tx:expense-after-1d"
        after_one_day.income = Decimal("0.00")
        after_one_day.expense = Decimal("30.00")

        at_seven_days = transaction()
        at_seven_days.transaction_time = first.transaction_time + timedelta(days=7)
        at_seven_days.transaction_id = "tx:expense-7d"
        at_seven_days.income = Decimal("0.00")
        at_seven_days.expense = Decimal("40.00")

        result = build_bankflow_result([first, at_one_day, after_one_day, at_seven_days])
        indicators = {
            indicator["parameters"].get("window_days"): indicator
            for indicator in result["result"]["indicators"]
            if indicator["indicator_type"] == "fund_time_proximity"
        }

        self.assertEqual(indicators[1]["value"]["time_proximity_pair_count"], 1)
        self.assertEqual(
            indicators[1]["evidence_transaction_ids"],
            ["tx:income", "tx:expense-1d"],
        )
        self.assertEqual(indicators[3]["value"]["time_proximity_pair_count"], 2)
        self.assertEqual(indicators[7]["value"]["time_proximity_pair_count"], 3)
        self.assertIn("不表示支出资金来源于某笔收入", indicators[1]["parameters"]["interpretation"])

    def test_counterparty_concentration_uses_only_reliable_existing_fields(self):
        reliable = transaction()
        reliable.transaction_id = "tx:reliable"
        reliable.counterparty_name = "甲公司"
        reliable.field_confidence["counterparty_name"] = 1.0

        unreliable = transaction()
        unreliable.transaction_id = "tx:unreliable"
        unreliable.counterparty_name = "猜测名称"
        unreliable.field_confidence["counterparty_name"] = 0.5

        result = build_bankflow_result([reliable, unreliable])
        indicator = next(
            item
            for item in result["result"]["indicators"]
            if item["indicator_type"] == "income_counterparty_concentration"
        )

        self.assertTrue(indicator["value"]["available"])
        self.assertEqual(indicator["value"]["distinct_counterparty_count"], 1)
        self.assertEqual(indicator["value"]["top_counterparty"]["identity_value"], "甲公司")
        self.assertEqual(indicator["evidence_transaction_ids"], ["tx:reliable"])
        self.assertEqual(indicator["field_coverage"]["covered_transaction_count"], 1)
        self.assertEqual(indicator["field_coverage"]["eligible_transaction_count"], 2)
        self.assertEqual(indicator["field_coverage"]["transaction_coverage_rate"], "0.5000")

    def test_reports_unavailable_counterparty_indicator_when_fields_are_missing(self):
        result = build_bankflow_result([transaction()])
        indicators = {
            item["indicator_type"]: item for item in result["result"]["indicators"]
        }
        income = indicators["income_counterparty_concentration"]
        expense = indicators["expense_counterparty_concentration"]

        self.assertFalse(income["value"]["available"])
        self.assertEqual(income["value"]["reason"], "reliable_counterparty_fields_unavailable")
        self.assertEqual(income["field_coverage"]["transaction_coverage_rate"], "0.0000")
        self.assertEqual(income["evidence_transaction_ids"], [])
        self.assertFalse(expense["value"]["available"])
        self.assertIsNone(expense["field_coverage"]["transaction_coverage_rate"])

    def test_marks_missing_evidence_for_manual_review(self):
        row = transaction()
        row.transaction_id = ""
        row.source_file_id = ""

        result = build_bankflow_result([row])

        self.assertTrue(result["manual_review"]["required"])
        self.assertEqual(result["manual_review"]["items"][0]["reasons"], ["缺少交易 ID", "缺少来源文件 ID"])
        self.assertEqual(result["manual_review"]["items"][0]["scope"], "transaction")
        self.assertEqual(result["manual_review"]["items"][0]["evidence_transaction_ids"], [])

    def test_exports_summary_review_with_supporting_transaction_ids(self):
        first = transaction()
        second = transaction()
        second.transaction_time = datetime(2026, 7, 27, 10, 30)
        second.transaction_id = "tx:source:second"
        second.income = Decimal("0.00")
        second.expense = Decimal("20.00")
        second.balance = Decimal("70.00")

        result = build_bankflow_result([first, second])

        review = result["manual_review"]["items"]
        self.assertEqual(review[0]["scope"], "summary")
        self.assertEqual(review[0]["evidence_transaction_ids"], ["tx:source:second"])

    def test_writes_utf8_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_bankflow_json(build_bankflow_result([transaction()]), Path(directory) / "evidence.json")
            loaded = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["result"]["original_transactions"][0]["bank"], "测试银行")


if __name__ == "__main__":
    unittest.main()
