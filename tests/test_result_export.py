import json
import tempfile
import unittest
from unittest.mock import patch
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
    def test_loads_default_ai_runtime_when_no_adapter_is_injected(self):
        row = transaction()
        row.purpose = "环保设备采购"
        row.field_confidence["purpose"] = 1.0
        config = {
            "enabled": True,
            "data_authorized": True,
            "retention_policy_confirmed": True,
            "allow_business_names": True,
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key_available": True,
        }
        evaluator = lambda payload: [{
            "transaction_id": "tx:source:transaction",
            "semantic_judgement": "medium",
            "reason": "用途字段需人工复核",
            "used_fields": ["purpose"],
        }]

        with patch(
            "bankflow_v2.result_export.load_deepseek_runtime",
            return_value=(config, evaluator),
        ) as loader:
            result = build_bankflow_result(
                [row],
                case_context={
                    "search_context": {
                        "declared_industries": ["环保工程"],
                    }
                },
            )

        loader.assert_called_once_with()
        observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "ai_business_relevance_candidates"
        )
        self.assertTrue(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["ai_candidates"][0]["transaction_id"],
            "tx:source:transaction",
        )

    def test_exports_only_original_transactions_with_evidence(self):
        row = transaction()
        transactions = TransactionList([row], metadata=StatementMetadata(account_name="张三", account_number="6222"))

        result = build_bankflow_result(transactions)
        exported = result["result"]["original_transactions"][0]

        self.assertEqual(result["schema_version"], "1.16")
        self.assertEqual(result["module"], "bankflow")
        self.assertEqual(result["analysis_source"], "original_transactions")
        self.assertEqual(result["statement_metadata"]["account_name"], "张三")
        self.assertEqual(result["source_files"], [{"source_file_id": "sha256:source", "source_file": "statement.pdf", "transaction_count": 1}])
        self.assertEqual(exported["transaction_id"], "tx:source:transaction")
        self.assertEqual(exported["page_no"], 2)
        self.assertEqual(exported["row_no"], 5)
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
        for observation in result["result"]["observations"]:
            self.assertTrue(
                {
                    "observation_type",
                    "value",
                    "parameters",
                    "evidence_transaction_ids",
                    "field_coverage",
                }.issubset(observation)
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
        evidence = result["result"]["evidence"]
        self.assertEqual(
            evidence["transaction_index"]["tx:source:transaction"],
            {
                "original_transaction_index": 0,
                "source_file_id": "sha256:source",
                "source_file": "statement.pdf",
                "page_no": 2,
                "row_no": 5,
                "evidence_locator": "page=2;row=5",
            },
        )
        self.assertTrue(evidence["integrity"]["complete"])
        self.assertEqual(
            evidence["coverage"]["fully_traceable_coverage_rate"],
            "1.0000",
        )
        self.assertEqual(
            evidence["integrity"]["unresolved_transaction_ids"],
            [],
        )

    def test_evidence_index_rejects_duplicate_transaction_ids_as_ambiguous(self):
        first = transaction()
        second = transaction()
        second.page_no = 3
        second.row_no = 1
        second.evidence_locator = "page=3;row=1"

        evidence = build_bankflow_result([first, second])["result"]["evidence"]

        self.assertNotIn("tx:source:transaction", evidence["transaction_index"])
        self.assertFalse(evidence["integrity"]["complete"])
        self.assertEqual(
            evidence["integrity"]["duplicate_transaction_ids"],
            ["tx:source:transaction"],
        )
        self.assertEqual(
            evidence["integrity"]["ambiguous_reference_transaction_ids"],
            ["tx:source:transaction"],
        )
        self.assertGreater(
            evidence["coverage"]["ambiguous_evidence_link_count"],
            0,
        )

    def test_reports_own_account_observation_unavailable_without_context(self):
        observation = build_bankflow_result([transaction()])["result"]["observations"][0]

        self.assertEqual(
            observation["observation_type"],
            "confirmed_own_account_transfer_candidates",
        )
        self.assertFalse(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["reason"],
            "confirmed_owned_accounts_unavailable",
        )
        self.assertEqual(observation["evidence_transaction_ids"], [])

    def test_reports_own_account_observation_unavailable_without_reliable_accounts(self):
        context = {
            "confirmed_owned_accounts": [
                {
                    "account_ref": "owned:salary-card",
                    "account_number": "6222000000001234",
                    "verification_status": "confirmed",
                    "ownership_evidence_ref": "case-file:account-proof-1",
                }
            ]
        }
        observation = build_bankflow_result(
            [transaction()],
            verification_context=context,
        )["result"]["observations"][0]

        self.assertFalse(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["reason"],
            "reliable_counterparty_accounts_unavailable",
        )
        self.assertEqual(
            observation["field_coverage"]["covered_transaction_count"],
            0,
        )

    def test_matches_only_confirmed_full_reliable_counterparty_accounts(self):
        matched_income = transaction()
        matched_income.transaction_id = "tx:matched-income"
        matched_income.counterparty_account = "6222 0000 0000 1234"
        matched_income.field_confidence["counterparty_account"] = 1.0

        matched_expense = transaction()
        matched_expense.transaction_id = "tx:matched-expense"
        matched_expense.transaction_time = datetime(2026, 7, 27, 10, 30)
        matched_expense.income = Decimal("0.00")
        matched_expense.expense = Decimal("40.00")
        matched_expense.counterparty_account = "6222-0000-0000-1234"
        matched_expense.field_confidence["counterparty_account"] = 1.0

        context = {
            "confirmed_owned_accounts": [
                {
                    "account_ref": "owned:salary-card",
                    "account_number": "6222000000001234",
                    "verification_status": "confirmed",
                    "ownership_evidence_ref": "case-file:account-proof-1",
                }
            ]
        }
        observation = build_bankflow_result(
            [matched_income, matched_expense],
            verification_context=context,
        )["result"]["observations"][0]

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(observation["value"]["matched_transaction_count"], 2)
        self.assertEqual(observation["value"]["matched_income"], "100.00")
        self.assertEqual(observation["value"]["matched_expense"], "40.00")
        self.assertEqual(
            observation["value"]["candidates"],
            [
                {
                    "transaction_id": "tx:matched-income",
                    "confirmed_account_ref": "owned:salary-card",
                    "ownership_evidence_ref": "case-file:account-proof-1",
                    "direction": "income_from_confirmed_owned_account",
                    "transaction_time": "2026-07-26T10:30:00",
                    "amount": "100.00",
                },
                {
                    "transaction_id": "tx:matched-expense",
                    "confirmed_account_ref": "owned:salary-card",
                    "ownership_evidence_ref": "case-file:account-proof-1",
                    "direction": "expense_to_confirmed_owned_account",
                    "transaction_time": "2026-07-27T10:30:00",
                    "amount": "40.00",
                },
            ],
        )
        self.assertEqual(
            observation["evidence_transaction_ids"],
            ["tx:matched-income", "tx:matched-expense"],
        )
        self.assertEqual(
            observation["parameters"]["matching_rule"],
            "normalized_full_account_exact_match",
        )
        self.assertIn(
            "不表示资金来源、资金闭环或账户实际控制关系",
            observation["parameters"]["interpretation"],
        )

    def test_rejects_unconfirmed_masked_unreliable_neutral_and_name_only_matches(self):
        unreliable = transaction()
        unreliable.transaction_id = "tx:unreliable"
        unreliable.counterparty_account = "6222000000001234"
        unreliable.field_confidence["counterparty_account"] = 0.99

        masked = transaction()
        masked.transaction_id = "tx:masked"
        masked.counterparty_account = "****1234"
        masked.field_confidence["counterparty_account"] = 1.0

        neutral = transaction()
        neutral.transaction_id = "tx:neutral"
        neutral.counterparty_account = "6222000000001234"
        neutral.field_confidence["counterparty_account"] = 1.0
        neutral.neutral = True

        name_only = transaction()
        name_only.transaction_id = "tx:name-only"
        name_only.counterparty_name = "张三"
        name_only.field_confidence["counterparty_name"] = 1.0

        pending_account = transaction()
        pending_account.transaction_id = "tx:pending-account"
        pending_account.counterparty_account = "9558800000000000"
        pending_account.field_confidence["counterparty_account"] = 1.0

        context = {
            "confirmed_owned_accounts": [
                {
                    "account_ref": "owned:confirmed",
                    "account_number": "6222000000001234",
                    "verification_status": "confirmed",
                    "ownership_evidence_ref": "case-file:confirmed",
                },
                {
                    "account_ref": "owned:unconfirmed",
                    "account_number": "9558800000000000",
                    "verification_status": "pending",
                    "ownership_evidence_ref": "case-file:pending",
                },
            ]
        }
        observation = build_bankflow_result(
            [unreliable, masked, neutral, name_only, pending_account],
            verification_context=context,
        )["result"]["observations"][0]

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(observation["value"]["matched_transaction_count"], 0)
        self.assertEqual(observation["value"]["candidates"], [])
        self.assertEqual(observation["evidence_transaction_ids"], [])
        self.assertEqual(
            observation["field_coverage"]["eligible_transaction_count"],
            4,
        )
        self.assertEqual(
            observation["field_coverage"]["covered_transaction_count"],
            1,
        )

    def test_pairs_only_mutual_same_day_opposite_direction_candidates(self):
        outgoing = transaction()
        outgoing.transaction_id = "tx:company-expense"
        outgoing.source_file_id = "sha256:company"
        outgoing.income = Decimal("0.00")
        outgoing.expense = Decimal("100.00")
        outgoing.counterparty_account = "6222 0000 0000 1234"
        outgoing.field_confidence["counterparty_account"] = 1.0

        incoming = transaction()
        incoming.transaction_id = "tx:personal-income"
        incoming.source_file_id = "sha256:personal"
        incoming.counterparty_account = "3000-2401-0400-09217"
        incoming.field_confidence["counterparty_account"] = 1.0

        single_sided = transaction()
        single_sided.transaction_id = "tx:company-single"
        single_sided.source_file_id = "sha256:company"
        single_sided.income = Decimal("0.00")
        single_sided.expense = Decimal("50.00")
        single_sided.counterparty_account = "6222000000001234"
        single_sided.field_confidence["counterparty_account"] = 1.0

        ambiguous_outgoing = transaction()
        ambiguous_outgoing.transaction_id = "tx:company-ambiguous"
        ambiguous_outgoing.source_file_id = "sha256:company"
        ambiguous_outgoing.income = Decimal("0.00")
        ambiguous_outgoing.expense = Decimal("200.00")
        ambiguous_outgoing.counterparty_account = "6222000000001234"
        ambiguous_outgoing.field_confidence["counterparty_account"] = 1.0

        ambiguous_incoming_one = transaction()
        ambiguous_incoming_one.transaction_id = "tx:personal-ambiguous-1"
        ambiguous_incoming_one.source_file_id = "sha256:personal"
        ambiguous_incoming_one.income = Decimal("200.00")
        ambiguous_incoming_one.counterparty_account = "30002401040009217"
        ambiguous_incoming_one.field_confidence["counterparty_account"] = 1.0

        ambiguous_incoming_two = transaction()
        ambiguous_incoming_two.transaction_id = "tx:personal-ambiguous-2"
        ambiguous_incoming_two.source_file_id = "sha256:personal"
        ambiguous_incoming_two.income = Decimal("200.00")
        ambiguous_incoming_two.counterparty_account = "30002401040009217"
        ambiguous_incoming_two.field_confidence["counterparty_account"] = 1.0

        context = {
            "confirmed_owned_accounts": [
                {
                    "account_ref": "owned:company",
                    "account_number": "30002401040009217",
                    "verification_status": "confirmed",
                    "ownership_evidence_ref": "case-file:company",
                    "source_file_ids": ["sha256:company"],
                },
                {
                    "account_ref": "owned:personal",
                    "account_number": "6222000000001234",
                    "verification_status": "confirmed",
                    "ownership_evidence_ref": "case-file:personal",
                    "source_file_ids": ["sha256:personal"],
                },
            ]
        }
        observation = build_bankflow_result(
            [
                outgoing,
                incoming,
                single_sided,
                ambiguous_outgoing,
                ambiguous_incoming_one,
                ambiguous_incoming_two,
            ],
            verification_context=context,
        )["result"]["observations"][1]

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["paired"],
            [
                {
                    "transaction_ids": ["tx:company-expense", "tx:personal-income"],
                    "calendar_date": "2026-07-26",
                    "amount": "100.00",
                    "account_refs": ["owned:company", "owned:personal"],
                }
            ],
        )
        self.assertEqual(
            [item["transaction_id"] for item in observation["value"]["single_sided_candidates"]],
            ["tx:company-single"],
        )
        self.assertEqual(
            [item["transaction_id"] for item in observation["value"]["ambiguous_candidates"]],
            ["tx:company-ambiguous", "tx:personal-ambiguous-1", "tx:personal-ambiguous-2"],
        )

    def test_reports_pairing_unavailable_without_confirmed_source_files(self):
        context = {
            "confirmed_owned_accounts": [
                {
                    "account_ref": "owned:personal",
                    "account_number": "6222000000001234",
                    "verification_status": "confirmed",
                    "ownership_evidence_ref": "case-file:personal",
                }
            ]
        }
        observation = build_bankflow_result(
            [transaction()], verification_context=context
        )["result"]["observations"][1]

        self.assertFalse(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["reason"],
            "confirmed_account_source_files_unavailable",
        )

    def test_exports_neutral_flag_needed_to_reproduce_indicator_eligibility(self):
        counted = transaction()
        counted.transaction_id = "tx:counted"

        neutral = transaction()
        neutral.transaction_id = "tx:neutral"
        neutral.income = Decimal("0.00")
        neutral.neutral = True

        result = build_bankflow_result([counted, neutral])
        exported = {
            row["transaction_id"]: row
            for row in result["result"]["original_transactions"]
        }

        self.assertFalse(exported["tx:counted"]["neutral"])
        self.assertTrue(exported["tx:neutral"]["neutral"])
        amount_shape = next(
            item
            for item in result["result"]["indicators"]
            if item["indicator_type"] == "amount_shape"
        )
        self.assertEqual(amount_shape["field_coverage"]["eligible_transaction_count"], 1)
        self.assertEqual(amount_shape["evidence_transaction_ids"], ["tx:counted"])

    def test_includes_deterministic_text_observations_from_case_context(self):
        purchase = transaction()
        purchase.transaction_id = "tx:purchase"
        purchase.income = Decimal("0.00")
        purchase.expense = Decimal("10000.00")
        purchase.counterparty_name = "重庆问界汽车销售有限公司"
        purchase.field_confidence["counterparty_name"] = 1.0

        result = build_bankflow_result(
            [purchase],
            case_context={
                "search_context": {
                    "vehicle_models": ["问界M9"],
                    "work_units": [],
                    "declared_industries": [],
                    "work_locations": [],
                    "residence_locations": [],
                    "vehicle_registration_locations": [],
                    "dealer_names": [],
                }
            },
        )
        observations = {
            item["observation_type"]: item
            for item in result["result"]["observations"]
        }

        self.assertEqual(result["schema_version"], "1.16")
        self.assertIn("controlled_keyword_candidates", observations)
        self.assertIn(
            "sensitive_transaction_context_candidates",
            observations,
        )
        self.assertIn("industry_text_search_coverage", observations)
        self.assertIn("purchase_prepayment_funding_candidates", observations)
        self.assertIn("ai_business_relevance_candidates", observations)
        self.assertIn("large_transaction_candidates", observations)
        self.assertIn("large_inflow_balance_paths", observations)
        self.assertIn("end_of_day_balance_and_interest", observations)
        self.assertIn("top_counterparties", observations)
        self.assertIn("cross_source_counterparty_occurrences", observations)
        self.assertIn("explicit_purpose_candidates", observations)
        self.assertIn("declaration_flow_cross_checks", observations)
        self.assertIn("manual_verification_questions", observations)
        self.assertIn(
            "major_counterparty_expense",
            {
                question["question_type"]
                for question in observations[
                    "manual_verification_questions"
                ]["value"]["questions"]
            },
        )
        self.assertEqual(
            observations["controlled_keyword_candidates"]["value"]["hits"][0][
                "transaction_id"
            ],
            "tx:purchase",
        )

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

    def test_counterparty_concentration_excludes_masked_and_placeholder_names(self):
        rows = []
        for index, name in enumerate(
            (
                "***中心",
                "（空）",
                "88BE张鑫",
                "0高衡",
                "JXLCJXZD200106004赎回账户",
                "甲公司",
            ),
        ):
            row = transaction()
            row.transaction_id = f"tx:counterparty:{index}"
            row.counterparty_name = name
            row.field_confidence["counterparty_name"] = 1.0
            rows.append(row)

        result = build_bankflow_result(rows)
        indicator = next(
            item
            for item in result["result"]["indicators"]
            if item["indicator_type"] == "income_counterparty_concentration"
        )

        self.assertEqual(indicator["value"]["distinct_counterparty_count"], 1)
        self.assertEqual(
            indicator["value"]["top_counterparty"]["identity_value"],
            "甲公司",
        )
        self.assertEqual(
            indicator["evidence_transaction_ids"],
            ["tx:counterparty:5"],
        )

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
        self.assertFalse(result["result"]["evidence"]["integrity"]["complete"])
        self.assertEqual(
            result["result"]["evidence"]["integrity"]["missing_transaction_id_count"],
            1,
        )

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

    def test_links_unique_wechat_payment_to_confirmed_bank_debit(self):
        wallet = transaction()
        wallet.bank = "微信流水"
        wallet.transaction_id = "tx:wechat-payment"
        wallet.source_file_id = "sha256:wechat"
        wallet.income = Decimal("0.00")
        wallet.expense = Decimal("395.98")
        wallet.transaction_method = "建设银行储 蓄卡 (2404)"
        wallet.counterparty_name = "小白房子·White House"
        wallet.field_confidence.update({"transaction_method": 1.0, "counterparty_name": 1.0})

        bank = transaction()
        bank.bank = "建设银行个人"
        bank.transaction_id = "tx:bank-debit"
        bank.source_file_id = "sha256:ccb"
        bank.income = Decimal("0.00")
        bank.expense = Decimal("395.98")
        bank.summary = "财付通-微信支付-小白房子"

        result = build_bankflow_result(
            [wallet, bank],
            verification_context={
                "reliable_header_bank_accounts": [
                    {
                        "account_ref": "account:ccb-2404",
                        "account_number": "6217000480002792404",
                        "verification_status": "confirmed",
                        "ownership_evidence_ref": "source:ccb-header",
                        "source_file_ids": ["sha256:ccb"],
                    }
                ],
                "confirmed_owned_payment_sources": [
                    {
                        "payment_account_type": "wechat_account",
                        "account_ref": "payment:wechat-client",
                        "source_file_id": "sha256:wechat",
                        "verification_status": "confirmed",
                        "ownership_evidence_ref": "source:wechat-header",
                        "identity_owner_name": "\u5f20\u4e09",
                        "identity_number": "110101199001011234",
                        "payment_account_id": "wechat:client",
                    }
                ],
            },
        )
        observation = next(
            item for item in result["result"]["observations"]
            if item["observation_type"] == "wechat_payment_bank_debit_link_candidates"
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["paired"],
            [{
                "wallet_transaction_id": "tx:wechat-payment",
                "bank_transaction_id": "tx:bank-debit",
                "wechat_account_ref": "payment:wechat-client",
                "wechat_ownership_evidence_ref": "source:wechat-header",
                "funding_account_ref": "account:ccb-2404",
                "calendar_date": "2026-07-26",
                "amount": "395.98",
            }],
        )
        self.assertEqual(observation["value"]["ambiguous_candidates"], [])
        self.assertIn("不表示本人账户互转", observation["parameters"]["interpretation"])

    def test_marks_multiple_bank_debits_as_ambiguous_wechat_payment_links(self):
        wallet = transaction()
        wallet.bank = "微信流水"
        wallet.transaction_id = "tx:wechat-payment"
        wallet.source_file_id = "sha256:wechat"
        wallet.income = Decimal("0.00")
        wallet.expense = Decimal("12.25")
        wallet.transaction_method = "建设银行储蓄卡(2404)"
        wallet.counterparty_name = "滴滴出行"
        wallet.field_confidence.update({"transaction_method": 1.0, "counterparty_name": 1.0})

        bank_rows = []
        for suffix in ("one", "two"):
            bank = transaction()
            bank.bank = "建设银行个人"
            bank.transaction_id = f"tx:bank-{suffix}"
            bank.source_file_id = "sha256:ccb"
            bank.income = Decimal("0.00")
            bank.expense = Decimal("12.25")
            bank.summary = "财付通-微信支付-滴滴出行"
            bank_rows.append(bank)

        result = build_bankflow_result(
            [wallet, *bank_rows],
            verification_context={
                "confirmed_owned_accounts": [
                    {
                        "account_ref": "account:ccb-2404",
                        "account_number": "6217000480002792404",
                        "verification_status": "confirmed",
                        "ownership_evidence_ref": "source:ccb-header",
                        "source_file_ids": ["sha256:ccb"],
                    }
                ],
                "confirmed_owned_payment_sources": [
                    {
                        "payment_account_type": "wechat_account",
                        "account_ref": "payment:wechat-client",
                        "source_file_id": "sha256:wechat",
                        "verification_status": "confirmed",
                        "ownership_evidence_ref": "source:wechat-header",
                        "identity_owner_name": "\u5f20\u4e09",
                        "identity_number": "110101199001011234",
                        "payment_account_id": "wechat:client",
                    }
                ],
            },
        )
        observation = next(
            item for item in result["result"]["observations"]
            if item["observation_type"] == "wechat_payment_bank_debit_link_candidates"
        )

        self.assertEqual(observation["value"]["paired"], [])
        self.assertEqual(len(observation["value"]["ambiguous_candidates"]), 2)

    def test_rejects_nonunique_card_tail_for_wechat_payment_links(self):
        wallet = transaction()
        wallet.bank = "微信流水"
        wallet.transaction_id = "tx:wechat-payment"
        wallet.source_file_id = "sha256:wechat"
        wallet.income = Decimal("0.00")
        wallet.expense = Decimal("12.25")
        wallet.transaction_method = "建设银行储蓄卡(2404)"
        wallet.counterparty_name = "滴滴出行"
        wallet.field_confidence.update({"transaction_method": 1.0, "counterparty_name": 1.0})

        observation = next(
            item for item in build_bankflow_result(
                [wallet],
                verification_context={
                    "confirmed_owned_accounts": [
                        {
                            "account_ref": "account:first-2404",
                            "account_number": "6217000480002792404",
                            "verification_status": "confirmed",
                            "ownership_evidence_ref": "source:first",
                        },
                        {
                            "account_ref": "account:second-2404",
                            "account_number": "6222000000000002404",
                            "verification_status": "confirmed",
                            "ownership_evidence_ref": "source:second",
                        },
                    ],
                    "confirmed_owned_payment_sources": [
                        {
                            "payment_account_type": "wechat_account",
                            "account_ref": "payment:wechat-client",
                            "source_file_id": "sha256:wechat",
                            "verification_status": "confirmed",
                            "ownership_evidence_ref": "source:wechat-header",
                            "identity_owner_name": "\u5f20\u4e09",
                            "identity_number": "110101199001011234",
                            "payment_account_id": "wechat:client",
                        }
                    ],
                },
            )["result"]["observations"]
            if item["observation_type"] == "wechat_payment_bank_debit_link_candidates"
        )

        self.assertFalse(observation["value"]["available"])
        self.assertEqual(observation["value"]["reason"], "reliable_wechat_card_tail_or_merchant_unavailable")

    def test_rejects_wechat_link_without_identity_triplet(self):
        wallet = transaction()
        wallet.bank = "\u5fae\u4fe1\u6d41\u6c34"
        wallet.transaction_id = "tx:wechat-payment"
        wallet.source_file_id = "sha256:wechat"
        wallet.income = Decimal("0.00")
        wallet.expense = Decimal("395.98")
        wallet.transaction_method = "\u5efa\u8bbe\u94f6\u884c\u50a8\u84c4\u5361(2404)"
        wallet.counterparty_name = "\u5c0f\u767d\u623f\u5b50"
        wallet.field_confidence.update({"transaction_method": 1.0, "counterparty_name": 1.0})

        observation = next(
            item for item in build_bankflow_result(
                [wallet],
                verification_context={
                    "confirmed_owned_accounts": [
                        {
                            "account_ref": "account:ccb-2404",
                            "account_number": "6217000480002792404",
                            "verification_status": "confirmed",
                            "ownership_evidence_ref": "source:ccb-header",
                        }
                    ],
                    "confirmed_owned_payment_sources": [
                        {
                            "payment_account_type": "wechat_account",
                            "account_ref": "payment:wechat-client",
                            "source_file_id": "sha256:wechat",
                            "verification_status": "confirmed",
                            "ownership_evidence_ref": "source:wechat-header",
                        }
                    ],
                },
            )["result"]["observations"]
            if item["observation_type"] == "wechat_payment_bank_debit_link_candidates"
        )

        self.assertFalse(observation["value"]["available"])
        self.assertEqual(observation["value"]["reason"], "confirmed_owned_wechat_sources_unavailable")

    def test_marks_alipay_linking_pending_confirmation(self):
        observation = next(
            item for item in build_bankflow_result([transaction()])["result"]["observations"]
            if item["observation_type"] == "alipay_payment_bank_debit_link_pending_field_confirmation"
        )

        self.assertFalse(observation["value"]["available"])
        self.assertEqual(
            observation["value"]["reason"],
            "alipay_payment_bank_debit_link_fields_pending_confirmation",
        )

    def test_writes_utf8_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_bankflow_json(build_bankflow_result([transaction()]), Path(directory) / "evidence.json")
            loaded = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["result"]["original_transactions"][0]["bank"], "测试银行")


if __name__ == "__main__":
    unittest.main()
