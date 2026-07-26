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

        self.assertEqual(result["schema_version"], "1.3")
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

    def test_income_continuity_uses_inclusive_calendar_months(self):
        rows = []
        for index, (month, income, expense) in enumerate(
            [
                (1, "100.00", "0.00"),
                (2, "0.00", "10.00"),
                (3, "200.00", "0.00"),
                (4, "300.00", "0.00"),
            ],
            start=1,
        ):
            row = transaction()
            row.transaction_time = datetime(2026, month, 10, 9, 0)
            row.transaction_id = f"tx:month-{index}"
            row.income = Decimal(income)
            row.expense = Decimal(expense)
            rows.append(row)

        indicator = next(
            item
            for item in build_bankflow_result(rows)["result"]["indicators"]
            if item["indicator_type"] == "income_continuity"
        )

        self.assertEqual(indicator["value"]["period_month_count"], 4)
        self.assertEqual(indicator["value"]["income_month_count"], 3)
        self.assertEqual(indicator["value"]["income_month_coverage_rate"], "0.7500")
        self.assertEqual(indicator["value"]["longest_consecutive_income_month_count"], 2)
        self.assertEqual(indicator["value"]["months_without_income"], ["2026-02"])
        self.assertEqual(
            indicator["evidence_transaction_ids"],
            ["tx:month-1", "tx:month-3", "tx:month-4"],
        )

    def test_balance_observation_uses_last_balance_per_source_file_and_day(self):
        rows = []
        for index, (day, hour, balance, source_id) in enumerate(
            [
                (1, 9, "100.00", "sha256:first"),
                (1, 15, "80.00", "sha256:first"),
                (2, 12, "70.00", "sha256:first"),
                (3, 8, "50.00", "sha256:second"),
            ],
            start=1,
        ):
            row = transaction()
            row.transaction_time = datetime(2026, 1, day, hour, 0)
            row.transaction_id = f"tx:balance-{index}"
            row.source_file_id = source_id
            row.balance = Decimal(balance)
            rows.append(row)

        indicator = next(
            item
            for item in build_bankflow_result(rows)["result"]["indicators"]
            if item["indicator_type"] == "balance_observation"
        )

        self.assertEqual(indicator["value"]["daily_snapshot_count"], 3)
        self.assertEqual(indicator["value"]["source_file_count"], 2)
        self.assertEqual(indicator["value"]["minimum_balance"], "50.00")
        self.assertEqual(indicator["value"]["median_balance"], "70.00")
        self.assertEqual(indicator["value"]["average_balance"], "66.67")
        self.assertEqual(indicator["value"]["latest_snapshot_balance"], "50.00")
        self.assertEqual(
            indicator["evidence_transaction_ids"],
            ["tx:balance-2", "tx:balance-3", "tx:balance-4"],
        )

    def test_amount_shape_reports_fixed_rounding_units_without_classification(self):
        rows = []
        for index, (income, expense) in enumerate(
            [
                ("1000.00", "0.00"),
                ("0.00", "125.00"),
                ("10.50", "0.00"),
            ],
            start=1,
        ):
            row = transaction()
            row.transaction_time = datetime(2026, 1, index, 9, 0)
            row.transaction_id = f"tx:amount-{index}"
            row.income = Decimal(income)
            row.expense = Decimal(expense)
            rows.append(row)

        indicator = next(
            item
            for item in build_bankflow_result(rows)["result"]["indicators"]
            if item["indicator_type"] == "amount_shape"
        )

        self.assertEqual(
            indicator["value"]["rounding_units"],
            {
                "1": {"transaction_count": 2, "transaction_share": "0.6667"},
                "100": {"transaction_count": 1, "transaction_share": "0.3333"},
                "1000": {"transaction_count": 1, "transaction_share": "0.3333"},
            },
        )
        self.assertEqual(
            indicator["evidence_transaction_ids"],
            ["tx:amount-1", "tx:amount-2", "tx:amount-3"],
        )

    def test_cashflow_scale_compares_latest_three_months_with_previous_three(self):
        rows = []
        for month in range(1, 7):
            row = transaction()
            row.transaction_time = datetime(2026, month, 10, 9, 0)
            row.transaction_id = f"tx:scale-{month}"
            row.income = Decimal(month * 100)
            row.expense = Decimal(month * 10)
            rows.append(row)

        indicator = next(
            item
            for item in build_bankflow_result(rows)["result"]["indicators"]
            if item["indicator_type"] == "cashflow_scale_and_recent_change"
        )
        comparison = indicator["value"]["recent_comparison"]

        self.assertEqual(indicator["value"]["full_period"]["month_count"], 6)
        self.assertEqual(indicator["value"]["full_period"]["monthly_average_income"], "350.00")
        self.assertEqual(indicator["value"]["full_period"]["monthly_average_expense"], "35.00")
        self.assertTrue(comparison["available"])
        self.assertEqual(comparison["previous_window_income"], "600.00")
        self.assertEqual(comparison["recent_window_income"], "1500.00")
        self.assertEqual(comparison["income_change"], "900.00")
        self.assertEqual(comparison["income_change_rate"], "1.5000")
        self.assertEqual(comparison["previous_window_expense"], "60.00")
        self.assertEqual(comparison["recent_window_expense"], "150.00")
        self.assertEqual(comparison["expense_change"], "90.00")
        self.assertEqual(comparison["expense_change_rate"], "1.5000")

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
