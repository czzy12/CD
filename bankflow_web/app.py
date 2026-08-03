"""Independent PyQt6 WebEngine desktop shell for the integration slice."""

from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import QUrl
from PyQt6.QtWebChannel import QWebChannel
from PyQt6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QLabel, QMainWindow, QStackedWidget

from .bridge import WebBridge
from .case_session import CaseSession
from .network_policy import OfflineRequestInterceptor
from .resource_paths import frontend_index


LOGGER = logging.getLogger("bankflow_web.app")


class WebSpikeWindow(QMainWindow):
    def __init__(self, *, dev_url: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle("流水核查工作台 · Web集成切片")
        self.resize(1500, 850)
        self._session = CaseSession()
        self._stack = QStackedWidget(self)
        self._loading = QLabel("正在加载流水核查 Web 集成切片…", self)
        self._loading.setStyleSheet("padding: 32px; font: 14px 'Microsoft YaHei UI'; color: #777;")
        self._view = QWebEngineView(self)
        self._stack.addWidget(self._loading)
        self._stack.addWidget(self._view)
        self.setCentralWidget(self._stack)

        self._profile = QWebEngineProfile("bankflow-web-spike", self)
        self._profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.NoPersistentCookies)
        self._profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        self._interceptor = OfflineRequestInterceptor(dev_url, self._profile)
        self._profile.setUrlRequestInterceptor(self._interceptor)
        self._page = QWebEnginePage(self._profile, self._view)
        self._view.setPage(self._page)
        self._view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        self._view.settings().setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)

        self._channel = QWebChannel(self._page)
        self._bridge = WebBridge(self._session, mode="dev" if dev_url else "local", parent=self._channel)
        self._channel.registerObject("bankflowBridge", self._bridge)
        self._page.setWebChannel(self._channel)
        self._view.loadFinished.connect(self._on_load_finished)
        target = QUrl(dev_url) if dev_url else QUrl.fromLocalFile(str(frontend_index()))
        self._view.load(target)

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            self._stack.setCurrentWidget(self._view)
            return
        target = frontend_index()
        self._loading.setText(f"前端加载失败。\n请先运行 npm.cmd run build。\n本地资源：{target.name}")
        LOGGER.error("Frontend failed to load: %s", target)

    def closeEvent(self, event) -> None:
        self._session.close()
        self._view.setPage(None)
        self._page.deleteLater()
        self._profile.deleteLater()
        super().closeEvent(event)
