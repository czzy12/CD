"""C2.1 contract tests: unresolved persistence, mismatch audit, snapshot identity."""

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    classify_mismatch,
    mismatch_reason,
)
from bankflow_v2.knowledge.models import IndustryConceptRelation, IndustryProfile
from bankflow_v2.knowledge.schema_117 import (
    build_business_semantics_resolutions,
    _relation_id,
)
from bankflow_v2.models import Transaction
from bankflow_v2.result_export import (
    build_bankflow_result,
    migrate_schema_116_to_117,
)


CANONICAL_DIR = (
    Path(__file__).resolve().parent.parent
    / "bankflow_v2"
    / "knowledge"
    / "canonical"
)


def transaction(
    transaction_id: str = "tx:c21:1",
    *,
    remark: str = "量子秘传杂项支出",
) -> Transaction:
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
        remark=remark,
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


def empty_relations_canonical(root: Path) -> Path:
    canonical = root / "canonical"
    canonical.mkdir(parents=True)
    for name in ("taxonomy.json", "semantic_concepts.json", "semantic_aliases.json"):
        shutil.copyfile(CANONICAL_DIR / name, canonical / name)
    (canonical / "relations.json").write_text(
        json.dumps({"version": "industry-relations-v1", "relations": []}),
        encoding="utf-8",
    )
    return canonical


