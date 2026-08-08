"""Gate F1.2 shadow contract: case-level business trace synthesis (Layer C).

The case layer combines transaction-level Industry Direct Relation (B1) and
Business Evidence Role / Trace Strength (B2) into two distinct questions:

    business_activity_presence      = does the customer visibly run a business?
    declared_industry_consistency   = does the activity match the *declared*
                                      industry?

Rules are explainable and conservative. Simple strength summation
(weak+weak+weak=strong) is forbidden; independence, recurrence, temporal
consistency, directional consistency and counterparty/evidence diversity are
considered instead.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .evidence import BUSINESS_EVIDENCE_CONTRACT_VERSION


CASE_TRACE_RESOLVER_VERSION = "case-trace-resolver-v1"

_POSITIVE_STRENGTHS = {"strong", "medium"}
_WEAK_STRENGTHS = {"weak"}


def _month_key(value: Any) -> str:
    text = str(value or "")
    if len(text) >= 7 and text[:4].isdigit():
        return text[:7]
    return text[:7] if len(text) >= 7 else ""


def _counterparty_digest(fields: Mapping[str, Any]) -> str:
    import hashlib
    import json

    value = str(fields.get("counterparty_name") or fields.get("merchant_name") or "")
    if not value.strip():
        return ""
    return hashlib.sha256(
        json.dumps(
            value.strip().casefold(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:16]


class CaseTraceResolver:
    """Deterministic, explainable case-level synthesis (shadow only)."""

    version = CASE_TRACE_RESOLVER_VERSION

    def synthesize(
        self,
        entries: Sequence[Mapping[str, Any]],
        *,
        case_context: Mapping[str, object] | None = None,
        profile_name: str = "",
    ) -> dict[str, Any]:
        families: dict[str, dict[str, Any]] = {}
        total = 0

        for entry in entries:
            total += 1
            role = str(entry.get("role") or "unknown")
            strength = str(entry.get("trace_strength") or "undetermined")
            group_key = str(entry.get("evidence_group_key") or f"{role}|unknown")
            family = families.setdefault(
                role,
                {
                    "groups": set(),
                    "occurrences": 0,
                    "positive_occurrences": 0,
                    "weak_occurrences": 0,
                    "months": set(),
                    "counterparties": set(),
                    "directions": Counter(),
                    "samples": [],
                },
            )
            family["groups"].add(group_key)
            family["occurrences"] += 1
            family["months"].add(_month_key(entry.get("occurred_at") or ""))
            family["counterparties"].add(
                _counterparty_digest(entry.get("fields") or {})
            )
            family["directions"][str(entry.get("direction") or "")] += 1
            if strength in _POSITIVE_STRENGTHS:
                family["positive_occurrences"] += 1
            elif strength in _WEAK_STRENGTHS:
                family["weak_occurrences"] += 1
            if len(family["samples"]) < 5:
                family["samples"].append(
                    {
                        "transaction_id": str(entry.get("transaction_id") or ""),
                        "role": role,
                        "trace_strength": strength,
                        "industry_relevance": str(
                            entry.get("industry_relevance") or ""
                        ),
                        "direction": str(entry.get("direction") or ""),
                        "amount": str(entry.get("amount") or ""),
                        "occurred_at": str(entry.get("occurred_at") or ""),
                        "evidence_group_key": group_key,
                        "safe_semantic_evidence": entry.get("fields") or {},
                    }
                )

        positive_families = {
            role: fam
            for role, fam in families.items()
            if fam["positive_occurrences"] > 0
        }
        weak_families = {
            role: fam
            for role, fam in families.items()
            if fam["weak_occurrences"] > 0 and fam["positive_occurrences"] == 0
        }
        direct = families.get("direct_business")
        direct_groups = len(direct["groups"]) if direct else 0
        direct_occurrences = direct["occurrences"] if direct else 0
        direct_positive = direct["positive_occurrences"] if direct else 0

        distinct_positive_groups = len(
            set().union(*(fam["groups"] for fam in positive_families.values()))
            if positive_families
            else set()
        )
        recurrence_months = max(
            (len(fam["months"]) for fam in positive_families.values()),
            default=0,
        )
        counterparty_count = len(
            set().union(
                *(fam["counterparties"] for fam in positive_families.values())
            )
            if positive_families
            else set()
        )
        raw_occurrences = sum(fam["occurrences"] for fam in families.values())
        group_occurrences = sum(len(fam["groups"]) for fam in families.values())

        # Direct industry trace: only direct_business evidence can directly
        # support the declared industry; indirect evidence cannot.
        if direct and direct_groups:
            direct_industry_strengths = [
                str(item.get("industry_relevance") or "")
                for item in direct["samples"]
            ]
            if "strong" in direct_industry_strengths:
                direct_industry_trace = "strong"
            elif "medium" in direct_industry_strengths:
                direct_industry_trace = "medium"
            elif "weak" in direct_industry_strengths:
                direct_industry_trace = "weak"
            else:
                # Direct business evidence exists, but no positive tie to the
                # declared industry; this can only support a weak consistency.
                direct_industry_trace = "weak"
        else:
            direct_industry_trace = "undetermined"

        # Business activity presence (explainable rule table, no scoring).
        if len(positive_families) >= 3 and distinct_positive_groups >= 5:
            business_activity_presence = "strong"
        elif len(positive_families) >= 2 and recurrence_months >= 2:
            business_activity_presence = "strong"
        elif len(positive_families) >= 2 or distinct_positive_groups >= 2:
            business_activity_presence = "medium"
        elif positive_families:
            business_activity_presence = "weak"
        elif weak_families:
            business_activity_presence = "weak"
        else:
            business_activity_presence = "undetermined"

        # Declared industry consistency: never stronger than direct industry
        # trace, and requires at least some direct evidence.
        if direct_industry_trace == "strong":
            declared_industry_consistency = "strong"
        elif direct_industry_trace == "medium":
            declared_industry_consistency = "medium"
        elif direct_industry_trace == "weak":
            declared_industry_consistency = "weak"
        else:
            declared_industry_consistency = "undetermined"

        contradictions: list[str] = []
        if (
            "personal_consumption" in families
            and families["personal_consumption"]["occurrences"] > 0
            and "direct_business" in families
            and families["direct_business"]["positive_occurrences"] > 0
        ):
            contradictions.append(
                "同时存在直接经营证据与个人消费证据；个人消费不计入经营证据"
            )
        if (
            business_activity_presence in {"strong", "medium"}
            and declared_industry_consistency in {"weak", "undetermined"}
        ):
            contradictions.append(
                "存在经营活动证据，但申报行业未得到直接交易印证"
            )

        unresolved_areas: list[str] = []
        unknown = families.get("unknown")
        neutral = families.get("neutral_transfer")
        if unknown and unknown["occurrences"]:
            unresolved_areas.append(
                f"unknown={unknown['occurrences']}（证据不足无法判断角色）"
            )
        if neutral and neutral["occurrences"]:
            unresolved_areas.append(
                f"neutral_transfer={neutral['occurrences']}（纯资金移动不构成经营证据）"
            )

        supporting_roles = sorted(positive_families)
        indirect_groups = [
            {
                "role": role,
                "group_count": len(fam["groups"]),
                "occurrence_count": fam["occurrences"],
                "positive_occurrence_count": fam["positive_occurrences"],
                "month_count": len(fam["months"]),
                "counterparty_count": len(fam["counterparties"]),
                "directions": dict(fam["directions"]),
            }
            for role, fam in sorted(families.items())
            if role != "direct_business"
            and fam["positive_occurrences"] + fam["weak_occurrences"] > 0
        ]

        return {
            "case_business_trace": business_activity_presence,
            "business_activity_presence": business_activity_presence,
            "declared_industry_consistency": declared_industry_consistency,
            "direct_industry_trace": direct_industry_trace,
            "supporting_evidence_roles": supporting_roles,
            "direct_business_evidence_count": direct_occurrences,
            "direct_business_group_count": direct_groups,
            "direct_business_positive_count": direct_positive,
            "indirect_evidence_groups": indirect_groups,
            "evidence_diversity": {
                "positive_family_count": len(positive_families),
                "distinct_positive_group_count": distinct_positive_groups,
                "recurrence_month_max": recurrence_months,
                "counterparty_diversity_count": counterparty_count,
            },
            "dedup": {
                "raw_occurrences": raw_occurrences,
                "group_occurrences": group_occurrences,
                "duplicate_suppressed_count": raw_occurrences - group_occurrences,
            },
            "personal_non_business": {
                "occurrence_count": families.get(
                    "personal_consumption",
                    {},
                ).get("occurrences", 0),
                "group_count": len(
                    families.get("personal_consumption", {}).get("groups", set())
                ),
            },
            "unknown": {
                "occurrence_count": unknown["occurrences"] if unknown else 0,
                "group_count": len(unknown["groups"]) if unknown else 0,
            },
            "neutral_transfer": {
                "occurrence_count": neutral["occurrences"] if neutral else 0,
                "group_count": len(neutral["groups"]) if neutral else 0,
            },
            "contradictions": contradictions,
            "unresolved_areas": unresolved_areas,
            "reason": self._reason_text(
                business_activity_presence=business_activity_presence,
                declared_industry_consistency=declared_industry_consistency,
                positive_families=len(positive_families),
                positive_groups=distinct_positive_groups,
                direct_groups=direct_groups,
                recurrence=recurrence_months,
            ),
            "contract_version": BUSINESS_EVIDENCE_CONTRACT_VERSION,
            "case_trace_resolver_version": self.version,
            "case_context_used": bool(case_context),
            "profile_name": profile_name,
            "evidence_families": {
                role: {
                    "group_count": len(fam["groups"]),
                    "occurrence_count": fam["occurrences"],
                    "positive_occurrence_count": fam["positive_occurrences"],
                    "weak_occurrence_count": fam["weak_occurrences"],
                    "month_count": len(fam["months"]),
                    "counterparty_count": len(fam["counterparties"]),
                    "directions": dict(fam["directions"]),
                    "samples": fam["samples"],
                }
                for role, fam in sorted(families.items())
            },
            "total_entries": total,
        }

    @staticmethod
    def _reason_text(
        *,
        business_activity_presence: str,
        declared_industry_consistency: str,
        positive_families: int,
        positive_groups: int,
        direct_groups: int,
        recurrence: int,
    ) -> str:
        parts = [
            f"经营存在={business_activity_presence}",
            f"申报行业一致性={declared_industry_consistency}",
            f"正向证据族={positive_families}、去重证据组={positive_groups}、"
            f"直接经营证据组={direct_groups}、跨月复现={recurrence}",
        ]
        return "；".join(parts)
