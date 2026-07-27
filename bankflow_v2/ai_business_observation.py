"""Provider-neutral AI business-relevance observation with deterministic fallback."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from .models import Transaction
from .mvp_observations import is_informative_text
from .summary import sort_transactions


AI_PROMPT_VERSION = "business-relevance-mvp-v5"
AI_CLASSIFICATIONS = {
    "directly_related",
    "possibly_related",
    "no_relation_evidence",
    "undetermined",
}
AI_INPUT_FIELDS = (
    "counterparty_name",
    "summary",
    "remark",
    "purpose",
    "product_description",
    "merchant_name",
    "merchant_category",
)
AI_EVIDENCE_STRENGTHS = {"strong", "medium", "weak", "none"}
AI_SEMANTIC_EVIDENCE_FIELDS = {
    "counterparty_name",
    "summary",
    "remark",
    "purpose",
    "product_description",
    "merchant_name",
    "merchant_category",
}
AI_DIRECT_EVIDENCE_FIELDS = {
    "summary",
    "remark",
    "purpose",
    "product_description",
    "merchant_category",
}
_ORGANIZATION_MARKERS = (
    "公司",
    "集团",
    "商行",
    "经营部",
    "门市部",
    "银行",
    "税务",
    "医院",
    "超市",
    "商店",
    "中心",
    "厂",
    "店",
)
_FINANCIAL_INFRASTRUCTURE_MARKERS = (
    "银行",
    "财付通支付",
    "支付宝",
    "银联",
    "零钱通",
)
_GENERIC_SUMMARY_RE = re.compile(
    r"^(?:跨行)?(?:汇款|转账|网转|ATM取款|微信零钱提现|利息|结息)$",
    re.IGNORECASE,
)


def _values(case_context: Mapping[str, object] | None, field_name: str) -> list[str]:
    if not isinstance(case_context, Mapping):
        return []
    search_context = case_context.get("search_context")
    if not isinstance(search_context, Mapping):
        return []
    values = search_context.get(field_name, [])
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _anchors(case_context: Mapping[str, object] | None) -> list[str]:
    return list(
        dict.fromkeys(
            _values(case_context, "work_units")
            + _values(case_context, "declared_industries")
        )
    )


def _reliable_fields(transaction: Transaction) -> dict[str, str]:
    return {
        field_name: str(getattr(transaction, field_name) or "").strip()
        for field_name in AI_INPUT_FIELDS
        if str(getattr(transaction, field_name) or "").strip()
        and transaction.field_confidence.get(field_name) == 1.0
    }


def _contains_exact_anchor(value: str, anchors: list[str]) -> list[str]:
    compact = re.sub(r"\s+", "", value).casefold()
    return [
        anchor
        for anchor in anchors
        if re.sub(r"\s+", "", anchor).casefold() in compact
    ]


def _deterministic_candidates(
    transactions: list[Transaction],
    anchors: list[str],
) -> tuple[list[dict[str, object]], set[str]]:
    candidates: list[dict[str, object]] = []
    matched_ids: set[str] = set()
    for transaction in sort_transactions(transactions):
        fields = _reliable_fields(transaction)
        field_matches = {
            field_name: _contains_exact_anchor(value, anchors)
            for field_name, value in fields.items()
        }
        field_matches = {
            field_name: matches
            for field_name, matches in field_matches.items()
            if matches
        }
        if not field_matches:
            continue
        matched_ids.add(transaction.transaction_id)
        candidates.append(
            {
                "transaction_id": transaction.transaction_id,
                "classification": "directly_related",
                "decision_source": "deterministic_exact_match",
                "reason": "可靠标准字段精确包含案件中显式申报的单位或行业词，仅表示文字直接命中。",
                "used_fields": sorted(field_matches),
                "matched_anchors": sorted(
                    {anchor for matches in field_matches.values() for anchor in matches}
                ),
                "evidence_locator": transaction.evidence_locator,
            }
        )
    return candidates, matched_ids


def _safe_ai_fields(
    fields: Mapping[str, str],
    allow_business_names: bool,
) -> dict[str, str]:
    safe: dict[str, str] = {}
    for field_name, value in fields.items():
        if field_name not in {"counterparty_name", "merchant_name"}:
            safe[field_name] = value
            continue
        if allow_business_names and any(marker in value for marker in _ORGANIZATION_MARKERS):
            safe[field_name] = value
    return safe


def _ai_semantic_evidence_fields(fields: Mapping[str, str]) -> list[str]:
    evidence_fields: list[str] = []
    for field_name, value in fields.items():
        if (
            field_name not in AI_SEMANTIC_EVIDENCE_FIELDS
            or not is_informative_text(value)
        ):
            continue
        normalized = re.sub(r"[\s\d]+", "", value).strip("()（）[]【】")
        if field_name == "summary" and _GENERIC_SUMMARY_RE.fullmatch(normalized):
            continue
        if (
            field_name in {"counterparty_name", "merchant_name"}
            and any(marker in normalized for marker in _FINANCIAL_INFRASTRUCTURE_MARKERS)
        ):
            continue
        evidence_fields.append(field_name)
    return evidence_fields


def _has_ai_semantic_evidence(fields: Mapping[str, str]) -> bool:
    return bool(_ai_semantic_evidence_fields(fields))


def _ai_semantic_signature(fields: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    evidence_fields = _ai_semantic_evidence_fields(fields)
    return tuple(
        sorted(
            (
                field_name,
                re.sub(r"\s+", "", str(fields[field_name])).casefold(),
            )
            for field_name in evidence_fields
        )
    )


def _payload_records(
    transactions: list[Transaction],
    deterministic_ids: set[str],
    allow_business_names: bool,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for transaction in sort_transactions(transactions):
        if transaction.transaction_id in deterministic_ids:
            continue
        fields = _safe_ai_fields(
            _reliable_fields(transaction),
            allow_business_names,
        )
        if not fields or not _has_ai_semantic_evidence(fields):
            continue
        records.append(
            {
                "transaction_id": transaction.transaction_id,
                "fields": fields,
            }
        )
    return records


def build_ai_input_profile(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
    *,
    allow_business_names: bool,
) -> dict[str, object]:
    """Describe eligible AI inputs and their reliable field coverage without calling AI."""
    anchors = _anchors(case_context)
    deterministic, deterministic_ids = _deterministic_candidates(
        transactions,
        anchors,
    )
    records = _payload_records(
        transactions,
        deterministic_ids,
        allow_business_names,
    )
    transaction_by_id = {
        transaction.transaction_id: transaction
        for transaction in transactions
        if transaction.transaction_id
    }
    source_transaction_counts = Counter(
        transaction.source_file_id for transaction in transactions
    )
    source_profiles: dict[str, dict[str, object]] = {}
    total_input_fields: Counter[str] = Counter()
    total_evidence_fields: Counter[str] = Counter()
    total_signatures: set[tuple[tuple[str, str], ...]] = set()
    for record in records:
        transaction = transaction_by_id.get(str(record["transaction_id"]))
        if transaction is None:
            continue
        fields = record["fields"]
        if not isinstance(fields, Mapping):
            continue
        evidence_fields = _ai_semantic_evidence_fields(
            {str(name): str(value) for name, value in fields.items()}
        )
        signature = _ai_semantic_signature(
            {str(name): str(value) for name, value in fields.items()}
        )
        total_signatures.add(signature)
        total_input_fields.update(str(name) for name in fields)
        total_evidence_fields.update(evidence_fields)
        profile = source_profiles.setdefault(
            transaction.source_file_id,
            {
                "source_file_id": transaction.source_file_id,
                "source_file": transaction.source_file,
                "bank": transaction.bank,
                "transaction_count": source_transaction_counts[
                    transaction.source_file_id
                ],
                "ai_candidate_count": 0,
                "input_field_counts": Counter(),
                "semantic_evidence_field_counts": Counter(),
                "semantic_signatures": set(),
            },
        )
        profile["ai_candidate_count"] = int(profile["ai_candidate_count"]) + 1
        profile["input_field_counts"].update(str(name) for name in fields)
        profile["semantic_evidence_field_counts"].update(evidence_fields)
        profile["semantic_signatures"].add(signature)

    sources: list[dict[str, object]] = []
    for profile in source_profiles.values():
        sources.append(
            {
                **{
                    key: value
                    for key, value in profile.items()
                    if key
                    not in {
                        "input_field_counts",
                        "semantic_evidence_field_counts",
                        "semantic_signatures",
                    }
                },
                "input_field_counts": dict(
                    sorted(profile["input_field_counts"].items())
                ),
                "semantic_evidence_field_counts": dict(
                    sorted(profile["semantic_evidence_field_counts"].items())
                ),
                "unique_semantic_signature_count": len(
                    profile["semantic_signatures"]
                ),
                "reusable_duplicate_candidate_count": (
                    int(profile["ai_candidate_count"])
                    - len(profile["semantic_signatures"])
                ),
            }
        )
    return {
        "transaction_count": len(transactions),
        "deterministic_exact_match_count": len(deterministic),
        "ai_candidate_count": len(records),
        "unique_semantic_signature_count": len(total_signatures),
        "reusable_duplicate_candidate_count": len(records) - len(total_signatures),
        "input_field_counts": dict(sorted(total_input_fields.items())),
        "semantic_evidence_field_counts": dict(
            sorted(total_evidence_fields.items())
        ),
        "sources": sorted(
            sources,
            key=lambda item: (
                str(item["bank"]),
                str(item["source_file"]),
            ),
        ),
    }


def select_ai_input_sample(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
    *,
    allow_business_names: bool,
    sample_size: int,
    source_balanced: bool = False,
    unique_semantic_signatures: bool = False,
) -> tuple[list[Transaction], int]:
    """Select an evenly distributed, reproducible sample of eligible AI inputs."""
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    anchors = _anchors(case_context)
    _, deterministic_ids = _deterministic_candidates(transactions, anchors)
    records = _payload_records(
        transactions,
        deterministic_ids,
        allow_business_names,
    )
    transaction_by_id = {
        transaction.transaction_id: transaction
        for transaction in transactions
        if transaction.transaction_id
    }
    eligible: list[Transaction] = []
    seen_signatures: set[tuple[tuple[str, str], ...]] = set()
    for record in records:
        transaction = transaction_by_id.get(str(record["transaction_id"]))
        fields = record.get("fields")
        if transaction is None or not isinstance(fields, Mapping):
            continue
        signature = _ai_semantic_signature(
            {str(name): str(value) for name, value in fields.items()}
        )
        if unique_semantic_signatures and signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        eligible.append(transaction)
    total = len(eligible)
    if total <= sample_size:
        return eligible, total
    if source_balanced:
        groups: dict[str, list[Transaction]] = {}
        for transaction in eligible:
            groups.setdefault(transaction.source_file_id, []).append(transaction)
        quotas = {
            source_file_id: min(len(rows), sample_size // len(groups))
            for source_file_id, rows in groups.items()
        }
        remaining = sample_size - sum(quotas.values())
        while remaining:
            progressed = False
            for source_file_id, rows in groups.items():
                if quotas[source_file_id] >= len(rows):
                    continue
                quotas[source_file_id] += 1
                remaining -= 1
                progressed = True
                if remaining == 0:
                    break
            if not progressed:
                break
        selected: list[Transaction] = []
        for source_file_id, rows in groups.items():
            quota = quotas[source_file_id]
            if quota == 1:
                selected.append(rows[len(rows) // 2])
                continue
            indexes = [
                position * (len(rows) - 1) // (quota - 1)
                for position in range(quota)
            ]
            selected.extend(rows[index] for index in indexes)
        return sort_transactions(selected), total
    if sample_size == 1:
        return [eligible[total // 2]], total
    indexes = [
        position * (total - 1) // (sample_size - 1)
        for position in range(sample_size)
    ]
    return [eligible[index] for index in indexes], total


def _validate_response(
    response: object,
    records: list[dict[str, object]],
) -> list[dict[str, object]] | None:
    if not isinstance(response, list):
        return None
    by_id = {str(record["transaction_id"]): record for record in records}
    validated: list[dict[str, object]] = []
    seen: set[str] = set()
    for item in response:
        if not isinstance(item, Mapping):
            return None
        transaction_id = str(item.get("transaction_id", ""))
        classification = str(item.get("classification", ""))
        reason = str(item.get("reason", "")).strip()
        used_fields = item.get("used_fields", [])
        default_strength = (
            "strong"
            if classification == "directly_related"
            else "medium"
            if classification == "possibly_related"
            else "none"
        )
        evidence_strength = str(
            item.get("evidence_strength", default_strength)
        )
        if (
            transaction_id not in by_id
            or transaction_id in seen
            or classification not in AI_CLASSIFICATIONS
            or evidence_strength not in AI_EVIDENCE_STRENGTHS
            or not reason
            or not isinstance(used_fields, list)
        ):
            return None
        if (
            (classification == "directly_related" and evidence_strength != "strong")
            or (
                classification == "possibly_related"
                and evidence_strength not in {"medium", "weak"}
            )
            or (
                classification in {"no_relation_evidence", "undetermined"}
                and evidence_strength != "none"
            )
        ):
            return None
        allowed_fields = set(by_id[transaction_id]["fields"])
        normalized_fields = [str(field_name) for field_name in used_fields]
        if not normalized_fields or not set(normalized_fields).issubset(allowed_fields):
            return None
        if (
            classification in {"directly_related", "possibly_related"}
            and not set(normalized_fields).intersection(AI_SEMANTIC_EVIDENCE_FIELDS)
        ):
            return None
        if (
            classification == "directly_related"
            and not set(normalized_fields).intersection(AI_DIRECT_EVIDENCE_FIELDS)
        ):
            return None
        seen.add(transaction_id)
        validated.append(
            {
                "transaction_id": transaction_id,
                "classification": classification,
                "evidence_strength": evidence_strength,
                "decision_source": "ai_model",
                "reason": reason,
                "used_fields": normalized_fields,
            }
        )
    return validated if seen == set(by_id) else None


def build_ai_business_observation(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
    ai_config: Mapping[str, object] | None = None,
    evaluator: Callable[[dict[str, object]], object] | None = None,
) -> dict[str, object]:
    """Build a guarded AI observation; never performs a provider call itself."""
    config = dict(ai_config or {})
    anchors = _anchors(case_context)
    deterministic, deterministic_ids = _deterministic_candidates(
        transactions,
        anchors,
    )
    records = _payload_records(
        transactions,
        deterministic_ids,
        bool(config.get("allow_business_names")),
    )
    reason = ""
    ai_candidates: list[dict[str, object]] = []

    if not anchors:
        reason = "case_business_context_unavailable"
    elif not config.get("enabled") or not config.get("data_authorized"):
        reason = "ai_data_authorization_missing"
    elif not config.get("retention_policy_confirmed"):
        reason = "ai_retention_policy_unconfirmed"
    elif not config.get("provider") or not config.get("model"):
        reason = "ai_provider_configuration_missing"
    elif config.get("api_key_available") is False:
        reason = "ai_api_key_missing"
    elif not records:
        reason = "ai_input_candidates_unavailable"
    elif evaluator is None:
        reason = "ai_provider_unavailable"
    else:
        payload = {
            "prompt_version": AI_PROMPT_VERSION,
            "business_context": {
                "declared_industries": _values(
                    case_context, "declared_industries"
                ),
                "declared_work_units": (
                    _values(case_context, "work_units")
                    if config.get("allow_business_names")
                    else []
                ),
            },
            "allowed_classifications": sorted(AI_CLASSIFICATIONS),
            "allowed_evidence_strengths": sorted(AI_EVIDENCE_STRENGTHS),
            "transactions": records,
            "instructions": [
                "只能引用输入中的交易ID和字段。",
                "不得判断真实经营、欺诈、包装、准入或拒绝。",
                "必须联合查看同一交易提供的全部语义字段。",
                "明确出现申报行业商品、服务或用途时可判directly_related且evidence_strength为strong。",
                "名称中有具体行业产品或服务、但用途不确定时判possibly_related且evidence_strength为medium。",
                "实业、贸易、科技、工业、工程等泛化企业类型或货款只能作为possibly_related弱提示，evidence_strength必须为weak，理由必须说明缺少具体产品或用途。",
                "reason必须与classification一致；possibly_related的理由不得写成直接相关。",
                "证据不足时使用undetermined。",
            ],
        }
        try:
            response = evaluator(payload)
        except Exception:
            reason = "ai_provider_failed"
        else:
            validated = _validate_response(response, records)
            if validated is None:
                reason = "ai_response_invalid"
            else:
                ai_candidates = validated

    evidence_ids = [
        str(item["transaction_id"])
        for item in [*deterministic, *ai_candidates]
        if item.get("transaction_id")
    ]
    return {
        "observation_type": "ai_business_relevance_candidates",
        "value": {
            "available": not reason,
            "reason": reason,
            "deterministic_candidates": deterministic,
            "ai_candidates": ai_candidates,
            "ai_input_candidate_count": len(records),
        },
        "parameters": {
            "prompt_version": AI_PROMPT_VERSION,
            "provider": str(config.get("provider", "")),
            "model": str(config.get("model", "")),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "data_authorized": bool(config.get("data_authorized")),
            "retention_policy_confirmed": bool(
                config.get("retention_policy_confirmed")
            ),
            "allow_business_names": bool(config.get("allow_business_names")),
            "provider_call_implemented_here": False,
            "interpretation": "AI结果仅为可复核经营关联候选，不表示真实经营、欺诈、包装或准入结论。",
        },
        "evidence_transaction_ids": list(dict.fromkeys(evidence_ids)),
        "field_coverage": {
            "required_fields": [*AI_INPUT_FIELDS, "field_confidence"],
            "eligible_transaction_count": len(transactions),
            "covered_transaction_count": len(records) + len(deterministic),
        },
    }
