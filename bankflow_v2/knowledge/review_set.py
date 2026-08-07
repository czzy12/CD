"""Frozen Real-AI Candidate Review Set manifest (deterministic identity)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any


def review_set_identity(
    *,
    review_set_version: str,
    knowledge_version: str,
    candidate_ids: list[str],
) -> str:
    """Deterministic manifest identity (content-based, no timestamps)."""
    payload = {
        "review_set_version": review_set_version,
        "knowledge_version": knowledge_version,
        "candidate_ids": sorted(set(candidate_ids)),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_review_set_manifest(
    *,
    review_set_version: str,
    knowledge_version: str,
    candidates: list[Mapping[str, Any]],
    legacy_pending_count: int,
    human_decision_count: int,
    freeze_timestamp: str | None = None,
) -> dict[str, Any]:
    """Build the frozen manifest from review-queue candidate records.

    Each candidate record must carry at least:
    candidate_id, candidate_type, semantic_signature, task, stage,
    review_status, privacy_status and (for relation) concept_candidate_ref.
    """
    candidate_ids = sorted(
        str(candidate["candidate_id"]) for candidate in candidates
    )
    identity = review_set_identity(
        review_set_version=review_set_version,
        knowledge_version=knowledge_version,
        candidate_ids=candidate_ids,
    )
    by_stage: dict[str, int] = {}
    for candidate in candidates:
        stage = str(candidate.get("stage", "Gate D"))
        by_stage[stage] = by_stage.get(stage, 0) + 1
    concept_ids = [
        str(candidate["candidate_id"])
        for candidate in candidates
        if candidate.get("task") == "semantic-concept-v1"
    ]
    relation_ids = [
        str(candidate["candidate_id"])
        for candidate in candidates
        if candidate.get("task") == "industry-concept-relevance-v1"
    ]
    return {
        "review_set_version": review_set_version,
        "freeze_timestamp": freeze_timestamp
        or datetime.now(timezone.utc).isoformat(),
        "knowledge_version": knowledge_version,
        "total_candidates": len(candidate_ids),
        "concept_candidates": len(concept_ids),
        "relation_candidates": len(relation_ids),
        "candidate_ids": candidate_ids,
        "concept_candidate_ids": concept_ids,
        "relation_candidate_ids": relation_ids,
        "stage_counts": dict(sorted(by_stage.items())),
        "legacy_relation_pending_excluded": legacy_pending_count,
        "human_decisions": human_decision_count,
        "manifest_identity": identity,
        "checksum": identity,
        "provenance_required_fields": [
            "candidate_id",
            "candidate_type",
            "semantic_signature",
            "task",
            "provider_run",
            "knowledge_version",
            "source",
            "stage",
            "review_status",
            "privacy_status",
        ],
    }
