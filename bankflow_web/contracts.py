"""Stable, deliberately small DTO contracts exposed to the Web frontend."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


ERROR_MESSAGES = {
    "NO_CASE": "尚未打开标准结果",
    "FILE_NOT_FOUND": "所选标准结果不存在",
    "INVALID_JSON": "所选文件不是有效的 JSON",
    "SCHEMA_INCOMPATIBLE": "该结果版本不受当前程序支持",
    "INVALID_ARGUMENT": "请求参数无效",
    "STALE_CASE": "案件已切换，本次请求已过期",
    "TRANSACTION_NOT_FOUND": "未找到指定交易",
    "EVIDENCE_UNAVAILABLE": "该交易的证据不可用",
    "FRONTEND_NOT_READY": "前端尚未准备完成",
    "CASE_DIRECTORY_NOT_FOUND": "所选案件目录不存在",
    "CASE_DIRECTORY_READ_FAILED": "无法读取所选案件目录",
    "CASE_HANDLE_INVALID": "案件选择已失效，请重新选择",
    "NO_SUPPORTED_SOURCES": "目录中没有可处理的 PDF/Excel 流水文件",
    "ANALYSIS_ALREADY_RUNNING": "已有分析任务正在运行",
    "ANALYSIS_TASK_NOT_FOUND": "分析任务不存在或已经失效",
    "ANALYSIS_STILL_RUNNING": "分析仍在进行，暂时不能关闭任务",
    "ANALYSIS_FAILED": "分析未完成，请重试",
    "SAVE_CANCELLED": "已取消保存",
    "SAVE_INPUT_OVERWRITE_FORBIDDEN": "不能覆盖当前打开的输入结果文件",
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
    api_version: str = "1"
    frontend_version: str = "0.2.0"
    schema_versions_supported: list[str] = field(default_factory=lambda: ["1.16"])
    renderer: str = "edgechromium"
    capabilities: list[str] = field(default_factory=lambda: [
        "load_standard_result", "review_modules", "paged_items",
        "evidence_inspector", "source_review", "theme", "case_switch",
        "case_analysis", "analysis_progress", "analysis_cancellation", "save_result",
    ])
    case_session_id: str | None = None
    case_revision: int = 0


@dataclass(frozen=True)
class SourceReviewItemDTO:
    source_id: str
    display_name: str
    source_type: str
    status: str
    review_reason: str
    parser_name: str | None
    generated_transactions: bool


@dataclass(frozen=True)
class SourceReviewSummaryDTO:
    case_session_id: str
    total: int
    items: list[SourceReviewItemDTO] = field(default_factory=list)


@dataclass(frozen=True)
class SourceReviewDTO:
    """Compatibility DTO retained for the validated 12B-0 slice."""
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
    case_session_id: str = ""
    case_revision: int = 0
    review_source_count: int = 0
    review_sources: list[SourceReviewDTO] = field(default_factory=list)


@dataclass(frozen=True)
class FilterOptionDTO:
    value: str
    label: str


@dataclass(frozen=True)
class FilterDefinitionDTO:
    key: str
    label: str
    kind: str
    options: list[FilterOptionDTO] = field(default_factory=list)


@dataclass(frozen=True)
class ModuleDescriptorDTO:
    module_id: str
    title: str
    icon: str
    availability: str
    display_kind: str
    total_count: int
    review_count: int
    status: str
    description: str
    supported_filters: list[FilterDefinitionDTO]
    evidence_supported: bool


@dataclass(frozen=True)
class ModuleRegistryDTO:
    case_session_id: str
    modules: list[ModuleDescriptorDTO]


@dataclass(frozen=True)
class ModuleSummaryDTO:
    module_id: str
    title: str
    total_count: int
    review_count: int
    status: str
    description: str
    boundary_note: str
    category_counts: dict[str, int]
    source_count: int
    case_session_id: str


@dataclass(frozen=True)
class ReviewItemDTO:
    item_id: str
    transaction_id: str | None
    date: str | None
    direction: str | None
    amount: str | None
    primary_text: str
    secondary_text: str | None
    counterparty: str | None
    matched_text: str | None
    interpretation: str | None
    category: str | None
    review_status: str | None
    source_name: str | None
    evidence_available: bool


@dataclass(frozen=True)
class PagedModuleItemsDTO:
    module_id: str
    case_session_id: str
    page: int
    page_size: int
    total: int
    total_pages: int
    items: list[ReviewItemDTO]
    available_filters: list[FilterDefinitionDTO]
    meta: dict[str, object] = field(default_factory=dict)


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
    case_session_id: str = ""


def to_dict(value: Any) -> Any:
    return asdict(value) if hasattr(value, "__dataclass_fields__") else value


class ApplicationError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or ERROR_MESSAGES.get(code, ERROR_MESSAGES["INTERNAL_ERROR"]))
