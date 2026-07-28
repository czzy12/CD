import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from bankflow_v2.models import Transaction
from bankflow_v2.mvp_fund_observations import build_fund_observations


def tx(
    transaction_id: str,
    when: datetime,
    *,
    income: str = "0",
    expense: str = "0",
    balance: str | None = None,
    source_file_id: str = "source:bank",
    source_file: str = "bank.pdf",
    counterparty_name: str = "",
    summary: str = "",
    purpose: str = "",
) -> Transaction:
    transaction = Transaction(
        when,
        income=Decimal(income),
        expense=Decimal(expense),
        balance=Decimal(balance) if balance is not None else None,
        source_file_id=source_file_id,
        source_file=source_file,
        transaction_id=transaction_id,
        evidence_locator="page=1;row=1",
        counterparty_name=counterparty_name,
        summary=summary,
        purpose=purpose,
    )
    for field_name in ("counterparty_name", "summary", "purpose"):
        if getattr(transaction, field_name):
            transaction.field_confidence[field_name] = 1.0
    return transaction


class MvpFundObservationTests(unittest.TestCase):
    def test_large_inflow_path_reports_split_outflow_and_low_retention(self):
        start = datetime(2026, 1, 10, 10)
        rows = [
            tx("tx:in", start, income="100000", balance="105000"),
            tx(
                "tx:out-one",
                start + timedelta(hours=2),
                expense="60000",
                balance="45000",
            ),
            tx(
                "tx:out-two",
                start + timedelta(hours=20),
                expense="35000",
                balance="10000",
            ),
        ]

        observations = {
            item["observation_type"]: item
            for item in build_fund_observations(rows)
        }
        path = observations["large_inflow_balance_paths"]["value"]["candidates"][0]
        one_day = path["windows"][0]

        self.assertEqual(path["pre_inflow_balance"], "5000.00")
        self.assertEqual(one_day["cumulative_expense"], "95000.00")
        self.assertEqual(one_day["included_component_expense_count"], 2)
        self.assertEqual(one_day["cumulative_expense_ratio"], "0.9500")
        self.assertTrue(one_day["near_total_outflow"])
        self.assertTrue(one_day["large_portion_outflow"])
        self.assertTrue(one_day["low_retained_balance_increment"])
        self.assertEqual(one_day["end_of_day_balance"], "10000.00")
        self.assertFalse(
            observations["large_inflow_balance_paths"]["parameters"][
                "fund_source_attribution"
            ]
        )

    def test_retained_increment_ratio_is_clamped_at_zero(self):
        start = datetime(2026, 1, 10, 10)
        rows = [
            tx("tx:in", start, income="100000", balance="105000"),
            tx(
                "tx:out",
                start + timedelta(hours=2),
                expense="105000",
                balance="0",
            ),
        ]

        path = {
            item["observation_type"]: item
            for item in build_fund_observations(rows)
        }["large_inflow_balance_paths"]["value"]["candidates"][0]

        self.assertEqual(
            path["windows"][0]["retained_balance_increment_ratio"],
            "0.0000",
        )
        self.assertTrue(
            path["windows"][0]["low_retained_balance_increment"],
        )

    def test_large_inflow_path_requires_source_file_id(self):
        start = datetime(2026, 1, 10, 10)
        rows = [
            tx(
                "tx:in",
                start,
                income="100000",
                balance="105000",
                source_file_id="",
                source_file="first.pdf",
            ),
            tx(
                "tx:out",
                start + timedelta(hours=2),
                expense="95000",
                balance="10000",
                source_file_id="",
                source_file="second.pdf",
            ),
        ]

        path_observation = {
            item["observation_type"]: item
            for item in build_fund_observations(rows)
        }["large_inflow_balance_paths"]

        self.assertFalse(path_observation["value"]["available"])
        self.assertEqual(
            path_observation["value"]["reason"],
            "source_file_id_unavailable",
        )
        self.assertEqual(path_observation["value"]["candidates"], [])

    def test_large_inflow_path_reports_partially_unavailable_sources(self):
        start = datetime(2026, 1, 10, 10)
        rows = [
            tx("tx:usable", start, income="30000", balance="30000"),
            tx(
                "tx:missing-source",
                start + timedelta(days=1),
                income="40000",
                balance="40000",
                source_file_id="",
                source_file="unknown.pdf",
            ),
        ]

        value = {
            item["observation_type"]: item
            for item in build_fund_observations(rows)
        }["large_inflow_balance_paths"]["value"]

        self.assertTrue(value["available"])
        self.assertTrue(value["partially_available"])
        self.assertEqual(value["eligible_inflow_count"], 2)
        self.assertEqual(value["path_candidate_count"], 1)
        self.assertEqual(value["source_file_id_unavailable_count"], 1)
        self.assertEqual(
            value["candidates"][0]["inflow_transaction"]["transaction_id"],
            "tx:usable",
        )

    def test_large_transaction_threshold_is_ten_thousand_inclusive(self):
        rows = [
            tx("tx:large", datetime(2026, 1, 1), expense="10000"),
            tx("tx:small", datetime(2026, 1, 2), expense="9999.99"),
        ]

        large = build_fund_observations(rows)[0]

        self.assertEqual(
            [item["transaction_id"] for item in large["value"]["candidates"]],
            ["tx:large"],
        )

    def test_balance_statistics_and_quarterly_interest_are_source_scoped(self):
        rows = [
            tx(
                "tx:q1",
                datetime(2026, 3, 21),
                income="12.34",
                balance="100",
                summary="结息",
            ),
            tx(
                "tx:q2",
                datetime(2026, 6, 21),
                income="20",
                balance="300",
                summary="利息",
            ),
        ]

        observation = {
            item["observation_type"]: item
            for item in build_fund_observations(rows)
        }["end_of_day_balance_and_interest"]
        source = observation["value"]["sources"][0]

        self.assertEqual(source["balance_statistics"]["minimum"], "100.00")
        self.assertEqual(source["balance_statistics"]["median"], "200.00")
        self.assertEqual(source["balance_statistics"]["average"], "200.00")
        self.assertEqual(source["balance_statistics"]["closing"], "300.00")
        self.assertEqual(
            source["balance_snapshot_transaction_ids"],
            ["tx:q1", "tx:q2"],
        )
        self.assertEqual(
            [item["quarter"] for item in source["quarterly_interest"]],
            ["2026-Q1", "2026-Q2"],
        )
        self.assertEqual(source["quarterly_interest"][1]["change_from_previous"], "7.66")

    def test_balance_and_interest_distinguish_not_applicable_and_no_hit(self):
        wechat = tx(
            "tx:wechat",
            datetime(2026, 1, 1),
            income="100",
            balance=None,
            source_file_id="source:wechat",
            source_file="wechat.pdf",
            summary="普通收款",
        )
        wechat.bank = "微信流水"

        source = {
            item["observation_type"]: item
            for item in build_fund_observations([wechat])
        }["end_of_day_balance_and_interest"]["value"]["sources"][0]

        self.assertEqual(
            source["balance_unavailable_reason"],
            "balance_not_applicable",
        )
        self.assertFalse(source["interest_available"])
        self.assertEqual(
            source["interest_unavailable_reason"],
            "no_interest_records_in_reliable_fields",
        )

    def test_top_five_excludes_masked_names_and_builds_cross_source_occurrence(self):
        rows = [
            tx(
                "tx:a-bank",
                datetime(2026, 1, 1),
                income="100",
                counterparty_name="张鑫",
            ),
            tx(
                "tx:a-wechat",
                datetime(2026, 1, 2),
                expense="20",
                source_file_id="source:wechat",
                source_file="wechat.pdf",
                counterparty_name="张鑫",
            ),
            tx(
                "tx:masked",
                datetime(2026, 1, 3),
                income="999",
                counterparty_name="***中心",
            ),
            tx(
                "tx:prefixed",
                datetime(2026, 1, 4),
                income="888",
                counterparty_name="88BE张鑫",
            ),
            tx(
                "tx:short-prefixed",
                datetime(2026, 1, 5),
                income="777",
                counterparty_name="0高衡",
            ),
            tx(
                "tx:account-label",
                datetime(2026, 1, 6),
                income="666",
                counterparty_name="JXLCJXZD200106004赎回账户",
            ),
        ]

        observations = {
            item["observation_type"]: item
            for item in build_fund_observations(rows)
        }
        top = observations["top_counterparties"]["value"]
        occurrence = observations["cross_source_counterparty_occurrences"]["value"]

        self.assertEqual(top["income"][0]["identity_value"], "张鑫")
        self.assertEqual(top["expense"][0]["identity_value"], "张鑫")
        self.assertEqual(top["income"][0]["covered_amount_share"], "1.0000")
        self.assertEqual(top["income"][0]["direction_amount_share"], "0.0292")
        self.assertEqual(
            top["income_summary"]["amount_coverage_rate"],
            "0.0292",
        )
        self.assertNotIn("***中心", str(top))
        self.assertNotIn("88BE张鑫", str(top))
        self.assertNotIn("0高衡", str(top))
        self.assertNotIn("赎回账户", str(top))
        self.assertEqual(occurrence["counterparties"][0]["counterparty_name"], "张鑫")
        self.assertEqual(occurrence["counterparties"][0]["source_count"], 2)

    def test_top_counterparties_reports_direction_unavailable_reason(self):
        row = tx(
            "tx:income",
            datetime(2026, 1, 1),
            income="100",
        )

        top = {
            item["observation_type"]: item
            for item in build_fund_observations([row])
        }["top_counterparties"]["value"]

        self.assertFalse(top["income_summary"]["available"])
        self.assertEqual(
            top["income_summary"]["reason"],
            "identifiable_counterparty_unavailable",
        )
        self.assertFalse(top["expense_summary"]["available"])
        self.assertEqual(
            top["expense_summary"]["reason"],
            "no_expense_transactions",
        )

    def test_explicit_purpose_candidates_keep_transaction_evidence(self):
        rows = [
            tx(
                "tx:salary",
                datetime(2026, 1, 1),
                income="4500",
                purpose="工资",
            ),
            tx(
                "tx:tax",
                datetime(2026, 1, 2),
                expense="200",
                summary="税费缴纳",
            ),
        ]

        observation = {
            item["observation_type"]: item
            for item in build_fund_observations(rows)
        }["explicit_purpose_candidates"]

        self.assertEqual(
            [item["category"] for item in observation["value"]["candidates"]],
            ["salary", "tax"],
        )
        self.assertEqual(
            observation["evidence_transaction_ids"],
            ["tx:salary", "tx:tax"],
        )


if __name__ == "__main__":
    unittest.main()
