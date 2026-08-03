"""Framework-neutral envelopes for the pywebview API boundary."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from bankflow_web.contracts import ApplicationError, ApplicationErrorDTO, to_dict


LOGGER = logging.getLogger("bankflow_webview2.bridge")


class PyWebviewBridgeAdapter:
    def invoke(self, callback: Callable[[], object]) -> dict[str, object]:
        started = time.perf_counter()
        request_id = uuid.uuid4().hex
        try:
            envelope: dict[str, Any] = {"ok": True, "data": to_dict(callback()), "error": None}
        except ApplicationError as exc:
            envelope = {
                "ok": False,
                "data": None,
                "error": to_dict(ApplicationErrorDTO(exc.code, str(exc))),
            }
        except Exception:
            LOGGER.exception("WebView2 API request %s failed", request_id)
            envelope = {
                "ok": False,
                "data": None,
                "error": to_dict(ApplicationErrorDTO("INTERNAL_ERROR", "程序处理请求时发生内部错误")),
            }
        elapsed_ms = round((time.perf_counter() - started) * 1000, 3)
        envelope["meta"] = {"request_id": request_id, "elapsed_ms": elapsed_ms}
        encoded = json.dumps(envelope, ensure_ascii=False, separators=(",", ":"), default=to_dict)
        envelope["meta"]["payload_bytes"] = len(encoded.encode("utf-8"))
        return envelope
