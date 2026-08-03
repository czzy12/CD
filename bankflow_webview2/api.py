"""Whitelisted pywebview JavaScript API backed by the existing read-only session."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from bankflow_web.case_session import CaseSession
from bankflow_web.contracts import AppStateDTO, ApplicationError

from .bridge_adapter import PyWebviewBridgeAdapter


STANDARD_RESULT_FILE_FILTER = "JSON 标准结果 (*.json)"


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

    def _attach_window(self, window: Any) -> None:
        self._window = window

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
                lambda: AppStateDTO(True, self._session.loaded, self._loading, "webview2")
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

    def get_evidence(self, transaction_id: str) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: self._session.adapter().evidence(transaction_id))

    def close_case(self) -> dict[str, object]:
        def close() -> None:
            with self._lock:
                self._session.close()
            return None

        return self._bridge.invoke(close)

    def _shutdown(self) -> None:
        self._closed.set()
        with self._lock:
            self._session.close()
