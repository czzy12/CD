"""Small analysis DTOs that never expose customer paths or result payloads."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CaseSelectionDTO:
    case_handle: str
    case_display_name: str


@dataclass(frozen=True)
class PreflightSourceDTO:
    source_ref: str
    display_name: str
    extension: str
    detected_source_type: str
    detected_bank_type: str
    supported: bool
    initial_status: str
    warning: str
    size: int
    may_use_generic_fallback: bool


@dataclass(frozen=True)
class CasePreflightDTO:
    case_handle: str
    case_display_name: str
    source_count: int
    supported_source_count: int
    unsupported_source_count: int
    sources: list[PreflightSourceDTO]
    warnings: list[str]
    can_start: bool
    elapsed_ms: float


@dataclass(frozen=True)
class AnalysisSourceStatusDTO:
    source_ref: str
    display_name: str
    source_type: str
    status: str
    transaction_count: int
    message: str


@dataclass(frozen=True)
class AnalysisStatusDTO:
    analysis_task_id: str
    state: str
    case_display_name: str
    current_stage: str
    current_source_name: str
    completed_sources: int
    total_sources: int
    success_sources: int
    review_sources: int
    failed_sources: int
    warning_count: int
    started_at: str
    elapsed_ms: float
    cancellation_requested: bool
    error_code: str | None
    error_message: str | None
    result_ready: bool
    sources: list[AnalysisSourceStatusDTO] = field(default_factory=list)
    case_session_id: str | None = None
    case_revision: int | None = None
    transaction_count: int = 0
    result_build_ms: float | None = None
    result_bind_ms: float | None = None
    diagnostic_id: str | None = None
