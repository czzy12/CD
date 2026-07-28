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
            candidate["transaction_context"]["direction"],
            "expense",
        )
        self.assertIn(
            "counterparty_name",
            candidate["matched_fields"],
        )
        self.assertEqual(
            [item["transaction_id"] for item in candidate["prior_income_candidates"]],
            ["tx:large-income", "tx:near-income"],
        )
        self.assertFalse(
            candidate["prior_income_candidates"][0][
                "same_source_as_purchase"
            ]
        )
        near = candidate["prior_income_candidates"][1]
        self.assertTrue(near["near_amount"])
        self.assertEqual(near["within_windows_days"], [1, 3, 7])
        self.assertFalse(funding["parameters"]["fund_source_attribution"])

    def test_purchase_vocabulary_accepts_explicit_order_payment_synonyms(self):
        for index, term in enumerate(("订金", "购车款", "首付款", "补款")):
            with self.subTest(term=term):
                purchase = tx(
                    f"tx:purchase:{index}",
                    datetime(2026, 1, 2),
                    expense="1000",
                    purpose=term,
                )

                observations = build_deterministic_text_observations(
                    [purchase],
                    None,
                )
                keyword = observations[0]
                funding = observations[2]

                self.assertIn(
                    term,
                    keyword["value"]["hits"][0]["matched_terms"],
                )
                self.assertEqual(
                    funding["value"]["purchase_candidates"][0][
                        "purchase_transaction_id"
                    ],
                    f"tx:purchase:{index}",
                )

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

    def test_sensitive_context_has_group_fields_period_and_source_coverage(self):
        cash_advance = tx(
            "tx:cash-advance",
            datetime(2026, 1, 2),
            expense="1000",
            purpose="信用卡套现还款",
        )
        court = tx(
            "tx:court",
            datetime(2026, 2, 3),
            expense="200",
            counterparty_name="甲区人民法院",
            summary="司法缴费",
        )

        sensitive = build_deterministic_text_observations(
            [cash_advance, court],
            None,
        )[3]

        self.assertEqual(
            sensitive["observation_type"],
            "sensitive_transaction_context_candidates",
        )
        self.assertTrue(sensitive["value"]["available"])
        self.assertEqual(sensitive["value"]["candidate_count"], 2)
        self.assertEqual(
            sensitive["value"]["candidates"][0]["matched_terms"],
            ["套现"],
        )
        self.assertEqual(
            sensitive["value"]["candidates"][0]["matched_fields"],
            {"purpose": ["套现"]},
        )
        self.assertEqual(
            sensitive["value"]["candidates"][0][
                "observed_source_period_start"
            ],
            "2026-01-02T00:00:00",
        )
        source = sensitive["value"]["searched_sources"][0]
        self.assertEqual(source["eligible_transaction_count"], 2)
        self.assertEqual(source["searched_transaction_count"], 2)
        self.assertEqual(source["candidate_count"], 2)
        self.assertEqual(
            sensitive["evidence_transaction_ids"],
            ["tx:cash-advance", "tx:court"],
        )
        self.assertFalse(
            sensitive["parameters"]["single_character_unconditional_matching"]
        )

    def test_sensitive_context_distinguishes_no_hit_from_unavailable_fields(self):
        no_hit = tx(
            "tx:no-hit",
            datetime(2026, 1, 2),
            expense="10",
            summary="普通消费",
        )
        unavailable = tx(
            "tx:unavailable",
            datetime(2026, 1, 3),
            expense="10",
            summary="法院",
        )
        unavailable.field_confidence.clear()

        no_hit_observation = build_deterministic_text_observations(
            [no_hit],
            None,
        )[3]
        unavailable_observation = build_deterministic_text_observations(
            [unavailable],
            None,
        )[3]

        self.assertEqual(
            no_hit_observation["value"]["reason"],
            "no_sensitive_hits_in_reliable_fields",
        )
        self.assertEqual(
            unavailable_observation["value"]["reason"],
            "sensitive_search_fields_unavailable",
        )


if __name__ == "__main__":
    unittest.main()
