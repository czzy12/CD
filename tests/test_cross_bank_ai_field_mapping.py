import unittest
from datetime import datetime
from decimal import Decimal

from bankflow_v2.ai_business_observation import build_ai_business_observation
from bankflow_v2.models import Transaction


def transaction(
    transaction_id: str,
    source_file_id: str,
    headers: list[str],
    fields: list[str],
) -> Transaction:
    return Transaction(
        datetime(2026, 1, 2),
        income=Decimal("1000"),
        transaction_id=transaction_id,
        source_file_id=source_file_id,
        evidence_locator="page=1;row=2",
        raw_headers=headers,
        raw_fields=fields,
    )


def case_context() -> dict[str, object]:
    return {
        "search_context": {
            "work_units": [],
            "declared_industries": ["环保工程"],
        }
    }


def ai_config() -> dict[str, object]:
    return {
        "enabled": True,
        "data_authorized": True,
        "retention_policy_confirmed": True,
        "allow_business_names": True,
        "provider": "test-provider",
        "model": "test-model",
        "api_key_available": True,
    }


class CrossBankAiFieldMappingTests(unittest.TestCase):
    def test_different_bank_headers_map_to_the_same_standard_fields(self):
        first = transaction(
            "tx:first",
            "source:first",
            ["对方账户名称", "交易摘要", "附言", "交易用途"],
            ["宜城市杭艺建材厂", "转账", "项目材料", "材料采购"],
        )
        second = transaction(
            "tx:second",
            "source:second",
            ["交易对方", "摘要描述", "备注", "用途"],
            ["宜城市杭艺建材厂", "转账", "项目材料", "材料采购"],
        )

        for row in (first, second):
            self.assertEqual(row.counterparty_name, "宜城市杭艺建材厂")
            self.assertEqual(row.summary, "转账")
            self.assertEqual(row.remark, "项目材料")
            self.assertEqual(row.purpose, "材料采购")
            self.assertEqual(row.field_confidence["counterparty_name"], 1.0)
            self.assertEqual(row.field_confidence["summary"], 1.0)
            self.assertEqual(row.field_confidence["remark"], 1.0)
            self.assertEqual(row.field_confidence["purpose"], 1.0)

    def test_ai_receives_only_standard_semantic_field_names(self):
        rows = [
            transaction(
                "tx:first",
                "source:first",
                ["对方账户名称", "交易摘要", "附言", "交易用途"],
                ["宜城市杭艺建材厂", "转账", "项目材料", "材料采购"],
            ),
            transaction(
                "tx:second",
                "source:second",
                ["交易对方", "摘要描述", "备注", "用途"],
                ["宜城市杭艺建材厂", "转账", "项目材料", "材料采购"],
            ),
        ]
        captured = {}

        def evaluator(payload):
            captured.update(payload)
            return [
                {
                    "transaction_id": row.transaction_id,
                    "semantic_judgement": "medium",
                    "reason": "建材和材料采购属于具体产品或用途候选",
                    "used_fields": [
                        "counterparty_name",
                        "remark",
                        "purpose",
                    ],
                }
                for row in rows
            ]

        observation = build_ai_business_observation(
            rows,
            case_context(),
            ai_config(),
            evaluator,
        )

        self.assertTrue(observation["value"]["available"])
        self.assertEqual(len(captured["transactions"]), 2)
        for record in captured["transactions"]:
            self.assertEqual(
                record["fields"],
                {
                    "counterparty_name": "宜城市杭艺建材厂",
                    "remark": "项目材料",
                    "purpose": "材料采购",
                },
            )
            self.assertNotIn("交易对方", record)
            self.assertNotIn("对方账户名称", record)
            self.assertNotIn("summary", record["fields"])

    def test_unknown_mixed_headers_remain_unavailable(self):
        row = transaction(
            "tx:mixed",
            "source:mixed",
            ["对手信息", "摘要/备注"],
            ["62220001/宜城市杭艺建材厂", "材料采购/转账"],
        )
        calls = []

        observation = build_ai_business_observation(
            [row],
            case_context(),
            ai_config(),
            lambda payload: calls.append(payload),
        )

        self.assertEqual(row.counterparty_name, "")
        self.assertEqual(row.summary, "")
        self.assertEqual(row.remark, "")
        self.assertEqual(
            observation["value"]["reason"],
            "ai_input_candidates_unavailable",
        )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
