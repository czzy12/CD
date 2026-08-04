"""Single-task background manager with stale-task isolation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import logging
import threading
import time
import uuid
from typing import Callable

from bankflow_web.contracts import ApplicationError

from .cancellation import CancellationToken
from .contracts import AnalysisSourceStatusDTO, AnalysisStatusDTO
from .progress import ProgressEvent
from .service import AnalysisCancelled, AnalysisService, SourceOutcome


TERMINAL_STATES = {"completed", "failed", "cancelled"}
ACTIVE_STATES = {"running", "cancelling"}
LOGGER = logging.getLogger("bankflow_web.analysis")


@dataclass
class _Task:
    analysis_task_id: str
    case_display_name: str
    paths: list[Path]
    case_context: dict[str, object]
    state: str = "running"
    current_stage: str = "discovering_sources"
    current_source_name: str = ""
    completed_sources: int = 0
    success_sources: int = 0
    review_sources: int = 0
    failed_sources: int = 0
    warning_count: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_perf: float = field(default_factory=time.perf_counter)
    cancellation: CancellationToken = field(default_factory=CancellationToken)
    error_code: str | None = None
    error_message: str | None = None
    result_ready: bool = False
    sources: list[AnalysisSourceStatusDTO] = field(default_factory=list)
    case_session_id: str | None = None
    case_revision: int | None = None
    transaction_count: int = 0
    result_build_ms: float | None = None
    result_bind_ms: float | None = None
    diagnostic_id: str | None = None


class AnalysisTaskManager:
    def __init__(
        self,
        promote_result: Callable[[dict[str, object], str], tuple[str, int, int]],
        *,
        service: AnalysisService | None = None,
    ) -> None:
        self._service = service or AnalysisService()
        self._promote_result = promote_result
        self._lock = threading.RLock()
        self._task: _Task | None = None
        self._thread: threading.Thread | None = None

    def start(
        self,
        case_display_name: str,
        paths: list[Path],
        case_context: dict[str, object],
        source_refs: dict[Path, str] | None = None,
    ) -> AnalysisStatusDTO:
        if not paths:
            raise ApplicationError("NO_SUPPORTED_SOURCES")
        with self._lock:
            if self._task is not None and self._task.state in ACTIVE_STATES:
                raise ApplicationError("ANALYSIS_ALREADY_RUNNING")
            task = _Task(uuid.uuid4().hex, case_display_name, list(paths), dict(case_context))
            refs = source_refs or {}
            task.sources = [AnalysisSourceStatusDTO(refs.get(path, uuid.uuid4().hex), path.name, "pdf" if path.suffix.lower() == ".pdf" else "excel", "pending", 0, "") for path in paths]
            self._task = task
            self._thread = threading.Thread(target=self._run, args=(task,), name=f"bankflow-analysis-{task.analysis_task_id[:8]}", daemon=False)
            self._thread.start()
            return self._snapshot(task)

    def _run(self, task: _Task) -> None:
        def progress(event: ProgressEvent) -> None:
            with self._lock:
                if self._task is not task:
                    return
                task.current_stage = event.stage
                task.current_source_name = event.source_name

        def source_complete(outcome: SourceOutcome) -> None:
            with self._lock:
                if self._task is not task:
                    return
                index = task.completed_sources
                previous = task.sources[index]
                status = outcome.status
                if outcome.failed:
                    safe_message = "来源解析失败，已标记为需复核"
                elif outcome.message.startswith("专用解析失败"):
                    safe_message = "专用解析失败，已使用通用识别"
                else:
                    safe_message = outcome.message.replace(str(outcome.path), outcome.path.name)
                task.sources[index] = AnalysisSourceStatusDTO(
                    previous.source_ref, previous.display_name, previous.source_type,
                    status, len(outcome.transactions), safe_message,
                )
                task.completed_sources += 1
                if status == "included":
                    task.success_sources += 1
                else:
                    task.review_sources += 1
                    task.warning_count += 1
                    if outcome.failed:
                        task.failed_sources += 1

        try:
            outcome = self._service.run(
                task.paths,
                case_context=task.case_context,
                cancellation=task.cancellation,
                progress=progress,
                source_complete=source_complete,
            )
            with self._lock:
                if self._task is not task:
                    return
                if task.cancellation.requested:
                    raise AnalysisCancelled()
                bind_started = time.perf_counter()
                session_id, revision, transaction_count = self._promote_result(outcome.standard_result, task.case_display_name)
                task.result_bind_ms = round((time.perf_counter() - bind_started) * 1000, 3)
                task.result_build_ms = outcome.result_build_ms
                task.case_session_id = session_id
                task.case_revision = revision
                task.transaction_count = transaction_count
                task.current_stage = "completed"
                task.current_source_name = ""
                task.result_ready = True
                task.state = "completed"
        except AnalysisCancelled:
            with self._lock:
                if self._task is task:
                    task.state = "cancelled"
                    task.current_stage = "cancelled"
                    task.current_source_name = ""
        except Exception:
            diagnostic_id = uuid.uuid4().hex
            LOGGER.exception("Analysis task %s failed; diagnostic=%s", task.analysis_task_id, diagnostic_id)
            with self._lock:
                if self._task is task:
                    task.state = "failed"
                    task.current_stage = "failed"
                    task.current_source_name = ""
                    task.error_code = "ANALYSIS_FAILED"
                    task.error_message = f"分析未完成，请重试。诊断编号：{diagnostic_id[:8]}"
                    task.diagnostic_id = diagnostic_id

    def status(self, analysis_task_id: str) -> AnalysisStatusDTO:
        with self._lock:
            if self._task is None or self._task.analysis_task_id != analysis_task_id:
                raise ApplicationError("ANALYSIS_TASK_NOT_FOUND")
            return self._snapshot(self._task)

    def cancel(self, analysis_task_id: str) -> AnalysisStatusDTO:
        with self._lock:
            if self._task is None or self._task.analysis_task_id != analysis_task_id:
                raise ApplicationError("ANALYSIS_TASK_NOT_FOUND")
            if self._task.state == "running":
                self._task.cancellation.request()
                self._task.state = "cancelling"
            return self._snapshot(self._task)

    def dismiss(self, analysis_task_id: str) -> None:
        with self._lock:
            if self._task is None or self._task.analysis_task_id != analysis_task_id:
                raise ApplicationError("ANALYSIS_TASK_NOT_FOUND")
            if self._task.state not in TERMINAL_STATES:
                raise ApplicationError("ANALYSIS_STILL_RUNNING")
            self._task = None
            self._thread = None

    def shutdown(self, timeout: float = 5.0) -> bool:
        with self._lock:
            task = self._task
            thread = self._thread
            if task is not None and task.state in ACTIVE_STATES:
                task.cancellation.request()
                task.state = "cancelling"
        if thread is not None and thread.is_alive():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def has_active_task(self) -> bool:
        with self._lock:
            return self._task is not None and self._task.state in ACTIVE_STATES

    def _snapshot(self, task: _Task) -> AnalysisStatusDTO:
        return AnalysisStatusDTO(
            analysis_task_id=task.analysis_task_id,
            state=task.state,
            case_display_name=task.case_display_name,
            current_stage=task.current_stage,
            current_source_name=task.current_source_name,
            completed_sources=task.completed_sources,
            total_sources=len(task.paths),
            success_sources=task.success_sources,
            review_sources=task.review_sources,
            failed_sources=task.failed_sources,
            warning_count=task.warning_count,
            started_at=task.started_at.isoformat(),
            elapsed_ms=round((time.perf_counter() - task.started_perf) * 1000, 3),
            cancellation_requested=task.cancellation.requested,
            error_code=task.error_code,
            error_message=task.error_message,
            result_ready=task.result_ready,
            sources=list(task.sources),
            case_session_id=task.case_session_id,
            case_revision=task.case_revision,
            transaction_count=task.transaction_count,
            result_build_ms=task.result_build_ms,
            result_bind_ms=task.result_bind_ms,
            diagnostic_id=task.diagnostic_id,
        )
