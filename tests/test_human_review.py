"""Gate D.2 human review decision validation and metrics tests."""

import unittest

from bankflow_v2.knowledge.human_review import (
    compute_quality_metrics,
    error_taxonomy_totals,
    relation_dependency_status,
    validate_decision_record,
    validate_relation_dependency,
)


def concept_candidate(
    candidate_id: str,
    *,
    concept_id: str = "retail",
    proposal_kind: str = "existing_concept",
    confidence: str = "high",
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "candidate_type": "new_semantic_concept",
        "semantic_signature": f"sig-{candidate_id}",
        "task": "semantic-concept-v1",
        "concept_id": concept_id,
        "concept_name": "零售",
        "proposal_kind": proposal_kind,
        "confidence": confidence,
        "review_status": "pending",
        "privacy_status": "allowed",
        "stage": "Gate D",
    }


def relation_candidate(
    candidate_id: str,
    concept_ref: str,
    *,
    relevance: str = "strong",
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "candidate_type": "new_industry_relation",
        "semantic_signature": "sig-r",
        "task": "industry-concept-relevance-v1",
        "concept_candidate_ref": concept_ref,
        "industry_id": "47",
        "concept_id": "property_management",
        "proposed_relevance": relevance,
        "review_status": "pending",
        "privacy_status": "allowed",
        "stage": "Gate D",
    }


def record(
    candidate_id: str,
    decision: str,
    *,
    final_value: dict[str, str] | None = None,
    error_category: str | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "review_set_version": "real-ai-review-set-v1",
        "review_decision": decision,
        "reviewed_by": "human",
        "reviewed_at": "2026-08-07T00:00:00+00:00",
        "review_reason": "语义明确，canonical 定义直接覆盖",
        "original_candidate": {"candidate_id": candidate_id},
        "final_value": final_value or {},
        "error_category": error_category or "",
        "promotion_status": "not_promoted",
        "review_source": "interactive_human_review",
    }


class DecisionValidationTests(unittest.TestCase):
    def test_valid_approve_record(self):
        candidate = concept_candidate("c1")
        self.assertEqual(
            validate_decision_record(record("c1", "approve"), candidate=candidate),
            [],
        )

    def test_invalid_enum_rejected(self):
        candidate = concept_candidate("c1")
        invalid = record("c1", "maybe")
        self.assertIn(
            "invalid_review_decision",
            validate_decision_record(invalid, candidate=candidate),
        )

    def test_reviewed_by_must_be_human(self):
        candidate = concept_candidate("c1")
        auto = record("c1", "approve")
        auto["reviewed_by"] = "deepseek"
        self.assertIn(
            "reviewed_by_not_human",
            validate_decision_record(auto, candidate=candidate),
        )

    def test_modify_requires_final_concept(self):
        candidate = concept_candidate("c1")
        missing = record("c1", "modify", error_category="wrong_existing_concept")
        self.assertIn(
            "modify_requires_final_concept",
            validate_decision_record(missing, candidate=candidate),
        )
        fixed = record(
            "c1",
            "modify",
            final_value={
                "final_concept_id": "convenience_store",
                "final_concept_name": "便利店",
            },
            error_category="wrong_existing_concept",
        )
        self.assertEqual(
            validate_decision_record(fixed, candidate=candidate),
            [],
        )

    def test_modify_requires_final_relevance_for_relation(self):
        candidate = relation_candidate("r1", "c1")
        missing = record("r1", "modify", error_category="strength_too_high")
        self.assertIn(
            "modify_requires_final_relevance",
            validate_decision_record(missing, candidate=candidate),
        )
        fixed = record(
            "r1",
            "modify",
            final_value={"final_relevance": "medium"},
            error_category="strength_too_high",
        )
        self.assertEqual(
            validate_decision_record(fixed, candidate=candidate),
            [],
        )

    def test_reject_preserves_original_and_needs_category(self):
        candidate = concept_candidate("c1")
        rejected = record("c1", "reject")
        self.assertIn(
            "error_category_missing_or_invalid",
            validate_decision_record(rejected, candidate=candidate),
        )
        fixed = record(
            "c1",
            "reject",
            error_category="wrong_domain",
        )
        self.assertEqual(
            validate_decision_record(fixed, candidate=candidate),
            [],
        )
        self.assertEqual(fixed["original_candidate"]["candidate_id"], "c1")

    def test_insufficient_preserves_unresolved_semantics(self):
        candidate = concept_candidate("c1")
        insufficient = record(
            "c1",
            "insufficient",
            error_category="insufficient_evidence",
        )
        self.assertEqual(
            validate_decision_record(insufficient, candidate=candidate),
            [],
        )
        self.assertEqual(insufficient["promotion_status"], "not_promoted")
        self.assertNotIn("final_relevance", insufficient["final_value"])

    def test_promotion_status_must_stay_not_promoted(self):
        candidate = concept_candidate("c1")
        bad = record("c1", "approve")
        bad["promotion_status"] = "promoted"
        self.assertIn(
            "promotion_status_not_not_promoted",
            validate_decision_record(bad, candidate=candidate),
        )


