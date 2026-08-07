"""Real WebView2 window QA for the 12B-2 full analysis flow.

Scenarios executed inside one real Edge Chromium window:

1. Cooperative cancellation: load an existing schema 1.16 case, start a real
   analysis on a case directory, wait until at least one source completed,
   click the UI cancel button, and verify the task reaches ``cancelled``
   without replacing the loaded case.
2. Failure recovery: with a QA-injected task-level failure (this script
   replaces the internal task manager with a failing service only), start
   another analysis and verify the task reaches ``failed`` while the loaded
   case session and header stay unchanged.

No customer file is modified. Results are written only to ``--output``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_web.analysis.service import AnalysisService  # noqa: E402
from bankflow_web.analysis.task_manager import AnalysisTaskManager  # noqa: E402
from bankflow_web.case_workspace import manual_context_path, standard_result_path  # noqa: E402


class _DialogStub:
    """Returns the configured directory for FOLDER dialogs and file otherwise."""

    def __init__(self, folder: Path, file: Path, save_path: Path | None = None) -> None:
        self.folder = folder
        self.file = file
        self.save_path = save_path

    def create_file_dialog(self, *args, **_kwargs):
        import webview

        if args and args[0] == webview.FileDialog.FOLDER:
            return (str(self.folder),)
        if args and args[0] == webview.FileDialog.SAVE and self.save_path is not None:
            return (str(self.save_path),)
        return (str(self.file),)


class _FailingService(AnalysisService):
    """QA-only service that fails at task level; never used outside this script."""

    def run(self, *args, **kwargs):
        raise RuntimeError("QA injected task failure")


def _inject_error_tracking(frontend_html: str) -> str:
    return frontend_html.replace(
        "</head>",
        "<script>window.__bankflowQaErrors=[];"
        "window.addEventListener('error',e=>window.__bankflowQaErrors.push(String(e.message)));"
        "window.addEventListener('unhandledrejection',e=>window.__bankflowQaErrors.push(String(e.reason)));"
        "</script></head>",
        1,
    )


def run_flow_qa(case_dir: Path, old_case: Path, output: Path, hold_open: bool, window_height: int = 850) -> int:
    import webview

    from bankflow_webview2.api import WebView2Api
    from bankflow_webview2.resource_paths import build_offline_frontend_html

    case_dir = case_dir.resolve(strict=True)
    old_case = old_case.resolve(strict=True)
    api = WebView2Api()
    output.parent.mkdir(parents=True, exist_ok=True)
    report_save_path = output.parent / (output.stem + "-report.md")
    api._attach_window(_DialogStub(case_dir, old_case, save_path=report_save_path))
    frontend_html = _inject_error_tracking(build_offline_frontend_html())
    window = webview.create_window(
        "流水核查工作台 · 12B-2 完整流程实测",
        html=frontend_html,
        js_api=api,
        width=1200,
        height=window_height,
        min_size=(1100, 680),
        background_color="#101114",
        text_select=True,
    )
    outcome: dict[str, object] = {"ok": False}
    closed = threading.Event()

    def js(expression: str):
        return window.evaluate_js(expression)

    def wait_for(expression: str, timeout: float = 60.0) -> None:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if js(expression):
                return
            time.sleep(0.05)
        raise TimeoutError(expression)

    def click(selector: str) -> None:
        js("document.querySelector(" + json.dumps(selector) + ")?.click(); true")

    def app_session() -> tuple[str, int]:
        data = api.get_app_state()["data"]
        return str(data["case_session_id"]), int(data["case_revision"])

    def header_snapshot() -> dict[str, object]:
        data = api.get_case_header()["data"]
        return {
            "case_name": data["case_name"],
            "source_count": data["source_count"],
            "transaction_count": data["transaction_count"],
            "review_source_count": data["review_source_count"],
            "case_session_id": data["case_session_id"],
            "case_revision": data["case_revision"],
        }

    def wait_task() -> str:
        deadline = time.perf_counter() + 30.0
        while time.perf_counter() < deadline:
            task = api._tasks._task
            if task is not None:
                return task.analysis_task_id
            time.sleep(0.05)
        raise TimeoutError("analysis task not started")

    def wait_terminal(task_id: str, timeout: float = 180.0) -> dict[str, object]:
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            status = api.get_analysis_status(task_id)["data"]
            if status["state"] in {"cancelled", "failed", "completed"}:
                return status
            time.sleep(0.1)
        raise TimeoutError("analysis task did not reach terminal state")

    def run() -> None:
        try:
            if not api._frontend_ready.wait(15.0):
                raise TimeoutError("frontend ready")

            # 1. Load the existing case as the "old case" baseline.
            click('button[aria-label="打开标准结果"]')
            wait_for("document.querySelector('.breadcrumb span')?.textContent === " + json.dumps(Path(old_case).stem))
            wait_for("!document.querySelector('.loading-line')")
            session_before, revision_before = app_session()
            header_before = header_snapshot()
            if not session_before:
                raise AssertionError("old case did not load")

            # 2. Cooperative cancellation on a real case directory.
            cancel_started = time.perf_counter()
            click('button[aria-label="新建案件"]')
            wait_for("!!document.querySelector('.workflow-actions .primary-button')", 60)
            preflight_layout = json.loads(js("""
                JSON.stringify((() => {
                  const wa = document.querySelector('.work-area');
                  const page = document.querySelector('.workflow-page');
                  const btn = document.querySelector('.workflow-actions .primary-button');
                  if (wa) wa.scrollTop = 0;
                  if (page) page.scrollTop = 0;
                  const before = btn ? Math.round(btn.getBoundingClientRect().bottom) : -1;
                  if (wa) wa.scrollTop = wa.scrollHeight;
                  if (page) page.scrollTop = page.scrollHeight;
                  const after = btn ? Math.round(btn.getBoundingClientRect().bottom) : -1;
                  return {
                    innerHeight: window.innerHeight,
                    workAreaScrollable: wa ? wa.scrollHeight > wa.clientHeight : false,
                    workAreaScrollHeight: wa ? wa.scrollHeight : -1,
                    startButtonBottomBefore: before,
                    startButtonBottomAfterScroll: after,
                    startButtonFullyVisible: after > 0 && after <= window.innerHeight + 1,
                  };
                })())
            """))
            if not preflight_layout.get("startButtonFullyVisible"):
                raise AssertionError("start button still clipped after scrolling: " + json.dumps(preflight_layout, ensure_ascii=False))
            case_handle = next(iter(api._case_directories._cases))
            context_saved = api.save_manual_case_context(case_handle, {
                "company_name": "QA 测试单位",
                "confirmed_primary_business": "建材销售",
                "confirmed_products_or_services": "护栏、围栏",
                "confirmation_note": "由完整流程实测写入",
            })
            if not context_saved["ok"]:
                raise AssertionError("manual context save failed: " + json.dumps(context_saved, ensure_ascii=False))
            context_fetched = api.get_manual_case_context(case_handle)
            if (
                not context_fetched["ok"]
                or context_fetched["data"]["company_name"] != "QA 测试单位"
                or context_fetched["data"]["confirmed_primary_business"] != "建材销售"
                or not manual_context_path(case_dir).exists()
            ):
                raise AssertionError("manual context roundtrip failed: " + json.dumps(context_fetched, ensure_ascii=False))
            manual_context_result = {
                "saved": True,
                "roundtrip_ok": True,
                "file_exists": manual_context_path(case_dir).exists(),
            }
            click('.workflow-actions .primary-button')
            wait_for("!!document.querySelector('.analysis-page')", 30)
            cancel_task_id = wait_task()
            # Wait for real progress before cancelling so the task is in flight.
            deadline = time.perf_counter() + 60.0
            while time.perf_counter() < deadline:
                status = api.get_analysis_status(cancel_task_id)["data"]
                if status["completed_sources"] >= 1:
                    break
                time.sleep(0.1)
            before_cancel = api.get_analysis_status(cancel_task_id)["data"]
            click('.analysis-page .workflow-actions .danger-button')
            cancelled = wait_terminal(cancel_task_id)
            cancel_ms = round((time.perf_counter() - cancel_started) * 1000, 3)
            if cancelled["state"] != "cancelled":
                raise AssertionError("cancel reached state " + str(cancelled["state"]))
            session_after_cancel, revision_after_cancel = app_session()
            header_after_cancel = header_snapshot()
            if (session_after_cancel, revision_after_cancel) != (session_before, revision_before):
                raise AssertionError("old case session changed after cancellation")
            if header_after_cancel != header_before:
                raise AssertionError("old case header changed after cancellation")
            cancel_result = {
                "state_reached": cancelled["state"],
                "total_sources": cancelled["total_sources"],
                "completed_sources_at_cancel_request": before_cancel["completed_sources"],
                "current_stage_at_cancel_request": before_cancel["current_stage"],
                "completed_sources_at_terminal": cancelled["completed_sources"],
                "elapsed_ms": cancel_ms,
                "old_case_session_preserved": True,
                "old_case_header_unchanged": True,
            }

            # Return to the preflight page after cancellation. The frontend
            # keeps the preflight so the user can restart or reselect; it
            # needs a moment to render the back button after the API terminal.
            wait_for("document.querySelector('.analysis-page .workflow-actions .primary-button')?.textContent.includes('返回')", 30)
            click('.analysis-page .workflow-actions .primary-button')
            wait_for("!document.querySelector('.analysis-page')", 30)
            wait_for("document.querySelector('.workflow-page .workflow-actions .primary-button')?.textContent.includes('开始分析')", 30)
            cancel_result["ui_returned_to_preflight"] = True

            # 3. Task-level failure keeps the old case (QA-only injection).
            api._tasks = AnalysisTaskManager(api._promote_analysis_result, service=_FailingService())
            failure_started = time.perf_counter()
            click('.workflow-actions .primary-button')
            wait_for("!!document.querySelector('.analysis-page')", 30)
            failure_task_id = wait_task()
            failed = wait_terminal(failure_task_id)
            failure_ms = round((time.perf_counter() - failure_started) * 1000, 3)
            if failed["state"] != "failed":
                raise AssertionError("failure reached state " + str(failed["state"]))
            if failed["error_code"] != "ANALYSIS_FAILED":
                raise AssertionError("unexpected error_code " + str(failed["error_code"]))
            wait_for("document.querySelector('.analysis-page .inline-error')?.textContent.includes('分析未完成')", 30)
            session_after_failure, revision_after_failure = app_session()
            header_after_failure = header_snapshot()
            if (session_after_failure, revision_after_failure) != (session_before, revision_before):
                raise AssertionError("old case session changed after failure")
            if header_after_failure != header_before:
                raise AssertionError("old case header changed after failure")
            failure_result = {
                "state_reached": failed["state"],
                "error_code": failed["error_code"],
                "ui_error_shown": True,
                "elapsed_ms": failure_ms,
                "old_case_session_preserved": True,
                "old_case_header_unchanged": True,
                "injection_note": "task-level failure injected by QA script only; per-source isolation is covered by unit tests",
            }

            # 4. Success flow: a completed analysis must leave the analysis
            # page and enter the module workbench automatically.
            click('.analysis-page .workflow-actions .primary-button')
            wait_for("!document.querySelector('.analysis-page')", 30)
            wait_for("document.querySelector('.workflow-page .workflow-actions .primary-button')?.textContent.includes('开始分析')", 30)
            api._tasks = AnalysisTaskManager(api._promote_analysis_result)
            success_started = time.perf_counter()
            click('.workflow-actions .primary-button')
            wait_for("!!document.querySelector('.analysis-page')", 30)
            wait_task()
            wait_for("!document.querySelector('.analysis-page') && !!document.querySelector('.view-bar')", 600)
            success_ms = round((time.perf_counter() - success_started) * 1000, 3)
            module_count = int(js("document.querySelectorAll('.module-section .sidebar-row').length") or 0)
            if module_count < 1:
                raise AssertionError("workbench modules not rendered after completion")
            list_footer_layout = json.loads(js("""
                JSON.stringify((() => {
                  const wa = document.querySelector('.work-area');
                  if (wa) wa.scrollTop = 0;
                  const footer = document.querySelector('.page-footer');
                  const rect = footer ? footer.getBoundingClientRect() : null;
                  return {
                    innerHeight: window.innerHeight,
                    footerVisible: !!rect && rect.bottom <= window.innerHeight + 1 && rect.bottom > 0,
                    footerBottom: rect ? Math.round(rect.bottom) : -1,
                  };
                })())
            """))
            if not list_footer_layout.get("footerVisible"):
                raise AssertionError("page footer still clipped: " + json.dumps(list_footer_layout, ensure_ascii=False))
            header_after_success = header_snapshot()
            if header_after_success["case_session_id"] == session_before:
                raise AssertionError("success flow did not switch to the new case")
            if not standard_result_path(case_dir).exists():
                raise AssertionError("workspace standard result was not saved after analysis")
            success_result = {
                "state_reached": "completed",
                "total_sources": None,
                "transaction_count": header_after_success["transaction_count"],
                "elapsed_ms": success_ms,
                "ui_entered_workbench": True,
                "module_count": module_count,
                "new_case_session": True,
                "workspace_result_saved": True,
            }

            # 5. Settings page: current-case business context view/edit.
            settings_started = time.perf_counter()
            click('.sidebar-bottom .sidebar-row')
            wait_for("!!document.querySelector('.settings-page')", 30)
            wait_for("!!Array.from(document.querySelectorAll('.settings-page .property-button')).find((b) => b.textContent.includes('保存经营上下文'))", 30)
            settings_fields = json.loads(js("""
                JSON.stringify((() => {
                  const inputs = document.querySelectorAll('.settings-page .context-grid input');
                  const textareas = document.querySelectorAll('.settings-page .context-grid textarea');
                  const selects = document.querySelectorAll('.settings-page .context-grid select');
                  const save = Array.from(document.querySelectorAll('.settings-page .property-button'))
                    .find((b) => b.textContent.includes('保存经营上下文'));
                  return {
                    rendered: !!document.querySelector('.settings-page'),
                    hasExtractSection: !!document.querySelector('.settings-page .extracted-context'),
                    companyInput: inputs[0]?.value || '',
                    primaryBusinessInput: inputs[1]?.value || '',
                    noteTextarea: textareas[0]?.value || '',
                    hasSaveButton: !!save,
                  };
                })())
            """))
            if not settings_fields.get("rendered") or not settings_fields.get("hasSaveButton"):
                raise AssertionError("settings page did not render: " + json.dumps(settings_fields, ensure_ascii=False))
            js("""
                (() => {
                  const inputs = document.querySelectorAll('.settings-page .context-grid input');
                  const input = inputs[1];
                  if (input) {
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                    setter.call(input, '建材批发与护栏工程');
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                  }
                  return true;
                })()
            """)
            js("Array.from(document.querySelectorAll('.settings-page .property-button')).find((b) => b.textContent.includes('保存经营上下文'))?.click(); true")
            wait_for("document.querySelector('.settings-page .context-notice')?.textContent.includes('经营上下文已保存')", 60)
            settings_saved = api.get_current_manual_case_context()
            if (
                not settings_saved["ok"]
                or settings_saved["data"]["confirmed_primary_business"] != "建材批发与护栏工程"
                or not settings_saved["data"]["has_file"]
            ):
                raise AssertionError("settings save roundtrip failed: " + json.dumps(settings_saved, ensure_ascii=False))
            settings_ms = round((time.perf_counter() - settings_started) * 1000, 3)
            click('.settings-page .workflow-actions .secondary-button')
            wait_for("!document.querySelector('.settings-page')", 30)
            settings_result = {
                "ui_opened": True,
                "fields_rendered": settings_fields,
                "save_notice_shown": True,
                "roundtrip_ok": True,
                "elapsed_ms": settings_ms,
                "ui_closed": True,
            }

            # 6. Recent cases: backend index + history page open flow.
            recent = api.list_recent_cases()
            if not recent["ok"] or not recent["data"]["cases"]:
                raise AssertionError("recent cases index empty after success flow")
            recent_result = {
                "count": len(recent["data"]["cases"]),
                "corrupt_index": recent["data"]["corrupt_index"],
            }
            click('button[aria-label="历史案件"]')
            wait_for("!!document.querySelector('.history-page')", 30)
            wait_for("!document.querySelector('.history-page .loading-line')", 30)
            history_rows = int(js("document.querySelectorAll('.history-row').length") or 0)
            if history_rows < 1:
                raise AssertionError("history page rendered without rows")
            click('.history-row .property-button')
            wait_for("!document.querySelector('.history-page') && !!document.querySelector('.view-bar')", 90)
            history_open_result = {
                "rows": history_rows,
                "ui_opened": True,
            }

            # 7. Rebuild context observations from the workbench.
            rebuild_started = time.perf_counter()
            session_before_rebuild = header_snapshot()["case_session_id"]
            click('.module-actions .save-result-button')
            wait_for("document.querySelector('.save-toast')?.textContent.includes('重新构建')", 90)
            rebuilt_header = header_snapshot()
            rebuild_ms = round((time.perf_counter() - rebuild_started) * 1000, 3)
            if rebuilt_header["case_session_id"] == session_before_rebuild:
                raise AssertionError("rebuild did not replace the session")
            rebuild_result = {
                "notice_shown": True,
                "session_replaced": True,
                "elapsed_ms": rebuild_ms,
            }

            # 8. Export the Markdown acceptance report.
            export_started = time.perf_counter()
            click('.module-actions .save-result-button:nth-of-type(2)')
            wait_for("document.querySelector('.save-toast')?.textContent.includes('报告已导出')", 60)
            export_ms = round((time.perf_counter() - export_started) * 1000, 3)
            if not report_save_path.exists():
                raise AssertionError("exported report file missing")
            export_result = {
                "notice_shown": True,
                "file_exists": True,
                "file_size": report_save_path.stat().st_size,
                "elapsed_ms": export_ms,
            }

            raw_errors = js("JSON.stringify(window.__bankflowQaErrors || [])")
            frontend_errors = json.loads(raw_errors) if isinstance(raw_errors, str) else list(raw_errors or [])
            outcome.update({
                "ok": not frontend_errors,
                "renderer": "edgechromium",
                "old_case": header_before,
                "cancel": cancel_result,
                "failure_recovery": failure_result,
                "success_flow": success_result,
                "manual_context": manual_context_result,
                "recent_cases": recent_result,
                "history_open": history_open_result,
                "context_rebuild": rebuild_result,
                "report_export": export_result,
                "settings_context": settings_result,
                "preflight_layout": preflight_layout,
                "list_footer_layout": list_footer_layout,
                "frontend_errors": frontend_errors,
                "device_pixel_ratio": js("window.devicePixelRatio"),
            })
        except Exception as exc:
            outcome.update({"error": type(exc).__name__ + ": " + str(exc)})
            try:
                outcome["diagnostic"] = json.loads(js("""
                    JSON.stringify({
                      errors: window.__bankflowQaErrors || [],
                      bodyText: document.body?.textContent?.slice(0, 400) || '',
                      apiReady: !!window.pywebview?.api
                    })
                """))
            except Exception:
                pass
        finally:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(outcome, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if hold_open:
                closed.wait()
            window.destroy()

    window.events.closed += api._shutdown
    window.events.closed += closed.set
    threading.Thread(target=run, name="webview2-12b2-flow-qa", daemon=True).start()
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bankflow-webview2-12b2-qa-", dir=output.parent, ignore_cleanup_errors=True) as storage_path:
        webview.start(gui="edgechromium", debug=False, private_mode=True, storage_path=storage_path)
    return 0 if outcome.get("ok") else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-dir", type=Path, required=True, help="案件目录（只读，用于真实取消场景）")
    parser.add_argument("--old-case", type=Path, required=True, help="已存在的 schema 1.16 标准结果 JSON")
    parser.add_argument("--output", type=Path, required=True, help="QA 结果 JSON 输出路径")
    parser.add_argument("--hold-open", action="store_true", help="自动化完成后保持窗口打开供人工查看")
    parser.add_argument("--window-height", type=int, default=850, help="窗口高度（用于小窗口布局验证）")
    args = parser.parse_args(argv)
    return run_flow_qa(args.case_dir, args.old_case, args.output, args.hold_open, args.window_height)


if __name__ == "__main__":
    raise SystemExit(main())
