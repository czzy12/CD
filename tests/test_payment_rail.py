"""Gate D.3A: payment rail boundary tests."""

import unittest

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    build_validation_items,
)
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.payment_rail import is_payment_rail_only
from bankflow_v2.knowledge import versioning


CANONICAL_DIR = (
    __import__("pathlib").Path(__file__).resolve().parent.parent
    / "bankflow_v2"
    / "knowledge"
    / "canonical"
)

PROFILE = IndustryProfile(
    primary_industry_ids=("internal.building_material_trade",),
    taxonomy_version=versioning.TAXONOMY_VERSION,
)


class PaymentRailDetectionTests(unittest.TestCase):
    def test_payment_rail_only_texts(self):
        cases = [
            {"remark": "财付通-微信支付-扫二维码付款"},
            {"remark": "微信零钱提现"},
            {"remark": "财付通-微信支付-微信转账"},
            {"summary": "支付机构提现", "remark": "微信零钱提现"},
            {"remark": "支付宝-扫二维码付款"},
            {"product_description": "收钱码收款"},
            {"counterparty_name": "拉卡拉支付股份有限公司"},
            {"counterparty_name": "财付通支付科技有限公司"},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                self.assertTrue(is_payment_rail_only(fields))

    def test_business_object_not_payment_rail_only(self):
        cases = [
            {"remark": "财付通-微信支付-锡林浩特市原阿宝鲜肉店"},
            {"remark": "财付通-微信支付-民盛购物中心"},
            {"remark": "支付宝-淘宝-龙政煊"},
            {"remark": "财付通-微信支付-美团平台商户"},
            {"remark": "财付通-微信支付-手机充值-中国移动"},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                self.assertFalse(is_payment_rail_only(fields))

    def test_no_payment_marker_is_not_payment_rail_only(self):
        self.assertFalse(is_payment_rail_only({"remark": "物流费"}))


class PaymentRailResolverTests(unittest.TestCase):
    def test_resolver_keeps_payment_rail_only_unresolved(self):
        runtime = KnowledgeRuntime.load(CANONICAL_DIR)
        resolved = runtime.resolve_transaction_fields(
            {"remark": "财付通-微信支付-扫二维码付款"},
            PROFILE,
        )
        self.assertEqual(resolved["semantic"]["concept_id"], "")
        self.assertEqual(
            resolved["semantic"]["concept_resolution_source"],
            "unresolved",
        )
        self.assertIn("支付渠道", resolved["semantic"]["reason"])
        self.assertEqual(resolved["final_relevance"], "undetermined")

    def test_resolver_still_resolves_business_object(self):
        runtime = KnowledgeRuntime.load(CANONICAL_DIR)
        resolved = runtime.resolve_transaction_fields(
            {"remark": "财付通-微信支付-物流费"},
            PROFILE,
        )
        self.assertEqual(resolved["semantic"]["concept_id"], "logistics")

    def test_build_validation_items_skips_payment_rail_only(self):
        runtime = KnowledgeRuntime.load(CANONICAL_DIR)
        entries = [
            {
                "signature_hash": "p" * 24,
                "fields": {"remark": "财付通-微信支付-扫二维码付款"},
                "legacy_business_context": {},
            },
            {
                "signature_hash": "q" * 24,
                "fields": {"remark": "量子秘传杂项支出"},
                "legacy_business_context": {},
            },
        ]
        items, counts = build_validation_items(entries, runtime, PROFILE)
        self.assertEqual(counts["payment_rail_non_business_skipped"], 1)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["fields"], {"remark": "量子秘传杂项支出"})


if __name__ == "__main__":
    unittest.main()
