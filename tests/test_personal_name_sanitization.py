"""Gate D.3D: personal-name sanitization tests."""

import unittest

from bankflow_v2.knowledge.ai_validation import safe_validation_fields
from bankflow_v2.knowledge.normalization import (
    normalize_semantic_text,
    sanitize_personal_names,
)


class SanitizationTests(unittest.TestCase):
    def test_person_after_organization_marker(self):
        self.assertEqual(
            sanitize_personal_names("世腾集团- 李易180881 44526"),
            "世腾集团- [PERSON]180881 44526",
        )
        self.assertEqual(
            sanitize_personal_names("世腾集团-李易"),
            "世腾集团-[PERSON]",
        )

    def test_person_after_platform_marker(self):
        self.assertEqual(
            sanitize_personal_names("支付宝-淘宝-龙政煊"),
            "支付宝-淘宝-[PERSON]",
        )

    def test_business_entities_untouched(self):
        cases = [
            "王府井",
            "麦当劳",
            "紫罗兰花艺厂家直销",
            "全款交易：水龙头 过滤棉防溅过滤自 来水井水山泉水泥 沙铁锈水垢杂质过 滤棉袋",
            "美宜佳绿都脉动公寓店 100210026051116",
            "温心名烟名酒喜茶铺",
            "圣林工艺一楼300店面",
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(sanitize_personal_names(value), value)

    def test_sanitization_idempotent(self):
        once = sanitize_personal_names("世腾集团-李易")
        self.assertEqual(sanitize_personal_names(once), once)

    def test_normalized_text_contains_no_personal_name(self):
        normalized = normalize_semantic_text("世腾集团- 李易180881 44526")
        self.assertNotIn("李易", normalized)

    def test_outbound_fields_sanitized(self):
        safe = safe_validation_fields(
            {"remark": "世腾集团- 李易180881 44526"}
        )
        self.assertNotIn("李易", safe["remark"])
        self.assertIn("[PERSON]", safe["remark"])


if __name__ == "__main__":
    unittest.main()
