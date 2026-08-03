"""Default-deny remote network policy for QWebEngine."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from PyQt6.QtWebEngineCore import QWebEngineUrlRequestInfo, QWebEngineUrlRequestInterceptor


LOGGER = logging.getLogger("bankflow_web.network")


class OfflineRequestInterceptor(QWebEngineUrlRequestInterceptor):
    def __init__(self, dev_url: str | None = None, parent=None) -> None:
        super().__init__(parent)
        self._dev_origin = ""
        if dev_url:
            parsed = urlparse(dev_url)
            if parsed.scheme in {"http", "https"} and parsed.hostname == "127.0.0.1":
                self._dev_origin = f"{parsed.scheme}://{parsed.netloc}"

    def interceptRequest(self, info: QWebEngineUrlRequestInfo) -> None:
        url = info.requestUrl()
        scheme = url.scheme().lower()
        allowed = scheme in {"file", "qrc", "data", "blob", "about"}
        if self._dev_origin and url.toString().startswith(self._dev_origin):
            allowed = scheme in {"http", "ws"}
        if not allowed:
            LOGGER.warning("Blocked remote WebEngine request: scheme=%s host=%s", scheme, url.host())
            info.block(True)
