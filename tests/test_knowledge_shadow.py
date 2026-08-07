import json
import tempfile
import unittest
from pathlib import Path

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    compare_legacy_cache,
    load_legacy_signature_entries,
    render_shadow_markdown,
)
from bankflow_v2.knowledge.models import IndustryProfile


CANONICAL_DIR = (
    Path(__file__).resolve().parent.parent
    / "bankflow_v2"
    / "knowledge"
    / "canonical"
)


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


PROFILE = IndustryProfile(
    primary_industry_ids=("internal.building_material_trade",),
    secondary_industry_ids=("internal.environmental_engineering",),
    taxonomy_version="gb-t-4754-2017-core-v1",
)


class KnowledgeShadowTests(unittest.TestCase):
    def test_load_legacy_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cache"
            _write_legacy_cache(root, [{"fields": {"remark": "物流费"}, "legacy": "medium"}])
            entries = load_legacy_signature_entries(root)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["legacy_semantic_judgement"], "medium")
            self.assertEqual(entries[0]["fields"], {"remark": "物流费"})

    def test_shadow_comparison_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            _write_legacy_cache(
                cache,
                [
                    {"fields": {"remark": "物流费"}, "legacy": "medium"},
                    {"fields": {"remark": "货款"}, "legacy": "weak"},
                    {"fields": {"purpose": "环保工程款"}, "legacy": "strong"},
                    {"fields": {"merchant_name": "示例餐厅"}, "legacy": "none"},
                    {"fields": {"remark": "技术咨询费"}, "legacy": "weak"},
                    {"fields": {"remark": "银河系量子食堂"}, "legacy": "none"},
                ],
            )
            runtime = KnowledgeRuntime.load(CANONICAL_DIR)
            report = compare_legacy_cache(cache, runtime, PROFILE)
            self.assertEqual(report["total_entries"], 6)
            self.assertGreaterEqual(report["agreement_count"], 5)
            self.assertEqual(report["new_undetermined_count"], 1)
            self.assertEqual(report["strength_escalation_count"], 0)
            self.assertEqual(report["life_positive_count"], 0)
            self.assertEqual(report["usage_stats"]["semantic_requests"], 6)
            self.assertNotIn("示例餐厅", json.dumps(report, ensure_ascii=False))

    def test_strength_escalation_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            _write_legacy_cache(
                cache,
                [{"fields": {"remark": "物流费"}, "legacy": "none"}],
            )
            runtime = KnowledgeRuntime.load(CANONICAL_DIR)
            report = compare_legacy_cache(cache, runtime, PROFILE)
            self.assertEqual(report["strength_escalation_count"], 1)
            self.assertEqual(
                report["violations"][0]["violation"],
                "strength_escalation_vs_legacy",
            )

    def test_life_positive_stays_blocked_by_hard_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            canonical = root / "canonical"
            canonical.mkdir()
            for name in (
                "taxonomy.json",
                "semantic_concepts.json",
                "semantic_aliases.json",
            ):
                (canonical / name).write_text(
                    (CANONICAL_DIR / name).read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
            relations = json.loads(
                (CANONICAL_DIR / "relations.json").read_text(encoding="utf-8")
            )
            relations["relations"].append(
                {
                    "industry_id": "internal.building_material_trade",
                    "concept_id": "dining",
                    "relevance": "strong",
                    "reason_template": "test",
                    "source": "test",
                    "review_status": "approved",
                    "confidence_tier": "test",
                    "knowledge_version": "business-semantic-kb-v1",
                    "created_by": "test",
                    "reviewed_at": "2026-08-07T00:00:00+08:00",
                }
            )
            (canonical / "relations.json").write_text(
                json.dumps(relations, ensure_ascii=False),
                encoding="utf-8",
            )
            cache = root / "cache"
            _write_legacy_cache(
                cache,
                [{"fields": {"merchant_name": "示例餐厅"}, "legacy": "none"}],
            )
            runtime = KnowledgeRuntime.load(canonical)
            report = compare_legacy_cache(cache, runtime, PROFILE)
            self.assertEqual(report["life_positive_count"], 0)

    def test_shadow_markdown_renders(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "cache"
            _write_legacy_cache(
                cache,
                [{"fields": {"remark": "物流费"}, "legacy": "medium"}],
            )
            runtime = KnowledgeRuntime.load(CANONICAL_DIR)
            report = compare_legacy_cache(cache, runtime, PROFILE)
            markdown = render_shadow_markdown(report)
            self.assertIn("legacy_v11 vs knowledge_v1", markdown)
            self.assertIn("AI 使用统计", markdown)


if __name__ == "__main__":
    unittest.main()
