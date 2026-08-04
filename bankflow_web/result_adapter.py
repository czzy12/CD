"""Read-only presentation adapter for the existing purchase observation."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Mapping

from bankflow_v2.standard_result_view import (
    StandardResultError,
    evidence_transaction,
    observation_by_type,
    redact_sensitive_text,
    result_summary,
    short_transaction_id,
)

from .contracts import (
    ApplicationError,
    CaseHeaderDTO,
    EvidenceDetailDTO,
    PagedTransactionsDTO,
    PurchaseSummaryDTO,
    SourceReviewDTO,
    SourceReviewItemDTO,
    SourceReviewSummaryDTO,
    TransactionListItemDTO,
)


PURCHASE_BOUNDARY_NOTE = "此前收入只作时间并列，不表示资金来源。"
TERM_CATEGORIES = {
    "下定": "下定",
    "问界": "下定",
    "订金": "订金/定金",
    "定金": "订金/定金",
    "购车款": "购车款",
    "首付款": "首付款",
    "补款": "补款",
}
ALLOWED_FILTERS = {"all", "direct", "deposit", "prior_income", "review"}
ALLOWED_PAGE_SIZES = {25, 50, 100}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _direction_amount(record: Mapping[str, object]) -> tuple[str, str]:
    direction = str(record.get("direction") or _mapping(record.get("transaction_context")).get("direction") or "")
    if direction == "income":
        return "收入", str(record.get("income") or "0.00")
    return "支出", str(record.get("expense") or "0.00")


def _display_fields(record: Mapping[str, object]) -> Mapping[str, object]:
    context = _mapping(record.get("transaction_context"))
    return _mapping(context.get("reliable_standard_fields"))


def _matched_text(record: Mapping[str, object]) -> str:
    terms = [str(value) for value in _list(record.get("matched_terms")) if str(value)]
    return "、".join(sorted(set(terms))) or "现有购车候选"


def _category(record: Mapping[str, object]) -> str:
    terms = [str(value) for value in _list(record.get("matched_terms"))]
    categories = [TERM_CATEGORIES[value] for value in terms if value in TERM_CATEGORIES]
    return categories[0] if categories else "其他购车文字"


def _source_name(record: Mapping[str, object]) -> str:
    context = _mapping(record.get("transaction_context"))
    return Path(str(context.get("source_file") or record.get("source_file") or "")).name


def _counterparty(record: Mapping[str, object]) -> str:
    fields = _display_fields(record)
    return str(fields.get("counterparty_name") or fields.get("merchant_name") or "未提供交易对手")


def _purchase_item(candidate: Mapping[str, object]) -> TransactionListItemDTO:
    direction, amount = _direction_amount(candidate)
    context = _mapping(candidate.get("transaction_context"))
    matched = _matched_text(candidate)
    return TransactionListItemDTO(
        transaction_id=str(candidate.get("purchase_transaction_id") or candidate.get("transaction_id") or ""),
        date=str(candidate.get("transaction_time") or context.get("transaction_time") or "")[:19],
        direction=direction,
        amount=amount,
        counterparty=_counterparty(candidate),
        matched_text=matched,
        interpretation="直接命中现有下定与购车观察；收入退款仅提示，不判断订单取消。" if direction == "收入" else "直接命中现有下定与购车观察。",
        source_name=_source_name(candidate),
        category=_category(candidate),
        review_status="direct",
    )


def _prior_income_item(prior: Mapping[str, object], purchase: Mapping[str, object]) -> TransactionListItemDTO:
    context = _mapping(prior.get("transaction_context"))
    source = Path(str(prior.get("source_file") or context.get("source_file") or "")).name
    return TransactionListItemDTO(
        transaction_id=str(prior.get("transaction_id") or ""),
        date=str(prior.get("transaction_time") or context.get("transaction_time") or "")[:19],
        direction="收入",
        amount=str(prior.get("income") or prior.get("amount") or "0.00"),
        counterparty=str(prior.get("counterparty_name") or "此前收入"),
        matched_text="此前收入",
        interpretation=PURCHASE_BOUNDARY_NOTE,
        source_name=source,
        category="此前收入",
        review_status="review",
    )


class PurchaseResultAdapter:
    def __init__(
        self,
        result: Mapping[str, object],
        case_name: str,
        case_session_id: str = "",
        case_revision: int = 0,
    ) -> None:
        self._result = result
        self._case_name = case_name
        self._case_session_id = case_session_id
        self._case_revision = case_revision
        observation = observation_by_type(result, "purchase_prepayment_funding_candidates")
        value = _mapping(observation.get("value"))
        candidates = [value for value in _list(value.get("purchase_candidates")) if isinstance(value, Mapping)]
        self._items: list[TransactionListItemDTO] = []
        seen_prior: set[str] = set()
        for candidate in candidates:
            item = _purchase_item(candidate)
            if item.transaction_id:
                self._items.append(item)
            for prior in _list(candidate.get("prior_income_candidates")):
                if not isinstance(prior, Mapping):
                    continue
                prior_id = str(prior.get("transaction_id") or "")
                if prior_id and prior_id not in seen_prior:
                    seen_prior.add(prior_id)
                    self._items.append(_prior_income_item(prior, candidate))

    def case_header(self) -> CaseHeaderDTO:
        summary = result_summary(self._result, self._case_name)
        review_sources = [
            SourceReviewDTO(
                source_name=Path(str(source.get("source_file") or "")).name,
                reason=str(source.get("review_reason") or "需复核"),
            )
            for source in _list(self._result.get("source_files"))
            if isinstance(source, Mapping) and source.get("status") == "review"
        ]
        return CaseHeaderDTO(
            case_name=str(summary["case_name"]),
            period_start=str(summary["period_start"]),
            period_end=str(summary["period_end"]),
            source_count=int(summary["source_count"]),
            transaction_count=int(summary["transaction_count"]),
            analysis_status="已完成",
            evidence_status="证据完整" if summary["evidence_complete"] else "证据需复核",
            schema_version=str(summary["schema_version"]),
            case_session_id=self._case_session_id,
            case_revision=self._case_revision,
            review_source_count=len(review_sources),
            review_sources=review_sources,
        )

    def source_review_summary(self) -> SourceReviewSummaryDTO:
        items: list[SourceReviewItemDTO] = []
        for index, source in enumerate(_list(self._result.get("source_files"))):
            if not isinstance(source, Mapping) or source.get("status") != "review":
                continue
            source_id = str(source.get("source_file_id") or f"source-{index + 1}")
            items.append(SourceReviewItemDTO(
                source_id=source_id,
                display_name=Path(str(source.get("source_file") or "")).name or f"来源 {index + 1}",
                source_type=str(source.get("source_type") or source.get("bank") or "标准结果来源"),
                status="review",
                review_reason=str(source.get("review_reason") or "需复核"),
                parser_name=(str(source.get("parser_name")) if source.get("parser_name") else None),
                generated_transactions=int(source.get("transaction_count") or 0) > 0,
            ))
        return SourceReviewSummaryDTO(self._case_session_id, len(items), items)

    def purchase_summary(self) -> PurchaseSummaryDTO:
        direct = [item for item in self._items if item.review_status == "direct"]
        prior = [item for item in self._items if item.category == "此前收入"]
        categories: dict[str, int] = {}
        for item in direct:
            categories[item.category] = categories.get(item.category, 0) + 1
        return PurchaseSummaryDTO(
            total_count=len(self._items),
            direct_count=len(direct),
            deposit_count=sum(categories.get(value, 0) for value in ("订金/定金",)),
            prior_income_count=len(prior),
            review_count=len(prior),
            category_counts=categories,
            boundary_note=PURCHASE_BOUNDARY_NOTE,
        )

    def list_transactions(self, page: int = 1, page_size: int = 50, filters: Mapping[str, object] | None = None) -> PagedTransactionsDTO:
        started = time.perf_counter()
        if not isinstance(page, int) or page < 1 or page_size not in ALLOWED_PAGE_SIZES:
            raise ApplicationError("INVALID_ARGUMENT")
        raw_filter = str((filters or {}).get("status") or "all")
        if raw_filter not in ALLOWED_FILTERS:
            raise ApplicationError("INVALID_ARGUMENT")
        items = self._items
        if raw_filter == "direct":
            items = [item for item in items if item.review_status == "direct"]
        elif raw_filter == "deposit":
            items = [item for item in items if item.category == "订金/定金"]
        elif raw_filter == "prior_income":
            items = [item for item in items if item.category == "此前收入"]
        elif raw_filter == "review":
            items = [item for item in items if item.review_status == "review"]
        start = (page - 1) * page_size
        page_items = items[start:start + page_size]
        elapsed = (time.perf_counter() - started) * 1000
        payload = json.dumps([item.__dict__ for item in page_items], ensure_ascii=False).encode("utf-8")
        return PagedTransactionsDTO(
            items=page_items,
            page=page,
            page_size=page_size,
            total=len(items),
            total_pages=max(1, math.ceil(len(items) / page_size)),
            filters={"status": raw_filter},
            query_elapsed_ms=round(elapsed, 3),
            payload_bytes=len(payload),
        )

    def evidence(self, transaction_id: str) -> EvidenceDetailDTO:
        if not transaction_id:
            raise ApplicationError("INVALID_ARGUMENT")
        try:
            resolved = evidence_transaction(self._result, transaction_id)
        except StandardResultError as exc:
            if exc.code == "transaction_id_not_indexed":
                raise ApplicationError("TRANSACTION_NOT_FOUND") from exc
            raise ApplicationError("EVIDENCE_UNAVAILABLE") from exc
        transaction = _mapping(resolved["transaction"])
        standard = _mapping(transaction.get("standard_fields"))
        original = _mapping(transaction.get("original"))
        direction = "收入" if str(transaction.get("income") or "0") not in {"", "0", "0.0", "0.00"} else "支出"
        amount = str(transaction.get("income") if direction == "收入" else transaction.get("expense") or "0.00")
        raw_values: list[str] = []
        if original.get("raw_text"):
            raw_values.append(f"raw_text：{original['raw_text']}")
        for index, value in enumerate(_list(original.get("raw_fields"))):
            if str(value).strip():
                raw_values.append(f"raw_fields[{index}]：{value}")
        references = [value for value in _list(resolved.get("references")) if isinstance(value, Mapping)]
        statuses = sorted({str(value.get("status") or "") for value in references if value.get("status")})
        integrity = _mapping(resolved.get("integrity"))
        return EvidenceDetailDTO(
            transaction_id=transaction_id,
            transaction_id_short=short_transaction_id(transaction_id),
            date=str(transaction.get("transaction_time") or "")[:19],
            direction=direction,
            amount=amount,
            counterparty=redact_sensitive_text(standard.get("counterparty_name") or standard.get("merchant_name") or ""),
            summary=redact_sensitive_text(standard.get("summary") or standard.get("remark") or ""),
            purpose=redact_sensitive_text(standard.get("purpose") or ""),
            source_name=Path(str(transaction.get("source_file") or "")).name,
            page_no=int(transaction.get("page_no") or 0),
            row_no=int(transaction.get("row_no") or 0),
            evidence_locator=str(transaction.get("evidence_locator") or ""),
            reference_reason="、".join(statuses) or "未登记消费者引用",
            integrity_status="完整" if integrity.get("complete") and set(statuses) <= {"resolved"} else "需复核",
            masked_original_fields=[redact_sensitive_text(value) for value in raw_values],
            full_original_fields=raw_values,
            case_session_id=self._case_session_id,
        )
