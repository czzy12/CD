"""Read-only helpers for presenting schema 1.16 results in the desktop GUI."""

from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Mapping

from .case_context import (
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)
from .models import Transaction


SUPPORTED_SCHEMA_VERSIONS = ("1.16", "1.17")
SUPPORTED_SCHEMA_VERSION = SUPPORTED_SCHEMA_VERSIONS[-1]


class StandardResultError(ValueError):
    """Stable error raised when a saved standard result cannot be displayed."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_standard_result(result: object) -> dict[str, object]:
    if not isinstance(result, dict):
        raise StandardResultError("invalid_result_root", "标准结果根节点必须是对象。")
    version = str(result.get("schema_version", ""))
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise StandardResultError(
            "unsupported_schema_version",
            f"当前GUI只支持schema {'/'.join(SUPPORTED_SCHEMA_VERSIONS)}，"
            f"文件版本为{version or '未知'}。",
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


def build_case_context_from_directory(
    case_dir: str | Path,
    *,
    business_confirmation: Mapping[str, object] | None = None,
) -> dict[str, object]:
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
    return build_case_context(
        directory.name,
        sources,
        business_confirmation=business_confirmation,
    )


def transactions_from_standard_result(
    result: Mapping[str, object],
) -> list[Transaction]:
    """Restore Transaction values needed for scoped result rebuilding."""
    validated = validate_standard_result(result)
    records = validated["result"]["original_transactions"]
    transactions: list[Transaction] = []
    for record in records:
        if not isinstance(record, Mapping):
            raise StandardResultError(
                "original_transaction_invalid",
                "标准结果包含无效的原交易记录。",
            )
        original = record.get("original")
        standard = record.get("standard_fields")
        original = original if isinstance(original, Mapping) else {}
        standard = standard if isinstance(standard, Mapping) else {}
        try:
            transaction_time = datetime.fromisoformat(
                str(record.get("transaction_time") or "")
            )
        except ValueError as exc:
            raise StandardResultError(
                "transaction_time_invalid",
                "标准结果包含无法恢复的交易时间。",
            ) from exc
        transaction = Transaction(
            transaction_time=transaction_time,
            income=Decimal(str(record.get("income") or "0")),
            expense=Decimal(str(record.get("expense") or "0")),
            balance=(
                Decimal(str(record["balance"]))
                if record.get("balance") is not None
                else None
            ),
            bank=str(record.get("bank") or ""),
            page_no=int(record.get("page_no") or 0),
            row_no=int(record.get("row_no") or 0),
            raw_time=str(original.get("raw_time") or ""),
            raw_amount=str(original.get("raw_amount") or ""),
            raw_balance=str(original.get("raw_balance") or ""),
            raw_text=str(original.get("raw_text") or ""),
            raw_fields=list(original.get("raw_fields") or []),
            raw_headers=list(original.get("raw_headers") or []),
            status=str(record.get("status") or "ok"),
            issues=list(record.get("issues") or []),
            counterparty_name=str(standard.get("counterparty_name") or ""),
            counterparty_account=str(
                standard.get("counterparty_account") or ""
            ),
            counterparty_bank=str(standard.get("counterparty_bank") or ""),
            summary=str(standard.get("summary") or ""),
            remark=str(standard.get("remark") or ""),
            purpose=str(standard.get("purpose") or ""),
            transaction_type=str(standard.get("transaction_type") or ""),
            transaction_direction=str(
                standard.get("transaction_direction") or ""
            ),
            transaction_method=str(
                standard.get("transaction_method") or ""
            ),
            payment_method=str(standard.get("payment_method") or ""),
            product_description=str(
                standard.get("product_description") or ""
            ),
            merchant_name=str(standard.get("merchant_name") or ""),
            merchant_category=str(standard.get("merchant_category") or ""),
            merchant_location=str(standard.get("merchant_location") or ""),
            field_sources=dict(standard.get("field_sources") or {}),
            field_confidence=dict(standard.get("field_confidence") or {}),
            manual_review=dict(record.get("manual_review") or {}),
            source_fields=dict(original.get("source_fields") or {}),
            source_file=str(record.get("source_file") or ""),
            source_file_id=str(record.get("source_file_id") or ""),
            evidence_locator=str(record.get("evidence_locator") or ""),
            transaction_id=str(record.get("transaction_id") or ""),
        )
        transaction.neutral = bool(record.get("neutral"))
        transactions.append(transaction)
    return transactions


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
