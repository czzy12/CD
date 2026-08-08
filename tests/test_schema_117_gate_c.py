import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from bankflow_v2.knowledge import versioning
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.resolver import KnowledgeRuntime
from bankflow_v2.knowledge.schema_117 import (
    _relation_id,
    build_business_semantics_resolutions,
)
from bankflow_v2.models import Transaction
from bankflow_v2.result_export import (
    build_bankflow_result,
    migrate_schema_116_to_117,
)
from bankflow_v2.standard_result_view import (
    validate_standard_result,
)


def transaction(transaction_id: str = "tx:schema:1") -> Transaction:
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
        remark="物流费",
        field_confidence={"counterparty_name": 1.0, "remark": 1.0},
    )


def case_context() -> dict[str, object]:
    return {
        "business_context": {
            "confirmed_primary_business": "建筑材料批发",
            "confirmation_status": "confirmed",
        }
    }


def knowledge_observation(result: dict[str, object]) -> dict[str, object]:
    return next(
        item
        for item in result["result"]["observations"]
        if item["observation_type"] == "business_semantics_resolutions"
    )


class Schema117FoundationRetentionTests(unittest.TestCase):
    def test_source_diagnostics_retained_in_117(self):
        result = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
            source_diagnostics=[
                {
                    "source_file": "sample.pdf",
                    "status": "included",
                    "source_row_count": 10,
                    "parsed_transaction_count": 9,
                    "skipped_row_count": 1,
                    "unparsed_row_count": 1,
                    "ignored_non_transaction_row_count": 2,
                    "metadata_owner_available": True,
                    "metadata_account_available": False,
                    "metadata_period_available": False,
                }
            ],
        )
        record = result["source_files"][0]
        self.assertEqual(record["source_row_count"], 10)
        self.assertEqual(record["metadata_owner_available"], True)
        self.assertEqual(result["schema_version"], "1.17")

    def test_metadata_availability_retained_in_117(self):
        result = build_bankflow_result([transaction()], ai_config={})
        metadata = result["statement_metadata"]
        self.assertIn("account_name_available", metadata)
        self.assertIn("account_number_available", metadata)
        self.assertIn("statement_period_available", metadata)

    def test_raw_evidence_refs_retained_in_117(self):
        result = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        record = result["result"]["original_transactions"][0]
        self.assertEqual(record["transaction_id"], "tx:schema:1")
        self.assertEqual(record["source_file_id"], "sha256:sample")
        self.assertEqual(record["evidence_locator"], "page=2;row=3")
        self.assertIn("raw_fields", record["original"])
        self.assertIn("field_sources", record["standard_fields"])

    def test_transaction_ids_unchanged_between_116_and_117(self):
        base = build_bankflow_result([transaction()], ai_config={})
        base_ids = [
            item["transaction_id"]
            for item in base["result"]["original_transactions"]
        ]
        shadow = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        shadow_ids = [
            item["transaction_id"]
            for item in shadow["result"]["original_transactions"]
        ]
        self.assertEqual(base_ids, shadow_ids)

    def test_legacy_production_observation_unchanged_by_shadow(self):
        plain = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
            include_knowledge_shadow=False,
        )
        shadow = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        plain_legacy = next(
            item
            for item in plain["result"]["observations"]
            if item["observation_type"] == "ai_business_relevance_candidates"
        )
        shadow_legacy = next(
            item
            for item in shadow["result"]["observations"]
            if item["observation_type"] == "ai_business_relevance_candidates"
        )

        def _strip_created_at(node):
            if isinstance(node, dict):
                for key in ("created_at", "run_at"):
                    node.pop(key, None)
                for value in node.values():
                    _strip_created_at(value)
            elif isinstance(node, list):
                for value in node:
                    _strip_created_at(value)

        for item in (plain_legacy, shadow_legacy):
            _strip_created_at(item)
        self.assertEqual(plain_legacy, shadow_legacy)
        self.assertEqual(
            plain["result"]["summary"],
            shadow["result"]["summary"],
        )

    def test_unknown_observation_tolerated_by_reader(self):
        result = build_bankflow_result([transaction()], ai_config={})
        result["result"]["observations"].append(
            {"observation_type": "future_unknown_observation", "value": {}}
        )
        validated = validate_standard_result(result)
        self.assertEqual(validated["schema_version"], "1.17")


