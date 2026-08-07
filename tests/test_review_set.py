"""Frozen Real-AI Review Set manifest determinism tests."""

import unittest

from bankflow_v2.knowledge.review_set import (
    build_review_set_manifest,
    review_set_identity,
)


def _candidates() -> list[dict[str, object]]:
    return [
        {
            "candidate_id": "a1",
            "candidate_type": "new_semantic_concept",
            "semantic_signature": "sig-1",
            "task": "semantic-concept-v1",
            "stage": "Gate D",
            "review_status": "pending",
            "privacy_status": "allowed",
        },
        {
            "candidate_id": "b2",
            "candidate_type": "new_semantic_concept",
            "semantic_signature": "sig-2",
            "task": "semantic-concept-v1",
            "stage": "Gate D.1C",
            "review_status": "pending",
            "privacy_status": "allowed",
        },
        {
            "candidate_id": "c3",
            "candidate_type": "new_industry_relation",
            "semantic_signature": "sig-1",
            "task": "industry-concept-relevance-v1",
            "stage": "Gate D",
            "review_status": "pending",
            "privacy_status": "allowed",
            "concept_candidate_ref": "a1",
        },
    ]


class ReviewSetManifestTests(unittest.TestCase):
    def test_identity_deterministic(self):
        first = review_set_identity(
            review_set_version="real-ai-review-set-v1",
            knowledge_version="business-semantic-kb-v1",
            candidate_ids=["c3", "a1", "b2"],
        )
        second = review_set_identity(
            review_set_version="real-ai-review-set-v1",
            knowledge_version="business-semantic-kb-v1",
            candidate_ids=["a1", "b2", "c3"],
        )
        self.assertEqual(first, second)

    def test_identity_changes_with_ids(self):
        base = review_set_identity(
            review_set_version="real-ai-review-set-v1",
            knowledge_version="business-semantic-kb-v1",
            candidate_ids=["a1", "b2", "c3"],
        )
        changed = review_set_identity(
            review_set_version="real-ai-review-set-v1",
            knowledge_version="business-semantic-kb-v1",
            candidate_ids=["a1", "b2"],
        )
        self.assertNotEqual(base, changed)

    def test_manifest_counts_and_stages(self):
        manifest = build_review_set_manifest(
            review_set_version="real-ai-review-set-v1",
            knowledge_version="business-semantic-kb-v1",
            candidates=_candidates(),
            legacy_pending_count=12,
            human_decision_count=0,
            freeze_timestamp="2026-08-07T00:00:00+00:00",
        )
        self.assertEqual(manifest["total_candidates"], 3)
        self.assertEqual(manifest["concept_candidates"], 2)
        self.assertEqual(manifest["relation_candidates"], 1)
        self.assertEqual(
            manifest["stage_counts"],
            {"Gate D": 2, "Gate D.1C": 1},
        )
        self.assertEqual(manifest["legacy_relation_pending_excluded"], 12)
        self.assertEqual(manifest["human_decisions"], 0)
        self.assertEqual(
            manifest["checksum"],
            review_set_identity(
                review_set_version="real-ai-review-set-v1",
                knowledge_version="business-semantic-kb-v1",
                candidate_ids=["a1", "b2", "c3"],
            ),
        )


if __name__ == "__main__":
    unittest.main()
