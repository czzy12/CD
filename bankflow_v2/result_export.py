"""Versioned evidence JSON for downstream bank-flow verification."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from .models import Transaction, get_statement_metadata
from .summary import Summary, sort_transactions, summarize


SCHEMA_VERSION = "1.1"


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _date(value: date | datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _transaction_record(transaction: Transaction) -> dict[str, object]:
    return {
        "transaction_id": transaction.transaction_id,
        "source_file_id": transaction.source_file_id,
        "source_file": transaction.source_file,
        "evidence_locator": transaction.evidence_locator,
        "bank": transaction.bank,
        "transaction_time": transaction.transaction_time.isoformat(),
        "income": _decimal(transaction.income),
        "expense": _decimal(transaction.expense),
        "balance": _decimal(transaction.balance),
        "status": transaction.status,
        "issues": list(transaction.issues),
        "original": {
            "raw_time": transaction.raw_time,
            "raw_amount": transaction.raw_amount,
            "raw_balance": transaction.raw_balance,
            "raw_text": transaction.raw_text,
            "raw_headers": list(transaction.raw_headers),
            "raw_fields": list(transaction.raw_fields),
            "source_fields": dict(transaction.source_fields),
        },
        "standard_fields": {
            "counterparty_name": transaction.counterparty_name,
            "counterparty_account": transaction.counterparty_account,
            "counterparty_bank": transaction.counterparty_bank,
            "summary": transaction.summary,
            "remark": transaction.remark,
            "purpose": transaction.purpose,
            "transaction_type": transaction.transaction_type,
            "transaction_direction": transaction.transaction_direction,
            "transaction_method": transaction.transaction_method,
            "payment_method": transaction.payment_method,
            "product_description": transaction.product_description,
            "merchant_name": transaction.merchant_name,
            "merchant_category": transaction.merchant_category,
            "merchant_location": transaction.merchant_location,
            "field_sources": dict(transaction.field_sources),
            "field_confidence": dict(transaction.field_confidence),
        },
        "manual_review": dict(transaction.manual_review),
    }


def _summary_record(summary: Summary) -> dict[str, object]:
    return {
        "count": summary.count,
        "income_count": summary.income_count,
        "income_sum": _decimal(summary.income_sum),
        "expense_count": summary.expense_count,
        "expense_sum": _decimal(summary.expense_sum),
        "net": _decimal(summary.net),
        "opening_balance": _decimal(summary.opening_balance),
        "closing_balance": _decimal(summary.closing_balance),
    }


def _source_files(transactions: list[Transaction]) -> list[dict[str, object]]:
    sources: dict[tuple[str, str], int] = {}
    for transaction in transactions:
        key = (transaction.source_file_id, transaction.source_file)
        sources[key] = sources.get(key, 0) + 1
    return [
        {"source_file_id": source_id, "source_file": source_file, "transaction_count": count}
        for (source_id, source_file), count in sorted(sources.items())
    ]


def _transaction_ids(transactions: list[Transaction]) -> list[str]:
    return [transaction.transaction_id for transaction in transactions if transaction.transaction_id]


def _fact(
    fact_type: str, value: str | int, evidence_transactions: list[Transaction]
) -> dict[str, object]:
    return {
        "fact_type": fact_type,
        "value": value,
        "evidence_transaction_ids": _transaction_ids(evidence_transactions),
    }


def _facts(transactions: list[Transaction], summary: Summary) -> list[dict[str, object]]:
    ordered = sort_transactions(transactions)
    counted = [transaction for transaction in ordered if not getattr(transaction, "neutral", False)]
    facts = [
        _fact("transaction_count", summary.count, counted),
        _fact(
            "income_total",
            _decimal(summary.income_sum) or "0.00",
            [transaction for transaction in counted if transaction.income != Decimal("0.00")],
        ),
        _fact(
            "expense_total",
            _decimal(summary.expense_sum) or "0.00",
            [transaction for transaction in counted if transaction.expense != Decimal("0.00")],
        ),
        _fact("net_amount", _decimal(summary.net) or "0.00", counted),
    ]
    if ordered:
        facts.extend(
            [
                _fact("period_start", ordered[0].transaction_time.isoformat(), [ordered[0]]),
                _fact("period_end", ordered[-1].transaction_time.isoformat(), [ordered[-1]]),
            ]
        )
    if summary.opening_balance is not None and ordered:
        facts.append(_fact("opening_balance", _decimal(summary.opening_balance) or "0.00", [ordered[0]]))
    if summary.closing_balance is not None and ordered:
        facts.append(_fact("closing_balance", _decimal(summary.closing_balance) or "0.00", [ordered[-1]]))
    return facts


def _review_items(transactions: list[Transaction], summary: Summary) -> list[dict[str, object]]:
    review_items: list[dict[str, object]] = []
    transaction_issue_messages = {message for transaction in transactions for message in transaction.issues}

    for transaction in transactions:
        reasons = list(transaction.issues) + list(transaction.manual_review.values())
        if transaction.status != "ok":
            reasons.append(f"解析状态：{transaction.status}")
        if not transaction.transaction_id:
            reasons.append("缺少交易 ID")
        if not transaction.source_file_id:
            reasons.append("缺少来源文件 ID")
        if reasons:
            review_items.append(
                {
                    "scope": "transaction",
                    "transaction_id": transaction.transaction_id,
                    "source_file_id": transaction.source_file_id,
                    "evidence_locator": transaction.evidence_locator,
                    "evidence_transaction_ids": _transaction_ids([transaction]),
                    "reasons": reasons,
                }
            )

    ordered = sort_transactions(transactions)
    for issue in summary.issues:
        if issue.message in transaction_issue_messages:
            continue
        evidence = [
            transaction
            for transaction in ordered
            if transaction.transaction_time.strftime("%Y-%m-%d %H:%M:%S") == issue.time
            and transaction.raw_amount == issue.raw_amount
            and transaction.raw_balance == issue.raw_balance
        ]
        if not evidence and not issue.time:
            evidence = [transaction for transaction in ordered if not getattr(transaction, "neutral", False)]
        review_items.append(
            {
                "scope": "summary",
                "evidence_transaction_ids": _transaction_ids(evidence),
                "reasons": [issue.message],
            }
        )
    return review_items


def build_bankflow_result(
    transactions: list[Transaction], metadata: object | None = None
) -> dict[str, object]:
    """Build a verification result without applying adjustment or analysis logic."""
    original_transactions = list(transactions)
    statement_metadata = metadata or get_statement_metadata(transactions)
    summary = summarize(original_transactions)
    review_items = _review_items(original_transactions, summary)

    return {
        "schema_version": SCHEMA_VERSION,
        "module": "bankflow",
        "analysis_source": "original_transactions",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_files": _source_files(original_transactions),
        "statement_metadata": {
            "account_name": statement_metadata.account_name,
            "account_number": statement_metadata.account_number,
            "statement_period_start": _date(statement_metadata.statement_period_start),
            "statement_period_end": _date(statement_metadata.statement_period_end),
            "generated_at": _date(statement_metadata.generated_at),
            "source_part_label": statement_metadata.source_part_label,
            "page_total": statement_metadata.page_total,
        },
        "result": {
            "summary": _summary_record(summary),
            "original_transactions": [_transaction_record(transaction) for transaction in original_transactions],
            "facts": _facts(original_transactions, summary),
        },
        "manual_review": {"required": bool(review_items), "items": review_items},
        "warnings": [],
        "notes": ["仅包含原始标准交易、确定性事实和待人工核实事项；未应用流水调整或风险定性。"],
    }


def write_bankflow_json(result: dict[str, object], output_path: str | Path) -> Path:
    """Write a UTF-8 evidence JSON file and return its path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
