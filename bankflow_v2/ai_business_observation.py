"""Provider-neutral AI business-relevance observation with deterministic fallback."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from datetime import datetime, timezone

from .models import Transaction
from .mvp_observations import is_informative_text
from .summary import sort_transactions


AI_PROMPT_VERSION = "business-relevance-mvp-v11"
AI_TASK_TYPE = "business_relevance"
AI_OUTPUT_CONTRACT_VERSION = "semantic-judgement-v2"
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
AI_TRACEABLE_STANDARD_TEXT_FIELDS = (
    *AI_INPUT_FIELDS,
    "transaction_type",
    "transaction_method",
    "payment_method",
)
AI_EVIDENCE_STRENGTHS = {"strong", "medium", "weak", "none"}
AI_MODEL_JUDGEMENTS = {
    "strong",
    "medium",
    "weak",
    "none",
    "undetermined",
}
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
_ASCII_CODE_RE = re.compile(r"^[a-z0-9._/-]+$", re.IGNORECASE)
_ASCII_CODE_PREFIX_RE = re.compile(r"^[a-z0-9._/-]{6,}(?=[\u3400-\u9fff])", re.IGNORECASE)
_ASCII_CODE_SUFFIX_RE = re.compile(r"(?<=[\u3400-\u9fff])[a-z0-9._/-]{6,}$", re.IGNORECASE)
_HASH_RE = re.compile(r"^(?:[a-f0-9]{16,}|[a-z0-9+/]{24,}={0,2})$", re.IGNORECASE)
_ORDER_NUMBER_RE = re.compile(
    r"(?:订单号?|order(?:id|no)?)\s*[:：#-]?\s*[a-z0-9._/-]{4,}",
    re.IGNORECASE,
)
_REFERENCE_NUMBER_RE = re.compile(
    r"(?:参考号?|流水号?|交易号?|凭证号?|reference|ref)\s*[:：#-]?\s*[a-z0-9._/-]{4,}",
    re.IGNORECASE,
)
_GENERIC_WEAK_TEXTS = {
    "货款",
    "采购款",
    "材料费",
    "技术咨询费",
    "咨询费",
}
_SPECIFIC_BUSINESS_RE = re.compile(
    r"建材|建筑材料|护栏|栏杆|围栏|塑木|园林|景观|环保|金属制品|"
    r"水利|水电|装修|设备|五金|施工|项目|工程款"
)
_LIFE_CATEGORY_PATTERNS = {
    "dining": re.compile(r"餐饮|饭店|餐厅|小吃|火锅|烧烤|奶茶|咖啡|美食|外卖"),
    "convenience_store": re.compile(r"便利店|商超|超市"),
    "telecom": re.compile(r"话费|流量充值|通信缴费|电信缴费"),
    "bank_fee": re.compile(r"银行年费|账户管理费|短信服务费"),
    "medical": re.compile(r"医院|门诊|药房|医疗|诊所"),
    "ride_hailing": re.compile(r"打车|网约车|出租车|滴滴出行"),
}
_STRENGTH_RANK = {
    "none": 0,
    "weak": 1,
    "medium": 2,
    "strong": 3,
}


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


def _reliable_trace_fields(transaction: Transaction) -> dict[str, str]:
    return {
        field_name: str(getattr(transaction, field_name) or "").strip()
        for field_name in AI_TRACEABLE_STANDARD_TEXT_FIELDS
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


def classify_nonsemantic_text(value: str) -> str:
    """Return a stable reason when text is an identifier rather than semantics."""
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    compact = re.sub(r"\s+", "", normalized)
    if not compact:
        return "empty"
    if _ORDER_NUMBER_RE.fullmatch(compact):
        return "order_number"
    if _REFERENCE_NUMBER_RE.fullmatch(compact):
        return "reference_number"
    if compact.isdecimal():
        return "pure_numeric_code"
    if _HASH_RE.fullmatch(compact):
        return "hash_like"
    if _ASCII_CODE_RE.fullmatch(compact):
        return "alphanumeric_code"
    return ""


def _sanitize_semantic_text(value: str) -> tuple[str, list[str]]:
    """Remove identifier-only fragments while preserving the original transaction."""
    normalized = str(value or "").strip()
    reason = classify_nonsemantic_text(normalized)
    if reason:
        return "", [reason]

    categories: list[str] = []
    cleaned = normalized
    for pattern, category in (
        (_ORDER_NUMBER_RE, "order_number"),
        (_REFERENCE_NUMBER_RE, "reference_number"),
    ):
        replaced = pattern.sub("", cleaned)
        if replaced != cleaned:
            categories.append(category)
            cleaned = replaced
    replaced = _ASCII_CODE_PREFIX_RE.sub("", cleaned)
    if replaced != cleaned:
        categories.append("alphanumeric_code")
        cleaned = replaced
    replaced = _ASCII_CODE_SUFFIX_RE.sub("", cleaned)
    if replaced != cleaned:
        categories.append("alphanumeric_code")
        cleaned = replaced
    cleaned = cleaned.strip(" \t,，;；:：-_/.")
    if not cleaned:
        return "", list(dict.fromkeys(categories or ["alphanumeric_code"]))
    return cleaned, list(dict.fromkeys(categories))


def analyze_ai_semantic_fields(
    fields: Mapping[str, str],
) -> dict[str, object]:
    """Normalize model fields and expose every deterministic exclusion."""
    usable_fields: dict[str, str] = {}
    excluded_fields: dict[str, list[str]] = {}
    transformed_fields: dict[str, list[str]] = {}
    for field_name, value in fields.items():
        if field_name not in AI_SEMANTIC_EVIDENCE_FIELDS:
            continue
        if not is_informative_text(value):
            excluded_fields[field_name] = ["uninformative_text"]
            continue
        normalized = re.sub(r"[\s\d]+", "", value).strip("()（）[]【】")
        if field_name == "summary" and _GENERIC_SUMMARY_RE.fullmatch(normalized):
            excluded_fields[field_name] = ["generic_summary"]
            continue
        if (
            field_name in {"counterparty_name", "merchant_name"}
            and any(marker in normalized for marker in _FINANCIAL_INFRASTRUCTURE_MARKERS)
        ):
            excluded_fields[field_name] = ["financial_infrastructure_name"]
            continue
        cleaned, categories = _sanitize_semantic_text(value)
        if categories:
            transformed_fields[field_name] = categories
        if not cleaned:
            excluded_fields[field_name] = categories or ["uninformative_text"]
            continue
        usable_fields[field_name] = cleaned
    return {
        "usable_fields": usable_fields,
        "excluded_fields": excluded_fields,
        "transformed_fields": transformed_fields,
    }


def _life_categories(fields: Mapping[str, str]) -> list[str]:
    combined = " ".join(str(value) for value in fields.values())
    return [
        category
        for category, pattern in _LIFE_CATEGORY_PATTERNS.items()
        if pattern.search(combined)
    ]


def _deterministic_life_category(fields: Mapping[str, str]) -> str:
    categories = _life_categories(fields)
    if not categories:
        return ""
    non_name_values = [
        value
        for field_name, value in fields.items()
        if field_name not in {"counterparty_name", "merchant_name"}
        and value not in _GENERIC_WEAK_TEXTS
    ]
    if any(_SPECIFIC_BUSINESS_RE.search(value) for value in non_name_values):
        return ""
    return categories[0]


def build_classification_constraints(
    fields: Mapping[str, str],
) -> dict[str, object]:
    """Generate non-overridable classification limits from normalized fields."""
    direct_fields = sorted(set(fields).intersection(AI_DIRECT_EVIDENCE_FIELDS))
    life_category = _deterministic_life_category(fields)
    if life_category:
        maximum_strength = "none"
    elif not fields:
        maximum_strength = "none"
    elif direct_fields:
        direct_values = [str(fields[field_name]) for field_name in direct_fields]
        only_generic_direct = all(
            value in _GENERIC_WEAK_TEXTS for value in direct_values
        )
        if only_generic_direct:
            name_values = [
                str(fields[field_name])
                for field_name in ("counterparty_name", "merchant_name")
                if field_name in fields
            ]
            maximum_strength = (
                "medium"
                if any(_SPECIFIC_BUSINESS_RE.search(value) for value in name_values)
                else "weak"
            )
        else:
            maximum_strength = "strong"
    else:
        maximum_strength = "medium"
    directly_allowed = maximum_strength == "strong"
    return {
        "directly_related_allowed": directly_allowed,
        "directly_related_evidence_fields": direct_fields if directly_allowed else [],
        "maximum_allowed_strength": maximum_strength,
        "deterministic_non_business_category": life_category,
    }


def _ai_semantic_evidence_fields(fields: Mapping[str, str]) -> list[str]:
    analysis = analyze_ai_semantic_fields(fields)
    usable_fields = analysis["usable_fields"]
    return list(usable_fields) if isinstance(usable_fields, Mapping) else []


def ai_semantic_signature(fields: Mapping[str, str]) -> tuple[tuple[str, str], ...]:
    analysis = analyze_ai_semantic_fields(fields)
    usable_fields = analysis["usable_fields"]
    if not isinstance(usable_fields, Mapping):
        return ()
    return tuple(
        sorted(
            (
                field_name,
                re.sub(r"\s+", "", str(value)).casefold(),
            )
            for field_name, value in usable_fields.items()
        )
    )


def _legacy_ai_semantic_signature(
    fields: Mapping[str, str],
) -> tuple[tuple[str, str], ...]:
    """Reproduce the v9 pre-code-filter signature for the 337-item audit."""
    signature: list[tuple[str, str]] = []
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
        signature.append(
            (
                field_name,
                re.sub(r"\s+", "", str(value)).casefold(),
            )
        )
    return tuple(sorted(signature))


def _payload_records(
    transactions: list[Transaction],
    deterministic_ids: set[str],
    allow_business_names: bool,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for transaction in sort_transactions(transactions):
        if transaction.transaction_id in deterministic_ids:
            continue
        if _deterministic_life_category(
            _reliable_trace_fields(transaction)
        ):
            continue
        fields = _safe_ai_fields(
            _reliable_fields(transaction),
            allow_business_names,
        )
        analysis = analyze_ai_semantic_fields(fields)
        usable_fields = analysis["usable_fields"]
        if not isinstance(usable_fields, Mapping):
            continue
        fields = {str(name): str(value) for name, value in usable_fields.items()}
        if not fields:
            continue
        constraints = build_classification_constraints(fields)
        if constraints["deterministic_non_business_category"]:
            continue
        records.append(
            {
                "transaction_id": transaction.transaction_id,
                "fields": fields,
                "classification_constraints": constraints,
            }
        )
    return records


def _deterministic_non_business_candidates(
    transactions: list[Transaction],
    excluded_ids: set[str],
    allow_business_names: bool,
) -> tuple[list[dict[str, object]], set[str]]:
    candidates: list[dict[str, object]] = []
    matched_ids: set[str] = set()
    for transaction in sort_transactions(transactions):
        if transaction.transaction_id in excluded_ids:
            continue
        trace_fields = _reliable_trace_fields(transaction)
        analysis = analyze_ai_semantic_fields(trace_fields)
        usable_fields = analysis["usable_fields"]
        if not isinstance(usable_fields, Mapping):
            continue
        normalized_fields = {
            str(name): str(value) for name, value in usable_fields.items()
        }
        category = _deterministic_life_category(trace_fields)
        if not category:
            continue
        matched_ids.add(transaction.transaction_id)
        candidates.append(
            {
                "transaction_id": transaction.transaction_id,
                "classification": "no_relation_evidence",
                "evidence_strength": "none",
                "decision_source": "deterministic_non_business_rule",
                "reason": "明确生活或通用服务类别由本地规则排除，不进入经营关联模型。",
                "used_fields": sorted(
                    field_name
                    for field_name, value in trace_fields.items()
                    if _life_categories({field_name: value})
                ),
                "category": category,
                "evidence_locator": transaction.evidence_locator,
            }
        )
    return candidates, matched_ids


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
        signature = ai_semantic_signature(
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


def semantic_signature_id(
    signature: tuple[tuple[str, str], ...],
) -> str:
    encoded = json.dumps(signature, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:24]


def build_ai_input_audit(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
    *,
    allow_business_names: bool,
    representative_limit: int = 5,
) -> dict[str, object]:
    """Audit the complete v9-era semantic set without invoking a provider."""
    anchors = _anchors(case_context)
    deterministic, deterministic_ids = _deterministic_candidates(
        transactions,
        anchors,
    )
    _, deterministic_non_business_ids = _deterministic_non_business_candidates(
        transactions,
        deterministic_ids,
        allow_business_names,
    )
    grouped: dict[
        tuple[tuple[str, str], ...],
        list[tuple[Transaction, dict[str, str]]],
    ] = {}
    legacy_candidate_count = 0
    for transaction in sort_transactions(transactions):
        if transaction.transaction_id in deterministic_ids:
            continue
        safe_fields = _safe_ai_fields(
            _reliable_fields(transaction),
            allow_business_names,
        )
        signature = _legacy_ai_semantic_signature(safe_fields)
        if not signature:
            continue
        legacy_candidate_count += 1
        grouped.setdefault(signature, []).append((transaction, safe_fields))

    category_signature_counts: Counter[str] = Counter()
    category_field_counts: Counter[str] = Counter()
    maximum_strength_counts: Counter[str] = Counter()
    directly_allowed_counts: Counter[str] = Counter()
    model_signatures: set[tuple[tuple[str, str], ...]] = set()
    model_candidate_count = 0
    deterministic_life_transaction_count = 0
    representative_samples: dict[str, list[dict[str, object]]] = {}
    items: list[dict[str, object]] = []

    for legacy_signature, members in grouped.items():
        transaction, raw_fields = members[0]
        analysis = analyze_ai_semantic_fields(raw_fields)
        usable = analysis["usable_fields"]
        excluded = analysis["excluded_fields"]
        transformed = analysis["transformed_fields"]
        usable_fields = (
            {str(name): str(value) for name, value in usable.items()}
            if isinstance(usable, Mapping)
            else {}
        )
        constraints = build_classification_constraints(usable_fields)
        representative_life_category = _deterministic_life_category(
            _reliable_trace_fields(transaction)
        )
        if representative_life_category:
            constraints = {
                "directly_related_allowed": False,
                "directly_related_evidence_fields": [],
                "maximum_allowed_strength": "none",
                "deterministic_non_business_category": (
                    representative_life_category
                ),
            }
        categories_for_signature: set[str] = set()
        field_categories_for_signature: set[tuple[str, str]] = set()
        for field_map in (excluded, transformed):
            if not isinstance(field_map, Mapping):
                continue
            for field_name, reasons in field_map.items():
                if not isinstance(reasons, list):
                    continue
                for reason in reasons:
                    category = str(reason)
                    categories_for_signature.add(category)
                    field_category = (str(field_name), category)
                    if field_category in field_categories_for_signature:
                        continue
                    field_categories_for_signature.add(field_category)
                    category_field_counts[category] += 1
                    samples = representative_samples.setdefault(category, [])
                    sample_key = (
                        transaction.transaction_id,
                        str(field_name),
                        str(raw_fields.get(str(field_name), "")),
                    )
                    existing_keys = {
                        (
                            str(sample.get("transaction_id", "")),
                            str(sample.get("field_name", "")),
                            str(sample.get("value", "")),
                        )
                        for sample in samples
                    }
                    if (
                        len(samples) < representative_limit
                        and sample_key not in existing_keys
                    ):
                        samples.append(
                            {
                                "transaction_id": transaction.transaction_id,
                                "source_file_id": transaction.source_file_id,
                                "source_file": transaction.source_file,
                                "bank": transaction.bank,
                                "field_name": str(field_name),
                                "value": str(raw_fields.get(str(field_name), "")),
                                "evidence_locator": transaction.evidence_locator,
                            }
                        )
        for category in categories_for_signature:
            category_signature_counts[category] += 1

        maximum = str(constraints["maximum_allowed_strength"])
        maximum_strength_counts[maximum] += 1
        directly_allowed_counts[
            "allowed"
            if constraints["directly_related_allowed"]
            else "not_allowed"
        ] += 1
        life_category = str(
            constraints["deterministic_non_business_category"] or ""
        )
        locally_excluded_members = [
            member
            for member in members
            if member[0].transaction_id in deterministic_non_business_ids
        ]
        eligible_members = [
            member
            for member in members
            if member[0].transaction_id not in deterministic_non_business_ids
        ]
        if locally_excluded_members:
            deterministic_life_transaction_count += len(
                locally_excluded_members
            )
        if life_category:
            category_signature_counts[f"life:{life_category}"] += 1
        current_signature = ai_semantic_signature(usable_fields)
        send_to_model = bool(current_signature) and bool(eligible_members)
        if send_to_model:
            model_signatures.add(current_signature)
            model_candidate_count += len(eligible_members)

        items.append(
            {
                "legacy_signature_id": semantic_signature_id(legacy_signature),
                "legacy_signature": [list(pair) for pair in legacy_signature],
                "representative_transaction_id": transaction.transaction_id,
                "source_file_id": transaction.source_file_id,
                "source_file": transaction.source_file,
                "bank": transaction.bank,
                "evidence_locator": transaction.evidence_locator,
                "transaction_count": len(members),
                "deterministic_non_business_transaction_count": len(
                    locally_excluded_members
                ),
                "original_standard_fields": raw_fields,
                "model_fields": usable_fields,
                "excluded_fields": excluded,
                "transformed_fields": transformed,
                "classification_constraints": constraints,
                "send_to_model": send_to_model,
                "current_signature_id": (
                    semantic_signature_id(current_signature)
                    if current_signature
                    else ""
                ),
                "field_sources": {
                    field_name: transaction.field_sources.get(field_name, "")
                    for field_name in raw_fields
                },
            }
        )

    all_filter_categories = (
        "pure_numeric_code",
        "alphanumeric_code",
        "order_number",
        "reference_number",
        "hash_like",
        "generic_summary",
        "financial_infrastructure_name",
        "uninformative_text",
    )
    return {
        "audit_version": "ai-input-audit-v1",
        "prompt_version": AI_PROMPT_VERSION,
        "transaction_count": len(transactions),
        "deterministic_exact_match_count": len(deterministic),
        "legacy_ai_candidate_count": legacy_candidate_count,
        "legacy_unique_semantic_signature_count": len(grouped),
        "model_candidate_count_after_deterministic_boundaries": model_candidate_count,
        "model_unique_semantic_signature_count_after_deterministic_boundaries": len(
            model_signatures
        ),
        "deterministic_non_business_transaction_count": (
            deterministic_life_transaction_count
        ),
        "field_filter_category_counts_by_unique_signature": dict(
            sorted(
                {
                    **{
                        category: category_signature_counts[category]
                        for category in all_filter_categories
                    },
                    **dict(category_signature_counts),
                }.items()
            )
        ),
        "field_filter_occurrence_counts_by_unique_signature": dict(
            sorted(
                {
                    **{
                        category: category_field_counts[category]
                        for category in all_filter_categories
                    },
                    **dict(category_field_counts),
                }.items()
            )
        ),
        "maximum_allowed_strength_counts": dict(
            sorted(maximum_strength_counts.items())
        ),
        "directly_related_allowed_counts": dict(
            sorted(directly_allowed_counts.items())
        ),
        "representative_samples": representative_samples,
        "standard_field_contract": {
            "traceable_standard_text_fields": list(
                AI_TRACEABLE_STANDARD_TEXT_FIELDS
            ),
            "model_semantic_fields": list(AI_INPUT_FIELDS),
            "context_only_not_industry_evidence": [
                "transaction_type",
                "transaction_method",
                "payment_method",
            ],
            "source_independent": True,
            "bank_name_used_for_business_classification": False,
            "raw_header_used_for_business_classification": False,
        },
        "items": items,
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
        signature = ai_semantic_signature(
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


def build_fixed_ai_sample_manifest(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
    *,
    allow_business_names: bool,
    development_size: int = 50,
    reserved_size: int = 50,
) -> dict[str, object]:
    """Create a stable split so prompt iterations do not silently change samples."""
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
    representatives: dict[str, dict[str, object]] = {}
    for record in records:
        fields = record.get("fields")
        if not isinstance(fields, Mapping):
            continue
        signature = ai_semantic_signature(
            {str(name): str(value) for name, value in fields.items()}
        )
        signature_key = semantic_signature_id(signature)
        if signature_key in representatives:
            continue
        transaction = transaction_by_id.get(str(record["transaction_id"]))
        if transaction is None:
            continue
        representatives[signature_key] = {
            "signature_id": signature_key,
            "transaction_id": transaction.transaction_id,
            "source_file_id": transaction.source_file_id,
            "bank": transaction.bank,
        }

    ordered = sorted(
        representatives.values(),
        key=lambda item: (
            str(item["source_file_id"]),
            str(item["signature_id"]),
        ),
    )
    groups: dict[str, list[dict[str, object]]] = {}
    for item in ordered:
        groups.setdefault(str(item["source_file_id"]), []).append(item)

    def take_balanced(
        candidates: dict[str, list[dict[str, object]]],
        size: int,
    ) -> list[dict[str, object]]:
        selected: list[dict[str, object]] = []
        positions = {source_id: 0 for source_id in candidates}
        while len(selected) < size:
            progressed = False
            for source_id in sorted(candidates):
                index = positions[source_id]
                rows = candidates[source_id]
                if index >= len(rows):
                    continue
                selected.append(rows[index])
                positions[source_id] += 1
                progressed = True
                if len(selected) == size:
                    break
            if not progressed:
                break
        return selected

    development = take_balanced(groups, development_size)
    development_ids = {
        str(item["signature_id"]) for item in development
    }
    remaining_groups = {
        source_id: [
            item
            for item in rows
            if str(item["signature_id"]) not in development_ids
        ]
        for source_id, rows in groups.items()
    }
    reserved = take_balanced(remaining_groups, reserved_size)
    return {
        "manifest_version": "fixed-ai-semantic-split-v1",
        "prompt_version_at_creation": AI_PROMPT_VERSION,
        "candidate_unique_semantic_count": len(representatives),
        "development": development,
        "reserved_acceptance": reserved,
        "rules": {
            "development_is_fixed": True,
            "reserved_not_for_prompt_tuning": True,
            "selection_uses_standard_semantic_signature_only": True,
        },
    }


def select_ai_input_from_manifest(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
    manifest: Mapping[str, object],
    *,
    allow_business_names: bool,
    split: str = "development",
) -> tuple[list[Transaction], int]:
    entries = manifest.get(split)
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"sample manifest split unavailable: {split}")
    required_ids = {
        str(entry.get("signature_id", ""))
        for entry in entries
        if isinstance(entry, Mapping)
    }
    if "" in required_ids:
        raise ValueError("sample manifest contains an empty signature")
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
    selected: dict[str, Transaction] = {}
    all_signature_ids: set[str] = set()
    for record in records:
        fields = record.get("fields")
        if not isinstance(fields, Mapping):
            continue
        signature_id = semantic_signature_id(
            ai_semantic_signature(
                {str(name): str(value) for name, value in fields.items()}
            )
        )
        all_signature_ids.add(signature_id)
        if signature_id not in required_ids or signature_id in selected:
            continue
        transaction = transaction_by_id.get(str(record["transaction_id"]))
        if transaction is not None:
            selected[signature_id] = transaction
    missing = sorted(required_ids.difference(selected))
    if missing:
        raise ValueError(
            "sample manifest signatures no longer match current inputs: "
            + ",".join(missing[:5])
        )
    return sort_transactions(list(selected.values())), len(all_signature_ids)


def validate_ai_response_collecting(
    response: object,
    records: list[dict[str, object]],
) -> dict[str, object]:
    """Validate every result and aggregate item-level failures."""
    by_id = {str(record["transaction_id"]): record for record in records}
    failures: list[dict[str, object]] = []
    accepted: list[dict[str, object]] = []
    seen: set[str] = set()

    def reject(
        location: str,
        reason: str,
        transaction_id: str = "",
    ) -> None:
        record = by_id.get(transaction_id, {})
        failures.append(
            {
                "location": location,
                "reason": reason,
                "transaction_id": transaction_id,
                "representative_fields": dict(record.get("fields", {}))
                if isinstance(record, Mapping)
                and isinstance(record.get("fields"), Mapping)
                else {},
            }
        )

    if not isinstance(response, list):
        reject("response", "response_not_list")
        return {
            "accepted": [],
            "failures": failures,
            "expected_count": len(records),
            "accepted_count": 0,
        }
    for item_number, item in enumerate(response, start=1):
        location = f"item_{item_number}"
        if not isinstance(item, Mapping):
            reject(location, "item_not_object")
            continue
        transaction_id = str(item.get("transaction_id", ""))
        if transaction_id not in by_id:
            reject(location, "transaction_id_unknown", transaction_id)
            continue
        if transaction_id in seen:
            reject(location, "transaction_id_duplicate", transaction_id)
            continue
        seen.add(transaction_id)
        judgement = str(item.get("semantic_judgement", ""))
        if not judgement:
            reject(location, "semantic_judgement_missing", transaction_id)
            continue
        if judgement not in AI_MODEL_JUDGEMENTS:
            reject(location, "semantic_judgement_invalid", transaction_id)
            continue
        classification = (
            "directly_related"
            if judgement == "strong"
            else "possibly_related"
            if judgement in {"medium", "weak"}
            else "undetermined"
            if judgement == "undetermined"
            else "no_relation_evidence"
        )
        evidence_strength = (
            "none" if judgement == "undetermined" else judgement
        )
        reason = str(item.get("reason", "")).strip()
        used_fields = item.get("used_fields", [])
        if classification not in AI_CLASSIFICATIONS:
            reject(location, "classification_invalid", transaction_id)
            continue
        if evidence_strength not in AI_EVIDENCE_STRENGTHS:
            reject(location, "evidence_strength_invalid", transaction_id)
            continue
        if not reason:
            reject(location, "reason_missing", transaction_id)
            continue
        if not isinstance(used_fields, list):
            reject(location, "used_fields_not_list", transaction_id)
            continue
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
            reject(
                location,
                "classification_strength_mismatch",
                transaction_id,
            )
            continue
        allowed_fields = set(by_id[transaction_id]["fields"])
        normalized_fields = [str(field_name) for field_name in used_fields]
        if not normalized_fields:
            reject(location, "used_fields_empty", transaction_id)
            continue
        if not set(normalized_fields).issubset(allowed_fields):
            reject(location, "used_fields_not_allowed", transaction_id)
            continue
        if (
            classification in {"directly_related", "possibly_related"}
            and not set(normalized_fields).intersection(AI_SEMANTIC_EVIDENCE_FIELDS)
        ):
            reject(
                location,
                "semantic_evidence_field_missing",
                transaction_id,
            )
            continue
        constraints = by_id[transaction_id].get(
            "classification_constraints",
            {},
        )
        if not isinstance(constraints, Mapping):
            constraints = {}
        maximum_strength = str(
            constraints.get("maximum_allowed_strength", "strong")
        )
        if (
            maximum_strength not in _STRENGTH_RANK
            or _STRENGTH_RANK[evidence_strength]
            > _STRENGTH_RANK[maximum_strength]
        ):
            reject(
                location,
                "maximum_allowed_strength_exceeded",
                transaction_id,
            )
            continue
        if (
            classification == "directly_related"
            and not constraints.get("directly_related_allowed", True)
        ):
            reject(
                location,
                "directly_related_not_allowed",
                transaction_id,
            )
            continue
        direct_evidence_fields = set(
            constraints.get(
                "directly_related_evidence_fields",
                AI_DIRECT_EVIDENCE_FIELDS,
            )
        )
        if (
            classification == "directly_related"
            and not set(normalized_fields).intersection(direct_evidence_fields)
        ):
            reject(
                location,
                "direct_evidence_field_missing",
                transaction_id,
            )
            continue
        accepted.append(
            {
                "transaction_id": transaction_id,
                "classification": classification,
                "evidence_strength": evidence_strength,
                "decision_source": "ai_model",
                "reason": reason,
                "used_fields": normalized_fields,
            }
        )
    for transaction_id in sorted(set(by_id).difference(seen)):
        reject("coverage", "response_item_missing", transaction_id)
    return {
        "accepted": accepted,
        "failures": failures,
        "expected_count": len(records),
        "accepted_count": len(accepted),
    }


def summarize_validation_failures(
    failures: list[dict[str, object]],
    *,
    representative_limit: int = 5,
) -> dict[str, object]:
    counts = Counter(str(item.get("reason", "")) for item in failures)
    representatives: dict[str, list[dict[str, object]]] = {}
    for item in failures:
        reason = str(item.get("reason", ""))
        samples = representatives.setdefault(reason, [])
        if len(samples) < representative_limit:
            samples.append(dict(item))
    return {
        "total": len(failures),
        "counts": dict(sorted(counts.items())),
        "representative_samples": representatives,
    }


def validate_ai_response(
    response: object,
    records: list[dict[str, object]],
) -> tuple[list[dict[str, object]] | None, str]:
    """Compatibility wrapper returning the first failure for simple callers."""
    report = validate_ai_response_collecting(response, records)
    failures = report["failures"]
    if isinstance(failures, list) and failures:
        first = failures[0]
        return None, f"{first['location']}:{first['reason']}"
    accepted = report["accepted"]
    return list(accepted) if isinstance(accepted, list) else [], ""


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
    deterministic_non_business, non_business_ids = (
        _deterministic_non_business_candidates(
            transactions,
            deterministic_ids,
            bool(config.get("allow_business_names")),
        )
    )
    records = _payload_records(
        transactions,
        deterministic_ids | non_business_ids,
        bool(config.get("allow_business_names")),
    )
    reason = ""
    failure_detail = ""
    validation_failure_summary: dict[str, object] = {
        "total": 0,
        "counts": {},
        "representative_samples": {},
    }
    ai_candidates: list[dict[str, object]] = []
    provisional_ai_candidates: list[dict[str, object]] = []
    provider_execution: dict[str, int] = {
        "unique_semantic_count": 0,
        "provider_batch_count": 0,
        "provider_call_count": 0,
        "cache_hit_count": 0,
        "cache_miss_count": 0,
        "cache_replay_mismatch_count": 0,
        "invalid_cache_entry_count": 0,
    }

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
            "task_type": AI_TASK_TYPE,
            "prompt_version": AI_PROMPT_VERSION,
            "output_contract_version": AI_OUTPUT_CONTRACT_VERSION,
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
            "allowed_model_judgements": sorted(AI_MODEL_JUDGEMENTS),
            "transactions": records,
            "instructions": [
                "只能引用输入中的交易ID和字段。",
                "不得判断真实经营、欺诈、包装、准入或拒绝。",
                "必须联合查看同一交易提供的全部语义字段。",
                "明确出现申报行业商品、服务或用途时，semantic_judgement可为strong。",
                "classification_constraints由本地确定性代码生成，模型不得覆盖、改写或忽略。",
                "每笔不得超过maximum_allowed_strength；directly_related_allowed为false时semantic_judgement绝对不得为strong。",
                "企业或商户名称无论看起来多么具体，只要没有摘要、备注、用途、商品说明或商户类别字段支持，semantic_judgement就不得为strong。",
                "所有正向分类都必须与business_context中的申报行业或工作单位名称所明确体现的行业语义相关；具体但无关的产品或服务不得判正向。",
                "名称或其他字段中有与申报工作内容相关的具体产品或服务、但用途不确定时，semantic_judgement优先为medium；建材、护栏、园林景观设计等可与建筑材料或环保工程相关。",
                "对于本案建筑材料批发投资或环保工程上下文，建材、护栏、栏杆、围栏、塑木和园林景观设计属于具体相关产品或服务；即使同笔另有货款，semantic_judgement也必须优先为medium，不得降为weak。",
                "仅有技术咨询费、材料费、采购款等泛化用途而没有具体课题、产品、项目或行业对象时，不得仅凭可能性判为medium。",
                "餐饮、便利店、话费充值、银行年费、医疗和打车等生活或通用服务若与申报工作内容无关，semantic_judgement应为none；本轮不得将其用于生活轨迹判断。",
                "只有实业、贸易、科技、工业、工程等泛化企业类型，或只有货款而没有具体产品、服务、项目或用途时，semantic_judgement最多为weak。",
                "货款不得覆盖或削弱同笔交易中已经存在的具体产品或服务语义，不得仅因同时出现货款就把medium降为weak。",
                "reason必须与semantic_judgement一致，不能把medium或weak描述成确定的直接关系。",
                "证据不足时使用undetermined。",
            ],
        }
        try:
            response = evaluator(payload)
        except Exception as exc:
            provider_reason = getattr(exc, "failure_reason", "")
            reason = (
                provider_reason
                if provider_reason in {"ai_provider_failed", "ai_response_invalid"}
                else "ai_provider_failed"
            )
            provider_detail = getattr(exc, "safe_diagnostic", "")
            if (
                isinstance(provider_detail, str)
                and re.fullmatch(r"[a-z0-9_:-]+", provider_detail)
            ):
                failure_detail = provider_detail
        else:
            if isinstance(response, Mapping) and isinstance(
                response.get("results"), list
            ):
                for metric_name in provider_execution:
                    metric_value = response.get(metric_name, 0)
                    if isinstance(metric_value, int):
                        provider_execution[metric_name] = metric_value
                provisional_ai_candidates = list(response["results"])
                failures = response.get("validation_failures", [])
                if not isinstance(failures, list):
                    failures = [
                        {
                            "location": "provider",
                            "reason": "validation_failures_not_list",
                            "transaction_id": "",
                            "representative_fields": {},
                        }
                    ]
            else:
                validation_report = validate_ai_response_collecting(
                    response,
                    records,
                )
                provisional_ai_candidates = list(
                    validation_report["accepted"]
                )
                failures = list(validation_report["failures"])
            if failures:
                reason = "ai_response_invalid"
                validation_failure_summary = summarize_validation_failures(
                    failures
                )
                first = failures[0]
                failure_detail = (
                    f"{first.get('location', '')}:{first.get('reason', '')}"
                ).strip(":")
            else:
                ai_candidates = provisional_ai_candidates

    evidence_ids = [
        str(item["transaction_id"])
        for item in [
            *deterministic,
            *deterministic_non_business,
            *ai_candidates,
        ]
        if item.get("transaction_id")
    ]
    return {
        "observation_type": "ai_business_relevance_candidates",
        "value": {
            "available": not reason,
            "reason": reason,
            "failure_detail": failure_detail,
            "deterministic_candidates": deterministic,
            "deterministic_non_business_candidates": (
                deterministic_non_business
            ),
            "ai_candidates": ai_candidates,
            "provisional_ai_candidates": provisional_ai_candidates,
            "validation_failure_summary": validation_failure_summary,
            "provider_execution": provider_execution,
            "ai_input_candidate_count": len(records),
        },
        "parameters": {
            "task_type": AI_TASK_TYPE,
            "prompt_version": AI_PROMPT_VERSION,
            "output_contract_version": AI_OUTPUT_CONTRACT_VERSION,
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
            "covered_transaction_count": (
                len(records)
                + len(deterministic)
                + len(deterministic_non_business)
            ),
        },
    }
