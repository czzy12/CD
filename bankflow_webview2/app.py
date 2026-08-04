"""pywebview + Microsoft Edge WebView2 desktop shell."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from .api import WebView2Api
from .resource_paths import build_offline_frontend_html
from .runtime_check import RuntimeStatus, check_webview2_runtime


class StartupError(RuntimeError):
    pass


def runtime_storage_path(runtime_tag: str = "cd-bankflow-webview2-spike") -> Path:
    return Path(__file__).resolve().parents[2] / ".runtime" / runtime_tag


def run_app(
    *,
    debug: bool = False,
    smoke_close_after_ready: float | None = None,
    title: str = "流水核查工作台 · WebView2 集成切片",
    runtime_tag: str = "cd-bankflow-webview2-spike",
) -> dict[str, object]:
    started = time.perf_counter()
    runtime = check_webview2_runtime()
    if runtime.status is not RuntimeStatus.AVAILABLE:
        raise StartupError(runtime.message)

    import webview

    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = debug

    api = WebView2Api()
    frontend_html = build_offline_frontend_html()
    window = webview.create_window(
        title,
        html=frontend_html,
        js_api=api,
        width=1500,
        height=850,
        min_size=(1100, 680),
        background_color="#101114",
        text_select=True,
    )
    api._attach_window(window)
    selected_renderer: dict[str, str | None] = {"value": None}
    metrics: dict[str, object] = {
        "runtime_detect_ms": runtime.elapsed_ms,
        "frontend_payload_bytes": len(frontend_html.encode("utf-8")),
        "window_object_ms": round((time.perf_counter() - started) * 1000, 3),
    }

    def on_initialized(renderer: str) -> bool | None:
        selected_renderer["value"] = renderer
        metrics["window_initialized_ms"] = round((time.perf_counter() - started) * 1000, 3)
        if renderer != "edgechromium":
            return False
        return None

    window.events.initialized += on_initialized
    window.events.closing += api._on_closing
    window.events.closed += api._shutdown
    if smoke_close_after_ready is not None:
        def close_smoke_window() -> None:
            api._frontend_ready.wait(15.0)
            if api._frontend_ready.is_set():
                try:
                    import psutil

                    metrics["rss_at_frontend_ready_bytes"] = psutil.Process().memory_info().rss
                except (ImportError, OSError):
                    pass
                threading.Event().wait(max(0.1, smoke_close_after_ready))
            window.destroy()

        threading.Thread(target=close_smoke_window, name="webview2-shell-smoke", daemon=True).start()
    storage = runtime_storage_path(runtime_tag)
    storage.mkdir(parents=True, exist_ok=True)
    try:
        webview.start(
            gui="edgechromium",
            debug=debug,
            private_mode=True,
            storage_path=str(storage),
        )
    except Exception as exc:
        raise StartupError("Microsoft Edge WebView2 初始化失败。") from exc
    if selected_renderer["value"] != "edgechromium":
        raise StartupError("未能启用 Microsoft Edge WebView2；程序已拒绝回退旧浏览器内核。")
    if smoke_close_after_ready is not None and not api._frontend_ready.is_set():
        raise StartupError("本地 React 前端未能连接桌面 API。")
    metrics["renderer"] = selected_renderer["value"]
    if api._frontend_ready_at is not None:
        metrics["frontend_ready_ms"] = round((api._frontend_ready_at - started) * 1000, 3)
    metrics["total_lifetime_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return metrics
