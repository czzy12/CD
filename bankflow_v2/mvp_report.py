"""Declaration cross-check and Markdown view for the bank-flow MVP."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

from .models import Transaction


_ROLE_LABELS = {
    "system_customer_data": "系统客户资料",
    "customer_manager_description": "客户经理描述",
    "risk_investigation_report": "风控调查报告",
}
_VERIFICATION_LABELS = {
    "unverified": "未核实",
    "reported": "报告记载",
}
_CROSS_CHECK_LABELS = {
    "direct_match": "直接命中",
    "candidate_match": "候选命中",
    "no_evidence_in_reliable_fields": "可靠字段内未发现依据",
    "unavailable": "不可用",
}
_CHECK_TYPE_LABELS = {
    "work_unit": "工作单位",
    "declared_industry": "申报行业或经营内容",
    "purchase_deposit_expense": "下定相关流水",
    "work_location": "工作地点",
    "residence_location": "住家地址",
    "vehicle_registration_location": "车辆上牌地点",
    "vehicle_model": "车型",
    "dealer_name": "经销商或门店",
    "purchase_declaration": "下定描述",
}
_PURPOSE_LABELS = {
    "salary": "工资",
    "reimbursement": "报销",
    "tax": "税费",
    "engineering": "工程款",
    "material": "材料款",
    "purchase": "采购",
    "goods_payment": "货款",
    "merchant_receipt": "商户收款",
    "repayment": "还款",
    "interest": "结息/利息",
}
_AI_REASON_LABELS = {
    "ai_data_authorization_missing": "未取得AI数据授权，未调用模型",
    "ai_retention_policy_unconfirmed": "模型留存策略未确认，未调用模型",
    "ai_provider_configuration_missing": "模型配置缺失",
    "ai_provider_unavailable": "模型适配器不可用",
    "ai_provider_failed": "模型调用失败，已降级",
    "ai_response_invalid": "模型返回未通过证据校验，已降级",
    "case_business_context_unavailable": "案件单位/行业上下文不足",
    "business_context_confirmation_required": (
        "经营上下文不足，暂不执行行业关联分析；"
        "请人工确认客户实际主要经营内容和主要产品或服务"
    ),
}


def _observation_map(
    observations: list[dict[str, object]],
) -> dict[str, dict[str, object]]:
    return {
        str(observation.get("observation_type")): observation
        for observation in observations
    }


def _case_values(
    case_context: Mapping[str, object] | None,
    field_name: str,
) -> list[str]:
    if not isinstance(case_context, Mapping):
        return []
    search_context = case_context.get("search_context")
    if not isinstance(search_context, Mapping):
        return []
    values = search_context.get(field_name, [])
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def _field_records(
    case_context: Mapping[str, object] | None,
    field_name: str,
) -> list[dict[str, str]]:
    if not isinstance(case_context, Mapping):
        return []
    fields = case_context.get("fields")
    if not isinstance(fields, Mapping):
        return []
    records = fields.get(field_name, [])
    if not isinstance(records, list):
        return []
    return [dict(record) for record in records if isinstance(record, Mapping)]


def _reliable_text(transaction: Transaction) -> dict[str, str]:
    field_names = (
        "counterparty_name",
        "counterparty_bank",
        "summary",
        "remark",
        "purpose",
        "transaction_type",
        "transaction_method",
        "product_description",
        "merchant_name",
        "merchant_category",
        "merchant_location",
    )
    return {
        field_name: str(getattr(transaction, field_name) or "").strip()
        for field_name in field_names
        if str(getattr(transaction, field_name) or "").strip()
        and transaction.field_confidence.get(field_name) == 1.0
    }


def _location_terms(value: str) -> list[str]:
    terms: list[str] = []
    compact_value = re.sub(r"\s+", "", value).removesuffix("牌")
    if 2 <= len(compact_value) <= 8:
        terms.append(compact_value)
    for match in re.finditer(
        r"([\u4e00-\u9fff]{2,8}?)(?:自治区|省|市|区|县)",
        value,
    ):
        term = match.group(1) + match.group(0)[-1]
        terms.extend([term, term[:-1]])
    return list(dict.fromkeys(term for term in terms if len(term) >= 2))


def _search_terms(
    transactions: list[Transaction],
    terms: list[str],
) -> tuple[list[str], dict[str, list[str]]]:
    evidence_ids: list[str] = []
    matched: dict[str, list[str]] = {}
    normalized_terms = {
        term: re.sub(r"\s+", "", term).casefold()
        for term in terms
        if term
    }
    for transaction in transactions:
        for field_name, value in _reliable_text(transaction).items():
            compact = re.sub(r"\s+", "", value).casefold()
            field_terms = [
                term
                for term, normalized in normalized_terms.items()
                if normalized and normalized in compact
            ]
            if not field_terms:
                continue
            if transaction.transaction_id:
                evidence_ids.append(transaction.transaction_id)
            matched.setdefault(field_name, []).extend(field_terms)
    return list(dict.fromkeys(evidence_ids)), {
        field_name: sorted(set(field_terms))
        for field_name, field_terms in matched.items()
    }


def _coverage_available(observations: Mapping[str, dict[str, object]]) -> bool:
    coverage = observations.get("industry_text_search_coverage", {})
    sources = coverage.get("value", {}).get("sources", [])
    return any(
        int(source.get("industry_search_covered_transaction_count", 0)) > 0
        for source in sources
        if isinstance(source, Mapping)
    )


def _cross_check_item(
    check_type: str,
    declared_values: list[str],
    source_records: list[dict[str, str]],
    evidence_ids: list[str],
    matched_fields: dict[str, list[str]],
    *,
    direct: bool,
    coverage_available: bool,
) -> dict[str, object]:
    if evidence_ids:
        status = "direct_match" if direct else "candidate_match"
        reason = ""
    elif coverage_available:
        status = "no_evidence_in_reliable_fields"
        reason = "在当前可靠文字字段和流水期间内未发现对应文字依据；不表示申报不真实。"
    else:
        status = "unavailable"
        reason = "可靠文字字段覆盖不足，无法核查。"
    return {
        "check_type": check_type,
        "declared_values": declared_values,
        "source_roles": sorted(
            {
                record.get("source_role", "")
                for record in source_records
                if record.get("source_role")
            }
        ),
        "verification_statuses": sorted(
            {
                record.get("verification_status", "")
                for record in source_records
                if record.get("verification_status")
            }
        ),
        "source_refs": sorted(
            {
                record.get("source_ref", "")
                for record in source_records
                if record.get("source_ref")
            }
        ),
        "status": status,
        "reason": reason,
        "matched_fields": matched_fields,
        "evidence_transaction_ids": evidence_ids,
    }


def _display_only_item(
    check_type: str,
    source_records: list[dict[str, str]],
) -> dict[str, object] | None:
    values = list(
        dict.fromkeys(
            str(record.get("value", "")).strip()
            for record in source_records
            if str(record.get("value", "")).strip()
        )
    )
    if not values:
        return None
    return {
        "check_type": check_type,
        "declared_values": values,
        "source_roles": sorted(
            {
                record.get("source_role", "")
                for record in source_records
                if record.get("source_role")
            }
        ),
        "verification_statuses": sorted(
            {
                record.get("verification_status", "")
                for record in source_records
                if record.get("verification_status")
            }
        ),
        "source_refs": sorted(
            {
                record.get("source_ref", "")
                for record in source_records
                if record.get("source_ref")
            }
        ),
        "handling": "system_information_display_only",
        "reason": "仅展示系统资料，不与流水匹配或生成不一致结论。",
    }


def _declared_deposit_candidates(
    candidates: list[dict[str, object]],
) -> list[dict[str, object]]:
    direct_terms = {
        "下定",
        "订金",
        "定金",
        "购车款",
        "首付款",
        "补款",
        "问界",
    }
    return [
        candidate
        for candidate in candidates
        if direct_terms.intersection(candidate.get("matched_terms", []))
    ]


def build_declaration_flow_cross_check(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    """Compare explicit case fields with reliable flow text without truth inference."""
    observation_by_type = _observation_map(observations)
    coverage_available = _coverage_available(observation_by_type)
    items: list[dict[str, object]] = []
    industry_sources = (
        observation_by_type.get("industry_text_search_coverage", {})
        .get("value", {})
        .get("sources", [])
    )
    period_sources = {
        str(source.get("source_file_id", "")): source
        for source in (
            observation_by_type.get(
                "sensitive_transaction_context_candidates",
                {},
            )
            .get("value", {})
            .get("searched_sources", [])
        )
        if isinstance(source, Mapping)
    }
    searched_sources = []
    for source in industry_sources:
        if not isinstance(source, Mapping):
            continue
        period = period_sources.get(str(source.get("source_file_id", "")), {})
        searched_sources.append(
            {
                **dict(source),
                "observed_period_start": period.get("observed_period_start"),
                "observed_period_end": period.get("observed_period_end"),
            }
        )

    definitions = (
        ("work_unit", "work_units"),
        ("declared_industry", "declared_industries"),
    )
    for check_type, search_field in definitions:
        values = _case_values(case_context, search_field)
        if not values:
            continue
        terms = (
            [term for value in values for term in _location_terms(value)]
            if "location" in check_type
            else values
        )
        evidence_ids, matched_fields = _search_terms(transactions, terms)
        items.append(
            _cross_check_item(
                check_type,
                values,
                _field_records(case_context, check_type),
                evidence_ids,
                matched_fields,
                direct=True,
                coverage_available=coverage_available,
            )
        )

    purchase_records = (
        _field_records(case_context, "vehicle_model")
        + _field_records(case_context, "dealer_name")
        + _field_records(case_context, "purchase_declaration")
    )
    purchase_values = list(
        dict.fromkeys(
            str(record.get("value", "")).strip()
            for record in purchase_records
            if str(record.get("value", "")).strip()
        )
    )
    if purchase_values:
        funding = observation_by_type.get(
            "purchase_prepayment_funding_candidates",
            {},
        )
        purchase_candidates = _declared_deposit_candidates(
            funding.get("value", {}).get("purchase_candidates", []),
        )
        matched_fields: dict[str, list[str]] = {}
        for candidate in purchase_candidates:
            for field_name, terms in candidate.get("matched_fields", {}).items():
                matched_fields.setdefault(field_name, []).extend(terms)
        items.append(
            _cross_check_item(
                "purchase_deposit_expense",
                purchase_values,
                purchase_records,
                [
                    str(candidate.get("purchase_transaction_id"))
                    for candidate in purchase_candidates
                    if candidate.get("purchase_transaction_id")
                ],
                {
                    field_name: sorted(set(terms))
                    for field_name, terms in matched_fields.items()
                },
                direct=True,
                coverage_available=coverage_available,
            )
        )

    display_only_items = [
        item
        for item in (
            _display_only_item(
                field_name,
                _field_records(case_context, field_name),
            )
            for field_name in (
                "work_location",
                "residence_location",
                "vehicle_registration_location",
                "dealer_name",
                "purchase_declaration",
            )
        )
        if item is not None
    ]
    missing_automatic_fields = [
        check_type
        for check_type, search_field in definitions
        if not _case_values(case_context, search_field)
    ]
    if not purchase_values:
        missing_automatic_fields.append("purchase_deposit_expense")

    important = [
        item
        for item in items
        if item["status"] in {
            "no_evidence_in_reliable_fields",
            "unavailable",
        }
    ]
    return {
        "observation_type": "declaration_flow_cross_checks",
        "value": {
            "available": bool(items or display_only_items),
            "reason": (
                ""
                if items or display_only_items
                else "declared_information_unavailable"
            ),
            "items": items,
            "display_only_items": display_only_items,
            "missing_automatic_fields": missing_automatic_fields,
            "searched_sources": searched_sources,
            "important_notices": important,
        },
        "parameters": {
            "statuses": [
                "direct_match",
                "candidate_match",
                "no_evidence_in_reliable_fields",
                "unavailable",
            ],
            "absence_is_not_falsehood": True,
            "automatic_comparison_scope": [
                "work_unit",
                "declared_industry",
                "purchase_deposit_expense",
            ],
            "display_only_scope": [
                "work_location",
                "residence_location",
                "vehicle_registration_location",
                "dealer_name",
                "purchase_declaration",
            ],
            "purchase_direction": "income_or_expense",
            "future_life_trajectory_fields": [
                "work_location",
                "residence_location",
            ],
            "future_vehicle_trajectory_fields": [
                "vehicle_model",
                "vehicle_registration_location",
            ],
            "interpretation": "只对照显式申报与可靠流水文字；未发现依据或不可用不等于客户陈述虚假。",
        },
        "evidence_transaction_ids": list(
            dict.fromkeys(
                transaction_id
                for item in items
                for transaction_id in item["evidence_transaction_ids"]
            )
        ),
        "field_coverage": {
            "eligible_declared_item_count": len(items),
            "display_only_item_count": len(display_only_items),
            "covered_declared_item_count": len(
                [
                    item
                    for item in items
                    if item["status"] in {"direct_match", "candidate_match"}
                ]
            ),
        },
    }


def _question_id(question_type: str, key: str) -> str:
    digest = hashlib.sha256(f"{question_type}|{key}".encode("utf-8")).hexdigest()
    return f"question:{digest[:16]}"


def _question_record(
    question_type: str,
    key: str,
    question_text: str,
    trigger_reason: str,
    observation_type: str,
    evidence_ids: list[str],
    transactions_by_id: Mapping[str, Transaction],
    verification_points: list[str],
    trigger_summary: Mapping[str, object] | None = None,
) -> dict[str, object]:
    unique_evidence_ids = list(
        dict.fromkeys(evidence_id for evidence_id in evidence_ids if evidence_id)
    )
    evidence: list[dict[str, object]] = []
    for transaction_id in unique_evidence_ids:
        transaction = transactions_by_id.get(transaction_id)
        if transaction is None:
            continue
        evidence.append(
            {
                "transaction_id": transaction.transaction_id,
                "source_file_id": transaction.source_file_id,
                "source_file": transaction.source_file,
                "evidence_locator": transaction.evidence_locator,
                "transaction_time": transaction.transaction_time.isoformat(),
                "income": f"{transaction.income:.2f}",
                "expense": f"{transaction.expense:.2f}",
            }
        )
    attention_category = {
        "major_counterparty_income": "transaction_structure_attention",
        "major_counterparty_expense": "transaction_structure_attention",
        "large_inflow_short_term_outflow": "fund_flow_attention",
        "sensitive_transaction_context": "text_context_attention",
    }.get(question_type, "verification_item")
    return {
        "question_id": _question_id(question_type, key),
        "question_type": question_type,
        "question_text": question_text,
        "trigger_reason": trigger_reason,
        "trigger_observation_type": observation_type,
        "trigger_summary": dict(trigger_summary or {}),
        "verification_points": verification_points,
        "status": "pending",
        "attention_category": attention_category,
        "attention_hint_only": attention_category != "verification_item",
        "reference_only": True,
        "evidence_transaction_ids": unique_evidence_ids,
        "evidence": evidence,
        "source_file_ids": list(
            dict.fromkeys(
                str(item.get("source_file_id", ""))
                for item in evidence
                if item.get("source_file_id")
            )
        ),
        "non_conclusion": True,
    }


def _purchase_declared_completed(
    display_only_items: list[dict[str, object]],
) -> bool:
    descriptions = [
        str(value)
        for item in display_only_items
        if item.get("check_type") == "purchase_declaration"
        for value in item.get("declared_values", [])
    ]
    if any(
        re.search(pattern, description)
        for description in descriptions
        for pattern in (
            r"尚未下定",
            r"未下定",
            r"待.+下定",
            r"等.+后.+下定",
            r"准备下定",
        )
    ):
        return False
    return any(
        re.search(pattern, description)
        for description in descriptions
        for pattern in (
            r"已下定",
            r"已经下定",
            r"已(?:支付|交|付).{0,6}(?:定金|订金)",
        )
    )


def build_manual_verification_questions(
    transactions: list[Transaction],
    observations: list[dict[str, object]],
) -> dict[str, object]:
    """Build deterministic, evidence-linked questions without risk conclusions."""
    observation_by_type = _observation_map(observations)
    cross_check = observation_by_type.get("declaration_flow_cross_checks", {})
    transactions_by_id = {
        transaction.transaction_id: transaction
        for transaction in transactions
        if transaction.transaction_id
    }
    questions: list[dict[str, object]] = []
    cross_items = {
        str(item.get("check_type")): item
        for item in cross_check.get("value", {}).get("items", [])
    }

    work_unit = cross_items.get("work_unit")
    if work_unit and work_unit.get("status") in {
        "no_evidence_in_reliable_fields",
        "unavailable",
    }:
        questions.append(
            _question_record(
                "work_unit_evidence",
                str(work_unit.get("status")),
                "请确认工资或相关收入的实际发放主体，以及是否通过其他账户收取。",
                str(work_unit.get("reason", "")),
                "declaration_flow_cross_checks",
                list(work_unit.get("evidence_transaction_ids", [])),
                transactions_by_id,
                ["工资或相关收入发放主体", "是否存在其他收款账户"],
                {"cross_check_status": work_unit.get("status")},
            )
        )

    industry = cross_items.get("declared_industry")
    if industry:
        industry_status = str(industry.get("status", ""))
        if industry_status in {"direct_match", "candidate_match"}:
            questions.append(
                _question_record(
                    "declared_business_context",
                    "|".join(industry.get("evidence_transaction_ids", [])),
                    "请确认相关交易对手关系、具体商品或服务以及款项用途。",
                    "流水可靠字段中出现申报经营内容相关文字，需人工确认实际交易背景。",
                    "declaration_flow_cross_checks",
                    list(industry.get("evidence_transaction_ids", [])),
                    transactions_by_id,
                    ["交易对手关系", "具体商品或服务", "款项用途"],
                    {"cross_check_status": industry_status},
                )
            )
        elif industry_status in {
            "no_evidence_in_reliable_fields",
            "unavailable",
        }:
            questions.append(
                _question_record(
                    "declared_business_context",
                    industry_status,
                    "请结合其他账户或经营材料核实申报经营内容。",
                    str(industry.get("reason", "")),
                    "declaration_flow_cross_checks",
                    [],
                    transactions_by_id,
                    ["其他经营账户", "合同、订单或经营材料"],
                    {"cross_check_status": industry_status},
                )
            )

    purchase = cross_items.get("purchase_deposit_expense")
    display_only_items = cross_check.get("value", {}).get(
        "display_only_items",
        [],
    )
    if purchase and purchase.get("status") == "candidate_match":
        questions.append(
            _question_record(
                "purchase_deposit_expense",
                "|".join(purchase.get("evidence_transaction_ids", [])),
                "请确认该支出是否对应本次购车下定定金，并核对支付时间、金额、收款方及付款凭证。",
                "发现与系统车辆或下定信息相关的支出候选。",
                "declaration_flow_cross_checks",
                list(purchase.get("evidence_transaction_ids", [])),
                transactions_by_id,
                ["是否对应本次购车", "支付时间和金额", "收款方", "订单或付款凭证"],
                {"cross_check_status": "candidate_match"},
            )
        )
    elif (
        purchase
        and purchase.get("status") == "no_evidence_in_reliable_fields"
        and _purchase_declared_completed(display_only_items)
    ):
        questions.append(
            _question_record(
                "purchase_deposit_expense",
                "declared_completed_without_flow_evidence",
                "系统资料显示已下定，但当前可靠流水字段内未发现对应支出；请确认支付渠道并提供付款凭证。",
                str(purchase.get("reason", "")),
                "declaration_flow_cross_checks",
                [],
                transactions_by_id,
                ["支付渠道", "支付时间和金额", "订单或付款凭证"],
                {"cross_check_status": "no_evidence_in_reliable_fields"},
            )
        )

    top = observation_by_type.get("top_counterparties", {})
    declared_work_units = {
        re.sub(r"\s+", "", str(value)).casefold()
        for value in (
            work_unit.get("declared_values", [])
            if isinstance(work_unit, Mapping)
            else []
        )
    }
    for direction in ("income", "expense"):
        ranked = top.get("value", {}).get(direction, [])
        if not ranked:
            continue
        item = ranked[0]
        identity_value = re.sub(
            r"\s+",
            "",
            str(item.get("identity_value", "")),
        ).casefold()
        if identity_value in declared_work_units:
            continue
        amount = Decimal(str(item.get("amount") or "0"))
        share = Decimal(str(item.get("direction_amount_share") or "0"))
        if amount < Decimal("30000") and not (
            amount >= Decimal("1000") and share >= Decimal("0.30")
        ):
            continue
        item_evidence_ids = {
            str(value)
            for value in item.get("evidence_transaction_ids", [])
        }
        if any(
            item_evidence_ids
            and item_evidence_ids.issubset(
                set(question["evidence_transaction_ids"])
            )
            for question in questions
        ):
            continue
        questions.append(
            _question_record(
                f"major_counterparty_{direction}",
                f"{item.get('identity_field')}|{item.get('identity_value')}",
                (
                    "请确认该主要收入交易对手与客户的关系及主要款项性质。"
                    if direction == "income"
                    else "请确认该主要支出交易对手与客户的关系及主要款项性质。"
                ),
                "该对手在当前方向流水中的金额或占比较高。",
                "top_counterparties",
                list(item.get("evidence_transaction_ids", [])),
                transactions_by_id,
                ["交易对手关系", "主要款项性质"],
                {
                    "direction": direction,
                    "identity_field": item.get("identity_field"),
                    "identity_value": item.get("identity_value"),
                    "amount": item.get("amount"),
                    "direction_amount_share": item.get(
                        "direction_amount_share"
                    ),
                },
            )
        )

    paths = observation_by_type.get("large_inflow_balance_paths", {})
    low_retention_candidates = []
    low_retention_evidence: list[str] = []
    for candidate in paths.get("value", {}).get("candidates", []):
        matched_windows = [
            window
            for window in candidate.get("windows", [])
            if window.get("low_retained_balance_increment")
        ]
        if not matched_windows:
            continue
        low_retention_candidates.append(candidate)
        inflow = candidate.get("inflow_transaction", {})
        if inflow.get("transaction_id"):
            low_retention_evidence.append(str(inflow["transaction_id"]))
        for window in matched_windows:
            low_retention_evidence.extend(
                str(value)
                for value in window.get(
                    "included_component_transaction_ids",
                    [],
                )
            )
            if window.get("end_of_day_balance_transaction_id"):
                low_retention_evidence.append(
                    str(window["end_of_day_balance_transaction_id"])
                )
    if low_retention_candidates:
        questions.append(
            _question_record(
                "large_inflow_short_term_outflow",
                "|".join(
                    str(candidate.get("inflow_transaction", {}).get("transaction_id", ""))
                    for candidate in low_retention_candidates
                ),
                "请确认相关大额入账的性质及随后支出的实际用途。",
                "大额入账后1/3/7日内出现累计支出较高且余额增量留存较少的时间金额候选。",
                "large_inflow_balance_paths",
                low_retention_evidence,
                transactions_by_id,
                ["大额入账性质", "后续支出用途"],
                {
                    "candidate_count": len(low_retention_candidates),
                    "fund_source_attribution": False,
                },
            )
        )

    sensitive = observation_by_type.get(
        "sensitive_transaction_context_candidates",
        {},
    )
    sensitive_candidates = sensitive.get("value", {}).get("candidates", [])
    if sensitive_candidates:
        questions.append(
            _question_record(
                "sensitive_transaction_context",
                "|".join(
                    str(candidate.get("transaction_id", ""))
                    for candidate in sensitive_candidates
                ),
                "可靠流水字段中出现需核实的相关文字，请确认对应交易的实际性质和背景。",
                "敏感词组命中只表示文字共现，不表示真实事件、异常或风险。",
                "sensitive_transaction_context_candidates",
                [
                    str(candidate.get("transaction_id"))
                    for candidate in sensitive_candidates
                    if candidate.get("transaction_id")
                ],
                transactions_by_id,
                ["交易实际性质", "交易背景"],
                {
                    "candidate_count": len(sensitive_candidates),
                    "matched_terms": sorted(
                        {
                            str(term)
                            for candidate in sensitive_candidates
                            for term in candidate.get("matched_terms", [])
                        }
                    ),
                },
            )
        )

    search_scope_sources = cross_check.get("value", {}).get(
        "searched_sources",
        [],
    )
    search_scope_source_ids = list(
        dict.fromkeys(
            str(source.get("source_file_id", ""))
            for source in search_scope_sources
            if isinstance(source, Mapping) and source.get("source_file_id")
        )
    )
    for question in questions:
        if (
            not question["source_file_ids"]
            and question["trigger_observation_type"]
            == "declaration_flow_cross_checks"
        ):
            question["source_file_ids"] = list(search_scope_source_ids)
            question["source_scope"] = "all_declaration_search_sources"
        else:
            question["source_scope"] = "evidence_sources"

    evidence_transaction_ids = list(
        dict.fromkeys(
            transaction_id
            for question in questions
            for transaction_id in question["evidence_transaction_ids"]
        )
    )
    return {
        "observation_type": "manual_verification_questions",
        "value": {
            "available": bool(questions),
            "reason": "" if questions else "no_manual_verification_questions",
            "question_count": len(questions),
            "questions": questions,
            "search_scope_sources": search_scope_sources,
        },
        "parameters": {
            "generation_mode": "deterministic_rules_only",
            "default_status": "pending",
            "major_counterparty_amount_threshold_inclusive": "30000.00",
            "major_counterparty_direction_share_threshold_inclusive": "0.30",
            "major_counterparty_share_minimum_amount_inclusive": "1000.00",
            "similar_questions_aggregated": True,
            "display_only_fields_do_not_trigger_questions": True,
            "attention_hints_allowed": True,
            "attention_hints_are_reference_only": True,
            "risk_or_admission_conclusion": False,
            "interpretation": "问题和需关注提示只用于人工核实及参考，不预设客户陈述虚假、交易异常、欺诈、包装或准入结论。",
        },
        "evidence_transaction_ids": evidence_transaction_ids,
        "field_coverage": {
            "input_observation_count": len(observations),
            "question_count": len(questions),
            "evidence_linked_question_count": len(
                [
                    question
                    for question in questions
                    if question["evidence_transaction_ids"]
                ]
            ),
        },
    }


def _md(value: object) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _find_observation(
    result: Mapping[str, object],
    observation_type: str,
) -> dict[str, object]:
    observations = result.get("result", {}).get("observations", [])
    for observation in observations:
        if observation.get("observation_type") == observation_type:
            return observation
    return {}


def _find_indicator(
    result: Mapping[str, object],
    indicator_type: str,
) -> dict[str, object]:
    indicators = result.get("result", {}).get("indicators", [])
    for indicator in indicators:
        if indicator.get("indicator_type") == indicator_type:
            return indicator
    return {}


def _percentage(value: object) -> str:
    if value in (None, ""):
        return "不可用"
    return f"{Decimal(str(value)) * 100:.2f}%"


def _masked_display_value(field_name: str, field_value: object) -> str:
    value = str(field_value)
    if field_name == "counterparty_account":
        compact = re.sub(r"[\s-]+", "", value)
        return f"尾号{compact[-4:]}" if len(compact) >= 4 else "账号已隐藏"
    value = re.sub(
        r"(?<!\d)1\s*[3-9](?:\s*\d){9}(?!\d)",
        "手机号已隐藏",
        value,
    )
    value = re.sub(
        r"(?<!\d)\d{17}[\dXx](?!\d)",
        "证件号已隐藏",
        value,
    )
    return value


def _masked_context_summary(fields: Mapping[str, object]) -> str:
    for field_name in ("counterparty_name", "merchant_name", "summary", "purpose"):
        value = fields.get(field_name)
        if value:
            return _masked_display_value(field_name, value)
    return ""


def _fund_context_fields(context: Mapping[str, object]) -> str:
    fields = context.get("reliable_standard_fields", {})
    if not isinstance(fields, Mapping):
        return ""
    rendered: list[str] = []
    for field_name, field_value in fields.items():
        value = _masked_display_value(field_name, field_value)
        rendered.append(f"{field_name}={value}")
    return "；".join(rendered)


def _evidence_preview(values: object, limit: int = 20) -> str:
    if not isinstance(values, list):
        return ""
    evidence_ids = [str(value) for value in values if str(value)]
    preview = "；".join(evidence_ids[:limit])
    if len(evidence_ids) > limit:
        preview += f"；…另{len(evidence_ids) - limit}笔"
    return preview


def _question_trigger_display(question: Mapping[str, object]) -> str:
    reason = str(question.get("trigger_reason", ""))
    summary = question.get("trigger_summary", {})
    if not isinstance(summary, Mapping):
        return reason
    question_type = str(question.get("question_type", ""))
    details = ""
    if question_type.startswith("major_counterparty_"):
        identity_field = str(summary.get("identity_field", ""))
        identity_value = _masked_display_value(
            identity_field,
            summary.get("identity_value", ""),
        )
        details = (
            f"对手={identity_value}；金额={summary.get('amount', '')}；"
            f"占该方向金额={_percentage(summary.get('direction_amount_share'))}"
        )
    elif question_type == "large_inflow_short_term_outflow":
        details = f"候选入账数={summary.get('candidate_count', 0)}"
    elif question_type == "sensitive_transaction_context":
        details = "命中词组=" + "、".join(summary.get("matched_terms", []))
    return f"{reason} {details}".strip()


def render_mvp_markdown(
    result: Mapping[str, object],
    case_context: Mapping[str, object],
) -> str:
    """Render a concise, evidence-oriented first acceptance view."""
    case_id = str(case_context.get("case_id", "未命名案例"))
    cross_check = _find_observation(result, "declaration_flow_cross_checks")
    keyword = _find_observation(result, "controlled_keyword_candidates")
    sensitive = _find_observation(
        result,
        "sensitive_transaction_context_candidates",
    )
    funding = _find_observation(result, "purchase_prepayment_funding_candidates")
    large = _find_observation(result, "large_transaction_candidates")
    paths = _find_observation(result, "large_inflow_balance_paths")
    balance = _find_observation(result, "end_of_day_balance_and_interest")
    top = _find_observation(result, "top_counterparties")
    occurrences = _find_observation(result, "cross_source_counterparty_occurrences")
    purposes = _find_observation(result, "explicit_purpose_candidates")
    ai = _find_observation(result, "ai_business_relevance_candidates")
    questions = _find_observation(result, "manual_verification_questions")
    income_continuity = _find_indicator(result, "income_continuity")
    cashflow_change = _find_indicator(
        result,
        "cashflow_scale_and_recent_change",
    )
    fund_proximity = sorted(
        [
            indicator
            for indicator in result.get("result", {}).get("indicators", [])
            if indicator.get("indicator_type") == "fund_time_proximity"
        ],
        key=lambda indicator: indicator.get("parameters", {}).get(
            "window_days",
            0,
        ),
    )

    lines = [
        f"# 流水核查 MVP 验收报告：{case_id}",
        "",
        "> 本报告只展示程序事实、候选、证据、未发现依据和不可用原因；不输出欺诈、包装、资金来源、实际控制、通过或拒绝结论。",
        "",
        "## 1. 来源与范围",
        "",
        "| 来源文件 | 交易笔数 |",
        "| --- | ---: |",
    ]
    for source in result.get("source_files", []):
        lines.append(
            f"| {_md(Path(str(source.get('source_file', ''))).name)} | {source.get('transaction_count', 0)} |"
        )

    lines.extend(
        [
            "",
            "## 2. 申报与流水对照",
            "",
            "| 核查项 | 申报值 | 来源角色 | 来源引用 | 核实状态 | 结果 | 说明 | 证据交易ID |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in cross_check.get("value", {}).get("items", []):
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(
                        _CHECK_TYPE_LABELS.get(
                            item.get("check_type"),
                            item.get("check_type"),
                        )
                    ),
                    _md("；".join(item.get("declared_values", []))),
                    _md(
                        "；".join(
                            _ROLE_LABELS.get(role, role)
                            for role in item.get("source_roles", [])
                        )
                    ),
                    _md("；".join(item.get("source_refs", []))),
                    _md(
                        "；".join(
                            _VERIFICATION_LABELS.get(status, status)
                            for status in item.get("verification_statuses", [])
                        )
                    ),
                    _md(
                        _CROSS_CHECK_LABELS.get(
                            item.get("status"),
                            item.get("status"),
                        )
                    ),
                    _md(item.get("reason")),
                    _md("；".join(item.get("evidence_transaction_ids", [])[:10])),
                ]
            )
            + " |"
        )

    missing_automatic_fields = cross_check.get("value", {}).get(
        "missing_automatic_fields",
        [],
    )
    if missing_automatic_fields:
        lines.append(
            "\n- 系统未提供、因此未执行自动对照的项目："
            + "、".join(
                _CHECK_TYPE_LABELS.get(field_name, field_name)
                for field_name in missing_automatic_fields
            )
            + "。"
        )

    searched_sources = cross_check.get("value", {}).get(
        "searched_sources",
        [],
    )
    lines.extend(
        [
            "",
            "### 自动对照搜索范围",
            "",
            "| 来源 | 当前交易覆盖期 | 可搜索笔数/有效笔数 |",
            "| --- | --- | ---: |",
        ]
    )
    for source in searched_sources:
        period_start = source.get("observed_period_start") or "不可用"
        period_end = source.get("observed_period_end") or "不可用"
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(Path(str(source.get("source_file", ""))).name),
                    _md(f"{period_start} 至 {period_end}"),
                    _md(
                        f"{source.get('industry_search_covered_transaction_count', 0)}/"
                        f"{source.get('eligible_transaction_count', 0)}"
                    ),
                ]
            )
            + " |"
        )
    lines.append(
        "\n- 当前交易覆盖期由来源首末交易推得；未发现只表示上述期间和可靠字段内未命中。"
    )

    display_only_items = cross_check.get("value", {}).get(
        "display_only_items",
        [],
    )
    lines.extend(
        [
            "",
            "### 系统信息（仅展示）",
            "",
            "- 以下字段不与流水匹配，也不因流水未命中生成不一致结论；工作地点和住家地址留待后续生活轨迹模块共同对照。",
            "",
            "| 信息项 | 系统值 | 来源角色 | 来源引用 | 核实状态 | 处理方式 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in display_only_items:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(
                        _CHECK_TYPE_LABELS.get(
                            item.get("check_type"),
                            item.get("check_type"),
                        )
                    ),
                    _md("；".join(item.get("declared_values", []))),
                    _md(
                        "；".join(
                            _ROLE_LABELS.get(role, role)
                            for role in item.get("source_roles", [])
                        )
                    ),
                    _md("；".join(item.get("source_refs", []))),
                    _md(
                        "；".join(
                            _VERIFICATION_LABELS.get(status, status)
                            for status in item.get("verification_statuses", [])
                        )
                    ),
                    _md(item.get("reason")),
                ]
            )
            + " |"
        )

    keyword_hits = keyword.get("value", {}).get("hits", [])
    purchase_candidates = funding.get("value", {}).get("purchase_candidates", [])
    keyword_reason = {
        "no_hits_in_reliable_fields": "可靠标准文字字段内未发现受控关键词",
        "keyword_search_fields_unavailable": "没有可用于关键词搜索的可靠标准文字字段",
    }.get(
        keyword.get("value", {}).get("reason", ""),
        keyword.get("value", {}).get("reason", ""),
    )
    purchase_reason = {
        "purchase_expense_candidate_unavailable": "未发现下定或购车相关流水",
    }.get(
        funding.get("value", {}).get("reason", ""),
        funding.get("value", {}).get("reason", ""),
    )
    lines.extend(
        [
            "",
            "## 3. 关键词与下定候选",
            "",
            (
                f"- 关键词命中：{len(keyword_hits)} 笔；仅为候选。"
                if keyword_hits
                else f"- 关键词命中：0 笔；{keyword_reason}。"
            ),
            (
                f"- 下定/购车相关流水：{len(purchase_candidates)} 笔。"
                if purchase_candidates
                else f"- 下定/购车相关流水：0 笔；{purchase_reason}。"
            ),
            "",
            "| 下定相关时间 | 来源 | 方向 | 金额 | 命中字段及原文 | 命中词 | 此前收入候选 | 证据 |",
            "| --- | --- | --- | ---: | --- | --- | --- | --- |",
        ]
    )
    for candidate in purchase_candidates:
        transaction_context = candidate.get("transaction_context", {})
        reliable_fields = transaction_context.get(
            "reliable_standard_fields",
            {},
        )
        field_text = "；".join(
            f"{field_name}={field_value}"
            for field_name, field_value in reliable_fields.items()
        )
        prior = "；".join(
            f"{income.get('transaction_time')} 收入{income.get('income')}元 窗口{income.get('within_windows_days')}日"
            + (
                " 同来源"
                if income.get("same_source_as_purchase")
                else " 跨来源"
            )
            + (" 同额" if income.get("exact_amount") else "")
            + (" 近似" if income.get("near_amount") and not income.get("exact_amount") else "")
            + (" 大额" if income.get("large_income") else "")
            for income in candidate.get("prior_income_candidates", [])
        ) or (
            "当前为收入记录，不作此前收入并列"
            if candidate.get("direction") == "income"
            else "未发现满足当前规则的此前收入"
        )
        amount = (
            candidate.get("income")
            if candidate.get("direction") == "income"
            else candidate.get("expense")
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(candidate.get("transaction_time")),
                    _md(
                        Path(
                            str(transaction_context.get("source_file", ""))
                        ).name
                    ),
                    _md(transaction_context.get("direction")),
                    _md(amount),
                    _md(field_text),
                    _md("、".join(candidate.get("matched_terms", []))),
                    _md(prior),
                    _md(
                        f"{candidate.get('purchase_transaction_id', '')} {candidate.get('evidence_locator', '')}"
                    ),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "| 时间 | 收入 | 支出 | 命中词 | 对手/摘要 | 证据 |",
            "| --- | ---: | ---: | --- | --- | --- |",
        ]
    )
    for hit in keyword_hits[:30]:
        context = hit.get("transaction_context", {})
        fields = context.get("reliable_standard_fields", {})
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(context.get("transaction_time")),
                    _md(context.get("income")),
                    _md(context.get("expense")),
                    _md("、".join(hit.get("matched_terms", []))),
                    _md(_masked_context_summary(fields)),
                    _md(
                        f"{hit.get('transaction_id', '')} {hit.get('evidence_locator', '')}"
                    ),
                ]
            )
            + " |"
        )
    if len(keyword_hits) > 30:
        lines.append(f"\n> 关键词明细共 {len(keyword_hits)} 笔，本视图展示前30笔；结构化结果保留全部命中。")

    sensitive_value = sensitive.get("value", {})
    sensitive_candidates = sensitive_value.get("candidates", [])
    sensitive_reason = {
        "no_sensitive_hits_in_reliable_fields": "已搜索可靠标准文字字段，未发现敏感词组命中",
        "sensitive_search_fields_unavailable": "没有可用于敏感词组搜索的可靠标准文字字段",
    }.get(
        sensitive_value.get("reason", ""),
        sensitive_value.get("reason", ""),
    )
    lines.extend(
        [
            "",
            "### 敏感交易关键词及上下文",
            "",
            (
                f"- 敏感词组候选：{len(sensitive_candidates)} 笔；仅为待人工核查候选。"
                if sensitive_candidates
                else f"- 敏感词组候选：0 笔；{sensitive_reason}。"
            ),
            f"- 词表版本：{sensitive.get('parameters', {}).get('vocabulary_version', '')}；不对“抵、押、借、贷、租、融、资、医、法”等单字做无条件匹配。",
            "",
            "| 来源 | 当前交易覆盖期 | 可搜索笔数/有效笔数 | 候选笔数 | 状态 |",
            "| --- | --- | ---: | ---: | --- |",
        ]
    )
    for source in sensitive_value.get("searched_sources", []):
        source_reason = {
            "sensitive_search_fields_unavailable": "可靠标准文字字段不可用",
        }.get(source.get("reason", ""), "已搜索")
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(Path(str(source.get("source_file", ""))).name),
                    _md(
                        f"{source.get('observed_period_start')} 至 "
                        f"{source.get('observed_period_end')}"
                    ),
                    _md(
                        f"{source.get('searched_transaction_count')}/"
                        f"{source.get('eligible_transaction_count')}"
                    ),
                    _md(source.get("candidate_count")),
                    _md(source_reason),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "| 时间 | 来源 | 方向 | 收入 | 支出 | 余额 | 命中字段及原文 | 命中词组 | 完整可靠文字上下文 | 证据 |",
            "| --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for candidate in sensitive_candidates:
        context = candidate.get("transaction_context", {})
        reliable_fields = context.get("reliable_standard_fields", {})
        matched_fields = candidate.get("matched_fields", {})
        matched_original = "；".join(
            f"{field_name}="
            f"{_masked_display_value(field_name, reliable_fields.get(field_name, ''))}"
            for field_name in matched_fields
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(context.get("transaction_time")),
                    _md(Path(str(context.get("source_file", ""))).name),
                    _md(context.get("direction")),
                    _md(context.get("income")),
                    _md(context.get("expense")),
                    _md(context.get("balance")),
                    _md(matched_original),
                    _md("、".join(candidate.get("matched_terms", []))),
                    _md(_fund_context_fields(context)),
                    _md(
                        f"{candidate.get('transaction_id', '')} "
                        f"{candidate.get('evidence_locator', '')}"
                    ),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "- 当前交易覆盖期由各来源首末交易推得，不冒充原件声明期间。",
            "- 命中只表示可靠字段中出现受控词组，不表示真实借贷、抵押、诉讼、医疗事实、异常、欺诈或准入结论。",
        ]
    )

    large_count = len(large.get("value", {}).get("candidates", []))
    large_candidates = large.get("value", {}).get("candidates", [])
    path_candidates = paths.get("value", {}).get("candidates", [])
    path_value = paths.get("value", {})
    unavailable_source_count = path_value.get(
        "source_file_id_unavailable_count",
        0,
    )
    path_reason = {
        "no_income_meets_path_threshold": "没有达到3万元阈值的收入",
        "source_file_id_unavailable": "大额入账缺少可靠来源文件ID，不能构造同来源路径",
    }.get(
        paths.get("value", {}).get("reason", ""),
        paths.get("value", {}).get("reason", ""),
    )
    low_count = sum(
        any(window.get("low_retained_balance_increment") for window in candidate.get("windows", []))
        for candidate in path_candidates
    )
    lines.extend(
        [
            "",
            "## 4. 资金与余额观察",
            "",
            "### 1/3/7 日收入后支出时间共现",
            "",
            "| 窗口 | 配对数 | 涉及收入笔数 | 涉及后续支出笔数 | 证据交易ID |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    for indicator in fund_proximity:
        value = indicator.get("value", {})
        parameters = indicator.get("parameters", {})
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(f"{parameters.get('window_days')}日"),
                    _md(value.get("time_proximity_pair_count")),
                    _md(value.get("income_transaction_count_with_later_expense")),
                    _md(value.get("later_expense_transaction_count")),
                    _md(
                        _evidence_preview(
                            indicator.get("evidence_transaction_ids", [])
                        )
                    ),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "- 该指标窗口起止均含边界，只表示先收入后支出的时间共现；可跨来源并列，不表示支出资金来源于某笔收入。",
            "- 时间共现证据在本视图每个窗口最多展示20个交易ID；结构化结果保留全部证据。",
            "",
            f"- 1万元以上交易：{large_count} 笔。",
            (
                f"- 3万元以上入账路径：{len(path_candidates)} 笔；其中 {low_count} 笔至少一个窗口满足低留存候选。"
                if path_candidates
                else f"- 3万元以上入账路径：0 笔；{path_reason}。"
            ),
            (
                f"- 另有 {unavailable_source_count} 笔达到3万元阈值的入账因缺少可靠来源文件ID未构造路径。"
                if unavailable_source_count
                else ""
            ),
            "- 拆分支出纳入门槛：单笔支出达到 max(1000元, 入账额×5%)；累计支出等于入账额为精确同额，90%-110%为近似总额，达到80%为短期大部分转出。",
            "- 余额增量留存比例：max(窗口日末余额-入账前余额, 0)÷入账额；在短期大部分转出成立且该比例不超过20%时标记低留存候选。",
            "- 窗口日末余额取同一来源在目标日结束前最后一笔可得余额；目标日无交易时沿用此前最近余额快照。",
            "- 上述路径仅表示同来源时间、金额和余额共现，不认定后续支出使用了该笔收入。",
            "- fund_source_attribution=false。",
            "- 本模块只展示入账后 1/3/7 日路径，不计算或断言某笔资金实际停留时长。",
            "",
            "### 大额交易清单",
            "",
            "| 时间 | 来源 | 收入 | 支出 | 余额 | 可靠文字字段 | 证据 |",
            "| --- | --- | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for candidate in large_candidates:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(candidate.get("transaction_time")),
                    _md(Path(str(candidate.get("source_file", ""))).name),
                    _md(candidate.get("income")),
                    _md(candidate.get("expense")),
                    _md(candidate.get("balance")),
                    _md(_fund_context_fields(candidate)),
                    _md(
                        f"{candidate.get('transaction_id', '')} "
                        f"{candidate.get('evidence_locator', '')}"
                    ),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "### 大额入账后 1/3/7 日路径",
            "",
            "| 入账时间 | 来源 | 入账额 | 入账前余额 | 窗口路径 | 证据交易ID |",
            "| --- | --- | ---: | ---: | --- | --- |",
        ]
    )
    for candidate in path_candidates:
        inflow = candidate.get("inflow_transaction", {})
        windows: list[str] = []
        evidence_ids = [str(inflow.get("transaction_id", ""))]
        for window in candidate.get("windows", []):
            labels = []
            if window.get("exact_total_outflow"):
                labels.append("精确同额")
            if window.get("near_total_outflow"):
                labels.append("近似总额")
            if window.get("large_portion_outflow"):
                labels.append("短期大部分转出")
            if window.get("low_retained_balance_increment"):
                labels.append("余额增量低留存")
            window_evidence = [
                str(item)
                for item in window.get(
                    "included_component_transaction_ids",
                    [],
                )
            ]
            balance_evidence = str(
                window.get("end_of_day_balance_transaction_id", "")
            )
            evidence_ids.extend(window_evidence)
            if balance_evidence:
                evidence_ids.append(balance_evidence)
            windows.append(
                f"{window.get('window_days')}日："
                f"累计支出{window.get('cumulative_expense')}（"
                f"{_percentage(window.get('cumulative_expense_ratio'))}）；"
                f"日末余额{window.get('end_of_day_balance') or '不可用'}；"
                f"留存增量{_percentage(window.get('retained_balance_increment_ratio'))}"
                + (f"；{'、'.join(labels)}" if labels else "")
            )
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(inflow.get("transaction_time")),
                    _md(Path(str(inflow.get("source_file", ""))).name),
                    _md(inflow.get("income")),
                    _md(candidate.get("pre_inflow_balance")),
                    _md("<br>".join(windows)),
                    _md("；".join(dict.fromkeys(item for item in evidence_ids if item))),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "### 月度收入连续性与收支变化",
            "",
        ]
    )
    continuity_value = income_continuity.get("value", {})
    if continuity_value.get("available"):
        lines.extend(
            [
                (
                    f"- 数据期月份：{continuity_value.get('period_month_count')}；"
                    f"有收入月份：{continuity_value.get('income_month_count')}；"
                    f"收入月份覆盖率：{_percentage(continuity_value.get('income_month_coverage_rate'))}；"
                    f"最长连续收入月份：{continuity_value.get('longest_consecutive_income_month_count')}。"
                ),
                (
                    "- 无收入月份："
                    + (
                        "、".join(continuity_value.get("months_without_income", []))
                        or "无"
                    )
                    + "。"
                ),
                (
                    "- 收入连续性证据交易ID："
                    + _evidence_preview(
                        income_continuity.get(
                            "evidence_transaction_ids",
                            [],
                        )
                    )
                    + "。"
                ),
            ]
        )
    else:
        lines.append("- 月度收入连续性不可用：没有可分析交易。")

    cashflow_value = cashflow_change.get("value", {})
    full_period = cashflow_value.get("full_period", {})
    comparison = cashflow_value.get("recent_comparison", {})
    if cashflow_value.get("available"):
        lines.append(
            f"- 全期间 {full_period.get('period_start_month')} 至 "
            f"{full_period.get('period_end_month')}，按 {full_period.get('month_count')} 个自然月计算："
            f"月均收入 {full_period.get('monthly_average_income')} 元，"
            f"月均支出 {full_period.get('monthly_average_expense')} 元。"
        )
        lines.append(
            "- 月度收支证据交易ID："
            + _evidence_preview(
                cashflow_change.get("evidence_transaction_ids", [])
            )
            + "。"
        )
        if comparison.get("available"):
            lines.extend(
                [
                    "",
                    "| 比较项 | 前3个月 | 近3个月 | 变化额 | 变化率 |",
                    "| --- | ---: | ---: | ---: | ---: |",
                    (
                        f"| 收入（{comparison.get('previous_window_start_month')}至"
                        f"{comparison.get('previous_window_end_month')} 对 "
                        f"{comparison.get('recent_window_start_month')}至"
                        f"{comparison.get('recent_window_end_month')}） | "
                        f"{comparison.get('previous_window_income')} | "
                        f"{comparison.get('recent_window_income')} | "
                        f"{comparison.get('income_change')} | "
                        f"{_percentage(comparison.get('income_change_rate'))} |"
                    ),
                    (
                        f"| 支出 | {comparison.get('previous_window_expense')} | "
                        f"{comparison.get('recent_window_expense')} | "
                        f"{comparison.get('expense_change')} | "
                        f"{_percentage(comparison.get('expense_change_rate'))} |"
                    ),
                ]
            )
        else:
            lines.append("- 近3个月与此前3个月比较不可用：数据期不足连续6个自然月。")
    else:
        lines.append("- 月度收支变化不可用：没有可分析交易。")
    lines.extend(
        [
            "- 月份按首末交易所在自然月建立，零交易月计入；边界月份可能不是完整自然月。上述数值不表示经营趋势、收入稳定性或还款能力。",
            "",
            "### 日末余额与结息",
            "",
            "| 来源 | 余额状态 | 日末余额日数 | 最低 | 中位 | 平均 | 期末 | 结息/利息笔数 | 余额证据交易ID |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for source in balance.get("value", {}).get("sources", []):
        stats = source.get("balance_statistics") or {}
        balance_status = {
            "balance_not_applicable": "不适用（该来源无余额字段）",
            "reliable_balance_unavailable": "不可用（可靠余额缺失）",
        }.get(
            source.get("balance_unavailable_reason", ""),
            "可用",
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(Path(str(source.get("source_file", ""))).name),
                    _md(balance_status),
                    _md(stats.get("day_count", "不可用")),
                    _md(stats.get("minimum", "")),
                    _md(stats.get("median", "")),
                    _md(stats.get("average", "")),
                    _md(stats.get("closing", "")),
                    _md(len(source.get("interest_records", []))),
                    _md(
                        _evidence_preview(
                            source.get(
                                "balance_snapshot_transaction_ids",
                                [],
                            )
                        )
                    ),
                ]
            )
            + " |"
        )
    interest_reason_labels = {
        "interest_records_unavailable": "没有可用于检索结息/利息的可靠文字字段",
        "no_interest_records_in_reliable_fields": "已检索可靠文字字段，未发现结息/利息记录",
    }
    for source in balance.get("value", {}).get("sources", []):
        source_name = Path(str(source.get("source_file", ""))).name
        lines.extend(["", f"#### {source_name} 结息/利息"])
        interest_records = source.get("interest_records", [])
        if not interest_records:
            reason = interest_reason_labels.get(
                source.get("interest_unavailable_reason", ""),
                source.get("interest_unavailable_reason", ""),
            )
            lines.append(f"- {reason}。")
            continue
        lines.extend(
            [
                "",
                "| 时间 | 收入 | 支出 | 净结息 | 可靠文字字段 | 证据 |",
                "| --- | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for record in interest_records:
            net_interest = Decimal(str(record.get("income", "0"))) - Decimal(
                str(record.get("expense", "0"))
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md(record.get("transaction_time")),
                        _md(record.get("income")),
                        _md(record.get("expense")),
                        _md(f"{net_interest:.2f}"),
                        _md(_fund_context_fields(record)),
                        _md(
                            f"{record.get('transaction_id', '')} "
                            f"{record.get('evidence_locator', '')}"
                        ),
                    ]
                )
                + " |"
            )
        lines.extend(
            [
                "",
                "| 季度 | 净结息 | 较上一列示季度变化 |",
                "| --- | ---: | ---: |",
            ]
        )
        for quarter in source.get("quarterly_interest", []):
            lines.append(
                f"| {_md(quarter.get('quarter'))} | "
                f"{_md(quarter.get('net_interest'))} | "
                f"{_md(quarter.get('change_from_previous') or '不可比')} |"
            )
    lines.extend(
        [
            "",
            "- 日末余额为逐来源每个自然日最后一笔有余额交易后的快照，不是日均余额，也不合并不同账户。",
            "- 结息/利息只按可靠标准文字字段命中逐笔汇总；不能据此反推平均存款本金、资金充足程度或偿债能力。",
        ]
    )

    lines.extend(["", "## 5. 主要交易对手 Top 5", ""])
    for direction, title in (("income", "收入"), ("expense", "支出")):
        summary = top.get("value", {}).get(f"{direction}_summary", {})
        reason = {
            f"no_{direction}_transactions": f"没有{title}交易",
            "identifiable_counterparty_unavailable": "存在交易，但可靠可识别对手字段不可用",
        }.get(summary.get("reason", ""), summary.get("reason", ""))
        lines.extend(
            [
                f"### {title} Top 5",
                "",
                (
                    f"- 可识别对手金额覆盖：{summary.get('covered_amount', '0.00')} / "
                    f"{summary.get('eligible_amount', '0.00')} 元"
                    f"（{summary.get('amount_coverage_rate') or '不可计算'}）；"
                    f"可识别对手数：{summary.get('distinct_identifiable_counterparty_count', 0)}。"
                    if summary.get("available")
                    else f"- 当前不可用：{reason}。"
                ),
                "",
                "| 对手 | 身份字段 | 金额 | 占可识别金额 | 占全部方向金额 | 笔数 | 月份 | 证据交易ID |",
                "| --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
            ]
        )
        for item in top.get("value", {}).get(direction, []):
            identity_value = str(item.get("identity_value", ""))
            display_value = _masked_display_value(
                str(item.get("identity_field", "")),
                identity_value,
            )
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md(display_value),
                        _md(item.get("identity_field")),
                        _md(item.get("amount")),
                        _md(item.get("covered_amount_share")),
                        _md(item.get("direction_amount_share")),
                        _md(item.get("transaction_count")),
                        _md("、".join(item.get("months", []))),
                        _md(
                            "；".join(
                                item.get("evidence_transaction_ids", [])[:10]
                            )
                        ),
                    ]
                )
                + " |"
            )
        lines.append("")

    cross_rows = occurrences.get("value", {}).get("counterparties", [])
    lines.extend(
        [
            "## 6. 跨来源同名出现",
            "",
            "| 对手名称 | 来源数 | 各来源笔数与收支 |",
            "| --- | ---: | --- |",
        ]
    )
    for item in cross_rows[:20]:
        source_summary = "；".join(
            f"{Path(str(source.get('source_file', ''))).name} {source.get('transaction_count', 0)}笔 收{source.get('income')} 支{source.get('expense')}"
            for source in item.get("sources", [])
        )
        lines.append(
            f"| {_md(_masked_display_value('counterparty_name', item.get('counterparty_name')))} | "
            f"{item.get('source_count', 0)} | {_md(source_summary)} |"
        )
    if len(cross_rows) > 20:
        lines.append(f"\n> 跨来源同名共 {len(cross_rows)} 个，本视图展示前20个；精确证据保留在结构化结果中。")

    purpose_counts: dict[str, int] = {}
    for item in purposes.get("value", {}).get("candidates", []):
        category = str(item.get("category"))
        purpose_counts[category] = purpose_counts.get(category, 0) + 1
    lines.extend(
        [
            "",
            "## 7. 明确用途与 AI 状态",
            "",
            "- 明确用途候选：" + "；".join(
                f"{_PURPOSE_LABELS.get(category, category)} {count}笔"
                for category, count in sorted(purpose_counts.items())
            ),
            "- AI经营关联状态："
            + _md(
                _AI_REASON_LABELS.get(
                    ai.get("value", {}).get("reason"),
                    ai.get("value", {}).get("reason") or "可用",
                )
            )
            + "。",
            f"- 确定性单位/行业直接命中：{len(ai.get('value', {}).get('deterministic_candidates', []))} 笔。",
            "",
            "## 8. 人工核实事项与需关注提示",
            "",
            "- “需关注”仅表示建议优先人工查看的事实线索，只作参考，不是风险结论、评分或准入意见。",
            "",
            "| 类型 | 核实问题 | 触发原因 | 状态 | 证据交易ID |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    question_rows = questions.get("value", {}).get("questions", [])
    for question in question_rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    (
                        "需关注（仅供参考）"
                        if question.get("attention_hint_only")
                        else "一般核实"
                    ),
                    _md(question.get("question_text")),
                    _md(_question_trigger_display(question)),
                    _md(
                        "待核实"
                        if question.get("status") == "pending"
                        else question.get("status")
                    ),
                    _md(
                        _evidence_preview(
                            question.get("evidence_transaction_ids"),
                            10,
                        )
                    ),
                ]
            )
            + " |"
        )
    if not question_rows:
        lines.append("| 一般核实 | 当前规则未生成待人工核实事项 |  |  |  |")

    lines.extend(
        [
            "",
            "## 9. 可追溯交易证据",
            "",
        ]
    )
    evidence = result.get("result", {}).get("evidence", {})
    evidence_coverage = evidence.get("coverage", {})
    evidence_integrity = evidence.get("integrity", {})
    evidence_status = (
        "完整"
        if evidence_integrity.get("complete")
        else "存在缺失、重复或悬空引用，需人工复核"
    )
    lines.extend(
        [
            f"- 证据链状态：{evidence_status}。",
            (
                "- 原始交易："
                f"{evidence_coverage.get('original_transaction_count', 0)} 笔；"
                f"已建立唯一索引：{evidence_coverage.get('indexed_transaction_count', 0)} 笔；"
                f"完整交易ID、来源文件ID及页/行定位："
                f"{evidence_coverage.get('fully_traceable_transaction_count', 0)} 笔。"
            ),
            (
                "- 被事实、指标、观察和人工事项引用的交易："
                f"{evidence_coverage.get('referenced_transaction_count', 0)} 笔；"
                f"证据链接：{evidence_coverage.get('evidence_link_count', 0)} 个；"
                f"悬空：{evidence_coverage.get('unresolved_evidence_link_count', 0)} 个；"
                f"歧义：{evidence_coverage.get('ambiguous_evidence_link_count', 0)} 个。"
            ),
            "- 本视图只显示汇总；结构化结果保留交易ID到 original_transactions 的索引、页/行定位及逐项引用状态，供GUI按需展开。",
            "",
            "## 10. 重要提示",
            "",
        ]
    )
    notices = cross_check.get("value", {}).get("important_notices", [])
    if notices:
        for item in notices:
            lines.append(
                f"- {item.get('check_type')}：{_CROSS_CHECK_LABELS.get(item.get('status'), item.get('status'))}。{item.get('reason')}"
            )
    else:
        lines.append("- 当前已录入的重点申报字段均有直接或候选文字依据；仍需人工结合原始资料判断。")
    lines.extend(
        [
            "- 关键词、同名、近似金额、短期支出和低留存均是核查候选，不是风险定性。",
            "- 征信、企业关系、合同、订单、资产和客户解释等外部事实仍需人工核实。",
            "",
        ]
    )
    return "\n".join(lines)
