"""Deterministic text observations for the bank-flow verification MVP."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import timedelta
from decimal import Decimal

from .models import Transaction
from .summary import sort_transactions


CONTROLLED_VOCABULARY_VERSION = "mvp-2026-07-27-v1"

SEARCH_FIELDS = (
    "counterparty_name",
    "counterparty_bank",
    "summary",
    "remark",
    "purpose",
    "transaction_type",
    "transaction_method",
    "payment_method",
    "product_description",
    "merchant_name",
    "merchant_category",
    "merchant_location",
)

KEYWORD_GROUPS: dict[str, tuple[str, ...]] = {
    "purchase_and_vehicle_order": (
        "华为",
        "问界",
        "AITO",
        "下定",
        "定金",
        "试驾",
    ),
    "vehicle_and_location_trace": (
        "停车",
        "停车场",
        "加油",
        "加油站",
        "充电",
        "充电站",
        "高速",
        "高速公路",
        "ETC",
        "洗车",
        "车位",
    ),
    "business_and_income": (
        "工资",
        "薪资",
        "税费",
        "工程款",
        "材料款",
        "采购",
        "货款",
        "商户收款",
        "报销",
        "还款",
    ),
    "sensitive_transaction_context": (
        "抵押",
        "质押",
        "借款",
        "借贷",
        "贷款",
        "网贷",
        "二手",
        "租赁",
        "融资",
        "典当",
        "医院",
        "医疗",
        "法院",
        "司法",
        "诉讼",
        "律师",
    ),
}

_GENERIC_TEXT = {
    "转账",
    "转入",
    "转出",
    "消费",
    "商户消费",
    "扫码付款",
    "扫二维码付款",
    "二维码付款",
    "二维码收款",
    "转账收款",
    "微信支付",
    "微信红包",
    "支付宝",
    "支付宝支付",
    "快捷支付",
    "电子汇入",
    "电子汇出",
    "他行汇入",
    "汇入",
    "汇款",
    "中汇款",
    "跨行转账",
    "现金",
    "缴费",
    "其他",
    "收入",
    "支出",
    "付款",
    "收款",
}
_PLACE_RE = re.compile(r"([\u4e00-\u9fff]{2,8}?)(?:自治区|省|市|区|县)")
_PROVINCE_PREFIXES = (
    "北京",
    "天津",
    "上海",
    "重庆",
    "河北",
    "河南",
    "山东",
    "山西",
    "新疆",
    "西藏",
    "内蒙古",
    "宁夏",
    "广西",
    "广东",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "湖北",
    "湖南",
    "辽宁",
    "吉林",
    "黑龙江",
    "四川",
    "贵州",
    "云南",
    "陕西",
    "甘肃",
    "青海",
    "海南",
)
_COMPANY_SUFFIX_RE = re.compile(
    r"(?:有限责任公司|股份有限公司|集团有限公司|有限公司|公司|商行|经营部|门市部)$"
)


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _reliable_text_fields(transaction: Transaction) -> dict[str, str]:
    return {
        field_name: str(getattr(transaction, field_name) or "").strip()
        for field_name in SEARCH_FIELDS
        if str(getattr(transaction, field_name) or "").strip()
        and transaction.field_confidence.get(field_name) == 1.0
    }


def is_informative_text(value: str) -> bool:
    normalized = re.sub(r"\s+", "", value).strip("()（）[]【】")
    if not normalized or normalized in _GENERIC_TEXT:
        return False
    if normalized in {"空", "无", "未知", "N/A", "NA", "-"}:
        return False
    if "*" in normalized or normalized.count("x") >= 2 or normalized.count("X") >= 2:
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", normalized))


def _case_search_context(case_context: Mapping[str, object] | None) -> Mapping[str, object]:
    if not isinstance(case_context, Mapping):
        return {}
    search_context = case_context.get("search_context")
    return search_context if isinstance(search_context, Mapping) else {}


def _values(search_context: Mapping[str, object], field_name: str) -> list[str]:
    raw_values = search_context.get(field_name, [])
    if not isinstance(raw_values, list):
        return []
    return [str(value).strip() for value in raw_values if str(value).strip()]


def _dynamic_terms(
    case_context: Mapping[str, object] | None,
) -> dict[str, tuple[str, ...]]:
    search_context = _case_search_context(case_context)
    business_terms: list[str] = []
    for value in (
        _values(search_context, "work_units")
        + _values(search_context, "declared_industries")
    ):
        business_terms.append(value)
        shortened = _COMPANY_SUFFIX_RE.sub("", value).strip()
        if len(shortened) >= 4:
            business_terms.append(shortened)

    purchase_terms = _values(search_context, "vehicle_models") + _values(
        search_context, "dealer_names"
    )
    location_terms: list[str] = []
    for value in (
        _values(search_context, "work_locations")
        + _values(search_context, "residence_locations")
        + _values(search_context, "vehicle_registration_locations")
    ):
        compact_value = re.sub(r"\s+", "", value).removesuffix("牌")
        if 2 <= len(compact_value) <= 8:
            location_terms.append(compact_value)
        for match in _PLACE_RE.finditer(value):
            term = match.group(1) + match.group(0)[-1]
            location_terms.append(term)
            if len(term) >= 3:
                location_terms.append(term[:-1])
            for prefix in _PROVINCE_PREFIXES:
                if term.startswith(prefix) and len(term) - len(prefix) >= 3:
                    shortened = term[len(prefix):]
                    location_terms.append(shortened)
                    if len(shortened) >= 3:
                        location_terms.append(shortened[:-1])
                    break

    return {
        "purchase_and_vehicle_order": tuple(dict.fromkeys(purchase_terms)),
        "vehicle_and_location_trace": tuple(dict.fromkeys(location_terms)),
        "business_and_income": tuple(dict.fromkeys(business_terms)),
    }


def _context(transaction: Transaction, reliable_fields: Mapping[str, str]) -> dict[str, object]:
    return {
        "transaction_time": transaction.transaction_time.isoformat(),
        "income": _decimal(transaction.income),
        "expense": _decimal(transaction.expense),
        "balance": _decimal(transaction.balance),
        "source_file_id": transaction.source_file_id,
        "source_file": transaction.source_file,
        "reliable_standard_fields": dict(reliable_fields),
    }


def _keyword_observation(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
) -> dict[str, object]:
    dynamic = _dynamic_terms(case_context)
    hits: list[dict[str, object]] = []
    searched_transaction_count = 0

    for transaction in sort_transactions(transactions):
        if getattr(transaction, "neutral", False):
            continue
        reliable_fields = _reliable_text_fields(transaction)
        if reliable_fields:
            searched_transaction_count += 1
        group_hits: dict[str, set[str]] = {}
        field_hits: dict[str, set[str]] = {}
        for group_name, base_terms in KEYWORD_GROUPS.items():
            terms = (*base_terms, *dynamic.get(group_name, ()))
            for field_name, field_value in reliable_fields.items():
                for term in terms:
                    normalized_term = re.sub(r"\s+", "", term).casefold()
                    normalized_value = re.sub(r"\s+", "", field_value).casefold()
                    if normalized_term and normalized_term in normalized_value:
                        group_hits.setdefault(group_name, set()).add(term)
                        field_hits.setdefault(field_name, set()).add(term)
        if not group_hits:
            continue
        hits.append(
            {
                "transaction_id": transaction.transaction_id,
                "source_file_id": transaction.source_file_id,
                "evidence_locator": transaction.evidence_locator,
                "keyword_groups": sorted(group_hits),
                "matched_terms": sorted(
                    {term for terms in group_hits.values() for term in terms}
                ),
                "matched_fields": {
                    field_name: sorted(terms)
                    for field_name, terms in sorted(field_hits.items())
                },
                "transaction_context": _context(transaction, reliable_fields),
            }
        )

    return {
        "observation_type": "controlled_keyword_candidates",
        "value": {
            "available": bool(hits),
            "reason": "" if hits else (
                "no_hits_in_reliable_fields"
                if searched_transaction_count
                else "keyword_search_fields_unavailable"
            ),
            "candidate_only": True,
            "hit_count": len(hits),
            "hits": hits,
        },
        "parameters": {
            "vocabulary_version": CONTROLLED_VOCABULARY_VERSION,
            "searched_fields": list(SEARCH_FIELDS),
            "reliability_rule": "non_empty_and_field_confidence_equals_1.0",
            "single_character_unconditional_matching": False,
            "interpretation": "关键词命中仅为待人工核查候选，不等于异常、欺诈或交易目的已确认。",
        },
        "evidence_transaction_ids": [
            hit["transaction_id"] for hit in hits if hit["transaction_id"]
        ],
        "field_coverage": {
            "required_fields": [*SEARCH_FIELDS, "field_confidence"],
            "eligible_transaction_count": len(
                [
                    transaction
                    for transaction in transactions
                    if not getattr(transaction, "neutral", False)
                ]
            ),
            "covered_transaction_count": searched_transaction_count,
        },
    }


def _coverage_observation(transactions: list[Transaction]) -> dict[str, object]:
    groups: dict[str, list[Transaction]] = {}
    for transaction in sort_transactions(transactions):
        if getattr(transaction, "neutral", False):
            continue
        if transaction.income == Decimal("0.00") and transaction.expense == Decimal("0.00"):
            continue
        groups.setdefault(transaction.source_file_id or "source_file_id_unavailable", []).append(
            transaction
        )

    source_rows: list[dict[str, object]] = []
    evidence_ids: list[str] = []
    for source_file_id, eligible in sorted(groups.items()):
        counterparty_covered = 0
        summary_or_purpose_covered = 0
        merchant_or_product_covered = 0
        industry_covered = 0
        for transaction in eligible:
            fields = _reliable_text_fields(transaction)
            informative_fields = {
                name: value
                for name, value in fields.items()
                if is_informative_text(value)
            }
            if any(
                name in informative_fields
                for name in ("counterparty_name", "counterparty_bank")
            ):
                counterparty_covered += 1
            if any(
                name in informative_fields
                for name in ("summary", "remark", "purpose", "transaction_type")
            ):
                summary_or_purpose_covered += 1
            if any(
                name in informative_fields
                for name in (
                    "merchant_name",
                    "merchant_category",
                    "merchant_location",
                    "product_description",
                )
            ):
                merchant_or_product_covered += 1
            if informative_fields:
                industry_covered += 1
                if transaction.transaction_id:
                    evidence_ids.append(transaction.transaction_id)

        denominator = Decimal(len(eligible))
        source_rows.append(
            {
                "source_file_id": source_file_id,
                "source_file": eligible[0].source_file,
                "bank": eligible[0].bank,
                "eligible_transaction_count": len(eligible),
                "counterparty_covered_transaction_count": counterparty_covered,
                "summary_or_purpose_covered_transaction_count": summary_or_purpose_covered,
                "merchant_or_product_covered_transaction_count": merchant_or_product_covered,
                "industry_search_covered_transaction_count": industry_covered,
                "industry_search_coverage_rate": (
                    f"{Decimal(industry_covered) / denominator:.4f}"
                    if denominator
                    else None
                ),
            }
        )

    return {
        "observation_type": "industry_text_search_coverage",
        "value": {
            "available": bool(source_rows),
            "reason": "" if source_rows else "no_effective_income_or_expense_transactions",
            "sources": source_rows,
        },
        "parameters": {
            "searched_fields": list(SEARCH_FIELDS),
            "reliability_rule": "non_empty_and_field_confidence_equals_1.0",
            "generic_values_excluded": sorted(_GENERIC_TEXT),
            "interpretation": "该覆盖率表示可用于行业搜索的可靠文字字段覆盖，不是行业相关交易占比，也不是解析准确率。",
        },
        "evidence_transaction_ids": list(dict.fromkeys(evidence_ids)),
        "field_coverage": {
            "required_fields": [*SEARCH_FIELDS, "field_confidence"],
            "eligible_transaction_count": sum(len(rows) for rows in groups.values()),
            "covered_transaction_count": sum(
                int(row["industry_search_covered_transaction_count"])
                for row in source_rows
            ),
        },
    }


def _purchase_funding_observation(
    transactions: list[Transaction],
    keyword_observation: Mapping[str, object],
) -> dict[str, object]:
    ordered = sort_transactions(transactions)
    by_id = {transaction.transaction_id: transaction for transaction in ordered}
    purchase_hits = [
        hit
        for hit in keyword_observation["value"]["hits"]
        if "purchase_and_vehicle_order" in hit["keyword_groups"]
        and by_id.get(hit["transaction_id"])
        and by_id[hit["transaction_id"]].expense > Decimal("0.00")
    ]
    candidates: list[dict[str, object]] = []
    evidence_ids: list[str] = []

    for hit in purchase_hits:
        purchase = by_id[hit["transaction_id"]]
        prior_income_rows: list[dict[str, object]] = []
        for income in ordered:
            if income.income <= Decimal("0.00") or income.transaction_time > purchase.transaction_time:
                continue
            age = purchase.transaction_time - income.transaction_time
            if age > timedelta(days=7):
                continue
            ratio = income.income / purchase.expense
            exact_amount = income.income == purchase.expense
            near_amount = Decimal("0.90") <= ratio <= Decimal("1.10")
            large_income = income.income >= Decimal("30000.00")
            if not (near_amount or large_income):
                continue
            windows = [
                days for days in (1, 3, 7) if age <= timedelta(days=days)
            ]
            prior_income_rows.append(
                {
                    "transaction_id": income.transaction_id,
                    "source_file_id": income.source_file_id,
                    "evidence_locator": income.evidence_locator,
                    "transaction_time": income.transaction_time.isoformat(),
                    "income": _decimal(income.income),
                    "exact_amount": exact_amount,
                    "near_amount": near_amount,
                    "large_income": large_income,
                    "amount_ratio_to_purchase": f"{ratio:.4f}",
                    "within_windows_days": windows,
                }
            )
            if income.transaction_id:
                evidence_ids.append(income.transaction_id)
        candidates.append(
            {
                "purchase_transaction_id": purchase.transaction_id,
                "source_file_id": purchase.source_file_id,
                "evidence_locator": purchase.evidence_locator,
                "transaction_time": purchase.transaction_time.isoformat(),
                "expense": _decimal(purchase.expense),
                "matched_terms": hit["matched_terms"],
                "prior_income_candidates": prior_income_rows,
            }
        )
        if purchase.transaction_id:
            evidence_ids.append(purchase.transaction_id)

    return {
        "observation_type": "purchase_prepayment_funding_candidates",
        "value": {
            "available": bool(candidates),
            "reason": "" if candidates else "purchase_expense_candidate_unavailable",
            "candidate_only": True,
            "purchase_candidates": candidates,
        },
        "parameters": {
            "windows_days": [1, 3, 7],
            "near_amount_ratio_inclusive": ["0.90", "1.10"],
            "large_income_threshold": "30000.00",
            "cross_source_temporal_comparison": True,
            "fund_source_attribution": False,
            "interpretation": "仅并列下定候选前的收入时间和金额，不表示该收入是定金来源。",
        },
        "evidence_transaction_ids": list(dict.fromkeys(evidence_ids)),
        "field_coverage": {
            "required_fields": [
                "transaction_time",
                "income",
                "expense",
                "transaction_id",
                "source_file_id",
            ],
            "eligible_transaction_count": len(ordered),
            "covered_transaction_count": len(
                [
                    transaction
                    for transaction in ordered
                    if transaction.transaction_id and transaction.source_file_id
                ]
            ),
        },
    }


def build_deterministic_text_observations(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    """Build deterministic MVP observations without changing transactions."""
    keyword = _keyword_observation(transactions, case_context)
    return [
        keyword,
        _coverage_observation(transactions),
        _purchase_funding_observation(transactions, keyword),
    ]
