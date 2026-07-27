import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from bankflow_v2.models import Transaction
from bankflow_v2.mvp_observations import build_deterministic_text_observations


def tx(
    transaction_id: str,
    when: datetime,
    *,
    income: str = "0",
    expense: str = "0",
    source_file_id: str = "source:wechat",
    counterparty_name: str = "",
    summary: str = "",
    purpose: str = "",
) -> Transaction:
    transaction = Transaction(
        when,
        income=Decimal(income),
        expense=Decimal(expense),
        source_file="sample.pdf",
        source_file_id=source_file_id,
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


class MvpTextObservationTests(unittest.TestCase):
    def test_outputs_keyword_hits_with_full_context_and_dynamic_location(self):
        transaction = tx(
            "tx:parking",
            datetime(2026, 1, 2, 8),
            expense="20",
            counterparty_name="济宁市金乡县智慧停车",
            summary="微信支付",
        )
        context = {
            "search_context": {
                "work_units": [],
                "declared_industries": [],
                "work_locations": [],
                "residence_locations": ["山东省济宁市金乡县"],
                "vehicle_registration_locations": [],
                "vehicle_models": [],
                "dealer_names": [],
            }
        }

        observations = build_deterministic_text_observations([transaction], context)
        keyword = observations[0]

        self.assertEqual(keyword["observation_type"], "controlled_keyword_candidates")
        self.assertTrue(keyword["value"]["available"])
        self.assertTrue(keyword["value"]["candidate_only"])
        self.assertEqual(keyword["value"]["hits"][0]["transaction_id"], "tx:parking")
        self.assertIn("停车", keyword["value"]["hits"][0]["matched_terms"])
        self.assertIn("金乡县", keyword["value"]["hits"][0]["matched_terms"])
        self.assertEqual(
            keyword["value"]["hits"][0]["transaction_context"]["expense"],
            "20.00",
        )
        self.assertEqual(keyword["value"]["hits"][0]["evidence_locator"], "page=1;row=1")

    def test_extracts_city_term_when_address_starts_with_province_name(self):
        transaction = tx(
            "tx:urumqi",
            datetime(2026, 1, 2),
            expense="30",
            counterparty_name="乌鲁 木齐停车服务",
        )
        context = {
            "search_context": {
                "work_units": [],
                "declared_industries": [],
                "work_locations": ["新疆乌鲁木齐市水磨沟区"],
                "residence_locations": [],
                "vehicle_registration_locations": [],
                "vehicle_models": [],
                "dealer_names": [],
            }
        }

        keyword = build_deterministic_text_observations([transaction], context)[0]

        self.assertIn("乌鲁木齐", keyword["value"]["hits"][0]["matched_terms"])

    def test_uses_short_registration_location_without_city_suffix(self):
        transaction = tx(
            "tx:jinan",
            datetime(2026, 1, 2),
            expense="30",
            counterparty_name="济宁停车",
        )
        context = {
            "search_context": {
                "work_units": [],
                "declared_industries": [],
                "work_locations": [],
                "residence_locations": [],
                "vehicle_registration_locations": ["济宁牌"],
                "vehicle_models": [],
                "dealer_names": [],
            }
        }

        keyword = build_deterministic_text_observations([transaction], context)[0]

        self.assertIn("济宁", keyword["value"]["hits"][0]["matched_terms"])

    def test_excludes_generic_text_from_industry_search_coverage(self):
        generic = tx(
            "tx:generic",
            datetime(2026, 1, 2),
            expense="10",
            summary="商户消费",
        )
        informative = tx(
            "tx:informative",
            datetime(2026, 1, 3),
            income="100",
            counterparty_name="甲装修材料有限公司",
        )
        unreliable = tx(
            "tx:unreliable",
            datetime(2026, 1, 4),
            income="50",
            purpose="工程款",
        )
        unreliable.field_confidence["purpose"] = 0.99

        coverage = build_deterministic_text_observations(
            [generic, informative, unreliable],
            None,
        )[1]
        source = coverage["value"]["sources"][0]

        self.assertEqual(source["eligible_transaction_count"], 3)
        self.assertEqual(source["industry_search_covered_transaction_count"], 1)
        self.assertEqual(source["industry_search_coverage_rate"], "0.3333")
        self.assertEqual(source["counterparty_covered_transaction_count"], 1)
        self.assertEqual(source["summary_or_purpose_covered_transaction_count"], 0)
        self.assertEqual(source["source_file"], "sample.pdf")

    def test_purchase_hit_shows_prior_near_and_large_income_without_attribution(self):
        purchase_time = datetime(2026, 1, 10, 12)
        near_income = tx(
            "tx:near-income",
            purchase_time - timedelta(hours=20),
            income="9500",
            source_file_id="source:bank",
            summary="转入",
        )
        large_income = tx(
            "tx:large-income",
            purchase_time - timedelta(days=2),
            income="30000",
            source_file_id="source:bank",
            summary="转入",
        )
        purchase = tx(
            "tx:purchase",
            purchase_time,
            expense="10000",
            counterparty_name="重庆问界汽车销售有限公司",
        )

        funding = build_deterministic_text_observations(
            [large_income, near_income, purchase],
            None,
        )[2]
        candidate = funding["value"]["purchase_candidates"][0]

        self.assertEqual(candidate["purchase_transaction_id"], "tx:purchase")
        self.assertEqual(
            [item["transaction_id"] for item in candidate["prior_income_candidates"]],
            ["tx:large-income", "tx:near-income"],
        )
        near = candidate["prior_income_candidates"][1]
        self.assertTrue(near["near_amount"])
        self.assertEqual(near["within_windows_days"], [1, 3, 7])
        self.assertFalse(funding["parameters"]["fund_source_attribution"])

    def test_does_not_match_single_character_sensitive_or_vehicle_terms(self):
        unrelated = tx(
            "tx:unrelated",
            datetime(2026, 1, 2),
            expense="10",
            counterparty_name="电子科技法务咨询",
        )

        keyword = build_deterministic_text_observations([unrelated], None)[0]

        self.assertFalse(keyword["value"]["available"])
        self.assertEqual(keyword["value"]["reason"], "no_hits_in_reliable_fields")


if __name__ == "__main__":
    unittest.main()
