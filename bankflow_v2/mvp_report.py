"""Declaration cross-check and Markdown view for the bank-flow MVP."""

from __future__ import annotations

import re
from collections.abc import Mapping
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
        "status": status,
        "reason": reason,
        "matched_fields": matched_fields,
        "evidence_transaction_ids": evidence_ids,
    }


def build_declaration_flow_cross_check(
    transactions: list[Transaction],
    case_context: Mapping[str, object] | None,
    observations: list[dict[str, object]],
) -> dict[str, object]:
    """Compare explicit case fields with reliable flow text without truth inference."""
    observation_by_type = _observation_map(observations)
    coverage_available = _coverage_available(observation_by_type)
    items: list[dict[str, object]] = []

    definitions = (
        ("work_unit", "work_units", True),
        ("declared_industry", "declared_industries", True),
        ("work_location", "work_locations", False),
        ("residence_location", "residence_locations", False),
        (
            "vehicle_registration_location",
            "vehicle_registration_locations",
            False,
        ),
    )
    for check_type, search_field, direct in definitions:
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
                direct=direct,
                coverage_available=coverage_available,
            )
        )

    purchase_values = (
        _case_values(case_context, "vehicle_models")
        + _case_values(case_context, "dealer_names")
        + [
            record["value"]
            for record in _field_records(case_context, "purchase_declaration")
            if record.get("value")
        ]
    )
    if purchase_values:
        purchase_records = (
            _field_records(case_context, "vehicle_model")
            + _field_records(case_context, "dealer_name")
            + _field_records(case_context, "purchase_declaration")
        )
        keyword = observation_by_type.get("controlled_keyword_candidates", {})
        purchase_hits = [
            hit
            for hit in keyword.get("value", {}).get("hits", [])
            if "purchase_and_vehicle_order" in hit.get("keyword_groups", [])
        ]
        items.append(
            _cross_check_item(
                "purchase",
                purchase_values,
                purchase_records,
                [
                    str(hit.get("transaction_id"))
                    for hit in purchase_hits
                    if hit.get("transaction_id")
                ],
                {
                    field_name: list(terms)
                    for hit in purchase_hits
                    for field_name, terms in hit.get("matched_fields", {}).items()
                },
                direct=False,
                coverage_available=coverage_available,
            )
        )

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
            "available": bool(items),
            "reason": "" if items else "declared_search_fields_unavailable",
            "items": items,
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
            "covered_declared_item_count": len(
                [
                    item
                    for item in items
                    if item["status"] in {"direct_match", "candidate_match"}
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


def render_mvp_markdown(
    result: Mapping[str, object],
    case_context: Mapping[str, object],
) -> str:
    """Render a concise, evidence-oriented first acceptance view."""
    case_id = str(case_context.get("case_id", "未命名案例"))
    cross_check = _find_observation(result, "declaration_flow_cross_checks")
    keyword = _find_observation(result, "controlled_keyword_candidates")
    funding = _find_observation(result, "purchase_prepayment_funding_candidates")
    large = _find_observation(result, "large_transaction_candidates")
    paths = _find_observation(result, "large_inflow_balance_paths")
    balance = _find_observation(result, "end_of_day_balance_and_interest")
    top = _find_observation(result, "top_counterparties")
    occurrences = _find_observation(result, "cross_source_counterparty_occurrences")
    purposes = _find_observation(result, "explicit_purpose_candidates")
    ai = _find_observation(result, "ai_business_relevance_candidates")

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
            "| 核查项 | 申报值 | 来源角色 | 核实状态 | 结果 | 说明 | 证据交易ID |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in cross_check.get("value", {}).get("items", []):
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(item.get("check_type")),
                    _md("；".join(item.get("declared_values", []))),
                    _md(
                        "；".join(
                            _ROLE_LABELS.get(role, role)
                            for role in item.get("source_roles", [])
                        )
                    ),
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
        "purchase_expense_candidate_unavailable": "未发现下定或购车支出候选",
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
                f"- 下定/购车支出候选：{len(purchase_candidates)} 笔。"
                if purchase_candidates
                else f"- 下定/购车支出候选：0 笔；{purchase_reason}。"
            ),
            "",
            "| 下定候选时间 | 来源 | 方向 | 支出 | 命中字段及原文 | 命中词 | 此前收入候选 | 证据 |",
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
        ) or "未发现满足当前规则的此前收入"
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
                    _md(candidate.get("expense")),
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
                    _md(
                        fields.get("counterparty_name")
                        or fields.get("merchant_name")
                        or fields.get("summary")
                        or fields.get("purpose")
                        or ""
                    ),
                    _md(
                        f"{hit.get('transaction_id', '')} {hit.get('evidence_locator', '')}"
                    ),
                ]
            )
            + " |"
        )
    if len(keyword_hits) > 30:
        lines.append(f"\n> 关键词明细共 {len(keyword_hits)} 笔，本视图展示前30笔；结构化结果保留全部命中。")

    large_count = len(large.get("value", {}).get("candidates", []))
    path_candidates = paths.get("value", {}).get("candidates", [])
    low_count = sum(
        any(window.get("low_retained_balance_increment") for window in candidate.get("windows", []))
        for candidate in path_candidates
    )
    lines.extend(
        [
            "",
            "## 4. 资金与余额观察",
            "",
            f"- 1万元以上交易：{large_count} 笔。",
            f"- 3万元以上入账路径：{len(path_candidates)} 笔；其中 {low_count} 笔至少一个窗口满足低留存候选。",
            "- 上述路径仅表示同来源时间、金额和余额共现，不认定后续支出使用了该笔收入。",
            "",
            "| 来源 | 日末余额日数 | 最低 | 中位 | 平均 | 期末 | 结息/利息笔数 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for source in balance.get("value", {}).get("sources", []):
        stats = source.get("balance_statistics") or {}
        lines.append(
            "| "
            + " | ".join(
                [
                    _md(Path(str(source.get("source_file", ""))).name),
                    _md(stats.get("day_count", "不可用")),
                    _md(stats.get("minimum", "")),
                    _md(stats.get("median", "")),
                    _md(stats.get("average", "")),
                    _md(stats.get("closing", "")),
                    _md(len(source.get("interest_records", []))),
                ]
            )
            + " |"
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
            display_value = (
                f"账号尾号{identity_value[-4:]}"
                if item.get("identity_field") == "counterparty_account"
                else identity_value
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
            f"| {_md(item.get('counterparty_name'))} | {item.get('source_count', 0)} | {_md(source_summary)} |"
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
            "## 8. 重要提示",
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
