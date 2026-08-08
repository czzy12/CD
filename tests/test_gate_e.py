"""Gate E: legacy relation pending isolation and decision validation."""

from __future__ import annotations

import unittest

from bankflow_v2.knowledge.gate_e import (
    LEGACY_RELATION_PROMPT_VERSION,
    LEGACY_RELATION_SET_VERSION,
    build_legacy_relation_manifest,
    classify_legacy_relation_promotion,
    select_legacy_relation_pending,
    validate_legacy_relation_decision,
)
from bankflow_v2.knowledge.models import KnowledgeCandidate


def _candidate(
    candidate_id: str,
    *,
    candidate_type: str,
    prompt_version: str,
    review_status: str = "pending",
    relevance: str = "none",
    signature_hash: str = "a" * 24,
) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        candidate_id=candidate_id,
        candidate_type=candidate_type,
        proposed_value={
            "industry_id": "internal.building_material_trade",
            "concept_id": "service",
            "relevance": relevance,
        },
        reason="legacy migration",
        model="legacy_v11",
        prompt_version=prompt_version,
        input_signature={"signature_hash": signature_hash},
        review_status=review_status,
    )


class LegacyRelationIsolationTests(unittest.TestCase):
    def test_selects_only_legacy_relation_pending(self):
        candidates = [
            _candidate("c1", candidate_type="new_industry_relation", prompt_version=LEGACY_RELATION_PROMPT_VERSION),
            _candidate("c2", candidate_type="new_industry_relation", prompt_version=LEGACY_RELATION_PROMPT_VERSION, review_status="rejected"),
            _candidate("c3", candidate_type="new_semantic_concept", prompt_version=LEGACY_RELATION_PROMPT_VERSION),
            _candidate("c4", candidate_type="new_industry_relation", prompt_version="industry-concept-relevance-v1"),
        ]
        selected = select_legacy_relation_pending(candidates)
        self.assertEqual([c.candidate_id for c in selected], ["c1"])

    def test_manifest_isolated_from_real_ai_review_set(self):
        candidates = [
            _candidate("c1", candidate_type="new_industry_relation", prompt_version=LEGACY_RELATION_PROMPT_VERSION, signature_hash="s1"),
            _candidate("c2", candidate_type="new_industry_relation", prompt_version=LEGACY_RELATION_PROMPT_VERSION, signature_hash="s2"),
        ]
        manifest = build_legacy_relation_manifest(candidates)
        self.assertEqual(manifest["review_set_version"], LEGACY_RELATION_SET_VERSION)
        self.assertEqual(manifest["total_candidates"], 2)
        self.assertEqual(manifest["unique_signatures"], 2)
        self.assertEqual(manifest["isolated_from"], "real-ai-review-set-v1")
        self.assertTrue(manifest["gate_d_review_set_excluded"])
        self.assertTrue(manifest["calibration_pending_excluded"])
        same = build_legacy_relation_manifest(candidates)
        self.assertEqual(manifest["identity"], same["identity"])


class LegacyRelationDecisionValidationTests(unittest.TestCase):
    def _candidate_dict(self) -> dict:
        return {
            "candidate_id": "c1",
            "proposed_relevance": "none",
            "industry_id": "internal.building_material_trade",
            "concept_id": "service",
        }

    def test_valid_approve_record_passes(self):
        record = {
            "candidate_id": "c1",
            "review_set_version": LEGACY_RELATION_SET_VERSION,
            "review_decision": "approve",
            "reviewed_by": "human",
            "reviewed_at": "2026-08-08T00:00:00+00:00",
            "review_reason": "human approved none relation",
            "promotion_status": "not_promoted",
            "original_candidate": self._candidate_dict(),
        }
        self.assertEqual(
            validate_legacy_relation_decision(record, candidate=self._candidate_dict()),
            [],
        )

    def test_modify_requires_final_relevance(self):
        record = {
            "candidate_id": "c1",
            "review_set_version": LEGACY_RELATION_SET_VERSION,
            "review_decision": "modify",
            "reviewed_by": "human",
            "reviewed_at": "2026-08-08T00:00:00+00:00",
            "review_reason": "strength should change",
            "promotion_status": "not_promoted",
            "original_candidate": self._candidate_dict(),
            "final_value": {},
            "error_category": "strength_too_low",
        }
        errors = validate_legacy_relation_decision(
            record,
            candidate=self._candidate_dict(),
        )
        self.assertIn("modify_requires_final_relevance", errors)

    def test_human_reviewer_required(self):
        record = {
            "candidate_id": "c1",
            "review_set_version": LEGACY_RELATION_SET_VERSION,
            "review_decision": "approve",
            "reviewed_by": "ai",
            "reviewed_at": "2026-08-08T00:00:00+00:00",
            "review_reason": "machine decision",
            "promotion_status": "not_promoted",
            "original_candidate": self._candidate_dict(),
        }
        errors = validate_legacy_relation_decision(
            record,
            candidate=self._candidate_dict(),
        )
        self.assertIn("reviewed_by_not_human", errors)

    def test_real_ai_review_set_version_rejected(self):
        record = {
            "candidate_id": "c1",
            "review_set_version": "real-ai-review-set-v1",
            "review_decision": "approve",
            "reviewed_by": "human",
            "reviewed_at": "2026-08-08T00:00:00+00:00",
            "review_reason": "wrong set",
            "promotion_status": "not_promoted",
            "original_candidate": self._candidate_dict(),
        }
        errors = validate_legacy_relation_decision(
            record,
            candidate=self._candidate_dict(),
        )
        self.assertIn("review_set_version_mismatch", errors)


class LegacyRelationPromotionClassificationTests(unittest.TestCase):
    def test_weak_resolved_by_generic_business(self):
        result = classify_legacy_relation_promotion(
            review_decision="modify",
            final_relevance="weak",
            current_local_relevance="weak",
            existing_exact_relevance=None,
            generic_business_relevance="weak",
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["classification"], "resolved_by_existing_canonical")

    def test_explicit_none_blocked_when_generic_weak_exists(self):
        result = classify_legacy_relation_promotion(
            review_decision="approve",
            final_relevance="none",
            current_local_relevance="weak",
            existing_exact_relevance=None,
            generic_business_relevance="weak",
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["classification"], "blocked_contract")
        self.assertEqual(result["blocker"], "relation_model_expressiveness")

    def test_none_not_required_when_local_already_none(self):
        result = classify_legacy_relation_promotion(
            review_decision="approve",
            final_relevance="none",
            current_local_relevance="none",
            existing_exact_relevance=None,
            generic_business_relevance=None,
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["classification"], "promotion_not_required")

    def test_reject_not_promotable(self):
        result = classify_legacy_relation_promotion(
            review_decision="reject",
            final_relevance="none",
            current_local_relevance="weak",
            existing_exact_relevance=None,
            generic_business_relevance="weak",
        )
        self.assertFalse(result["eligible"])
        self.assertEqual(result["classification"], "not_eligible_human_decision")

    def test_new_snapshot_eligible_when_no_equivalent(self):
        result = classify_legacy_relation_promotion(
            review_decision="modify",
            final_relevance="medium",
            current_local_relevance="weak",
            existing_exact_relevance=None,
            generic_business_relevance="weak",
        )
        self.assertTrue(result["eligible"])
        self.assertEqual(result["classification"], "promoted_new_snapshot")


if __name__ == "__main__":
    unittest.main()
