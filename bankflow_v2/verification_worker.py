"""Background task for the standalone schema 1.16 verification workbench."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from .models import get_statement_metadata
from .summary import Issue, summarize


SUPPORTED_INPUTS = {".pdf", ".xlsx", ".xlsm"}


@dataclass
class VerificationSourceResult:
    path: Path
    status: str
    message: str
    transactions: list


class VerificationWorker(QThread):
    """Parse case sources and build one schema 1.16 result off the GUI thread."""

    finished = pyqtSignal(list, list, object)
    progress = pyqtSignal(str)
    stage_progress = pyqtSignal(int, int, str)
    source_error = pyqtSignal(str, str)
    cancelled = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(
        self,
        paths: list[Path],
        pdf_passwords: dict[Path, str] | None = None,
        case_context: dict[str, object] | None = None,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.pdf_passwords = pdf_passwords or {}
        self.case_context = case_context or {}

    def _extract(self, path: Path) -> tuple[list, str]:
        if path.suffix.lower() in {".xlsx", ".xlsm"}:
            from .excel_input import extract_excel_transactions

            return extract_excel_transactions(str(path)), ""

        from .auto_detect import detect_bank_type

        detection = detect_bank_type(str(path))
        if not detection.bank_id:
            from .generic_pdf import extract_generic_pdf

            return extract_generic_pdf(str(path)), detection.reason

        try:
            from .pipeline import extract_transactions

            transactions = extract_transactions(str(path), detection.bank_id)
        except Exception as exc:
            from .generic_pdf import extract_generic_pdf

            fallback = extract_generic_pdf(str(path))
            if fallback:
                return fallback, f"专用解析失败：{exc}；已使用通用识别"
            raise
        if transactions:
            return transactions, ""

        from .generic_pdf import extract_generic_pdf

        fallback = extract_generic_pdf(str(path))
        return fallback, "专用解析未得到流水，已尝试通用识别"

    def run(self) -> None:
        from .evidence import attach_source_evidence
        from .pdf_password import (
            install_pdf_password_support,
            register_pdf_passwords,
        )
        from .result_export import build_bankflow_result

        install_pdf_password_support()
        register_pdf_passwords(self.pdf_passwords)
        source_results: list[VerificationSourceResult] = []
        issues: list[Issue] = []
        transactions = []
        total = len(self.paths)

        for index, path in enumerate(self.paths, start=1):
            if self.isInterruptionRequested():
                self.cancelled.emit()
                return
            self.progress.emit(f"处理中：{path.name}")
            self.stage_progress.emit(index - 1, total, f"正在解析 {path.name}")
            try:
                source_transactions, message = self._extract(path)
                if not all(
                    getattr(transaction, "source_file_id", "")
                    for transaction in source_transactions
                ):
                    attach_source_evidence(source_transactions, path)
                for transaction in source_transactions:
                    transaction.source_file = path.name
                source_summary = summarize(source_transactions, path.name)
                issues.extend(source_summary.issues)
                status = "已纳入" if source_transactions else "需复核"
                if not source_transactions and not message:
                    message = "未解析到流水"
                source_results.append(
                    VerificationSourceResult(
                        path=path,
                        status=status,
                        message=message,
                        transactions=source_transactions,
                    )
                )
                transactions.extend(source_transactions)
                self.stage_progress.emit(index, total, f"已处理 {path.name}")
            except Exception as exc:
                message = str(exc)
                issues.append(Issue("需复核", path.name, "", f"解析失败：{message}"))
                source_results.append(
                    VerificationSourceResult(path, "需复核", message, [])
                )
                self.source_error.emit(path.name, message)
                self.stage_progress.emit(index, total, f"{path.name} 处理失败")

        if self.isInterruptionRequested():
            self.cancelled.emit()
            return
        self.progress.emit("正在生成 schema 1.16 标准结果")
        self.stage_progress.emit(total, total, "正在生成 schema 1.16 标准结果")
        try:
            standard_result = build_bankflow_result(
                transactions,
                metadata=get_statement_metadata(transactions),
                case_context=self.case_context,
                ai_config={},
                ai_evaluator=None,
            )
        except Exception as exc:
            self.failed.emit(f"标准结果生成失败：{exc}")
            return
        if self.isInterruptionRequested():
            self.cancelled.emit()
            return
        self.finished.emit(source_results, issues, standard_result)
