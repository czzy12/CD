"""Minimal, source-aware case context for bank-flow business observations."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


CASE_CONTEXT_SCHEMA_VERSION = "1.1"

SOURCE_ROLE_SYSTEM_CUSTOMER_DATA = "system_customer_data"
SOURCE_ROLE_CUSTOMER_MANAGER_DESCRIPTION = "customer_manager_description"
SOURCE_ROLE_RISK_INVESTIGATION_REPORT = "risk_investigation_report"

SOURCE_ROLES = {
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    SOURCE_ROLE_CUSTOMER_MANAGER_DESCRIPTION,
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
}

_ANALYSIS_BOUNDARY_RE = re.compile(r"^\s*(?:本人分析|个人分析)\s*[：:]?\s*$")
_INLINE_FIELD_RE = re.compile(r"^\s*([^：:]{1,40})\s*[：:]\s*(.*?)\s*$")
_EXPLICIT_WORK_CONTENT_RE = re.compile(
    r"(?:客户)?\s*(?:主要)?\s*(?:是做|从事|经营)\s*"
    r"([^，,。；;]+?)(?:的(?=[，,。；;]|$)|[，,。；;]|$)"
)
_SPECIFIC_WORK_CONTENT_RE = re.compile(
    r"批发|零售|销售|生产|加工|运输|物流|工程|施工|装修|"
    r"餐饮|烟酒|建材|建筑材料|维修|设计|种植|养殖|服务"
)
_IRRELEVANT_WORK_CONTEXT_RE = re.compile(
    r"信用卡|日常消费|家庭|住址|居住|购车|车型|负债|贷款"
)
_GENERIC_WORK_DESCRIPTIONS = {
    "是",
    "否",
    "做生意",
    "自己经营",
    "自行经营",
    "其他生意",
    "生意",
    "经商",
    "个体经营",
    "经营收入",
    "流水匹配",
    "与流水匹配",
    "基本匹配",
    "符合",
    "有体现",
    "已核实",
    "工作",
    "经营",
}
_BUSINESS_TOPIC_PATTERNS = {
    "construction_related": re.compile(
        r"建材|建筑材料|建筑安装|建安|施工|工程|装修|装饰|环保|环境治理"
    ),
    "alcohol": re.compile(r"烟酒|酒类"),
    "transport": re.compile(r"运输|物流"),
    "dining": re.compile(r"餐饮|饭店|餐厅"),
    "technology": re.compile(r"科技|软件|信息技术"),
}

_FIELD_BY_LABEL = {
    "姓名": "customer_name",
    "客户姓名": "customer_name",
    "工作单位全称": "work_unit",
    "单位全称": "work_unit",
    "工作单位详细地址": "work_location",
    "单位地址": "work_location",
    "家庭地址（详细到门牌号）": "residence_location",
    "家庭住址": "residence_location",
    "居住地址": "residence_location",
    "上牌地": "vehicle_registration_location",
    "落户地": "vehicle_registration_location",
    "购买车型": "vehicle_model",
    "车型": "vehicle_model",
    "经销商": "dealer_name",
    "经销商名称": "dealer_name",
    "行业": "declared_industry",
    "经营行业": "declared_industry",
    "主营业务": "declared_industry",
    "职务": "job_title",
    "收入构成": "income_type",
    "年收入": "annual_income",
    "月收入": "monthly_income",
    "家庭月收入": "monthly_income",
}

_MANAGER_DESCRIPTION_BY_LABEL = {
    "下定人及试驾情况": "purchase_declaration",
    "首台/置换/增购": "purchase_need",
    "购车需求": "purchase_need",
    "三地不一致解释": "location_consistency_description",
    "电核/面访异常点简介": "manager_risk_description",
    "电核/面访异常点": "manager_risk_description",
    "电核客户情况介绍（异常点或亮点）": "manager_risk_description",
    "工作介绍及收入情况（是否和流水匹配）": "manager_work_income_description",
    "业务人员备注": "manager_business_description",
    "客户经理备注": "manager_business_description",
    "银行流水验真手段和日期": "manager_bank_verification_description",
    "微信流水是否有体现工作地和生活地": "manager_location_trace_description",
    "本人是否熟悉车型配置": "manager_vehicle_familiarity_description",
}


def _normalize_label(value: str) -> str:
    return re.sub(r"\s+", "", value).strip("：:")


def _system_copy_lines(text: str) -> list[str]:
    lines: list[str] = []
    for line in str(text or "").splitlines():
        if _ANALYSIS_BOUNDARY_RE.match(line):
            break
        stripped = line.strip()
        if stripped:
            lines.append(stripped)
    return lines


def _recognized_label(line: str) -> str | None:
    normalized = _normalize_label(line)
    if normalized in _FIELD_BY_LABEL or normalized in _MANAGER_DESCRIPTION_BY_LABEL:
        return normalized
    return None


def _parse_system_copy(text: str) -> list[tuple[str, str, str]]:
    lines = _system_copy_lines(text)
    parsed: list[tuple[str, str, str]] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        match = _INLINE_FIELD_RE.match(line)
        if match:
            label = _normalize_label(match.group(1))
            value = match.group(2).strip()
            if label in _FIELD_BY_LABEL or label in _MANAGER_DESCRIPTION_BY_LABEL:
                if not value and index + 1 < len(lines) and _recognized_label(lines[index + 1]) is None:
                    index += 1
                    value = lines[index].strip()
                if value:
                    parsed.append((label, value, line))
            index += 1
            continue

        label = _recognized_label(line)
        if label and index + 1 < len(lines) and _recognized_label(lines[index + 1]) is None:
            value = lines[index + 1].strip()
            if value:
                parsed.append((label, value, f"{line}\\n{value}"))
            index += 2
            continue
        index += 1
    return parsed


def _field_record(
    value: str,
    source_role: str,
    source_ref: str,
    source_excerpt: str,
    source_field: str = "",
) -> dict[str, str]:
    return {
        "value": value,
        "source_role": source_role,
        "source_ref": source_ref,
        "verification_status": "reported" if source_role == SOURCE_ROLE_RISK_INVESTIGATION_REPORT else "unverified",
        "source_excerpt": source_excerpt,
        "source_field": source_field,
    }


def _normalized_field_value(field_name: str, value: str) -> str:
    normalized = value.strip()
    if field_name == "customer_name":
        normalized = re.split(r"[，,]", normalized, maxsplit=1)[0].strip()
        normalized = re.sub(r"[（(].*$", "", normalized).strip()
    return normalized


def _explicit_work_content_values(value: str) -> list[str]:
    values: list[str] = []
    for match in _EXPLICIT_WORK_CONTENT_RE.finditer(str(value or "")):
        work_content = match.group(1).strip()
        if (
            2 <= len(work_content) <= 40
            and work_content not in {"工作", "经营", "生意", "其他生意"}
            and not _IRRELEVANT_WORK_CONTEXT_RE.search(work_content)
        ):
            values.append(work_content)
    return list(dict.fromkeys(values))


def _declared_work_content_values(
    value: str,
    *,
    allow_standalone: bool = False,
) -> list[str]:
    explicit = _explicit_work_content_values(value)
    if explicit:
        return explicit
    values: list[str] = []
    for part in re.split(r"[，,。；;\n]+", str(value or "")):
        normalized = part.strip()
        normalized = re.sub(
            r"^(?:客户)?(?:主要)?(?:工作|业务|主营业务)(?:是|为|包括)?",
            "",
            normalized,
        ).strip()
        if (
            not normalized
            or normalized in _GENERIC_WORK_DESCRIPTIONS
            or _IRRELEVANT_WORK_CONTEXT_RE.search(normalized)
            or len(normalized) > 80
            or (
                not allow_standalone
                and not _SPECIFIC_WORK_CONTENT_RE.search(normalized)
            )
        ):
            continue
        values.append(normalized)
    return list(dict.fromkeys(values))


def _business_topics(value: str) -> set[str]:
    return {
        topic
        for topic, pattern in _BUSINESS_TOPIC_PATTERNS.items()
        if pattern.search(str(value or ""))
    }


def _build_business_context(
    fields: Mapping[str, list[dict[str, str]]],
    business_confirmation: Mapping[str, object] | None,
) -> dict[str, object]:
    evidence: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for field_name in ("declared_work_description", "declared_industry"):
        for record in fields.get(field_name, []):
            for value in _declared_work_content_values(
                record.get("value", ""),
                allow_standalone=(
                    field_name == "declared_work_description"
                    or record.get("source_field")
                    in {"行业", "经营行业", "主营业务"}
                ),
            ):
                key = (
                    value,
                    record.get("source_ref", ""),
                    record.get("source_field", ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                evidence.append(
                    {
                        "value": value,
                        "source_field": record.get("source_field", ""),
                        "source_ref": record.get("source_ref", ""),
                        "source_role": record.get("source_role", ""),
                        "source_excerpt": record.get("source_excerpt", ""),
                        "status": "declared_unverified",
                    }
                )
    declared_values = list(
        dict.fromkeys(item["value"] for item in evidence)
    )
    companies = _field_values(fields, "work_unit")
    confirmation = (
        business_confirmation
        if isinstance(business_confirmation, Mapping)
        else {}
    )
    confirmed_primary = str(
        confirmation.get("confirmed_primary_business", "") or ""
    ).strip()
    confirmed_products = str(
        confirmation.get("confirmed_products_or_services", "") or ""
    ).strip()
    confirmation_note = str(
        confirmation.get("confirmation_note", "") or ""
    ).strip()
    confirmation_status = str(
        confirmation.get("confirmation_status", "unconfirmed")
        or "unconfirmed"
    ).strip()
    if confirmation_status not in {"unconfirmed", "confirmed"}:
        raise ValueError("不支持的 confirmation_status")
    if confirmation_status == "confirmed" and not confirmed_primary:
        raise ValueError(
            "confirmed_primary_business 在确认状态下不能为空"
        )

    declared_description = (
        declared_values[0] if len(declared_values) == 1 else ""
    )
    company_name = companies[0] if companies else ""
    company_topics = _business_topics(company_name)
    declared_topics = _business_topics(declared_description)
    company_conflict = bool(
        declared_description
        and company_topics
        and declared_topics
        and company_topics.isdisjoint(declared_topics)
    )

    if confirmation_status == "confirmed":
        eligible = True
        eligibility_reason = "confirmed_primary_business"
        confirmation_reason = ""
    elif len(declared_values) > 1:
        eligible = False
        eligibility_reason = "business_context_confirmation_required"
        confirmation_reason = "multiple_declared_work_descriptions"
    elif company_conflict:
        eligible = False
        eligibility_reason = "business_context_confirmation_required"
        confirmation_reason = "company_description_conflict"
    elif declared_description:
        eligible = True
        eligibility_reason = "explicit_declared_work_description"
        confirmation_reason = ""
    else:
        eligible = False
        eligibility_reason = "business_context_confirmation_required"
        confirmation_reason = (
            "company_name_only" if company_name else "work_description_missing"
        )

    first_evidence = evidence[0] if evidence else {}
    return {
        "declared_work_description": declared_description,
        "declared_work_descriptions": declared_values,
        "declared_work_original_text": first_evidence.get(
            "source_excerpt",
            "",
        ),
        "declared_work_source": first_evidence.get("source_field", ""),
        "declared_work_source_ref": first_evidence.get("source_ref", ""),
        "declared_work_status": (
            "declared_unverified" if evidence else "unavailable"
        ),
        "declared_work_evidence": evidence,
        "company_name": company_name,
        "confirmed_primary_business": confirmed_primary,
        "confirmed_products_or_services": confirmed_products,
        "confirmation_note": confirmation_note,
        "confirmation_status": confirmation_status,
        "effective_primary_business": (
            confirmed_primary or declared_description
        ),
        "effective_products_or_services": confirmed_products,
        "ai_business_relevance_eligible": eligible,
        "eligibility_reason": eligibility_reason,
        "confirmation_reason": confirmation_reason,
        "confirmation_prompt": (
            ""
            if eligible
            else (
                "经营上下文不足，暂不执行行业关联分析。"
                "请人工确认客户实际主要经营内容和主要产品或服务。"
            )
        ),
    }


def build_case_context(
    case_id: str,
    sources: Iterable[Mapping[str, object]],
    *,
    business_confirmation: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build minimal search context from explicitly classified text sources."""
    normalized_case_id = str(case_id or "").strip()
    if not normalized_case_id:
        raise ValueError("case_id 不能为空")

    fields: dict[str, list[dict[str, str]]] = {}
    narratives: list[dict[str, str]] = []
    source_records: list[dict[str, str]] = []

    for source in sources:
        source_ref = str(source.get("source_ref", "")).strip()
        source_role = str(source.get("source_role", "")).strip()
        text = str(source.get("text", "") or "").strip()
        if not source_ref:
            raise ValueError("source_ref 不能为空")
        if source_role not in SOURCE_ROLES:
            raise ValueError(f"不支持的 source_role: {source_role}")
        if not text:
            raise ValueError(f"来源内容为空: {source_ref}")

        source_records.append({"source_ref": source_ref, "source_role": source_role})
        if source_role == SOURCE_ROLE_RISK_INVESTIGATION_REPORT:
            narratives.append(
                _field_record(text, source_role, source_ref, text)
            )
            continue

        for label, value, excerpt in _parse_system_copy(text):
            if label in _MANAGER_DESCRIPTION_BY_LABEL:
                field_name = _MANAGER_DESCRIPTION_BY_LABEL[label]
                field_role = SOURCE_ROLE_CUSTOMER_MANAGER_DESCRIPTION
            else:
                field_name = _FIELD_BY_LABEL[label]
                field_role = source_role
            value = _normalized_field_value(field_name, value)
            if not value:
                continue
            fields.setdefault(field_name, []).append(
                _field_record(
                    value,
                    field_role,
                    source_ref,
                    excerpt,
                    label,
                )
            )
            if field_name in {
                "manager_work_income_description",
                "manager_business_description",
            }:
                for work_content in _declared_work_content_values(
                    value,
                    allow_standalone=(
                        field_name == "manager_work_income_description"
                    ),
                ):
                    record = _field_record(
                        work_content,
                        field_role,
                        source_ref,
                        excerpt,
                        label,
                    )
                    fields.setdefault(
                        "declared_work_description",
                        [],
                    ).append(record)
                    fields.setdefault("declared_industry", []).append(
                        dict(record)
                    )

    search_context = {
        "customer_names": _field_values(fields, "customer_name"),
        "work_units": _field_values(fields, "work_unit"),
        "declared_industries": _field_values(fields, "declared_industry"),
        "work_locations": _field_values(fields, "work_location"),
        "residence_locations": _field_values(fields, "residence_location"),
        "vehicle_registration_locations": _field_values(fields, "vehicle_registration_location"),
        "vehicle_models": _field_values(fields, "vehicle_model"),
        "dealer_names": _field_values(fields, "dealer_name"),
    }
    return {
        "schema_version": CASE_CONTEXT_SCHEMA_VERSION,
        "case_id": normalized_case_id,
        "sources": source_records,
        "fields": fields,
        "narratives": narratives,
        "search_context": search_context,
        "business_context": _build_business_context(
            fields,
            business_confirmation,
        ),
    }


def _field_values(fields: Mapping[str, list[dict[str, str]]], field_name: str) -> list[str]:
    return list(
        dict.fromkeys(
            record["value"]
            for record in fields.get(field_name, [])
            if record.get("value")
        )
    )
