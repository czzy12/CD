"""Gate F0/F1: freeze determinism and holdout selection helpers."""

from __future__ import annotations

import unittest

from bankflow_v2.knowledge.freeze import file_checksums, manifest_checksum
from bankflow_v2.knowledge.holdout import (
    balanced_selection,
    classify_industry_availability,
    dedup_by_signature,
    holdout_manifest_checksum,
    relation_denominator_eligible,
)


class FreezeHelperTests(unittest.TestCase):
    def test_manifest_checksum_deterministic(self):
        payload = {"a": 1, "b": [2, 3], "c": "x"}
        self.assertEqual(manifest_checksum(payload), manifest_checksum(payload))

    def test_manifest_checksum_changes_with_payload(self):
        base = {"a": 1}
        changed = {"a": 2}
        self.assertNotEqual(manifest_checksum(base), manifest_checksum(changed))

    def test_file_checksums_stable_and_sensitive(self):
        files = {"a.py": b"print(1)", "b.json": b"{}"}
        self.assertEqual(file_checksums(files), file_checksums(files))
        self.assertNotEqual(
            file_checksums({"a.py": b"print(1)"}),
            file_checksums({"a.py": b"print(2)"}),
        )


class HoldoutHelperTests(unittest.TestCase):
    def test_dedup_by_signature_keeps_occurrence_count(self):
        entries = [
            {"signature_id": "s1", "occurrence_count": 3, "fields": {"a": "1"}},
            {"signature_id": "s1", "occurrence_count": 2, "fields": {"a": "1"}},
            {"signature_id": "s2", "occurrence_count": 1, "fields": {"b": "2"}},
        ]
        result = dedup_by_signature(entries)
        self.assertEqual(set(result), {"s1", "s2"})
        self.assertEqual(result["s1"]["occurrence_count"], 5)

    def test_balanced_selection_respects_cap_and_target(self):
        by_doc = {
            "d1": ["a", "b", "c", "d", "e"],
            "d2": ["f", "g", "h", "i", "j"],
            "d3": ["k", "l", "m", "n", "o"],
        }
        selected = balanced_selection(
            by_doc,
            max_per_document=2,
            target=6,
        )
        self.assertEqual(len(selected), 6)
        self.assertLessEqual(
            max(sum(1 for s in selected if s in sigs) for sigs in by_doc.values()),
            2,
        )

    def test_holdout_manifest_checksum_deterministic(self):
        payload = {"membership": ["a", "b"], "source_documents": ["d1"]}
        self.assertEqual(
            holdout_manifest_checksum(payload),
            holdout_manifest_checksum(payload),
        )

    def test_selected_signatures_not_in_excluded_registry(self):
        by_doc = {"d1": ["s1", "s2", "s3"], "d2": ["s4", "s5", "s6"]}
        excluded = {"s1"}
        selected = [
            s
            for s in balanced_selection(by_doc, max_per_document=1, target=2)
            if s not in excluded
        ]
        self.assertNotIn("s1", selected)

    def test_industry_availability_classification(self):
        self.assertEqual(
            classify_industry_availability(
                has_external_metadata=False,
                normalized_industry_ids=[],
            ),
            "unavailable",
        )
        self.assertEqual(
            classify_industry_availability(
                has_external_metadata=True,
                normalized_industry_ids=["47"],
            ),
            "confirmed",
        )
        self.assertEqual(
            classify_industry_availability(
                has_external_metadata=True,
                normalized_industry_ids=["47", "06"],
            ),
            "available_but_ambiguous",
        )
        self.assertEqual(
            classify_industry_availability(
                has_external_metadata=True,
                normalized_industry_ids=["47", "06"],
                metadata_conflict=True,
            ),
            "invalid_metadata",
        )

    def test_relation_denominator_requires_confirmed(self):
        self.assertTrue(relation_denominator_eligible("confirmed"))
        self.assertFalse(relation_denominator_eligible("unavailable"))
        self.assertFalse(relation_denominator_eligible("available_but_ambiguous"))


if __name__ == "__main__":
    unittest.main()
