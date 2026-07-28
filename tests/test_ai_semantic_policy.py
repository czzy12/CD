import json
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from bankflow_v2.ai_business_observation import (
    AI_INPUT_FIELDS,
    AI_TRACEABLE_STANDARD_TEXT_FIELDS,
    analyze_ai_semantic_fields,
    build_ai_business_observation,
    build_classification_constraints,
)
from bankflow_v2.models import Transaction


FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "ai_business_semantic_samples.json"
)


def context() -> dict[str, object]:
    return {
        "search_context": {
            "work_units": [],
            "declared_industries": ["环保工程"],
        }
    }


def config() -> dict[str, object]:
    return {
        "enabled": True,
        "data_authorized": True,
        "retention_policy_confirmed": True,
        "allow_business_names": True,
        "provider": "test",
        "model": "test",
        "api_key_available": True,
    }


def row(
    transaction_id: str,
    *,
    bank: str = "test",
    source_file_id: str = "source:test",
    **fields: str,
) -> Transaction:
    transaction = Transaction(
        datetime(2026, 1, 2),
        income=Decimal("100"),
        transaction_id=transaction_id,
        source_file_id=source_file_id,
        evidence_locator="page=1;row=2",
        bank=bank,
        **fields,
    )
    transaction.field_confidence.update(
        {field_name: 1.0 for field_name, value in fields.items() if value}
    )
    transaction.field_sources.update(
        {
            field_name: f"raw_headers[0]:{field_name}"
            for field_name, value in fields.items()
            if value
        }
    )
    return transaction


