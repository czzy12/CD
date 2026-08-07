"""Gate D.2: human review decision validation and quality metrics.

Only a human may produce decisions (reviewed_by=human). This module never
writes verdicts itself; it validates and aggregates them.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any


VALID_DECISIONS = ("approve", "modify", "reject", "insufficient")
CONCEPT_TASK = "semantic-concept-v1"
RELATION_TASK = "industry-concept-relevance-v1"
REVIEW_SET_VERSION = "real-ai-review-set-v1"

CONCEPT_ERROR_CATEGORIES = (
    "overly_generic",
    "overly_specific",
    "wrong_domain",
    "wrong_existing_concept",
    "new_concept_should_merge",
    "new_concept_not_generalizable",
    "insufficient_evidence",
    "concept_boundary_ambiguous",
    "other",
)
RELATION_ERROR_CATEGORIES = (
    "strength_too_high",
    "strength_too_low",
    "relation_should_none",
    "relation_should_undetermined",
    "upstream_concept_error",
    "constraint_conflict",
    "other",
)


def validate_decision_record(
    record: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
) -> list[str]:
    """Validate one human decision record; returns a list of violations."""
    errors: list[str] = []
    if str(record.get("candidate_id", "")) != str(candidate["candidate_id"]):
        errors.append("candidate_id_mismatch")
    if record.get("review_set_version") != REVIEW_SET_VERSION:
        errors.append("review_set_version_mismatch")
    decision = record.get("review_decision")
    if decision not in VALID_DECISIONS:
        errors.append("invalid_review_decision")
    if record.get("reviewed_by") != "human":
        errors.append("reviewed_by_not_human")
    if not str(record.get("reviewed_at", "") or "").strip():
        errors.append("reviewed_at_missing")
    if not str(record.get("review_reason", "") or "").strip():
        errors.append("review_reason_missing")
    if record.get("promotion_status") != "not_promoted":
        errors.append("promotion_status_not_not_promoted")
    original = record.get("original_candidate")
    if (
        not isinstance(original, Mapping)
        or str(original.get("candidate_id", ""))
        != str(candidate["candidate_id"])
    ):
        errors.append("original_candidate_not_preserved")
    if decision == "modify":
        final = record.get("final_value")
        if not isinstance(final, Mapping):
            errors.append("modify_requires_final_value")
        elif str(candidate.get("task", "")) == CONCEPT_TASK:
            if not final.get("final_concept_id") or not final.get(
                "final_concept_name"
            ):
                errors.append("modify_requires_final_concept")
        else:
            if not final.get("final_relevance"):
                errors.append("modify_requires_final_relevance")
    if decision != "approve":
        category = str(record.get("error_category", "") or "")
        allowed = (
            RELATION_ERROR_CATEGORIES
            if str(candidate.get("task", "")) == RELATION_TASK
            else CONCEPT_ERROR_CATEGORIES
        )
        if category not in allowed:
            errors.append("error_category_missing_or_invalid")
    return errors


def relation_dependency_status(
    relation_candidate: Mapping[str, Any],
    concept_decisions: Mapping[str, str],
) -> str:
    """Upstream Concept dependency for a relation candidate."""
    concept_ref = str(relation_candidate.get("concept_candidate_ref", ""))
    concept_decision = concept_decisions.get(concept_ref, "")
    if concept_decision in {"reject", "insufficient"}:
        return "dependent_concept_not_approved"
    if concept_decision == "modify":
        return "dependent_concept_modified"
    if concept_decision == "approve":
        return "upstream_concept_approved"
    return "upstream_concept_pending"


def validate_relation_dependency(
    relation_record: Mapping[str, Any],
    relation_candidate: Mapping[str, Any],
    concept_decisions: Mapping[str, str],
) -> list[str]:
    errors: list[str] = []
    status = relation_dependency_status(
        relation_candidate,
        concept_decisions,
    )
    if relation_record.get("review_decision") == "approve":
        if status != "upstream_concept_approved":
            errors.append(
                "relation_approve_requires_upstream_concept_approve"
            )
    if status == "dependent_concept_not_approved":
        if relation_record.get("review_decision") not in {
            "reject",
            "insufficient",
        }:
            errors.append("relation_must_follow_upstream_reject_or_insufficient")
    return errors


def _decision_counts(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    counts = {decision: 0 for decision in VALID_DECISIONS}
    for record in records:
        decision = str(record.get("review_decision", ""))
        if decision in counts:
            counts[decision] += 1
    return counts


def compute_quality_metrics(
    records: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
    *,
    legacy_pending_excluded: int = 12,
) -> dict[str, Any]:
    """Compute Gate D.2 metrics from human decisions (closed buckets)."""
    by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    records_by_id = {
        str(record.get("candidate_id", "")): record for record in records
    }
    reviewed_ids = set(records_by_id)
    concept_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.get("task", "")) == CONCEPT_TASK
    ]
    existing = [
        candidate
        for candidate in concept_candidates
        if candidate.get("proposal_kind") == "existing_concept"
    ]
    new = [
        candidate
        for candidate in concept_candidates
        if candidate.get("proposal_kind") == "new_concept"
    ]
    relation_candidates = [
        candidate
        for candidate in candidates
        if str(candidate.get("task", "")) == RELATION_TASK
    ]

    def group_stats(group: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        group_records = [
            records_by_id[str(candidate["candidate_id"])]
            for candidate in group
            if str(candidate["candidate_id"]) in records_by_id
        ]
        counts = _decision_counts(group_records)
        total = len(group)
        reviewed = len(group_records)
        exact_approve_rate = (
            round(counts["approve"] / reviewed, 4) if reviewed else None
        )
        usable = counts["approve"] + counts["modify"]
        usable_rate = round(usable / reviewed, 4) if reviewed else None
        return {
            "total": total,
            "reviewed": reviewed,
            "pending": total - reviewed,
            "exact_approve": counts["approve"],
            "modify": counts["modify"],
            "reject": counts["reject"],
            "insufficient": counts["insufficient"],
            "exact_approve_rate": exact_approve_rate,
            "usable_after_modification_rate": usable_rate,
            "closed": (
                counts["approve"]
                + counts["modify"]
                + counts["reject"]
                + counts["insufficient"]
                == reviewed
            ),
        }

    concept_stats = group_stats(concept_candidates)
    existing_stats = group_stats(existing)
    new_stats = group_stats(new)
    relation_stats = group_stats(relation_candidates)
    all_records = list(records)
    overall_counts = _decision_counts(all_records)
    reviewed_total = len(all_records)
    overall = {
        "total": len(candidates),
        "reviewed": reviewed_total,
        "pending": len(candidates) - reviewed_total,
        "exact_approve": overall_counts["approve"],
        "modify": overall_counts["modify"],
        "reject": overall_counts["reject"],
        "insufficient": overall_counts["insufficient"],
        "exact_approve_rate": (
            round(overall_counts["approve"] / reviewed_total, 4)
            if reviewed_total
            else None
        ),
        "usable_after_modification_rate": (
            round(
                (overall_counts["approve"] + overall_counts["modify"])
                / reviewed_total,
                4,
            )
            if reviewed_total
            else None
        ),
        "reject_rate": (
            round(overall_counts["reject"] / reviewed_total, 4)
            if reviewed_total
            else None
        ),
        "insufficient_rate": (
            round(overall_counts["insufficient"] / reviewed_total, 4)
            if reviewed_total
            else None
        ),
        "closed": (
            sum(overall_counts.values()) == reviewed_total
        ),
    }

    confidence: dict[str, dict[str, int]] = {}
    for candidate in candidates:
        confidence_value = str(candidate.get("confidence", "") or "unknown")
        bucket = confidence.setdefault(
            confidence_value,
            {decision: 0 for decision in VALID_DECISIONS},
        )
        record = records_by_id.get(str(candidate["candidate_id"]))
        if record is not None:
            decision = str(record.get("review_decision", ""))
            if decision in bucket:
                bucket[decision] += 1

    error_totals = error_taxonomy_totals(records, candidates)
    return {
        "status": (
            "computable" if reviewed_total == len(candidates) else "partial"
        ),
        "missing_human_labels": len(candidates) - reviewed_total,
        "concept": concept_stats,
        "existing_concept_recovery": {
            **existing_stats,
            "exact_recovery_accuracy": existing_stats["exact_approve_rate"],
            "usable_rate": existing_stats["usable_after_modification_rate"],
        },
        "new_concept_proposals": {
            **new_stats,
            "new_concept_proposal_acceptance_rate": new_stats[
                "usable_after_modification_rate"
            ],
        },
        "relation": relation_stats,
        "overall": overall,
        "confidence_calibration": {
            key: dict(value) for key, value in sorted(confidence.items())
        },
        "error_taxonomy": error_totals,
        "legacy_pending_excluded": legacy_pending_excluded,
    }


def error_taxonomy_totals(
    records: Sequence[Mapping[str, Any]],
    candidates: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Error taxonomy closed over modify+reject+insufficient (unexplained=0)."""
    by_id = {str(candidate["candidate_id"]): candidate for candidate in candidates}
    counts: Counter[str] = Counter()
    for record in records:
        decision = str(record.get("review_decision", ""))
        if decision == "approve":
            continue
        candidate = by_id.get(str(record.get("candidate_id", "")))
        allowed = (
            RELATION_ERROR_CATEGORIES
            if candidate is not None
            and str(candidate.get("task", "")) == RELATION_TASK
            else CONCEPT_ERROR_CATEGORIES
        )
        category = str(record.get("error_category", "") or "")
        if category in allowed:
            counts[category] += 1
        else:
            counts["unexplained"] += 1
    non_approve = sum(
        1
        for record in records
        if record.get("review_decision") != "approve"
    )
    closed = sum(counts.get(category, 0) for category in allowed_categories())
    return {
        "total_non_approve": non_approve,
        "taxonomy_closed": non_approve == closed,
        "unexplained": int(counts.get("unexplained", 0)),
        "categories": dict(sorted(counts.items())),
    }


def allowed_categories() -> tuple[str, ...]:
    return tuple(dict.fromkeys((*CONCEPT_ERROR_CATEGORIES, *RELATION_ERROR_CATEGORIES)))
