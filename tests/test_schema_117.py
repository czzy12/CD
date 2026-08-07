import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from bankflow_web.contracts import AppStateDTO
from bankflow_v2.models import Transaction
from bankflow_v2.result_export import (
    SCHEMA_VERSION,
    build_bankflow_result,
    migrate_schema_116_to_117,
)
from bankflow_v2.standard_result_view import (
    StandardResultError,
    load_standard_result,
    validate_standard_result,
)


def transaction() -> Transaction:
    return Transaction(
        transaction_time=datetime(2026, 1, 2, 9, 30),
        income=Decimal("1234.00"),
        balance=Decimal("2234.00"),
        source_file="sample.pdf",
        source_file_id="sha256:sample",
        transaction_id="tx:schema:1",
        page_no=2,
        row_no=3,
        evidence_locator="page=2;row=3",
        counterparty_name="测试公司",
        remark="物流费",
        field_confidence={"counterparty_name": 1.0, "remark": 1.0},
    )


class Schema117ContractTests(unittest.TestCase):
    def test_build_emits_schema_117_with_shadow_observation(self):
        result = build_bankflow_result(
            [transaction()],
            case_context={
                "business_context": {
                    "confirmed_primary_business": "建筑材料批发",
                    "confirmation_status": "confirmed",
                }
            },
            ai_config={},
        )
        self.assertEqual(result["schema_version"], "1.17")
        observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "business_semantics_resolutions"
        )
        self.assertTrue(observation["parameters"]["shadow"])
        self.assertEqual(
            observation["parameters"]["production_resolver"],
            "legacy_v11",
        )
        self.assertGreater(len(observation["value"]["resolutions"]), 0)
        self.assertEqual(
            result["diagnostics"]["knowledge_v1"]["migration_status"],
            "parsed",
        )

    def test_resolutions_carry_knowledge_fields_without_legacy_pollution(self):
        result = build_bankflow_result(
            [transaction()],
            case_context={
                "business_context": {
                    "confirmed_primary_business": "建筑材料批发",
                    "confirmation_status": "confirmed",
                }
            },
            ai_config={},
        )
        observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "business_semantics_resolutions"
        )
        entry = observation["value"]["resolutions"][0]
        for field in (
            "resolution_id",
            "transaction_ref",
            "semantic_signature_ref",
            "concept_id",
            "concept_name_snapshot",
            "concept_resolution_source",
            "industry_id",
            "industry_name_snapshot",
            "relation_id",
            "relation_resolution_source",
            "relevance",
            "inherited",
            "inherited_from_industry_id",
            "review_status",
        ):
            self.assertIn(field, entry)
        self.assertNotIn("legacy_relevance", entry)
        self.assertEqual(entry["concept_id"], "logistics")
        self.assertEqual(entry["relevance"], "medium")

    def test_legacy_comparison_lives_in_diagnostics_only(self):
        result = build_bankflow_result(
            [transaction()],
            case_context={
                "business_context": {
                    "confirmed_primary_business": "建筑材料批发",
                    "confirmation_status": "confirmed",
                }
            },
            ai_config={},
        )
        comparison = result["diagnostics"]["knowledge_v1"][
            "legacy_comparison"
        ]
        self.assertIn("tx:schema:1", comparison)
        observation = next(
            item
            for item in result["result"]["observations"]
            if item["observation_type"] == "business_semantics_resolutions"
        )
        self.assertNotIn("legacy_comparison", observation)

    def test_build_without_knowledge_shadow_omits_observation(self):
        result = build_bankflow_result(
            [transaction()],
            ai_config={},
            include_knowledge_shadow=False,
        )
        self.assertEqual(result["schema_version"], "1.17")
        self.assertNotIn(
            "business_semantics_resolutions",
            [
                item.get("observation_type", "")
                for item in result["result"]["observations"]
            ],
        )
        self.assertNotIn("diagnostics", result)

    def test_schema_116_file_still_accepted(self):
        result = build_bankflow_result([transaction()], ai_config={})
        result["schema_version"] = "1.16"
        result.pop("diagnostics", None)
        validated = validate_standard_result(result)
        self.assertEqual(validated["schema_version"], "1.16")

    def test_schema_117_accepted_and_115_rejected(self):
        result = build_bankflow_result([transaction()], ai_config={})
        self.assertEqual(validate_standard_result(result)["schema_version"], "1.17")
        result["schema_version"] = "1.15"
        with self.assertRaises(StandardResultError) as raised:
            validate_standard_result(result)
        self.assertEqual(raised.exception.code, "unsupported_schema_version")

    def test_migration_does_not_fabricate_history(self):
        result = build_bankflow_result(
            [transaction()],
            ai_config={},
            include_knowledge_shadow=False,
        )
        result["schema_version"] = "1.16"
        migrated = migrate_schema_116_to_117(result)
        self.assertEqual(migrated["schema_version"], "1.17")
        observation = next(
            item
            for item in migrated["result"]["observations"]
            if item["observation_type"] == "business_semantics_resolutions"
        )
        self.assertEqual(observation["value"]["resolutions"], [])
        self.assertEqual(
            migrated["diagnostics"]["knowledge_v1"]["migration_status"],
            "not_parsed",
        )
        self.assertEqual(
            migrated["diagnostics"]["knowledge_v1"]["legacy_comparison"],
            {},
        )

    def test_migration_is_idempotent(self):
        result = build_bankflow_result([transaction()], ai_config={})
        again = migrate_schema_116_to_117(result)
        self.assertEqual(again, result)

    def test_migration_rejects_unknown_version(self):
        with self.assertRaises(ValueError):
            migrate_schema_116_to_117({"schema_version": "1.15"})

    def test_schema_versions_supported_includes_both(self):
        state = AppStateDTO(frontend_ready=True, case_loaded=False, loading=False)
        self.assertEqual(state.schema_versions_supported, ["1.16", "1.17"])

    def test_saved_117_result_loads(self):
        result = build_bankflow_result([transaction()], ai_config={})
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "result.json"
            path.write_text(
                json.dumps(result, ensure_ascii=False),
                encoding="utf-8",
            )
            loaded = load_standard_result(path)
        self.assertEqual(loaded["schema_version"], "1.17")


if __name__ == "__main__":
    unittest.main()