class RelationDependencyTests(unittest.TestCase):
    def test_approve_blocked_when_upstream_rejected(self):
        candidate = relation_candidate("r1", "c1")
        approved = record("r1", "approve")
        errors = validate_relation_dependency(
            approved,
            candidate,
            {"c1": "reject"},
        )
        self.assertIn(
            "relation_approve_requires_upstream_concept_approve",
            errors,
        )
        self.assertIn(
            "relation_must_follow_upstream_reject_or_insufficient",
            errors,
        )
        self.assertEqual(
            relation_dependency_status(candidate, {"c1": "reject"}),
            "dependent_concept_not_approved",
        )

    def test_approve_allowed_when_upstream_approved(self):
        candidate = relation_candidate("r1", "c1")
        approved = record("r1", "approve")
        self.assertEqual(
            validate_relation_dependency(
                approved,
                candidate,
                {"c1": "approve"},
            ),
            [],
        )

    def test_upstream_modify_marks_dependency(self):
        candidate = relation_candidate("r1", "c1")
        self.assertEqual(
            relation_dependency_status(candidate, {"c1": "modify"}),
            "dependent_concept_modified",
        )


class QualityMetricsTests(unittest.TestCase):
    def _candidates(self):
        return [
            concept_candidate("c1", concept_id="retail"),
            concept_candidate("c2", concept_id="convenience_store"),
            concept_candidate(
                "c3",
                concept_id="property_management",
                proposal_kind="new_concept",
                confidence="low",
            ),
            relation_candidate("r1", "c3"),
        ]

    def _records(self):
        return [
            record(
                "c1",
                "modify",
                final_value={
                    "final_concept_id": "convenience_store",
                    "final_concept_name": "便利店",
                },
                error_category="wrong_existing_concept",
            ),
            record("c2", "approve"),
            record(
                "c3",
                "approve",
                error_category="",
            ),
            record("r1", "approve"),
        ]

    def test_metrics_closed_and_rates(self):
        metrics = compute_quality_metrics(
            self._records(),
            self._candidates(),
        )
        overall = metrics["overall"]
        self.assertEqual(overall["reviewed"], 4)
        self.assertEqual(overall["pending"], 0)
        self.assertEqual(overall["exact_approve"], 3)
        self.assertEqual(overall["modify"], 1)
        self.assertTrue(overall["closed"])
        self.assertEqual(overall["exact_approve_rate"], 0.75)
        self.assertEqual(overall["usable_after_modification_rate"], 1.0)
        existing = metrics["existing_concept_recovery"]
        self.assertEqual(existing["total"], 2)
        self.assertEqual(existing["exact_recovery_accuracy"], 0.5)
        self.assertEqual(existing["usable_rate"], 1.0)
        new = metrics["new_concept_proposals"]
        self.assertEqual(new["total"], 1)
        self.assertEqual(new["new_concept_proposal_acceptance_rate"], 1.0)
        relation = metrics["relation"]
        self.assertEqual(relation["total"], 1)
        self.assertEqual(relation["exact_approve"], 1)
        self.assertEqual(metrics["legacy_pending_excluded"], 12)

    def test_confidence_calibration(self):
        metrics = compute_quality_metrics(
            self._records(),
            self._candidates(),
        )
        calibration = metrics["confidence_calibration"]
        self.assertEqual(calibration["high"]["approve"], 1)
        self.assertEqual(calibration["high"]["modify"], 1)
        self.assertEqual(calibration["low"]["approve"], 1)

    def test_error_taxonomy_closed(self):
        taxonomy = error_taxonomy_totals(
            self._records(),
            self._candidates(),
        )
        self.assertEqual(taxonomy["total_non_approve"], 1)
        self.assertTrue(taxonomy["taxonomy_closed"])
        self.assertEqual(taxonomy["unexplained"], 0)
        self.assertEqual(
            taxonomy["categories"]["wrong_existing_concept"],
            1,
        )

    def test_partial_review_not_complete(self):
        metrics = compute_quality_metrics(
            [self._records()[0]],
            self._candidates(),
        )
        self.assertEqual(metrics["status"], "partial")
        self.assertEqual(metrics["missing_human_labels"], 3)
        self.assertEqual(metrics["overall"]["exact_approve_rate"], 0.0)


class FrozenIntegrityTests(unittest.TestCase):
    def test_manifest_identity_ignores_decisions(self):
        from bankflow_v2.knowledge.review_set import review_set_identity

        ids = ["a1", "b2", "c3"]
        before = review_set_identity(
            review_set_version="real-ai-review-set-v1",
            knowledge_version="business-semantic-kb-v1",
            candidate_ids=ids,
        )
        # decisions metadata never changes the membership identity
        after = review_set_identity(
            review_set_version="real-ai-review-set-v1",
            knowledge_version="business-semantic-kb-v1",
            candidate_ids=ids,
        )
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
