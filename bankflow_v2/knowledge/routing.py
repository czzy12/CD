"""Gate F1.3: Local / AI responsibility boundary contract (shadow).

The long-term architecture is Local Precision First:

    Local reliable knowledge     -> local resolve
    Local insufficient/ambiguous -> AI eligible
    No evidence / pure noise     -> insufficient (no AI)

The objective is NOT to minimise AI calls; it is to avoid unnecessary AI
calls on obvious items and missed AI calls on ambiguous items.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any


LOCAL_AI_RESPONSIBILITY_CONTRACT_VERSION = "local-ai-responsibility-contract-v1"
BUSINESS_EVIDENCE_TASK_VERSION = "business-evidence-task-v1"
CASE_EVIDENCE_PACK_VERSION = "case-evidence-pack-v1"
CASE_SYNTHESIS_TASK_VERSION = "case-synthesis-task-v1"

ROUTING_LOCAL_RESOLVED = "local_resolved"
ROUTING_AI_ELIGIBLE_TRANSACTION = "ai_eligible_transaction"
ROUTING_INSUFFICIENT_TRANSACTION = "insufficient_transaction"
ROUTING_CASE_AGGREGATION_ONLY = "case_aggregation_only"
ROUTING_CASE_AI_ELIGIBLE = "case_ai_eligible"

ROUTING_AI_EXECUTION_DEFERRED = "ai_execution_deferred"

TRANSACTION_AI_LIFECYCLE = "transaction_ai_knowledge_candidate_lifecycle"
CASE_AI_LIFECYCLE = "case_ai_case_observation_lifecycle"

ROUTING_STATES = frozenset(
    {
        ROUTING_LOCAL_RESOLVED,
        ROUTING_AI_ELIGIBLE_TRANSACTION,
        ROUTING_INSUFFICIENT_TRANSACTION,
        ROUTING_CASE_AGGREGATION_ONLY,
        ROUTING_CASE_AI_ELIGIBLE,
    }
)

COVERAGE_SUFFICIENT = "sufficient"
COVERAGE_PARTIAL = "partial"
COVERAGE_INSUFFICIENT = "insufficient"
COVERAGE_UNAVAILABLE = "unavailable"
COVERAGE_VALUES = frozenset(
    {
        COVERAGE_SUFFICIENT,
        COVERAGE_PARTIAL,
        COVERAGE_INSUFFICIENT,
        COVERAGE_UNAVAILABLE,
    }
)


def routing_counts(
    entries: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    """Count routing states across transaction evidence entries."""
    return dict(
        sorted(
            Counter(
                str(entry.get("routing_state") or ROUTING_INSUFFICIENT_TRANSACTION)
                for entry in entries
            ).items()
        )
    )


def evaluate_routing(
    entries: Iterable[Mapping[str, Any]],
    *,
    ai_invoked_ids: set[str] | frozenset[str] | None = None,
    execution_mode: str = "deferred",
) -> dict[str, Any]:
    """Routing metrics without treating local coverage as the success metric.

    unnecessary_ai_call: AI invoked on a locally-resolved obvious item.
    ai_execution_deferred: AI-eligible item intentionally not invoked because
                           the current Gate/execution mode disables real AI.
                           This is a normal state, not a defect.
    missed_ai_call:       AI-eligible item that should have been invoked in a
                          live mode but was not (implementation defect).
    """
    invoked = set(ai_invoked_ids or ())
    live_mode = execution_mode == "live"
    rows = list(entries)
    local_resolved = [
        row for row in rows if row.get("routing_state") == ROUTING_LOCAL_RESOLVED
    ]
    ai_eligible = [
        row for row in rows if row.get("routing_state") == ROUTING_AI_ELIGIBLE_TRANSACTION
    ]
    insufficient = [
        row
        for row in rows
        if row.get("routing_state") == ROUTING_INSUFFICIENT_TRANSACTION
    ]
    unnecessary_ai = [
        row for row in local_resolved if row.get("transaction_id") in invoked
    ]
    missed_ai = [
        row
        for row in ai_eligible
        if live_mode and row.get("transaction_id") not in invoked
    ]
    return {
        "total_entries": len(rows),
        "local_resolved": len(local_resolved),
        "ai_eligible": len(ai_eligible),
        "insufficient": len(insufficient),
        "case_aggregation_only": sum(
            1
            for row in rows
            if row.get("routing_state") == ROUTING_CASE_AGGREGATION_ONLY
        ),
        "case_ai_eligible": sum(
            1
            for row in rows
            if row.get("routing_state") == ROUTING_CASE_AI_ELIGIBLE
        ),
        "unnecessary_ai_call": len(unnecessary_ai),
        "ai_execution_deferred": len(ai_eligible) if not live_mode else 0,
        "missed_ai_call": len(missed_ai),
        "ai_invoked_count": len(invoked),
        "execution_mode": execution_mode,
        "local_overreach": 0,
        "local_false_confidence": 0,
    }


def update_overreach_metrics(
    metrics: dict[str, Any],
    *,
    local_overreach: int = 0,
    local_false_confidence: int = 0,
) -> dict[str, Any]:
    metrics["local_overreach"] = int(local_overreach)
    metrics["local_false_confidence"] = int(local_false_confidence)
    return metrics
