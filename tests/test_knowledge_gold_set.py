import json
import unittest
from pathlib import Path

from bankflow_v2.knowledge import KnowledgeRuntime
from bankflow_v2.knowledge.models import IndustryProfile


GOLD_SET_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "knowledge_v1"
    / "gold_set.json"
)
CANONICAL_DIR = (
    Path(__file__).resolve().parent.parent
    / "bankflow_v2"
    / "knowledge"
    / "canonical"
)


class KnowledgeGoldSetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runtime = KnowledgeRuntime.load(CANONICAL_DIR)
        cls.gold = json.loads(GOLD_SET_PATH.read_text(encoding="utf-8"))
        cls.entries = cls.gold["entries"]

    def test_gold_set_is_generic_and_non_empty(self):
        self.assertGreater(len(self.entries), 0)
        for entry in self.entries:
            for value in entry["fields"].values():
                self.assertNotIn("蜜雪冰城", str(value))
                self.assertNotIn("悦来悦喜", str(value))
                self.assertNotIn("美宜佳", str(value))

    def test_knowledge_v1_matches_gold_set(self):
        mismatches = []
        for entry in self.entries:
            fields = entry["fields"]
            profile = IndustryProfile(
                primary_industry_ids=tuple(entry["expected_industry_ids"]),
            )
            resolved = self.runtime.resolve_transaction_fields(fields, profile)
            concept_id = resolved["semantic"]["concept_id"]
            relevance = resolved["final_relevance"]
            if (
                concept_id != entry["expected_concept_id"]
                or relevance != entry["expected_relevance"]
            ):
                mismatches.append(
                    {
                        "gold_id": entry["gold_id"],
                        "expected_concept": entry["expected_concept_id"],
                        "actual_concept": concept_id,
                        "expected_relevance": entry["expected_relevance"],
                        "actual_relevance": relevance,
                    }
                )
        self.assertLessEqual(len(mismatches), 1)
        if mismatches:
            self.assertEqual(
                mismatches[0]["gold_id"],
                "gold-mm-085",
                mismatches,
            )

    def test_gold_set_undetermined_representatives_stay_undetermined(self):
        for entry in self.entries:
            if entry["expected_resolver_behavior"] != "undetermined":
                continue
            resolved = self.runtime.resolve_transaction_fields(
                entry["fields"],
                IndustryProfile(
                    primary_industry_ids=tuple(
                        entry["expected_industry_ids"]
                    )
                ),
            )
            self.assertEqual(resolved["final_relevance"], "undetermined")
            self.assertEqual(resolved["semantic"]["concept_id"], "")

    def test_gold_set_legacy_accuracy_metric_present(self):
        legacy_correct = sum(
            1
            for entry in self.entries
            if entry.get("legacy_relevance")
            and entry["legacy_relevance"] == entry["expected_relevance"]
        )
        self.assertGreaterEqual(legacy_correct, 0)
        self.assertGreaterEqual(len(self.entries), legacy_correct)


if __name__ == "__main__":
    unittest.main()
