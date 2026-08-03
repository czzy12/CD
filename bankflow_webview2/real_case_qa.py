"""Explicit CLI-only real-case QA for the packaged WebView2 spike."""

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


def run_real_case_qa(paths: list[Path], output: Path) -> int:
    if len(paths) != 2:
        raise ValueError("EXE real-case QA requires exactly two JSON paths")
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
        "</script></head>",
        1,
    )
    window = webview.create_window(
        "流水核查工作台 · WebView2 EXE 验收",
        html=frontend_html,
        js_api=api,
        width=1500,
        height=850,
        min_size=(1100, 680),
        background_color="#101114",
        text_select=True,
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
        raw = js("""
            JSON.stringify({
              caseName: document.querySelector('.breadcrumb span')?.textContent || '',
              rows: document.querySelectorAll('.transaction-row').length,
              inspector: !!document.querySelector('.inspector'),
              selected: document.querySelectorAll('.transaction-row.selected').length,
              footer: document.querySelector('.page-footer')?.textContent || '',
              metrics: document.querySelector('.summary-metrics')?.textContent || '',
              sourceReview: document.querySelector('.source-review-alert')?.textContent || '',
              error: document.querySelector('.inline-error,.empty-error')?.textContent || ''
            })
        """)
        return json.loads(raw)

    def ordered_items() -> list[dict[str, object]]:
        value = api.list_purchase_transactions(1, 50, {"status": "all"})
        items = value["data"]["items"]
        return [item for item in items if item["review_status"] == "direct"] + [
            item for item in items if item["review_status"] == "review"
        ]

    def click_three() -> list[dict[str, object]]:
        items = ordered_items()
        checks = []
        for index, item in enumerate(items[:3]):
            expected = short_transaction_id(item["transaction_id"])
            js(f"document.querySelectorAll('.transaction-row')[{index}].click(); true")
            wait_for(
                "document.querySelector('.inspector')?.textContent.includes("
                + json.dumps(expected, ensure_ascii=False)
                + ")"
            )
            checks.append({"transaction_id_short": expected, "matched": True})
        if len(checks) != 3:
            raise AssertionError("fewer than three transactions available")
        return checks

    def run() -> None:
        try:
            if not api._frontend_ready.wait(15.0):
                raise TimeoutError("frontend ready")
            js("document.querySelector('.primary-button').click(); true")
            wait_for(
                "document.querySelector('.breadcrumb span')?.textContent === "
                + json.dumps(paths[0].stem)
            )
            first = snapshot()
            if "1 来源需复核" not in str(first["sourceReview"]):
                raise AssertionError("review source status is not visible")
            first_checks = click_three()
            old_id = ordered_items()[0]["transaction_id"]

            dialog.current = paths[1]
            js("document.querySelector('button[aria-label=\"打开标准结果\"]').click(); true")
            wait_for(
                "document.querySelector('.breadcrumb span')?.textContent === "
                + json.dumps(paths[1].stem)
            )
            switched = snapshot()
            if switched["sourceReview"]:
                raise AssertionError("review source status leaked across cases")
            old_lookup = api.get_evidence(old_id)
            second_checks = click_three()
            second = snapshot()

            page = api.list_purchase_transactions(1, 50, {"status": "all"})
            evidence = api.get_evidence(ordered_items()[0]["transaction_id"])
            encoded = json.dumps([page, evidence], ensure_ascii=False)
            boundary_ok = not any(
                value in encoded
                for value in ("original_transactions", "standard_result", "D:\\Investigator PDF")
            )
            outcome.update({
                "ok": True,
                "renderer": "edgechromium",
                "file_filter": STANDARD_RESULT_FILE_FILTER,
                "first": first,
                "first_evidence": first_checks,
                "switch": switched,
                "old_id_lookup_code": old_lookup["error"]["code"],
                "second": second,
                "second_evidence": second_checks,
                "dto_boundary_ok": boundary_ok,
            })
        except Exception as exc:
            outcome.update({"error": type(exc).__name__ + ": " + str(exc)})
            try:
                outcome["diagnostic"] = json.loads(js("""
                    JSON.stringify({
                      errors: window.__bankflowQaErrors || [],
                      rootText: document.querySelector('#root')?.textContent || '',
                      scriptCount: document.scripts.length,
                      apiReady: !!window.pywebview?.api
                    })
                """))
            except Exception:
                pass
        finally:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps(outcome, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            window.destroy()

    window.events.closed += api._shutdown
    threading.Thread(target=run, name="webview2-exe-real-case-qa", daemon=True).start()
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="bankflow-webview2-qa-",
        dir=output.parent,
        ignore_cleanup_errors=True,
    ) as storage_path:
        webview.start(
            gui="edgechromium",
            debug=False,
            private_mode=True,
            storage_path=storage_path,
        )
    return 0 if outcome.get("ok") else 1
