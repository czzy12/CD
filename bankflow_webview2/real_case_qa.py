"""Process-local WebView2 QA for the formal review workbench."""

from __future__ import annotations

import json
import tempfile
import threading
import time
from pathlib import Path

from bankflow_v2.standard_result_view import short_transaction_id

from .api import STANDARD_RESULT_FILE_FILTER, WebView2Api
from .resource_paths import build_offline_frontend_html


class _DialogStub:
    def __init__(self, path: Path) -> None:
        self.current = path

    def create_file_dialog(self, *_args, **_kwargs):
        return (str(self.current),)


def run_real_case_qa(paths: list[Path], output: Path, *, title: str = "流水核查工作台") -> int:
    if len(paths) != 2:
        raise ValueError("real-case QA requires exactly two JSON paths")
    import webview
    from webview.util import parse_file_type

    parse_file_type(STANDARD_RESULT_FILE_FILTER)
    api = WebView2Api()
    dialog = _DialogStub(paths[0])
    api._attach_window(dialog)
    frontend_html = build_offline_frontend_html().replace(
        "</head>",
        "<script>window.__bankflowQaErrors=[];"
        "window.addEventListener('error',e=>window.__bankflowQaErrors.push(String(e.message)));"
        "window.addEventListener('unhandledrejection',e=>window.__bankflowQaErrors.push(String(e.reason)));"
        "</script></head>", 1,
    )
    window = webview.create_window(
        title, html=frontend_html, js_api=api, width=1500, height=850,
        min_size=(1100, 680), background_color="#101114", text_select=True,
    )
    outcome: dict[str, object] = {"ok": False}

    def js(expression: str):
        return window.evaluate_js(expression)

    def wait_for(expression: str, timeout: float = 30.0) -> None:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if js(expression):
                return
            time.sleep(0.05)
        raise TimeoutError(expression)

    def snapshot() -> dict[str, object]:
        return json.loads(js("""
            JSON.stringify({
              rows: document.querySelectorAll('.transaction-row').length,
              modules: document.querySelectorAll('.module-section .sidebar-row').length,
              inspector: !!document.querySelector('.inspector'),
              selected: document.querySelectorAll('.transaction-row.selected').length,
              reviewAlert: !!document.querySelector('.source-review-alert'),
              theme: document.querySelector('.app-shell')?.dataset.theme || '',
              error: document.querySelector('.inline-error,.empty-error')?.textContent || ''
            })
        """))

    def session_id() -> str:
        value = api.get_app_state()
        return str(value["data"]["case_session_id"])

    def module_items(module_id: str) -> list[dict[str, object]]:
        value = api.list_module_items(module_id, 1, 50, {}, "default", session_id())
        return list(value["data"]["items"])

    def click_rows(module_id: str, limit: int = 3) -> int:
        items = module_items(module_id)
        checked = 0
        for index, item in enumerate(items[:limit]):
            transaction_id = item.get("transaction_id")
            if not transaction_id:
                continue
            expected = short_transaction_id(transaction_id)
            js(f"document.querySelectorAll('.transaction-row')[{index}].click(); true")
            wait_for("document.querySelector('.inspector')?.textContent.includes(" + json.dumps(expected, ensure_ascii=False) + ")")
            checked += 1
        return checked

    def click_module(title_text: str) -> None:
        js("""
            (() => { const button=[...document.querySelectorAll('.module-section .sidebar-row')]
              .find(node=>node.textContent.includes(%s)); if(button){button.click();return true} return false })()
        """ % json.dumps(title_text, ensure_ascii=False))
        wait_for("document.querySelector('.breadcrumb strong')?.textContent === " + json.dumps(title_text, ensure_ascii=False))
        wait_for("!document.querySelector('.loading-line')")

    def run() -> None:
        try:
            if not api._frontend_ready.wait(15.0):
                raise TimeoutError("frontend ready")
            js("document.querySelector('.primary-button').click(); true")
            wait_for("document.querySelector('.breadcrumb span')?.textContent === " + json.dumps(paths[0].stem))
            first = snapshot()
            first_header = api.get_case_header()["data"]
            first_modules = api.get_review_modules(session_id())["data"]["modules"]
            if first_header["review_source_count"] != 1 or not first["reviewAlert"]:
                raise AssertionError("source review status missing")
            review = api.list_source_reviews(session_id())["data"]
            if review["total"] != 1 or not review["items"][0]["review_reason"]:
                raise AssertionError("source review reason missing")
            js("document.querySelector('.source-review-alert').click(); true")
            wait_for("document.querySelector('.source-review-panel')?.textContent.includes(" + json.dumps(review["items"][0]["review_reason"], ensure_ascii=False) + ")")
            js("document.querySelector('.source-review-panel button[aria-label=\"关闭来源复核\"]').click(); true")
            available = [item for item in first_modules if item["availability"] == "available"]
            if len(available) < 2:
                raise AssertionError("fewer than two available modules")
            purchase_evidence = click_rows("purchase")
            old_id = module_items("purchase")[0]["transaction_id"]
            click_module("敏感交易")
            sensitive_evidence = click_rows("sensitive", 1)
            js("[...document.querySelectorAll('.sidebar-bottom .sidebar-row')].find(b=>b.textContent.includes('主题'))?.click(); true")
            wait_for("document.querySelector('.app-shell')?.dataset.theme === 'light'")

            dialog.current = paths[1]
            js("document.querySelector('button[aria-label=\"打开标准结果\"]').click(); true")
            wait_for("document.querySelector('.breadcrumb span')?.textContent === " + json.dumps(paths[1].stem))
            wait_for("!document.querySelector('.loading-line')")
            second = snapshot()
            second_header = api.get_case_header()["data"]
            old_lookup = api.get_evidence(old_id, session_id())
            if second_header["review_source_count"] != 0 or second["reviewAlert"]:
                raise AssertionError("source review leaked across cases")
            if second["selected"] or second["inspector"]:
                raise AssertionError("selection or inspector leaked across cases")
            if old_lookup["error"]["code"] != "TRANSACTION_NOT_FOUND":
                raise AssertionError("old transaction remained available")
            network_blocked = bool(js("""
                (() => { try { const xhr = new XMLHttpRequest();
                  xhr.open('GET', 'https://example.invalid/'); return false;
                } catch (_) { return true; } })()
            """))
            if not network_blocked:
                raise AssertionError("external network guard failed")
            dialog.current = paths[0]
            js("document.querySelector('button[aria-label=\"打开标准结果\"]').click(); true")
            wait_for("document.querySelector('.breadcrumb span')?.textContent === " + json.dumps(paths[0].stem))
            wait_for("!!document.querySelector('.source-review-alert') && !document.querySelector('.loading-line')")
            switched_back = api.get_case_header()["data"]
            outcome.update({
                "ok": True,
                "renderer": "edgechromium",
                "first": {
                    "source_count": first_header["source_count"],
                    "review_source_count": first_header["review_source_count"],
                    "module_count": first["modules"],
                    "available_module_count": len(available),
                    "purchase_evidence_checks": purchase_evidence,
                    "sensitive_evidence_checks": sensitive_evidence,
                },
                "switch": {
                    "second_review_source_count": second_header["review_source_count"],
                    "selection_cleared": second["selected"] == 0,
                    "inspector_cleared": not second["inspector"],
                    "old_id_lookup_code": old_lookup["error"]["code"],
                    "switched_back_review_source_count": switched_back["review_source_count"],
                },
                "theme_switch": True,
                "network_blocked": network_blocked,
                "device_pixel_ratio": js("window.devicePixelRatio"),
                "frontend_errors": [],
            })
        except Exception as exc:
            outcome.update({"error": type(exc).__name__ + ": " + str(exc)})
            try:
                outcome["diagnostic"] = json.loads(js("""
                    JSON.stringify({
                      errors: window.__bankflowQaErrors || [],
                      rootLength: document.querySelector('#root')?.textContent?.length || 0,
                      scriptCount: document.scripts.length,
                      apiReady: !!window.pywebview?.api
                    })
                """))
            except Exception:
                pass
        finally:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            window.destroy()

    window.events.closed += api._shutdown
    threading.Thread(target=run, name="webview2-real-case-qa", daemon=True).start()
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bankflow-webview2-qa-", dir=output.parent, ignore_cleanup_errors=True) as storage_path:
        webview.start(gui="edgechromium", debug=False, private_mode=True, storage_path=storage_path)
    return 0 if outcome.get("ok") else 1