class AiSemanticPolicyTests(unittest.TestCase):
    def test_fixed_development_fixture_matches_deterministic_constraints(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        self.assertTrue(fixture["reserved_acceptance"])
        for sample in fixture["development"]:
            analysis = analyze_ai_semantic_fields(sample["fields"])
            constraints = build_classification_constraints(
                analysis["usable_fields"]
            )
            self.assertEqual(
                constraints["maximum_allowed_strength"],
                sample["expected_maximum_strength"],
                sample["id"],
            )
            self.assertEqual(
                constraints["directly_related_allowed"],
                sample["expected_direct_allowed"],
                sample["id"],
            )
            if "expected_life_category" in sample:
                self.assertEqual(
                    constraints["deterministic_non_business_category"],
                    sample["expected_life_category"],
                    sample["id"],
                )

    def test_same_semantics_across_supported_fields_have_same_constraint(self):
        for field_name in (
            "summary",
            "remark",
            "purpose",
            "product_description",
            "merchant_category",
        ):
            analysis = analyze_ai_semantic_fields(
                {field_name: "环境治理项目材料费"}
            )
            constraints = build_classification_constraints(
                analysis["usable_fields"]
            )
            self.assertEqual(
                constraints["maximum_allowed_strength"],
                "strong",
                field_name,
            )
            self.assertTrue(
                constraints["directly_related_allowed"],
                field_name,
            )

    def test_identifiers_never_create_business_semantics_in_any_model_field(self):
        values = (
            "1234567890",
            "M0EEHDNH",
            "订单号ABCD123456",
            "参考号REF998877",
            "a3f09e8d77c44bc1d109fb0a80ef9921",
        )
        for field_name in AI_INPUT_FIELDS:
            for value in values:
                analysis = analyze_ai_semantic_fields({field_name: value})
                self.assertEqual(
                    analysis["usable_fields"],
                    {},
                    (field_name, value),
                )

    def test_life_categories_are_deterministic_none_across_semantic_fields(self):
        values = (
            "示例餐厅",
            "示例医院",
            "手机话费充值",
            "示例便利店",
            "银行年费",
            "滴滴打车",
        )
        for field_name in AI_INPUT_FIELDS:
            for value in values:
                analysis = analyze_ai_semantic_fields({field_name: value})
                constraints = build_classification_constraints(
                    analysis["usable_fields"]
                )
                self.assertEqual(
                    constraints["maximum_allowed_strength"],
                    "none",
                    (field_name, value),
                )
                self.assertFalse(
                    constraints["directly_related_allowed"],
                    (field_name, value),
                )

    def test_business_name_only_is_never_direct(self):
        analysis = analyze_ai_semantic_fields(
            {"counterparty_name": "示例建材有限公司"}
        )
        constraints = build_classification_constraints(
            analysis["usable_fields"]
        )
        self.assertEqual(constraints["maximum_allowed_strength"], "medium")
        self.assertFalse(constraints["directly_related_allowed"])

    def test_conflicting_life_and_explicit_business_fields_are_not_silently_joined(self):
        analysis = analyze_ai_semantic_fields(
            {
                "merchant_name": "示例便利店",
                "purpose": "环保工程款",
            }
        )
        constraints = build_classification_constraints(
            analysis["usable_fields"]
        )
        self.assertEqual(
            constraints["deterministic_non_business_category"],
            "",
        )
        self.assertEqual(constraints["maximum_allowed_strength"], "strong")

    def test_source_and_bank_do_not_change_model_fields_or_constraints(self):
        rows = [
            row(
                "tx:personal",
                bank="bank_personal",
                source_file_id="source:personal",
                purpose="环境治理项目材料费",
            ),
            row(
                "tx:corp",
                bank="bank_corporate",
                source_file_id="source:corp",
                remark="环境治理项目材料费",
            ),
            row(
                "tx:wechat",
                bank="wechat",
                source_file_id="source:wechat",
                product_description="环境治理项目材料费",
            ),
        ]
        captured = {}

        def evaluator(payload):
            captured.update(payload)
            return [
                {
                    "transaction_id": item["transaction_id"],
                    "classification": "directly_related",
                    "evidence_strength": "strong",
                    "reason": "标准字段明确出现环保工程款",
                    "used_fields": list(item["fields"]),
                }
                for item in payload["transactions"]
            ]

        observation = build_ai_business_observation(
            rows,
            context(),
            config(),
            evaluator,
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(len(captured["transactions"]), 3)
        for item in captured["transactions"]:
            self.assertNotIn("bank", item)
            self.assertNotIn("source_file_id", item)
            self.assertEqual(
                item["classification_constraints"][
                    "maximum_allowed_strength"
                ],
                "strong",
            )

    def test_missing_standard_fields_do_not_fall_back_to_raw_text(self):
        transaction = row("tx:missing")
        transaction.raw_text = "原文中出现环保工程款"
        transaction.transaction_type = "转账"
        transaction.payment_method = "银行卡"
        transaction.field_confidence.update(
            {"transaction_type": 1.0, "payment_method": 1.0}
        )
        calls = []

        observation = build_ai_business_observation(
            [transaction],
            context(),
            config(),
            lambda payload: calls.append(payload),
        )

        self.assertEqual(
            observation["value"]["reason"],
            "ai_input_candidates_unavailable",
        )
        self.assertEqual(calls, [])
        self.assertIn("payment_method", AI_TRACEABLE_STANDARD_TEXT_FIELDS)
        self.assertNotIn("payment_method", AI_INPUT_FIELDS)

    def test_explicit_life_transaction_is_classified_locally_without_model(self):
        for field_name in (
            "merchant_name",
            "transaction_type",
            "payment_method",
        ):
            calls = []
            transaction = row(
                f"tx:life:{field_name}",
                **{field_name: "示例餐厅"},
            )

            observation = build_ai_business_observation(
                [transaction],
                context(),
                config(),
                lambda payload: calls.append(payload),
            )

            self.assertEqual(calls, [], field_name)
            self.assertEqual(
                observation["value"]["reason"],
                "ai_input_candidates_unavailable",
                field_name,
            )
            candidate = observation["value"][
                "deterministic_non_business_candidates"
            ][0]
            self.assertEqual(
                candidate["classification"],
                "no_relation_evidence",
                field_name,
            )
            self.assertEqual(candidate["evidence_strength"], "none")


if __name__ == "__main__":
    unittest.main()
