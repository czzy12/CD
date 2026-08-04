"""Whitelisted pywebview JavaScript API backed by the existing read-only session."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from bankflow_web.case_session import CaseSession
from bankflow_web.contracts import AppStateDTO, ApplicationError
from bankflow_web.analysis.source_discovery import CaseDirectoryRegistry
from bankflow_web.analysis.task_manager import AnalysisTaskManager
from bankflow_v2.result_export import write_bankflow_json
from bankflow_v2.standard_result_view import build_case_context_from_directory

from .bridge_adapter import PyWebviewBridgeAdapter


STANDARD_RESULT_FILE_FILTER = "JSON 标准结果 (*.json)"
STANDARD_RESULT_SAVE_FILTER = "JSON 标准结果 (*.json)"


class WebView2Api:
    """Only public methods on this class are exposed to JavaScript."""

    def __init__(self, session: CaseSession | None = None) -> None:
        self._session = session or CaseSession()
        self._bridge = PyWebviewBridgeAdapter()
        self._lock = threading.RLock()
        self._window: Any = None
        self._loading = False
        self._closed = threading.Event()
        self._frontend_ready = threading.Event()
        self._frontend_ready_at: float | None = None
        self._case_directories = CaseDirectoryRegistry()
        self._inspected_cases: set[str] = set()
        self._tasks = AnalysisTaskManager(self._promote_analysis_result)

    def _attach_window(self, window: Any) -> None:
        self._window = window

    def _promote_analysis_result(self, result: dict[str, object], case_name: str) -> tuple[str, int, int]:
        with self._lock:
            if self._closed.is_set():
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口正在关闭")
            self._session.load_result_dict(result, case_name=case_name, origin="analysis")
            header = self._session.adapter().case_header()
            return header.case_session_id, header.case_revision, header.transaction_count

    def _load(self, path: str) -> object:
        if not isinstance(path, str) or not path.strip():
            raise ApplicationError("INVALID_ARGUMENT")
        candidate = Path(path)
        if candidate.suffix.lower() != ".json":
            raise ApplicationError("INVALID_ARGUMENT", "只允许打开 JSON 标准结果")
        with self._lock:
            if self._closed.is_set():
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口正在关闭")
            self._loading = True
            try:
                self._session.load(candidate)
                return self._session.adapter().case_header()
            finally:
                self._loading = False

    def get_app_state(self) -> dict[str, object]:
        if self._frontend_ready_at is None:
            self._frontend_ready_at = time.perf_counter()
        self._frontend_ready.set()
        with self._lock:
            return self._bridge.invoke(
                lambda: AppStateDTO(
                    True,
                    self._session.loaded,
                    self._loading,
                    "webview2",
                    case_session_id=self._session.case_session_id,
                    case_revision=self._session.revision,
                )
            )

    def select_standard_result(self) -> dict[str, object]:
        def select() -> object:
            if self._window is None:
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口尚未初始化")
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                directory=str(Path.home()),
                allow_multiple=False,
                file_types=(STANDARD_RESULT_FILE_FILTER,),
            )
            if not selected:
                raise ApplicationError("CANCELLED", "未选择文件")
            if isinstance(selected, (str, Path)):
                filename = str(selected)
            else:
                try:
                    filename = str(next(iter(selected)))
                except (TypeError, StopIteration) as exc:
                    raise ApplicationError("CANCELLED", "未选择文件") from exc
            return self._load(filename)

        return self._bridge.invoke(select)

    def choose_case_directory(self) -> dict[str, object]:
        def choose() -> object:
            if self._window is None:
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口尚未初始化")
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.FOLDER,
                directory=str(Path.home()),
                allow_multiple=False,
            )
            if not selected:
                raise ApplicationError("CANCELLED", "未选择目录")
            if isinstance(selected, (str, Path)):
                folder = str(selected)
            else:
                try:
                    folder = str(next(iter(selected)))
                except (TypeError, StopIteration) as exc:
                    raise ApplicationError("CANCELLED", "未选择目录") from exc
            return self._case_directories.register(folder)

        return self._bridge.invoke(choose)

    def inspect_case_directory(self, case_handle: str) -> dict[str, object]:
        def inspect() -> object:
            _selection, dto = self._case_directories.inspect(case_handle)
            self._inspected_cases.add(case_handle)
            return dto

        return self._bridge.invoke(inspect)

    def start_case_analysis(self, case_handle: str, options: object | None = None) -> dict[str, object]:
        def start() -> object:
            if options is not None and not isinstance(options, dict):
                raise ApplicationError("INVALID_ARGUMENT")
            if isinstance(options, dict) and options:
                raise ApplicationError("INVALID_ARGUMENT", "当前分析不接受额外运行选项")
            if case_handle not in self._inspected_cases:
                raise ApplicationError("CASE_HANDLE_INVALID", "请先完成来源预检")
            selection = self._case_directories.get(case_handle)
            if not selection.sources:
                raise ApplicationError("NO_SUPPORTED_SOURCES")
            try:
                case_context = build_case_context_from_directory(selection.path)
            except OSError as exc:
                raise ApplicationError("CASE_DIRECTORY_READ_FAILED") from exc
            paths = [source.path for source in selection.sources]
            refs = {source.path: source.source_ref for source in selection.sources}
            return self._tasks.start(selection.path.name or "未命名案件", paths, case_context, refs)

        return self._bridge.invoke(start)

    def get_analysis_status(self, analysis_task_id: str) -> dict[str, object]:
        return self._bridge.invoke(lambda: self._tasks.status(analysis_task_id))

    def cancel_analysis(self, analysis_task_id: str) -> dict[str, object]:
        return self._bridge.invoke(lambda: self._tasks.cancel(analysis_task_id))

    def dismiss_analysis_task(self, analysis_task_id: str) -> dict[str, object]:
        return self._bridge.invoke(lambda: self._tasks.dismiss(analysis_task_id))

    def save_current_standard_result(self) -> dict[str, object]:
        def save() -> object:
            if self._window is None:
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口尚未初始化")
            result = self._session.current_result()
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=str(Path.home()),
                save_filename="bankflow_standard_result.json",
                file_types=(STANDARD_RESULT_SAVE_FILTER,),
            )
            if not selected:
                raise ApplicationError("CANCELLED", "已取消保存")
            if isinstance(selected, (str, Path)):
                filename = str(selected)
            else:
                try:
                    filename = str(next(iter(selected)))
                except (TypeError, StopIteration) as exc:
                    raise ApplicationError("CANCELLED", "已取消保存") from exc
            target = Path(filename)
            if target.suffix.lower() != ".json":
                target = target.with_suffix(".json")
            input_path = self._session.result_path
            if input_path is not None and target.resolve() == input_path.resolve():
                raise ApplicationError("SAVE_INPUT_OVERWRITE_FORBIDDEN")
            write_bankflow_json(result, target)
            return {"saved": True, "display_name": target.name}

        with self._lock:
            return self._bridge.invoke(save)

    def load_standard_result(self, path: str) -> dict[str, object]:
        return self._bridge.invoke(lambda: self._load(path))

    def get_case_header(self) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: self._session.adapter().case_header())

    def get_purchase_summary(self) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: self._session.adapter().purchase_summary())

    def list_purchase_transactions(
        self,
        page: int,
        page_size: int,
        filters: object | None = None,
    ) -> dict[str, object]:
        def query() -> object:
            parsed = filters
            if isinstance(filters, str):
                try:
                    parsed = json.loads(filters or "{}")
                except json.JSONDecodeError as exc:
                    raise ApplicationError("INVALID_ARGUMENT") from exc
            if parsed is None:
                parsed = {}
            if not isinstance(parsed, dict):
                raise ApplicationError("INVALID_ARGUMENT")
            return self._session.adapter().list_transactions(page, page_size, parsed)

        with self._lock:
            return self._bridge.invoke(query)

    def get_evidence(self, transaction_id: str, case_session_id: str | None = None) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: (
                self._session.assert_current(case_session_id),
                self._session.adapter().evidence(transaction_id),
            )[1])

    def get_review_modules(self, case_session_id: str | None = None) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: self._session.registry().catalogue(
                self._session.assert_current(case_session_id)
            ))

    def get_module_summary(self, module_id: str, case_session_id: str | None = None) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: self._session.registry().adapter(module_id).summary(
                self._session.assert_current(case_session_id)
            ))

    def list_module_items(
        self,
        module_id: str,
        page: int,
        page_size: int,
        filters: object | None = None,
        sort: str = "default",
        case_session_id: str | None = None,
    ) -> dict[str, object]:
        def query() -> object:
            parsed = filters
            if isinstance(filters, str):
                try:
                    parsed = json.loads(filters or "{}")
                except json.JSONDecodeError as exc:
                    raise ApplicationError("INVALID_ARGUMENT") from exc
            if parsed is None:
                parsed = {}
            if not isinstance(parsed, dict) or not isinstance(sort, str):
                raise ApplicationError("INVALID_ARGUMENT")
            session_id = self._session.assert_current(case_session_id)
            return self._session.registry().adapter(module_id).list_items(
                session_id, page, page_size, parsed, sort
            )

        with self._lock:
            return self._bridge.invoke(query)

    def list_source_reviews(self, case_session_id: str | None = None) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: (
                self._session.assert_current(case_session_id),
                self._session.adapter().source_review_summary(),
            )[1])

    def close_case(self) -> dict[str, object]:
        def close() -> None:
            with self._lock:
                self._session.close()
            return None

        return self._bridge.invoke(close)

    def _shutdown(self) -> None:
        self._closed.set()
        self._tasks.shutdown(5.0)
        with self._lock:
            self._session.close()

    def _on_closing(self) -> bool | None:
        if not self._tasks.has_active_task():
            return None
        import ctypes

        answer = ctypes.windll.user32.MessageBoxW(
            None,
            "分析仍在进行，关闭后本次分析结果不会保留。\n\n选择“是”请求停止并关闭；选择“否”继续分析。",
            "流水核查工作台",
            0x24,
        )
        if answer != 6:
            return False
        if not self._tasks.shutdown(5.0):
            ctypes.windll.user32.MessageBoxW(None, "正在停止，当前文件处理完成后即可关闭。", "流水核查工作台", 0x40)
            return False
        return None
