"""Stable, deliberately small DTO contracts exposed to the Web frontend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ERROR_MESSAGES = {
    "NO_CASE": "尚未打开标准结果",
    "FILE_NOT_FOUND": "所选标准结果不存在",
    "INVALID_JSON": "所选文件不是有效的JSON",
    "SCHEMA_INCOMPATIBLE": "该结果版本不受当前程序支持",
    "INVALID_ARGUMENT": "请求参数无效",
    "TRANSACTION_NOT_FOUND": "未找到指定交易",
    "EVIDENCE_UNAVAILABLE": "该交易的证据不可用",
    "FRONTEND_NOT_READY": "前端尚未准备完成",
    "INTERNAL_ERROR": "程序处理请求时发生内部错误",
}


@dataclass(frozen=True)
class ApplicationErrorDTO:
    code: str
    message: str


@dataclass(frozen=True)
class AppStateDTO:
    frontend_ready: bool
    case_loaded: bool
    loading: bool
    mode: str = "local"


@dataclass(frozen=True)
class SourceReviewDTO:
    source_name: str
    reason: str


@dataclass(frozen=True)
class CaseHeaderDTO:
    case_name: str
    period_start: str
    period_end: str
    source_count: int
    transaction_count: int
    analysis_status: str
    evidence_status: str
    schema_version: str
    review_source_count: int = 0
    review_sources: list[SourceReviewDTO] = field(default_factory=list)


@dataclass(frozen=True)
class PurchaseSummaryDTO:
    total_count: int
    direct_count: int
    deposit_count: int
    prior_income_count: int
    review_count: int
    category_counts: dict[str, int]
    boundary_note: str


@dataclass(frozen=True)
class TransactionListItemDTO:
    transaction_id: str
    date: str
    direction: str
    amount: str
    counterparty: str
    matched_text: str
    interpretation: str
    source_name: str
    category: str
    review_status: str


@dataclass(frozen=True)
class PagedTransactionsDTO:
    items: list[TransactionListItemDTO]
    page: int
    page_size: int
    total: int
    total_pages: int
    filters: dict[str, str] = field(default_factory=dict)
    query_elapsed_ms: float = 0.0
    payload_bytes: int = 0


@dataclass(frozen=True)
class EvidenceDetailDTO:
    transaction_id: str
    transaction_id_short: str
    date: str
    direction: str
    amount: str
    counterparty: str
    summary: str
    purpose: str
    source_name: str
    page_no: int
    row_no: int
    evidence_locator: str
    reference_reason: str
    integrity_status: str
    masked_original_fields: list[str]
    full_original_fields: list[str]


def to_dict(value: Any) -> Any:
    return asdict(value) if hasattr(value, "__dataclass_fields__") else value


class ApplicationError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or ERROR_MESSAGES.get(code, ERROR_MESSAGES["INTERNAL_ERROR"]))
