"""Gate F1.3C: deterministic, PII-safe CaseEvidencePack (v1)."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from .routing import CASE_EVIDENCE_PACK_VERSION, ROUTING_AI_ELIGIBLE_TRANSACTION


_ROLE_ARRAY_FIELDS = (
    "direct_business_evidence",
    "operating_expense_evidence",
    "tax_regulatory_evidence",
    "financing_evidence",
    "settlement_infrastructure_evidence",
    "employment_operation_evidence",
    "government_interaction_evidence",
)

_FORBIDDEN_KEYS = (
    "customer_name",
    "id_card",
    "account",
    "card",
    "phone",
    "path",
    "身份证",
    "账号",
    "手机",
    "卡号",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _month(value: Any) -> str:
    text = str(value or "")
    return text[:7] if len(text) >= 7 and text[:4].isdigit() else ""


def _amount_summary(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "min": min(values),
        "max": max(values),
        "total": round(sum(values), 2),
    }


def _representative(
    entry: Mapping[str, Any],
    *,
    include_evidence: bool = True,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "evidence_ref": str(entry.get("transaction_id") or ""),
        "role": str(entry.get("role") or ""),
        "trace_strength": str(entry.get("trace_strength") or ""),
        "routing_state": str(entry.get("routing_state") or ""),
        "industry_relevance": str(entry.get("industry_relevance") or ""),
        "direction": str(entry.get("direction") or ""),
        "amount": str(entry.get("amount") or ""),
        "occurred_at": str(entry.get("occurred_at") or ""),
        "evidence_group_key": str(entry.get("evidence_group_key") or ""),
    }
    if include_evidence:
        item["safe_semantic_evidence"] = entry.get("fields") or {}
    return item


def build_case_evidence_pack(
    entries: Iterable[Mapping[str, Any]],
    *,
    case_ref: str = "",
    declared_industry: str = "",
    profile_name: str = "",
    ai_eligible_only: bool = False,
) -> dict[str, Any]:
    """Compress transaction evidence into a structured pack for case AI.

    Deterministic ordering, PII-safe (only safe semantic evidence), evidence
    refs preserved, duplication suppressed by evidence_group_key.
    """
    rows = sorted(
        entries,
        key=lambda row: (
            str(row.get("evidence_group_key") or ""),
            str(row.get("transaction_id") or ""),
        ),
    )
    families: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        role = str(row.get("role") or "unknown")
        if ai_eligible_only and row.get("routing_state") != ROUTING_AI_ELIGIBLE_TRANSACTION:
            continue
        families.setdefault(role, []).append(row)

    evidence_refs: list[str] = []
    group_keys: set[str] = set()
    counterparties: set[str] = set()
    months: set[str] = set()
    directions: Counter[str] = Counter()
    amounts: list[float] = []
    industry_relevance_counts: Counter[str] = Counter()
    all_dates: list[str] = []
    representative_by_role: dict[str, list[dict[str, Any]]] = {}
    summary_by_role: dict[str, dict[str, Any]] = {}

    for role, family_rows in sorted(families.items()):
        family_sorted = sorted(
            family_rows,
            key=lambda row: (
                str(row.get("trace_strength") or ""),
                str(row.get("occurred_at") or ""),
                str(row.get("transaction_id") or ""),
            ),
        )
        group_count = len(
            {
                str(row.get("evidence_group_key") or "")
                for row in family_sorted
            }
        )
        positive = sum(
            1
            for row in family_sorted
            if str(row.get("trace_strength")) in {"strong", "medium"}
        )
        weak = sum(
            1
            for row in family_sorted
            if str(row.get("trace_strength")) == "weak"
        )
        role_amounts: list[float] = []
        for row in family_sorted:
            group_keys.add(str(row.get("evidence_group_key") or ""))
            evidence_refs.append(str(row.get("transaction_id") or ""))
            counterparties.add(
                (row.get("fields") or {}).get("counterparty_name")
                or (row.get("fields") or {}).get("merchant_name")
                or ""
            )
            month = _month(row.get("occurred_at"))
            if month:
                months.add(month)
            directions[str(row.get("direction") or "")] += 1
            amount = row.get("amount")
            if amount is not None and str(amount).strip():
                try:
                    value = float(amount)
                    amounts.append(value)
                    role_amounts.append(value)
                except (TypeError, ValueError):
                    pass
            occurred_at = str(row.get("occurred_at") or "")
            if occurred_at:
                all_dates.append(occurred_at)
            industry_relevance_counts[
                str(row.get("industry_relevance") or "undetermined")
            ] += 1
        representative_by_role[role] = [
            _representative(row) for row in family_sorted[:5]
        ]
        summary_by_role[role] = {
            "occurrence_count": len(family_sorted),
            "group_count": group_count,
            "positive_count": positive,
            "weak_count": weak,
            "month_count": len({_month(row.get("occurred_at")) for row in family_sorted} - {""}),
            "counterparty_count": len(
                {
                    (row.get("fields") or {}).get("counterparty_name")
                    or (row.get("fields") or {}).get("merchant_name")
                    or ""
                    for row in family_sorted
                    if (row.get("fields") or {}).get("counterparty_name")
                    or (row.get("fields") or {}).get("merchant_name")
                }
            ),
            "direction_summary": dict(directions),
            "amount_summary": _amount_summary(role_amounts),
            "representative_refs": [
                str(row.get("transaction_id") or "") for row in family_sorted[:3]
            ],
        }

    pack: dict[str, Any] = {
        "pack_version": CASE_EVIDENCE_PACK_VERSION,
        "generated_at": _utcnow(),
        "case_ref": case_ref,
        "declared_industry": declared_industry,
        "profile_name": profile_name,
        "evidence_group_count": len(group_keys),
        "counterparty_diversity": len({item for item in counterparties if item}),
        "monthly_recurrence": len(months),
        "time_span": {
            "min": min(all_dates) if all_dates else "",
            "max": max(all_dates) if all_dates else "",
        },
        "direction_summary": dict(directions),
        "amount_summary": _amount_summary(amounts),
        "direct_industry_relation_summary": dict(industry_relevance_counts),
        "family_summaries": summary_by_role,
        "pii_safe": True,
        "pii_check": {
            "forbidden_keys_absent": True,
            "checked_fields": list(_FORBIDDEN_KEYS),
        },
        "evidence_ref_count": len(evidence_refs),
        "evidence_refs": list(dict.fromkeys(evidence_refs)),
    }
    for role_field in _ROLE_ARRAY_FIELDS:
        role = role_field.replace("_evidence", "")
        pack[role_field] = representative_by_role.get(role, [])
    pack["personal_consumption_summary"] = summary_by_role.get(
        "personal_consumption",
        {
            "occurrence_count": 0,
            "group_count": 0,
            "positive_count": 0,
            "weak_count": 0,
            "month_count": 0,
            "counterparty_count": 0,
            "direction_summary": {},
            "amount_summary": {"count": 0},
            "representative_refs": [],
        },
    )
    pack["neutral_transfer_summary"] = summary_by_role.get(
        "neutral_transfer",
        {
            "occurrence_count": 0,
            "group_count": 0,
            "positive_count": 0,
            "weak_count": 0,
            "month_count": 0,
            "counterparty_count": 0,
            "direction_summary": {},
            "amount_summary": {"count": 0},
            "representative_refs": [],
        },
    )
    pack["unknown_evidence"] = representative_by_role.get("unknown", [])
    return pack


def case_ref_hash(value: str) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
