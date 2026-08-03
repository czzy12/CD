"""Minimal Edge Chromium and JavaScript-to-Python bridge smoke test."""

from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from typing import Any

from .runtime_check import RuntimeStatus, check_webview2_runtime


SMOKE_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'" />
  <title>WebView2 最小验证</title>
  <style>
    body { margin: 0; font-family: "Microsoft YaHei UI", "Microsoft YaHei", sans-serif;
      background: #f7f8fa; color: #191b1f; display: grid; min-height: 100vh; place-items: center; }
    main { width: min(560px, calc(100vw - 48px)); padding: 32px; background: white;
      border: 1px solid #e2e4e9; border-radius: 14px; box-shadow: 0 16px 50px #20242c1a; }
    h1 { font-size: 22px; margin: 0 0 12px; } p { color: #60646c; }
    #status { margin-top: 20px; padding: 12px 14px; border-radius: 8px; background: #eef7f1; color: #17663a; }
  </style>
</head>
<body><main><h1>WebView2 中文烟雾测试</h1><p>本页完全来自本地 HTML。</p>
<div id="status">正在连接 Python…</div></main>
<script>
  window.addEventListener('pywebviewready', async () => {
    const status = document.getElementById('status');
    try {
      const response = await window.pywebview.api.ping();
      let networkBlocked = false;
      try { await fetch('https://example.invalid/blocked-by-csp'); }
      catch (_) { networkBlocked = true; }
      status.textContent = `桥接成功：${response.value} · ${response.chinese}`;
      await window.pywebview.api.complete({
        pong: response.value,
        chinese: response.chinese,
        documentLanguage: document.documentElement.lang,
        networkBlocked,
        devicePixelRatio: window.devicePixelRatio
      });
    } catch (error) {
      status.textContent = '桥接失败';
      await window.pywebview.api.complete({error: String(error)});
    }
  });
</script></body></html>"""


class SmokeApi:
    def __init__(self, close_delay: float) -> None:
        self._close_delay = close_delay
        self._window: Any = None
        self._result: dict[str, Any] = {}
        self._finished = threading.Event()

    def ping(self) -> dict[str, object]:
        return {"ok": True, "value": "pong", "chinese": "中文显示正常"}

    def complete(self, payload: object) -> dict[str, object]:
        valid = (
            isinstance(payload, dict)
            and payload.get("pong") == "pong"
            and payload.get("networkBlocked") is True
        )
        self._result = {"bridge_ok": valid, "payload": payload}
        self._finished.set()
        if self._window is not None:
            threading.Timer(self._close_delay, self._window.destroy).start()
        return {"ok": valid}


def run_smoke(close_delay: float = 0.8, timeout: float = 15.0) -> dict[str, object]:
    runtime = check_webview2_runtime()
    result: dict[str, object] = {"runtime": runtime.to_dict(), "renderer": None}
    if runtime.status is not RuntimeStatus.AVAILABLE:
        result.update(ok=False, error_code=runtime.status.value, message=runtime.message)
        return result

    import webview

    api = SmokeApi(close_delay)
    storage_path = Path(__file__).resolve().parents[2] / ".runtime" / "cd-bankflow-webview2-spike"
    storage_path.mkdir(parents=True, exist_ok=True)
    window = webview.create_window(
        "WebView2 最小验证",
        html=SMOKE_HTML,
        js_api=api,
        width=720,
        height=480,
        min_size=(600, 400),
        text_select=True,
    )
    api._window = window
    started = time.perf_counter()

    def on_initialized(renderer: str) -> bool | None:
        result["renderer"] = renderer
        if renderer != "edgechromium":
            result.update(
                ok=False,
                error_code="RENDERER_REJECTED",
                message=f"拒绝非 Edge Chromium 渲染器：{renderer}",
            )
            return False
        return None

    def watchdog() -> None:
        if not api._finished.wait(timeout) and api._window is not None:
            result.update(ok=False, error_code="BRIDGE_TIMEOUT", message="JS-Python 桥接超时。")
            api._window.destroy()

    window.events.initialized += on_initialized
    threading.Thread(target=watchdog, name="webview2-smoke-watchdog", daemon=True).start()
    try:
        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=True,
            storage_path=str(storage_path),
        )
    except Exception:
        result.update(
            ok=False,
            error_code="INITIALIZATION_FAILED",
            message="Microsoft Edge WebView2 初始化失败。",
        )
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
    if "ok" not in result:
        api_result = dict(api._result)
        result.update(api_result)
        result["ok"] = result.get("renderer") == "edgechromium" and bool(api_result.get("bridge_ok"))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--close-delay", type=float, default=0.8)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args()
    result = run_smoke(max(0.1, args.close_delay), max(3.0, args.timeout))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
