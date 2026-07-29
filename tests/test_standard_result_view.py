from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from bankflow_v2.models import Transaction
from bankflow_v2.result_export import build_bankflow_result
from bankflow_v2.standard_result_view import (
    StandardResultError,
    evidence_transaction,
    load_standard_result,
    mask_account,
    redact_sensitive_text,
    result_summary,
    short_transaction_id,
    validate_standard_result,
)


def transaction(transaction_id: str = "tx:gui:1") -> Transaction:
    return Transaction(
        transaction_time=datetime(2026, 1, 2, 9, 30),
        income=Decimal("1234.00"),
        balance=Decimal("2234.00"),
        source_file="sample.pdf",
        source_file_id="sha256:sample",
        transaction_id=transaction_id,
        page_no=2,
        row_no=3,
        evidence_locator="page=2;row=3",
        counterparty_name="测试公司",
        field_confidence={"counterparty_name": 1.0},
    )


class StandardResultViewTests(unittest.TestCase):
    def test_validates_and_summarizes_schema_116(self):
        result = build_bankflow_result([transaction()], ai_config={})

        validated = validate_standard_result(result)
        summary = result_summary(validated, "测试案例")

        self.assertEqual(summary["case_name"], "测试案例")
        self.assertEqual(summary["schema_version"], "1.16")
        self.assertEqual(summary["source_count"], 1)
        self.assertEqual(summary["transaction_count"], 1)
        self.assertTrue(summary["evidence_complete"])

    def test_gui_transaction_count_includes_neutral_original_rows(self):
        counted = transaction("tx:gui:counted")
        neutral = transaction("tx:gui:neutral")
        neutral.neutral = True
        result = build_bankflow_result([counted, neutral], ai_config={})

        summary = result_summary(result, "测试案例")

        self.assertEqual(result["result"]["summary"]["count"], 1)
        self.assertEqual(summary["transaction_count"], 2)

    def test_rejects_incompatible_schema(self):
        result = build_bankflow_result([transaction()], ai_config={})
        result["schema_version"] = "1.15"

        with self.assertRaises(StandardResultError) as raised:
            validate_standard_result(result)

        self.assertEqual(raised.exception.code, "unsupported_schema_version")

    def test_loads_saved_standard_result(self):
        result = build_bankflow_result([transaction()], ai_config={})
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "result.json"
            path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

            loaded = load_standard_result(path)

        self.assertEqual(loaded["schema_version"], "1.16")

    def test_evidence_lookup_uses_index_and_checks_transaction_id(self):
        result = build_bankflow_result([transaction()], ai_config={})

        resolved = evidence_transaction(result, "tx:gui:1")

        self.assertEqual(resolved["entry"]["original_transaction_index"], 0)
        self.assertEqual(resolved["transaction"]["source_file"], "sample.pdf")
        self.assertEqual(resolved["transaction"]["page_no"], 2)
        self.assertTrue(resolved["integrity"]["complete"])

    def test_evidence_lookup_fails_closed_for_unindexed_id(self):
        result = build_bankflow_result([transaction()], ai_config={})

        with self.assertRaises(StandardResultError) as raised:
            evidence_transaction(result, "tx:missing")

        self.assertEqual(raised.exception.code, "transaction_id_not_indexed")

    def test_masks_sensitive_values_without_removing_business_text(self):
        self.assertEqual(mask_account("6222021234567890"), "•••• 7890")
        self.assertEqual(
            redact_sensitive_text("甲公司 13812345678 材料款"),
            "甲公司 138****5678 材料款",
        )
        self.assertEqual(short_transaction_id("tx:" + "a" * 40), "tx:aaaaaaa…aaaaaa")


if __name__ == "__main__":
    unittest.main()
