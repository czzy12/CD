"""QWebChannel bridge with stable JSON envelopes and no exception leakage."""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Callable

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import QFileDialog

from .case_session import CaseSession
from .contracts import AppStateDTO, ApplicationError, ApplicationErrorDTO, to_dict


LOGGER = logging.getLogger("bankflow_web.bridge")


class WebBridge(QObject):
    stateChanged = pyqtSignal(str)

    def __init__(self, session: CaseSession, *, mode: str = "local", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.session = session
        self.frontend_ready = False
        self.loading = False
        self.mode = mode

    def _invoke(self, callback: Callable[[], object]) -> str:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        try:
            data = to_dict(callback())
            envelope = {"ok": True, "data": data, "error": None}
        except ApplicationError as exc:
            envelope = {"ok": False, "data": None, "error": to_dict(ApplicationErrorDTO(exc.code, str(exc)))}
        except Exception:
            LOGGER.exception("Bridge request %s failed", request_id)
            envelope = {"ok": False, "data": None, "error": to_dict(ApplicationErrorDTO("INTERNAL_ERROR", "程序处理请求时发生内部错误"))}
        envelope["meta"] = {
            "request_id": request_id,
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
        }
        encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))
        envelope["meta"]["payload_bytes"] = len(encoded.encode("utf-8"))
        return json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))

    @pyqtSlot(result=str)
    def frontend_ready_event(self) -> str:
        self.frontend_ready = True
        return self.get_app_state()

    @pyqtSlot(result=str)
    def get_app_state(self) -> str:
        return self._invoke(lambda: AppStateDTO(self.frontend_ready, self.session.loaded, self.loading, self.mode))

    @pyqtSlot(result=str)
    def select_standard_result(self) -> str:
        filename, _ = QFileDialog.getOpenFileName(None, "打开schema 1.16标准结果JSON", "", "schema 1.16 标准结果 (*.json);;JSON 文件 (*.json)")
        if not filename:
            return self._invoke(lambda: (_ for _ in ()).throw(ApplicationError("INVALID_ARGUMENT", "未选择文件")))
        return self.load_standard_result(filename)

    @pyqtSlot(str, result=str)
    def load_standard_result(self, path: str) -> str:
        def load() -> object:
            self.loading = True
            try:
                self.session.load(path)
                return self.session.adapter().case_header()
            finally:
                self.loading = False
        response = self._invoke(load)
        self.stateChanged.emit(response)
        return response

    @pyqtSlot(result=str)
    def get_case_header(self) -> str:
        return self._invoke(lambda: self.session.adapter().case_header())

    @pyqtSlot(result=str)
    def get_purchase_summary(self) -> str:
        return self._invoke(lambda: self.session.adapter().purchase_summary())

    @pyqtSlot(int, int, str, result=str)
    def list_purchase_transactions(self, page: int, page_size: int, filters_json: str = "{}") -> str:
        def query() -> object:
            try:
                filters = json.loads(filters_json or "{}")
            except json.JSONDecodeError as exc:
                raise ApplicationError("INVALID_ARGUMENT") from exc
            if not isinstance(filters, dict):
                raise ApplicationError("INVALID_ARGUMENT")
            return self.session.adapter().list_transactions(page, page_size, filters)
        return self._invoke(query)

    @pyqtSlot(str, result=str)
    def get_evidence(self, transaction_id: str) -> str:
        return self._invoke(lambda: self.session.adapter().evidence(transaction_id))

    @pyqtSlot(result=str)
    def close_case(self) -> str:
        def close() -> AppStateDTO:
            self.session.close()
            return AppStateDTO(self.frontend_ready, False, False, self.mode)
        response = self._invoke(close)
        self.stateChanged.emit(response)
        return response