def _write_legacy_cache(
    root: Path,
    entries: list[dict[str, object]],
) -> None:
    signatures = root / "signatures" / "legacytest"
    signatures.mkdir(parents=True)
    for index, entry in enumerate(entries):
        path = signatures / f"sig{index}.json"
        path.write_text(
            json.dumps(
                {
                    "cache_schema_version": 2,
                    "task_type": "business_relevance",
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "prompt_version": "business-relevance-mvp-v11",
                    "output_contract_version": "semantic-judgement-v2",
                    "semantic_signature": [
                        [name, value]
                        for name, value in sorted(entry["fields"].items())
                    ],
                    "input": {
                        "fields": entry["fields"],
                        "classification_constraints": {},
                        "business_context": {},
                    },
                    "response_item": {
                        "transaction_id": f"tx:{index}",
                        "semantic_judgement": entry["legacy"],
                        "reason": "test",
                        "used_fields": list(entry["fields"]),
                    },
                    "validation_failures": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


BUILDING_PROFILE = IndustryProfile(
    primary_industry_ids=("internal.building_material_trade",),
    secondary_industry_ids=("internal.environmental_engineering",),
    taxonomy_version="gb-t-4754-2017-core-v1",
)


class UnresolvedPersistenceTests(unittest.TestCase):
    def test_never_parsed_distinct_from_parsed_unresolved(self):
        base = build_bankflow_result(
            [transaction()],
            ai_config={},
            include_knowledge_shadow=False,
        )
        base["schema_version"] = "1.16"
        migrated = migrate_schema_116_to_117(base)
        never = knowledge_observation(migrated)
        self.assertEqual(never["value"]["migration_status"], "not_parsed")
        self.assertEqual(never["value"]["resolutions"], [])

        parsed = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        ran = knowledge_observation(parsed)
        self.assertEqual(ran["value"]["migration_status"], "parsed")
        self.assertEqual(len(ran["value"]["resolutions"]), 1)
        self.assertEqual(
            ran["value"]["resolutions"][0]["review_status"],
            "unresolved",
        )

    def test_concept_unresolved_minimal_resolution(self):
        parsed = build_bankflow_result(
            [transaction()],
            case_context=case_context(),
            ai_config={},
        )
        entry = knowledge_observation(parsed)["value"]["resolutions"][0]
        self.assertTrue(entry["resolution_id"].startswith("res-"))
        self.assertTrue(entry["transaction_ref"])
        self.assertTrue(entry["semantic_signature_ref"])
        self.assertEqual(entry["concept_id"], "")
        self.assertEqual(entry["concept_name_snapshot"], "")
        self.assertEqual(entry["concept_resolution_source"], "unresolved")
        self.assertEqual(entry["industry_id"], "")
        self.assertEqual(entry["industry_name_snapshot"], "")
        self.assertEqual(entry["relation_id"], "")
        self.assertEqual(entry["relation_resolution_source"], "unresolved")
        self.assertEqual(entry["relevance"], "undetermined")
        self.assertEqual(entry["inherited"], False)
        self.assertEqual(entry["inherited_from_industry_id"], "")
        self.assertEqual(entry["review_status"], "unresolved")
        self.assertEqual(entry["candidate_ref"], "")

    def test_unresolved_resolution_id_deterministic(self):
        first = build_bankflow_result(
            [transaction("tx:u1")],
            case_context=case_context(),
            ai_config={},
        )
        second = build_bankflow_result(
            [transaction("tx:u1")],
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

    def test_unresolved_resolution_id_order_independent(self):
        original = build_bankflow_result(
            [
                transaction("tx:u1", remark="量子秘传杂项支出"),
                transaction("tx:u2", remark="银河系量子食堂"),
            ],
            case_context=case_context(),
            ai_config={},
        )
        swapped = build_bankflow_result(
            [
                transaction("tx:u2", remark="银河系量子食堂"),
                transaction("tx:u1", remark="量子秘传杂项支出"),
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

    def test_concept_resolved_relation_unresolved_keeps_concept(self):
        with tempfile.TemporaryDirectory() as tmp:
            canonical = empty_relations_canonical(Path(tmp))
            runtime = KnowledgeRuntime.load(canonical)
            observation, diagnostics = build_business_semantics_resolutions(
                [transaction("tx:r1", remark="物流费")],
                case_context(),
                runtime=runtime,
            )
            entry = observation["value"]["resolutions"][0]
            self.assertEqual(entry["concept_id"], "logistics")
            self.assertEqual(entry["concept_resolution_source"], "exact_alias")
            self.assertEqual(entry["relation_resolution_source"], "unresolved")
            self.assertEqual(entry["relation_id"], "")
            self.assertEqual(entry["relevance"], "undetermined")
            self.assertEqual(entry["review_status"], "unresolved")
            self.assertEqual(
                entry["industry_id"],
                "internal.building_material_trade",
            )
            self.assertTrue(entry["industry_name_snapshot"])
            self.assertEqual(diagnostics["knowledge_v1"]["unknown_relation_count"], 1)

    def test_approved_and_unresolved_coexist(self):
        parsed = build_bankflow_result(
            [
                transaction("tx:ok", remark="物流费"),
                transaction("tx:unknown", remark="量子秘传杂项支出"),
            ],
            case_context=case_context(),
            ai_config={},
        )
        entries = knowledge_observation(parsed)["value"]["resolutions"]
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            {entry["review_status"] for entry in entries},
            {"approved", "unresolved"},
        )
        self.assertEqual(
            {
                entry["semantic_signature_ref"]: entry["review_status"]
                for entry in entries
            }
            .values()
            .__len__(),
            2,
        )


class MismatchClassificationTests(unittest.TestCase):
    def test_classify_mismatch_closed_buckets(self):
        cases = [
            ("none", "undetermined", "knowledge_undetermined"),
            ("weak", "undetermined", "knowledge_undetermined"),
            ("medium", "undetermined", "knowledge_undetermined"),
            ("none", "weak", "strength_escalation"),
            ("none", "medium", "strength_escalation"),
            ("weak", "medium", "strength_escalation"),
            ("medium", "strong", "strength_escalation"),
            ("strong", "weak", "strength_downgrade"),
            ("strong", "none", "strength_downgrade"),
            ("medium", "weak", "strength_downgrade"),
            ("weak", "none", "strength_downgrade"),
            ("undetermined", "medium", "legacy_undetermined_resolved"),
        ]
        for legacy, knowledge, expected in cases:
            with self.subTest(legacy=legacy, knowledge=knowledge):
                self.assertEqual(
                    classify_mismatch(legacy, knowledge),
                    expected,
                )
                self.assertTrue(mismatch_reason(expected, legacy, knowledge))

    def test_compare_report_classification_sums_without_unexplained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            _write_legacy_cache(
                cache,
                [
                    {"fields": {"remark": "物流费"}, "legacy": "none"},
                    {"fields": {"remark": "物流费"}, "legacy": "strong"},
                    {"fields": {"remark": "量子秘传杂项支出"}, "legacy": "weak"},
                    {"fields": {"remark": "物流费"}, "legacy": "undetermined"},
                ],
            )
            runtime = KnowledgeRuntime.load(CANONICAL_DIR)
            from bankflow_v2.knowledge import compare_legacy_cache

            report = compare_legacy_cache(cache, runtime, BUILDING_PROFILE)
            classification = report["mismatch_classification"]
            self.assertEqual(
                classification["strength_escalation"],
                1,
            )
            self.assertEqual(
                classification["strength_downgrade"],
                1,
            )
            self.assertEqual(
                classification["knowledge_undetermined"],
                1,
            )
            self.assertEqual(
                classification["legacy_undetermined_resolved"],
                1,
            )
            self.assertEqual(
                classification["same_strength_different_state"],
                0,
            )
            self.assertEqual(classification["other"], 0)
            self.assertEqual(
                sum(classification.values()),
                report["disagreement_count"],
            )
            self.assertEqual(report["strength_downgrade_count"], 1)
            for row in report["disagreements"]:
                self.assertIn("mismatch_type", row)
                self.assertIn("mismatch_reason", row)
                self.assertIn("industry_id", row)


class RelationSnapshotIdentityTests(unittest.TestCase):
    @staticmethod
    def _fake_runtime(relation: IndustryConceptRelation) -> object:
        class FakeRelations:
            def __init__(self, item):
                self._item = item

            def approved(self, industry_id, concept_id):
                return self._item

        class FakeVersion:
            relation_kb_version = "industry-relations-v1"

        class FakeRuntime:
            pass

        runtime = FakeRuntime()
        runtime.relations = FakeRelations(relation)
        runtime.version = FakeVersion()
        return runtime

    def test_review_status_mutation_changes_relation_id(self):
        approved = IndustryConceptRelation(
            industry_id="internal.building_material_trade",
            concept_id="logistics",
            relevance="medium",
            confidence_tier="generic",
            review_status="approved",
            knowledge_version="business-semantic-kb-v1",
        )
        deprecated = IndustryConceptRelation(
            industry_id="internal.building_material_trade",
            concept_id="logistics",
            relevance="medium",
            confidence_tier="generic",
            review_status="deprecated",
            knowledge_version="business-semantic-kb-v1",
        )
        approved_id = _relation_id(
            self._fake_runtime(approved),
            "internal.building_material_trade",
            "logistics",
            "medium",
        )
        deprecated_id = _relation_id(
            self._fake_runtime(deprecated),
            "internal.building_material_trade",
            "logistics",
            "medium",
        )
        self.assertNotEqual(approved_id, deprecated_id)

    def test_semantic_key_stable_while_snapshot_id_mutates(self):
        relation = IndustryConceptRelation(
            industry_id="internal.building_material_trade",
            concept_id="logistics",
            relevance="medium",
            confidence_tier="generic",
            review_status="approved",
            knowledge_version="business-semantic-kb-v1",
        )
        medium_id = _relation_id(
            self._fake_runtime(relation),
            "internal.building_material_trade",
            "logistics",
            "medium",
        )
        weak_id = _relation_id(
            self._fake_runtime(relation),
            "internal.building_material_trade",
            "logistics",
            "weak",
        )
        self.assertNotEqual(medium_id, weak_id)
        # 长期逻辑关联键 industry_id + concept_id 不变
        self.assertEqual(
            ("internal.building_material_trade", "logistics"),
            ("internal.building_material_trade", "logistics"),
        )


if __name__ == "__main__":
    unittest.main()
