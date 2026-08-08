"""Gate D.3.1 regression guards: recall recovery without precision loss."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from bankflow_v2.deepseek_adapter import DeepSeekSettings
from bankflow_v2.knowledge import KnowledgeRuntime
from bankflow_v2.knowledge import versioning
from bankflow_v2.knowledge.ai_fallback import DeepSeekKnowledgeAdapter
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.payment_rail import is_payment_rail_only


CANONICAL_DIR = (
    Path(__file__).resolve().parent.parent
    / "bankflow_v2"
    / "knowledge"
    / "canonical"
)

PROFILE = IndustryProfile(
    primary_industry_ids=("internal.building_material_trade", "47"),
    secondary_industry_ids=("internal.environmental_engineering", "06"),
    taxonomy_version=versioning.TAXONOMY_VERSION,
    profile_name="building_material",
)


class RecallRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = KnowledgeRuntime.load(CANONICAL_DIR)
        cls.business_terms = tuple(
            dict.fromkeys(
                term
                for terms in cls.runtime.concepts.keyword_terms().values()
                for term in terms
            )
        )

    def resolve(self, fields: dict[str, str]) -> str:
        return str(
            self.runtime.resolve_transaction_fields(
                fields,
                PROFILE,
            )["semantic"].get("concept_id", "")
        )

    def test_broad_transaction_actions_map_to_generic(self):
        cases = {
            "取款": "generic",
            "卡存": "generic",
            "中跨行汇款": "generic",
            "3:转账": "generic",
            "退款": "generic",
            "订单支付": "generic",
            "帐户信息变更": "generic",
            "充值-普通充值": "generic",
            "提现-实时提现": "generic",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.resolve({"summary": text}), expected)

    def test_life_and_settlement_broad_concepts_recover(self):
        self.assertEqual(self.resolve({"summary": "3:消费"}), "life")
        self.assertEqual(self.resolve({"remark": "财付通-微信支付-微信红包"}), "life")
        self.assertEqual(self.resolve({"summary": "消费退货"}), "settlement")

    def test_payment_rail_plus_business_evidence_resolves(self):
        cases = {
            "财付通-微信支付-美团平台商户": "ecommerce",
            "财付通-微信支付-深圳市腾讯计算机系统有限公司": "generic_technology",
            "财付通-微信支付-创新广场": "retail",
            "财付通-微信支付-微信转账": "generic",
            "微信零钱提现": "generic",
            "收钱码收款": "generic",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                fields = {"remark": text}
                self.assertFalse(
                    is_payment_rail_only(
                        fields,
                        business_terms=self.business_terms,
                    )
                )
                self.assertEqual(self.resolve(fields), expected)

    def test_payment_rail_only_remains_unresolved(self):
        for text in ("支付宝", "财付通", "拉卡拉POS收单", "POS收单"):
            with self.subTest(text=text):
                fields = {"remark": text}
                self.assertTrue(
                    is_payment_rail_only(
                        fields,
                        business_terms=self.business_terms,
                    )
                )
                self.assertEqual(self.resolve(fields), "")

    def test_entity_place_name_not_business_concept(self):
        self.assertEqual(self.resolve({"product_description": "汽车小镇橄榄城店"}), "")


class PrecisionGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = KnowledgeRuntime.load(CANONICAL_DIR)

    def resolve(self, fields: dict[str, str]) -> str:
        return str(
            self.runtime.resolve_transaction_fields(
                fields,
                PROFILE,
            )["semantic"].get("concept_id", "")
        )

    def test_human_insufficient_texts_stay_unresolved_locally(self):
        cases = [
            {"summary": "充值", "remark": "财付通-微信支付-扫二维码付款"},
            {"product_description": "经营码交易"},
            {"remark": "财付通-微信支付-美团"},
            {"counterparty_name": "世腾集团-李易18088144526"},
            {"product_description": "【POS】_河南郑州嵩山路店-62301719_331596_62301719"},
            {"remark": "财付通-微信支付-彭州龙兴寺店"},
            {"counterparty_name": "圣林工艺一楼300店面"},
            {"product_description": "郑州二七区汉江路店"},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                self.assertEqual(self.resolve(fields), "")


class ConceptBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = KnowledgeRuntime.load(CANONICAL_DIR)

    def resolve(self, fields: dict[str, str]) -> str:
        return str(
            self.runtime.resolve_transaction_fields(
                fields,
                PROFILE,
            )["semantic"].get("concept_id", "")
        )

    def test_water_filter_home_appliance_boundary(self):
        texts = [
            "全款交易：一次性水龙头过滤棉冷热水通用高密度过拦截水垢泥沙家用净水神器",
            "全款交易：新款加厚一次性过滤棉过滤水龙头地下水自来水山泉水过滤器过滤袋",
            "全款交易：水龙头过滤棉防溅过滤自来水井水山泉水泥沙铁锈水垢杂质过滤棉袋",
        ]
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(
                    self.resolve({"product_description": text}),
                    "home_appliance",
                )

    def test_retail_broad_aliases(self):
        self.assertEqual(self.resolve({"remark": "财付通-微信支付-创新广场"}), "retail")
        self.assertEqual(self.resolve({"remark": "财付通-微信支付-民盛购物中心"}), "retail")

    def test_property_management_relations_stable(self):
        resolved = self.runtime.resolve_transaction_fields(
            {"remark": "财付通-微信支付-东方花园物业"},
            PROFILE,
        )
        self.assertEqual(resolved["semantic"]["concept_id"], "property_management")
        self.assertEqual(
            self.runtime.relation_resolver.resolve(
                industry_id="47",
                concept_id="property_management",
                profile=PROFILE,
            ).relevance,
            "strong",
        )
        self.assertEqual(
            self.runtime.relation_resolver.resolve(
                industry_id="06",
                concept_id="property_management",
                profile=PROFILE,
            ).relevance,
            "undetermined",
        )
        self.assertIsNone(
            self.runtime.relations.approved("06", "property_management")
        )


class PromptV3Tests(unittest.TestCase):
    def test_prompt_instructions_include_rebalancing_rules(self):
        captured: dict[str, str] = {}

        def transport(url: str, body: bytes, headers: object, timeout: float) -> bytes:
            captured["body"] = body.decode("utf-8")
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "results": [
                                            {
                                                "item_id": "i1",
                                                "concept_id": "undetermined",
                                                "confidence": "low",
                                                "reason": "insufficient",
                                                "used_fields": ["remark"],
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
                ensure_ascii=False,
            ).encode("utf-8")

        settings = DeepSeekSettings(
            api_key="k",
            base_url="https://example.com",
            enabled=True,
            data_authorized=True,
            retention_policy_confirmed=True,
        )
        adapter = DeepSeekKnowledgeAdapter(settings, transport)
        adapter.resolve_concepts(
            [{"item_id": "i1", "fields": {"remark": "支付宝便利店消费"}}],
            concept_candidates=[],
        )
        payload = json.loads(captured["body"])
        user = json.loads(payload["messages"][1]["content"])
        self.assertEqual(versioning.PROMPT_SEMANTIC_CONCEPT_VERSION, "semantic-concept-v3")
        instructions = " ".join(user.get("instructions", []))
        self.assertIn("支付渠道之外", instructions)
        self.assertIn("generic", instructions)
        self.assertIn("汽车小镇", instructions)
        self.assertIn("home_appliance", instructions)
        self.assertIn("retail", instructions)


if __name__ == "__main__":
    unittest.main()
