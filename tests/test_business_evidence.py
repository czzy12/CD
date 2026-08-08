"""Gate F1.2 tests: Business Evidence Role + Trace Strength (Layer B2)."""

from __future__ import annotations

import unittest
from pathlib import Path

from bankflow_v2.knowledge.evidence import BusinessEvidenceResolver
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.resolver import KnowledgeRuntime


REPO_ROOT = Path(__file__).resolve().parents[1]


def profile51() -> IndustryProfile:
    return IndustryProfile(
        primary_industry_ids=("51",),
        normalized_products_services=(
            "铝锭大宗贸易",
            "金属材料销售",
            "金属矿石销售",
            "金属制品销售",
            "生产性废旧金属回收",
            "石墨及碳素制品销售",
        ),
        profile_name="test-51-wholesale",
    )


class BusinessEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.resolver = BusinessEvidenceResolver()

    def resolve(self, fields, **kwargs):
        return self.resolver.resolve(fields, **kwargs)

    def test_tax_role_and_trace(self):
        result = self.resolve({"summary": "增值税缴税", "merchant_category": "税务"})
        self.assertEqual(result["role"], "tax_regulatory")
        self.assertEqual(result["trace_strength"], "medium")

    def test_tax_not_automatically_industry_strong(self):
        runtime = KnowledgeRuntime.load(
            REPO_ROOT / "bankflow_v2" / "knowledge" / "canonical"
        )
        profile = IndustryProfile(
            primary_industry_ids=("internal.building_material_trade",),
            profile_name="test-building-material",
        )
        resolved = runtime.resolve_transaction_fields(
            {"summary": "增值税缴税"},
            profile,
        )
        self.assertEqual(resolved["final_relevance"], "undetermined")

    def test_loan_financing(self):
        result = self.resolve({"summary": "企业经营贷款放款"})
        self.assertEqual(result["role"], "financing")
        self.assertEqual(result["trace_strength"], "medium")

    def test_generic_loan_weak(self):
        result = self.resolve({"summary": "借款"})
        self.assertEqual(result["role"], "financing")
        self.assertEqual(result["trace_strength"], "weak")

    def test_rent_operating_expense(self):
        result = self.resolve({"summary": "支付商铺租金"})
        self.assertEqual(result["role"], "operating_expense")
        self.assertEqual(result["trace_strength"], "medium")

    def test_utilities_operating_expense(self):
        result = self.resolve({"summary": "电费"})
        self.assertEqual(result["role"], "operating_expense")
        self.assertEqual(result["trace_strength"], "medium")

    def test_salary_employment(self):
        result = self.resolve({"summary": "代发工资"})
        self.assertEqual(result["role"], "employment_operation")
        self.assertEqual(result["trace_strength"], "medium")

    def test_social_security_employment(self):
        result = self.resolve({"summary": "社保缴费"})
        self.assertEqual(result["role"], "employment_operation")

    def test_settlement_card_fee(self):
        result = self.resolve({"summary": "企业结算卡年费"})
        self.assertEqual(result["role"], "settlement_infrastructure")
        self.assertEqual(result["trace_strength"], "weak")

    def test_dining_personal_none(self):
        result = self.resolve({"merchant_name": "黄家龙虾", "summary": "消费"})
        self.assertEqual(result["role"], "personal_consumption")
        self.assertEqual(result["trace_strength"], "none")

    def test_beauty_personal_none(self):
        result = self.resolve({"summary": "美容院消费"})
        self.assertEqual(result["role"], "personal_consumption")
        self.assertEqual(result["trace_strength"], "none")

    def test_payment_rail_only_neutral(self):
        result = self.resolve({"summary": "财付通"})
        self.assertEqual(result["role"], "neutral_transfer")
        self.assertEqual(result["trace_strength"], "undetermined")
        self.assertEqual(result["unresolved_reason"], "payment_rail_only")

    def test_transfer_action_is_neutral_not_business(self):
        result = self.resolve({"summary": "财付通转账"})
        self.assertEqual(result["role"], "neutral_transfer")
        self.assertEqual(result["trace_strength"], "undetermined")

    def test_direct_metal_goods_payment_with_profile51(self):
        result = self.resolve(
            {"summary": "铝锭货款"},
            concept_id="goods_payment",
            direction="expense",
            profile=profile51(),
        )
        self.assertEqual(result["role"], "direct_business")
        self.assertEqual(result["trace_strength"], "strong")
        self.assertEqual(result["role_source"], "context_override")

    def test_direct_metal_sales_with_profile51(self):
        result = self.resolve(
            {"summary": "金属材料销售"},
            concept_id="wholesale",
            direction="income",
            profile=profile51(),
        )
        self.assertEqual(result["role"], "direct_business")
        self.assertEqual(result["trace_strength"], "strong")

    def test_payment_acquirer_not_hardcoded_settlement(self):
        result = self.resolve(
            {"counterparty_name": "拉卡拉支付股份有限公司", "summary": "转账"}
        )
        self.assertNotEqual(result["role"], "settlement_infrastructure")

    def test_tax_institution_name_alone_not_tax(self):
        result = self.resolve({"counterparty_name": "国家税务总局XX市税务局"})
        self.assertNotEqual(result["role"], "tax_regulatory")

    def test_insufficient_unknown(self):
        result = self.resolve({"summary": "普通业务往来"})
        self.assertEqual(result["role"], "unknown")
        self.assertEqual(result["trace_strength"], "undetermined")


if __name__ == "__main__":
    unittest.main()
