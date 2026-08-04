"""Background task for the standalone schema 1.16 verification workbench."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal

from bankflow_web.analysis.cancellation import CancellationToken
from bankflow_web.analysis.service import AnalysisCancelled, AnalysisService
from bankflow_web.analysis.source_discovery import SUPPORTED_INPUTS


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
        ai_config: dict[str, object] | None = None,
        ai_evaluator: Callable[[dict[str, object]], object] | None = None,
    ) -> None:
        super().__init__()
        self.paths = paths
        self.pdf_passwords = pdf_passwords or {}
        self.case_context = case_context or {}
        self.ai_config = ai_config or {}
        self.ai_evaluator = ai_evaluator

    def _extract(self, path: Path) -> tuple[list, str]:
        return AnalysisService().extract_source(path)

    def run(self) -> None:
        cancellation = CancellationToken()
        total = len(self.paths)

        def on_progress(event) -> None:
            if self.isInterruptionRequested():
                cancellation.request()
            if event.source_name:
                self.progress.emit(f"处理中：{event.source_name}")
            if event.stage == "building_result":
                self.progress.emit("正在生成 schema 1.16 标准结果")
                self.stage_progress.emit(total, total, "正在生成 schema 1.16 标准结果")
            elif event.stage == "reading_source":
                self.stage_progress.emit(event.source_index, total, f"已处理 {event.source_name}")
            elif event.source_name:
                self.stage_progress.emit(event.source_index, total, f"正在解析 {event.source_name}")

        def on_source_complete(source) -> None:
            if source.failed:
                self.source_error.emit(source.path.name, source.message)

        try:
            service = AnalysisService()
            service.extract_source = self._extract
            outcome = service.run(
                self.paths,
                pdf_passwords=self.pdf_passwords,
                case_context=self.case_context,
                ai_config=self.ai_config,
                ai_evaluator=self.ai_evaluator,
                allow_external_network=self.ai_evaluator is not None,
                cancellation=cancellation,
                progress=on_progress,
                source_complete=on_source_complete,
            )
        except AnalysisCancelled:
            self.cancelled.emit()
            return
        except Exception as exc:
            self.failed.emit(f"标准结果生成失败：{exc}")
            return
        if self.isInterruptionRequested():
            self.cancelled.emit()
            return
        source_results = [
            VerificationSourceResult(
                source.path,
                "需复核" if source.status == "review" else "已纳入",
                source.message,
                source.transactions,
            )
            for source in outcome.source_results
        ]
        self.finished.emit(source_results, outcome.issues, outcome.standard_result)
