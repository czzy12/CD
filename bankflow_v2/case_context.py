"""Minimal, source-aware case context for bank-flow business observations."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


CASE_CONTEXT_SCHEMA_VERSION = "1.0"

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
) -> dict[str, str]:
    return {
        "value": value,
        "source_role": source_role,
        "source_ref": source_ref,
        "verification_status": "reported" if source_role == SOURCE_ROLE_RISK_INVESTIGATION_REPORT else "unverified",
        "source_excerpt": source_excerpt,
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
        ):
            values.append(work_content)
    return list(dict.fromkeys(values))


def build_case_context(
    case_id: str,
    sources: Iterable[Mapping[str, object]],
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
                _field_record(value, field_role, source_ref, excerpt)
            )
            if field_name == "manager_work_income_description":
                for work_content in _explicit_work_content_values(value):
                    fields.setdefault("declared_industry", []).append(
                        _field_record(
                            work_content,
                            field_role,
                            source_ref,
                            excerpt,
                        )
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
    }


def _field_values(fields: Mapping[str, list[dict[str, str]]], field_name: str) -> list[str]:
    return list(
        dict.fromkeys(
            record["value"]
            for record in fields.get(field_name, [])
            if record.get("value")
        )
    )
