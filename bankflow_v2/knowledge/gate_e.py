"""Gate E: legacy relation pending isolation and manifest helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from .models import KnowledgeCandidate
from .human_review import RELATION_ERROR_CATEGORIES, VALID_DECISIONS


LEGACY_RELATION_PROMPT_VERSION = "business-relevance-mvp-v11"
LEGACY_RELATION_SET_VERSION = "legacy-relation-pending-v1"
REAL_AI_REVIEW_SET_VERSION = "real-ai-review-set-v1"


def select_legacy_relation_pending(
    candidates: Iterable[KnowledgeCandidate],
) -> list[KnowledgeCandidate]:
    """Return only legacy_v11 relation candidates that are still pending."""
    return [
        candidate
        for candidate in candidates
        if candidate.candidate_type == "new_industry_relation"
        and candidate.prompt_version == LEGACY_RELATION_PROMPT_VERSION
        and candidate.review_status == "pending"
    ]


def build_legacy_relation_manifest(
    candidates: list[KnowledgeCandidate],
    *,
    set_version: str = LEGACY_RELATION_SET_VERSION,
) -> dict[str, Any]:
    """Deterministic manifest for the isolated legacy relation review set."""
    candidate_ids = [candidate.candidate_id for candidate in candidates]
    unique_signatures = sorted(
        {
            str(candidate.input_signature.get("signature_hash", ""))
            for candidate in candidates
        }
    )
    identity_payload = {
        "set_version": set_version,
        "candidate_ids": candidate_ids,
        "unique_signatures": unique_signatures,
    }
    identity = hashlib.sha256(
        json.dumps(
            identity_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return {
        "review_set_version": set_version,
        "identity": identity,
        "total_candidates": len(candidate_ids),
        "unique_signatures": len(unique_signatures),
        "candidate_ids": candidate_ids,
        "unique_signature_hashes": unique_signatures,
        "provenance": (
            "legacy_v11 acceptance migration (business-relevance-mvp-v11)"
        ),
        "isolated_from": REAL_AI_REVIEW_SET_VERSION,
        "gate_d_review_set_excluded": True,
        "calibration_pending_excluded": True,
    }


def validate_legacy_relation_decision(
    record: dict[str, Any],
    *,
    candidate: dict[str, Any],
) -> list[str]:
    """Validate one Gate E human decision for a legacy relation candidate."""
    errors: list[str] = []
    if str(record.get("candidate_id", "")) != str(
        candidate.get("candidate_id", "")
    ):
        errors.append("candidate_id_mismatch")
    if record.get("review_set_version") != LEGACY_RELATION_SET_VERSION:
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
        not isinstance(original, dict)
        or str(original.get("candidate_id", ""))
        != str(candidate.get("candidate_id", ""))
    ):
        errors.append("original_candidate_not_preserved")
    if decision == "modify":
        final = record.get("final_value")
        if not isinstance(final, dict) or not str(
            final.get("final_relevance", "") or ""
        ).strip():
            errors.append("modify_requires_final_relevance")
    if decision in {"approve", "modify"}:
        final_relevance = (
            str(
                (record.get("final_value") or {}).get(
                    "final_relevance",
                    record.get("original_candidate", {}).get(
                        "proposed_relevance",
                        "",
                    ),
                )
                or ""
            )
            if decision == "modify"
            else str(
                (record.get("original_candidate") or {}).get(
                    "proposed_relevance",
                    "",
                )
                or ""
            )
        )
        if final_relevance not in {
            "strong",
            "medium",
            "weak",
            "none",
            "undetermined",
        }:
            errors.append("invalid_final_relevance")
    if decision != "approve":
        category = str(record.get("error_category", "") or "")
        if category not in RELATION_ERROR_CATEGORIES:
            errors.append("error_category_missing_or_invalid")
    return errors
