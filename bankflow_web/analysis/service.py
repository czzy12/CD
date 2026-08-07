"""Framework-neutral adapter over the existing formal parsing pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time
from typing import Callable

from bankflow_v2.models import get_statement_metadata
from bankflow_v2.summary import Issue, summarize

from .cancellation import CancellationToken
from .network_guard import offline_analysis
from .progress import ProgressEvent


ProgressCallback = Callable[[ProgressEvent], None]


@dataclass
class SourceOutcome:
    path: Path
    status: str
    message: str
    transactions: list
    failed: bool = False


@dataclass
class AnalysisOutcome:
    source_results: list[SourceOutcome]
    issues: list[Issue]
    standard_result: dict[str, object]
    result_build_ms: float


class AnalysisCancelled(RuntimeError):
    pass


class AnalysisService:
    """Preserves the current source failure and generic fallback semantics."""

    def extract_source(self, path: Path) -> tuple[list, str]:
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            from bankflow_v2.excel_input import extract_excel_transactions

            return extract_excel_transactions(str(path)), ""
        from bankflow_v2.auto_detect import detect_bank_type

        detection = detect_bank_type(str(path))
        if not detection.bank_id:
            from bankflow_v2.generic_pdf import extract_generic_pdf

            return extract_generic_pdf(str(path)), detection.reason
        try:
            from bankflow_v2.pipeline import extract_transactions

            transactions = extract_transactions(str(path), detection.bank_id)
        except Exception as exc:
            from bankflow_v2.generic_pdf import extract_generic_pdf

            fallback = extract_generic_pdf(str(path))
            if fallback:
                return fallback, f"专用解析失败：{exc}；已使用通用识别"
            raise
        if transactions:
            return transactions, ""
        from bankflow_v2.generic_pdf import extract_generic_pdf

        return extract_generic_pdf(str(path)), "专用解析未得到流水，已尝试通用识别"

    @offline_analysis
    def run(
        self,
        paths: list[Path],
        *,
        case_context: dict[str, object] | None = None,
        pdf_passwords: dict[Path, str] | None = None,
        ai_config: dict[str, object] | None = None,
        ai_evaluator: Callable[[dict[str, object]], object] | None = None,
        cancellation: CancellationToken | None = None,
        progress: ProgressCallback | None = None,
        source_complete: Callable[[SourceOutcome], None] | None = None,
    ) -> AnalysisOutcome:
        from bankflow_v2.evidence import attach_source_evidence
        from bankflow_v2.pdf_password import install_pdf_password_support, register_pdf_passwords
        from bankflow_v2.result_export import build_bankflow_result

        token = cancellation or CancellationToken()
        emit = progress or (lambda _event: None)
        install_pdf_password_support()
        register_pdf_passwords(pdf_passwords or {})
        source_results: list[SourceOutcome] = []
        issues: list[Issue] = []
        transactions = []
        for index, path in enumerate(paths, start=1):
            if token.requested:
                raise AnalysisCancelled()
            emit(ProgressEvent("detecting_source_type", index - 1, path.name))
            try:
                emit(ProgressEvent("parsing_source", index - 1, path.name))
                source_transactions, message = self.extract_source(path)
                emit(ProgressEvent("normalizing_transactions", index - 1, path.name))
                if not all(getattr(item, "source_file_id", "") for item in source_transactions):
                    attach_source_evidence(source_transactions, path)
                for transaction in source_transactions:
                    transaction.source_file = path.name
                source_summary = summarize(source_transactions, path.name)
                issues.extend(source_summary.issues)
                status = "included" if source_transactions else "review"
                if not source_transactions and not message:
                    message = "未解析到流水"
                outcome = SourceOutcome(path, status, message, source_transactions)
            except Exception as exc:
                message = str(exc)
                issues.append(Issue("需复核", path.name, "", f"解析失败：{message}"))
                outcome = SourceOutcome(path, "review", message, [], failed=True)
            source_results.append(outcome)
            transactions.extend(outcome.transactions)
            if source_complete:
                source_complete(outcome)
            emit(ProgressEvent("reading_source", index, path.name))
            if token.requested:
                raise AnalysisCancelled()
        emit(ProgressEvent("building_result", len(paths), ""))
        build_started = time.perf_counter()
        standard_result = build_bankflow_result(
            transactions,
            metadata=get_statement_metadata(transactions),
            case_context=case_context or {},
            ai_config=ai_config,
            ai_evaluator=ai_evaluator,
            source_diagnostics=[{
                "source_file": source.path.name,
                "status": "review" if source.status == "review" else "included",
                "review_reason": source.message if source.status == "review" else "",
            } for source in source_results],
        )
        build_ms = round((time.perf_counter() - build_started) * 1000, 3)
        emit(ProgressEvent("validating_result", len(paths), ""))
        if token.requested:
            raise AnalysisCancelled()
        emit(ProgressEvent("finalizing", len(paths), ""))
        return AnalysisOutcome(source_results, issues, standard_result, build_ms)
