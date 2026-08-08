"""Gate F1.3D: industry consistency evidence coverage diagnostic."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .routing import (
    COVERAGE_INSUFFICIENT,
    COVERAGE_PARTIAL,
    COVERAGE_SUFFICIENT,
    COVERAGE_UNAVAILABLE,
    ROUTING_AI_ELIGIBLE_TRANSACTION,
    ROUTING_INSUFFICIENT_TRANSACTION,
)


_POSITIVE_RELEVANCE = {"strong", "medium", "weak"}


def industry_consistency_evidence_coverage(
    entries: Iterable[Mapping[str, Any]],
    *,
    relation_kb_covered_count: int = 0,
    relation_kb_total_count: int = 0,
    declared_industry_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Classify whether enough evidence exists to judge industry consistency.

    Missing knowledge is never interpreted as ``none``:

        knowledge coverage insufficient != declared industry inconsistent
        relation not known != relation none
    """
    rows = list(entries)
    direct_groups: set[str] = set()
    direct_occurrences = 0
    relation_positive = 0
    relation_undetermined = 0
    relation_known_none = 0
    ai_eligible = 0
    insufficient = 0
    for row in rows:
        role = str(row.get("role") or "")
        group = str(row.get("evidence_group_key") or "")
        if role == "direct_business" and group:
            direct_groups.add(group)
            direct_occurrences += 1
        relevance = str(row.get("industry_relevance") or "")
        if relevance in _POSITIVE_RELEVANCE:
            relation_positive += 1
        elif relevance == "none":
            relation_known_none += 1
        elif relevance == "undetermined":
            relation_undetermined += 1
        routing = str(row.get("routing_state") or "")
        if routing == ROUTING_AI_ELIGIBLE_TRANSACTION:
            ai_eligible += 1
        elif routing == ROUTING_INSUFFICIENT_TRANSACTION:
            insufficient += 1

    # Only approved canonical relations for the declared industry count as
    # direct KB coverage; inherited/generic weak or unresolved relations are
    # evidence of partial coverage, never sufficient coverage.
    relation_coverage_available = relation_kb_covered_count > 0
    direct_groups_count = len(direct_groups)
    if not rows:
        value = COVERAGE_UNAVAILABLE
        reason = "无可用交易证据条目"
    elif not relation_coverage_available and direct_groups_count == 0:
        value = COVERAGE_INSUFFICIENT
        reason = "Relation KB 无覆盖且无直接经营证据，无法判断行业一致性"
    elif not relation_coverage_available and direct_groups_count > 0:
        value = COVERAGE_PARTIAL
        reason = "存在直接经营证据，但 Relation KB 未覆盖申报行业，一致性无法完全确认"
    elif relation_coverage_available and direct_groups_count == 0:
        value = COVERAGE_PARTIAL
        reason = "Relation KB 有覆盖但缺少直接经营证据，一致性证据不完整"
    else:
        value = COVERAGE_SUFFICIENT
        reason = "Relation KB 覆盖与直接经营证据均存在，可判断行业一致性"

    return {
        "value": value,
        "reason": reason,
        "relation_kb_covered_count": int(relation_kb_covered_count),
        "relation_kb_total_count": int(relation_kb_total_count),
        "declared_industry_ids": list(declared_industry_ids),
        "direct_evidence_group_count": direct_groups_count,
        "direct_evidence_occurrence_count": direct_occurrences,
        "relation_positive_count": relation_positive,
        "relation_undetermined_count": relation_undetermined,
        "relation_known_none_count": relation_known_none,
        "ai_eligible_count": ai_eligible,
        "insufficient_count": insufficient,
        "relation_not_known_treated_as_none": False,
        "coverage_contract": "industry-coverage-contract-v1",
    }
