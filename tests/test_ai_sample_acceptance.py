import unittest
from datetime import datetime, timedelta
from decimal import Decimal

from bankflow_v2.ai_business_observation import (
    build_ai_input_profile,
    select_ai_input_sample,
)
from bankflow_v2.ai_sample_acceptance import render_ai_sample_markdown
from bankflow_v2.models import Transaction


def transaction(index: int, purpose: str = "材料采购") -> Transaction:
    row = Transaction(
        datetime(2026, 1, 1) + timedelta(days=index),
        expense=Decimal("1000"),
        transaction_id=f"tx:{index}",
        source_file_id="source:bank",
        evidence_locator=f"page=1;row={index + 1}",
        purpose=purpose,
    )
    row.field_confidence["purpose"] = 1.0
    return row


class AiSampleAcceptanceTests(unittest.TestCase):
    def test_selects_reproducible_even_sample_and_excludes_exact_anchors(self):
        rows = [transaction(index) for index in range(10)]
        rows[5].purpose = "装修工程款"
        context = {
            "search_context": {
                "declared_industries": ["装修"],
                "work_units": [],
            }
        }

        sample, eligible_count = select_ai_input_sample(
            rows,
            context,
            allow_business_names=True,
            sample_size=3,
        )

        self.assertEqual(eligible_count, 9)
        self.assertEqual(
            [row.transaction_id for row in sample],
            ["tx:0", "tx:4", "tx:9"],
        )
        self.assertNotIn("tx:5", [row.transaction_id for row in sample])

    def test_renders_traceable_markdown(self):
        row = transaction(0)
        observation = {
            "value": {
                "available": True,
                "reason": "",
                "ai_candidates": [{
                    "transaction_id": "tx:0",
                    "classification": "possibly_related",
                    "evidence_strength": "medium",
                    "reason": "用途可能与行业相关，需人工复核",
                    "used_fields": ["purpose"],
                }],
            }
        }

        rendered = render_ai_sample_markdown(
            case_name="示例客户",
            provider="deepseek",
            model="deepseek-v4-flash",
            eligible_count=10,
            sampled_transactions=[row],
            observation=observation,
        )

        self.assertIn("示例客户 AI经营关联小批量验收", rendered)
        self.assertIn("purpose=材料采购", rendered)
        self.assertIn("可能相关", rendered)
        self.assertIn("中等候选：1", rendered)
        self.assertIn("page=1;row=1", rendered)
        self.assertIn("不表示真实经营", rendered)

    def test_profiles_candidate_fields_without_provider_call(self):
        informative = transaction(0)
        generic = transaction(1)
        generic.purpose = ""
        generic.transaction_type = "二维码收款"
        generic.field_confidence = {"transaction_type": 1.0}

        profile = build_ai_input_profile(
            [informative, generic],
            {"search_context": {"declared_industries": ["装修"]}},
            allow_business_names=True,
        )

        self.assertEqual(profile["transaction_count"], 2)
        self.assertEqual(profile["ai_candidate_count"], 1)
        self.assertEqual(
            profile["semantic_evidence_field_counts"],
            {"purpose": 1},
        )
        self.assertEqual(profile["unique_semantic_signature_count"], 1)
        self.assertEqual(profile["reusable_duplicate_candidate_count"], 0)
        self.assertEqual(profile["sources"][0]["ai_candidate_count"], 1)

    def test_profiles_duplicate_semantic_signatures_for_reuse(self):
        rows = [transaction(0), transaction(1), transaction(2, "设备维护")]

        profile = build_ai_input_profile(
            rows,
            {"search_context": {"declared_industries": ["装修"]}},
            allow_business_names=True,
        )

        self.assertEqual(profile["ai_candidate_count"], 3)
        self.assertEqual(profile["unique_semantic_signature_count"], 2)
        self.assertEqual(profile["reusable_duplicate_candidate_count"], 1)

    def test_balances_sample_across_source_files(self):
        rows = [transaction(index) for index in range(12)]
        for index, row in enumerate(rows):
            row.source_file_id = "source:one" if index < 9 else "source:two"
            row.source_file = "one.pdf" if index < 9 else "two.pdf"

        sample, eligible_count = select_ai_input_sample(
            rows,
            {"search_context": {"declared_industries": ["装修"]}},
            allow_business_names=True,
            sample_size=6,
            source_balanced=True,
        )

        self.assertEqual(eligible_count, 12)
        self.assertEqual(
            [row.source_file_id for row in sample].count("source:one"),
            3,
        )
        self.assertEqual(
            [row.source_file_id for row in sample].count("source:two"),
            3,
        )

    def test_can_sample_unique_semantic_signatures_only(self):
        rows = [transaction(0), transaction(1), transaction(2, "设备维护")]

        sample, eligible_count = select_ai_input_sample(
            rows,
            {"search_context": {"declared_industries": ["装修"]}},
            allow_business_names=True,
            sample_size=10,
            unique_semantic_signatures=True,
        )

        self.assertEqual(eligible_count, 2)
        self.assertEqual(
            [row.transaction_id for row in sample],
            ["tx:0", "tx:2"],
        )


if __name__ == "__main__":
    unittest.main()
