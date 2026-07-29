"""Read-only helpers for presenting schema 1.16 results in the desktop GUI."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Mapping

from .case_context import (
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)


SUPPORTED_SCHEMA_VERSION = "1.16"


class StandardResultError(ValueError):
    """Stable error raised when a saved standard result cannot be displayed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_standard_result(result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        raise StandardResultError("invalid_result_root", "标准结果根节点必须是对象。")
    version = str(result.get("schema_version", ""))
    if version != SUPPORTED_SCHEMA_VERSION:
        raise StandardResultError(
            "unsupported_schema_version",
            f"当前GUI只支持schema {SUPPORTED_SCHEMA_VERSION}，文件版本为{version or '未知'}。",
        )
    result_body = result.get("result")
    if not isinstance(result_body, dict):
        raise StandardResultError("result_body_missing", "标准结果缺少result对象。")
    for field_name, expected_type in (
        ("original_transactions", list),
        ("facts", list),
        ("indicators", list),
        ("observations", list),
        ("evidence", dict),
    ):
        if not isinstance(result_body.get(field_name), expected_type):
            raise StandardResultError(
                f"{field_name}_invalid",
                f"标准结果中的result.{field_name}结构不兼容。",
            )
    evidence = result_body["evidence"]
    for field_name, expected_type in (
        ("transaction_index", dict),
        ("references", list),
        ("coverage", dict),
        ("integrity", dict),
    ):
        if not isinstance(evidence.get(field_name), expected_type):
            raise StandardResultError(
                f"evidence_{field_name}_invalid",
                f"标准结果中的result.evidence.{field_name}结构不兼容。",
            )
    return result


def load_standard_result(path: str | Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StandardResultError(
            "standard_result_read_failed",
            f"无法读取标准结果：{exc}",
        ) from exc
    return validate_standard_result(payload)


def build_case_context_from_directory(case_dir: str | Path) -> dict[str, object]:
    directory = Path(case_dir)
    sources: list[dict[str, str]] = []
    for text_path in sorted(directory.glob("*.txt")):
        role = (
            SOURCE_ROLE_RISK_INVESTIGATION_REPORT
            if "调查报告" in text_path.name
            else SOURCE_ROLE_SYSTEM_CUSTOMER_DATA
        )
        try:
            text = text_path.read_text(encoding="utf-8")
        except UnicodeError:
            text = text_path.read_text(encoding="utf-8-sig")
        sources.append(
            {
                "source_ref": text_path.name,
                "source_role": role,
                "text": text,
            }
        )
    return build_case_context(directory.name, sources)


def observation_by_type(
    result: Mapping[str, object],
    observation_type: str,
) -> dict[str, object]:
    result_body = result.get("result")
    observations = (
        result_body.get("observations", [])
        if isinstance(result_body, Mapping)
        else []
    )
    for observation in observations:
        if (
            isinstance(observation, dict)
            and observation.get("observation_type") == observation_type
        ):
            return observation
    return {}


def manual_verification_questions(result: Mapping[str, object]) -> list[object]:
    observation = observation_by_type(result, "manual_verification_questions")
    value = observation.get("value")
    questions = value.get("questions") if isinstance(value, Mapping) else None
    return questions if isinstance(questions, list) else []


def sensitive_transaction_candidates(result: Mapping[str, object]) -> list[object]:
    observation = observation_by_type(
        result,
        "sensitive_transaction_context_candidates",
    )
    value = observation.get("value")
    candidates = value.get("candidates") if isinstance(value, Mapping) else None
    return candidates if isinstance(candidates, list) else []


def fact_value(result: Mapping[str, object], fact_type: str) -> object:
    result_body = result.get("result")
    facts = result_body.get("facts", []) if isinstance(result_body, Mapping) else []
    for fact in facts:
        if isinstance(fact, Mapping) and fact.get("fact_type") == fact_type:
            return fact.get("value")
    return None


def result_summary(
    result: Mapping[str, object],
    case_name: str = "",
) -> dict[str, object]:
    result_body = result.get("result")
    summary = result_body.get("summary", {}) if isinstance(result_body, Mapping) else {}
    original_transactions = (
        result_body.get("original_transactions", [])
        if isinstance(result_body, Mapping)
        else []
    )
    metadata = result.get("statement_metadata")
    source_files = result.get("source_files")
    integrity = (
        result_body.get("evidence", {}).get("integrity", {})
        if isinstance(result_body, Mapping)
        and isinstance(result_body.get("evidence"), Mapping)
        else {}
    )
    resolved_case_name = case_name
    if not resolved_case_name and isinstance(metadata, Mapping):
        resolved_case_name = str(metadata.get("account_name") or "")
    return {
        "case_name": resolved_case_name or "未命名案例",
        "schema_version": result.get("schema_version", ""),
        "source_count": len(source_files) if isinstance(source_files, list) else 0,
        "transaction_count": (
            len(original_transactions)
            if isinstance(original_transactions, list)
            else 0
        ),
        "income_sum": (
            summary.get("income_sum", "0.00")
            if isinstance(summary, Mapping)
            else "0.00"
        ),
        "expense_sum": (
            summary.get("expense_sum", "0.00")
            if isinstance(summary, Mapping)
            else "0.00"
        ),
        "period_start": fact_value(result, "period_start") or "",
        "period_end": fact_value(result, "period_end") or "",
        "manual_question_count": len(manual_verification_questions(result)),
        "sensitive_candidate_count": len(sensitive_transaction_candidates(result)),
        "evidence_complete": bool(
            integrity.get("complete") if isinstance(integrity, Mapping) else False
        ),
    }


def evidence_transaction(
    result: Mapping[str, object],
    transaction_id: str,
) -> dict[str, object]:
    result_body = result.get("result")
    if not isinstance(result_body, Mapping):
        raise StandardResultError("result_body_missing", "标准结果缺少result对象。")
    evidence = result_body.get("evidence")
    transactions = result_body.get("original_transactions")
    if not isinstance(evidence, Mapping) or not isinstance(transactions, list):
        raise StandardResultError("evidence_unavailable", "标准结果缺少证据目录。")
    transaction_index = evidence.get("transaction_index")
    if not isinstance(transaction_index, Mapping):
        raise StandardResultError("transaction_index_invalid", "交易证据索引不可用。")
    entry = transaction_index.get(transaction_id)
    if not isinstance(entry, Mapping):
        raise StandardResultError(
            "transaction_id_not_indexed",
            "该交易ID没有唯一证据索引，可能缺失或存在歧义。",
        )
    original_index = entry.get("original_transaction_index")
    if (
        not isinstance(original_index, int)
        or original_index < 0
        or original_index >= len(transactions)
    ):
        raise StandardResultError(
            "original_transaction_index_out_of_range",
            "证据索引指向的原交易序号无效。",
        )
    transaction = transactions[original_index]
    if (
        not isinstance(transaction, Mapping)
        or transaction.get("transaction_id") != transaction_id
    ):
        raise StandardResultError(
            "transaction_id_mismatch",
            "证据索引与原交易ID不一致。",
        )
    references = evidence.get("references", [])
    matching_references = [
        reference
        for reference in references
        if isinstance(reference, Mapping)
        and transaction_id in reference.get("evidence_transaction_ids", [])
    ]
    integrity = evidence.get("integrity", {})
    return {
        "entry": entry,
        "transaction": transaction,
        "references": matching_references,
        "integrity": integrity if isinstance(integrity, Mapping) else {},
    }


def mask_account(value: object) -> str:
    text = str(value or "").strip()
    compact = re.sub(r"[\s-]+", "", text)
    if not compact:
        return ""
    return f"•••• {compact[-4:]}" if len(compact) > 4 else f"•••• {compact}"


def redact_sensitive_text(value: object) -> str:
    text = str(value or "")
    text = re.sub(
        r"(?<!\d)(1\d{2})\d{4}(\d{4})(?!\d)",
        r"\1****\2",
        text,
    )
    text = re.sub(
        r"(?<![0-9A-Za-z])(\d{3})\d{11}([0-9Xx]{4})(?![0-9A-Za-z])",
        r"\1***********\2",
        text,
    )
    text = re.sub(
        r"(?<!\d)(\d{4})\d{7,20}(\d{4})(?!\d)",
        r"\1••••\2",
        text,
    )
    return text


def short_transaction_id(value: object) -> str:
    text = str(value or "")
    if len(text) <= 18:
        return text
    return f"{text[:10]}…{text[-6:]}"