class Schema117DeterministicIdTests(unittest.TestCase):
    def test_resolution_id_stable_for_same_input(self):
        first = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        second = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        first_id = knowledge_observation(first)["value"]["resolutions"][0][
            "resolution_id"
        ]
        second_id = knowledge_observation(second)["value"]["resolutions"][0][
            "resolution_id"
        ]
        self.assertEqual(first_id, second_id)
        self.assertTrue(first_id.startswith("res-"))

    def test_resolution_id_order_independent(self):
        swapped = build_bankflow_result(
            [
                transaction("tx:second"),
                transaction("tx:first"),
            ],
            case_context=case_context(),
            ai_config={},
        )
        original = build_bankflow_result(
            [
                transaction("tx:first"),
                transaction("tx:second"),
            ],
            case_context=case_context(),
            ai_config={},
        )
        original_ids = {
            entry["semantic_signature_ref"]: entry["resolution_id"]
            for entry in knowledge_observation(original)["value"]["resolutions"]
        }
        swapped_ids = {
            entry["semantic_signature_ref"]: entry["resolution_id"]
            for entry in knowledge_observation(swapped)["value"]["resolutions"]
        }
        self.assertEqual(original_ids, swapped_ids)

    def test_relation_id_changes_when_relevance_changes(self):
        runtime = KnowledgeRuntime.load(
            Path(__file__).resolve().parents[1]
            / "bankflow_v2"
            / "knowledge"
            / "canonical"
        )
        medium = _relation_id(
            runtime,
            "internal.building_material_trade",
            "logistics",
            "medium",
        )
        weak = _relation_id(
            runtime,
            "internal.building_material_trade",
            "logistics",
            "weak",
        )
        self.assertNotEqual(medium, weak)

    def test_relation_payload_excludes_non_semantic_metadata(self):
        runtime = KnowledgeRuntime.load(
            Path(__file__).resolve().parents[1]
            / "bankflow_v2"
            / "knowledge"
            / "canonical"
        )
        from bankflow_v2.knowledge.schema_117 import _relation_payload

        payload = _relation_payload(
            runtime,
            "internal.building_material_trade",
            "logistics",
            "medium",
        )
        for field in ("created_by", "reviewed_at", "reason_template"):
            self.assertNotIn(field, payload)
        self.assertEqual(payload["relevance"], "medium")


class Schema117WriterContractTests(unittest.TestCase):
    def test_migration_status_in_value(self):
        result = build_bankflow_result(
            [transaction()],
            ai_config={},
            include_knowledge_shadow=False,
        )
        result["schema_version"] = "1.16"
        empty = migrate_schema_116_to_117(result)
        observation = knowledge_observation(empty)
        self.assertEqual(observation["value"]["migration_status"], "not_parsed")

        parsed = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        self.assertEqual(
            knowledge_observation(parsed)["value"]["migration_status"],
            "parsed",
        )

    def test_resolution_carries_candidate_ref_and_review_status(self):
        result = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        entry = knowledge_observation(result)["value"]["resolutions"][0]
        self.assertEqual(entry["review_status"], "approved")
        self.assertEqual(entry["candidate_ref"], "")

    def test_resolver_sources_are_written_directly(self):
        result = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        entry = knowledge_observation(result)["value"]["resolutions"][0]
        self.assertEqual(entry["concept_resolution_source"], "exact_alias")
        self.assertIn(
            entry["relation_resolution_source"],
            {
                "exact_relation",
                "specialty_relation",
                "inherited_relation",
                "generic_business_relation",
                "relation_cache",
                "ai_candidate",
                "unresolved",
            },
        )

    def test_per_entry_profiles_split_buckets(self):
        building = IndustryProfile(
            primary_industry_ids=("internal.building_material_trade",),
            taxonomy_version=versioning.TAXONOMY_VERSION,
            profile_name="building_material",
        )
        alcohol = IndustryProfile(
            primary_industry_ids=("internal.alcohol_tobacco_retail",),
            taxonomy_version=versioning.TAXONOMY_VERSION,
            profile_name="alcohol_retail",
        )
        observation, _ = build_business_semantics_resolutions(
            [transaction("tx:1"), transaction("tx:2")],
            case_context(),
            per_entry_profiles={"tx:1": building, "tx:2": alcohol},
        )
        self.assertEqual(len(observation["value"]["resolutions"]), 2)
        industry_ids = {
            entry["industry_id"]
            for entry in observation["value"]["resolutions"]
        }
        self.assertEqual(
            industry_ids,
            {
                "internal.building_material_trade",
                "internal.alcohol_tobacco_retail",
            },
        )

    def test_migration_observation_has_value_migration_status(self):
        result = build_bankflow_result(
            [transaction()],
            ai_config={},
            include_knowledge_shadow=False,
        )
        result["schema_version"] = "1.16"
        migrated = migrate_schema_116_to_117(result)
        value = knowledge_observation(migrated)["value"]
        self.assertIn("migration_status", value)
        self.assertEqual(value["migration_status"], "not_parsed")


if __name__ == "__main__":
    unittest.main()
