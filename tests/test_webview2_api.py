from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bankflow_v2.models import Transaction
from bankflow_v2.result_export import build_bankflow_result
from bankflow_web.case_session import CaseSession
from bankflow_webview2.api import STANDARD_RESULT_FILE_FILTER, WebView2Api


def _transaction(transaction_id: str, when: datetime, *, income: str = "0", expense: str = "0", purpose: str = "") -> Transaction:
    return Transaction(
        transaction_time=when,
        income=Decimal(income),
        expense=Decimal(expense),
        source_file="fixture.pdf",
        source_file_id="sha256:fixture",
        transaction_id=transaction_id,
        page_no=2,
        row_no=3,
        evidence_locator="page=2;row=3",
        purpose=purpose,
        counterparty_name="测试交易对手",
        raw_text="测试交易 13812345678",
        raw_fields=["测试交易", "6222021234567890"],
        field_confidence={"purpose": 1.0},
    )


def _fixture_result() -> dict[str, object]:
    purchase_time = datetime(2026, 1, 10, 12)
    return build_bankflow_result(
        [
            _transaction("tx:prior", purchase_time - timedelta(days=1), income="10000"),
            _transaction("tx:purchase", purchase_time, expense="10000", purpose="订金"),
        ],
        ai_config={},
    )


class WebView2ApiTests(unittest.TestCase):
    def setUp(self):
        self.session = CaseSession()
        self.session.bind(_fixture_result(), "WebView2 fixture")
        self.api = WebView2Api(self.session)

    def test_whitelisted_api_surface(self):
        public = {name for name in dir(self.api) if not name.startswith("_")}
        self.assertEqual(public, {
            "close_case", "get_app_state", "get_case_header", "get_evidence",
            "get_module_summary", "get_review_modules", "list_module_items",
            "list_source_reviews",
            "get_purchase_summary", "list_purchase_transactions",
            "load_standard_result", "select_standard_result",
            "choose_case_directory", "inspect_case_directory",
            "start_case_analysis", "get_analysis_status", "cancel_analysis",
            "dismiss_analysis_task", "save_current_standard_result",
            "list_recent_cases", "open_recent_case", "remove_recent_case",
            "reanalyze_recent_case",
            "get_manual_case_context", "save_manual_case_context",
            "get_current_manual_case_context", "save_current_manual_case_context",
            "clear_current_manual_case_context",
            "rebuild_context_observations", "export_report",
        })

    def test_current_case_context_unavailable_without_directory(self):
        read = self.api.get_current_manual_case_context()
        self.assertEqual(read["error"]["code"], "CURRENT_CASE_CONTEXT_UNAVAILABLE")
        save = self.api.save_current_manual_case_context(
            {"company_name": "单位"}
        )
        self.assertEqual(save["error"]["code"], "CURRENT_CASE_CONTEXT_UNAVAILABLE")

    def test_current_case_context_save_and_reload_roundtrip(self):
        from bankflow_web.case_workspace import case_workspace_dir

        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            workspace = case_workspace_dir(case_dir)
            try:
                dto = self.api.get_current_manual_case_context()
                self.assertEqual(dto["error"]["code"], "CURRENT_CASE_CONTEXT_UNAVAILABLE")
                self.api._current_case_dir = case_dir
                dto = self.api.get_current_manual_case_context()
                self.assertTrue(dto["ok"])
                self.assertEqual(dto["data"]["case_name"], case_dir.name)
                saved = self.api.save_current_manual_case_context({
                    "company_name": "测试单位",
                    "confirmed_primary_business": "建材批发",
                    "confirmed_products_or_services": "护栏",
                    "confirmation_note": "人工补充",
                })
                self.assertTrue(saved["ok"])
                self.assertEqual(saved["data"]["confirmation_status"], "confirmed")
                reloaded = self.api.get_current_manual_case_context()
                self.assertTrue(reloaded["ok"])
                self.assertEqual(reloaded["data"]["company_name"], "测试单位")
                self.assertEqual(reloaded["data"]["confirmed_primary_business"], "建材批发")
                self.assertEqual(reloaded["data"]["confirmed_products_or_services"], "护栏")
                self.assertEqual(reloaded["data"]["confirmation_note"], "人工补充")
                self.assertEqual(reloaded["data"]["confirmation_status"], "confirmed")
                self.assertTrue(reloaded["data"]["has_file"])
            finally:
                self.api._current_case_dir = None
                if workspace.exists():
                    shutil.rmtree(workspace)

    def test_clear_current_manual_case_context_empties_confirmation(self):
        from bankflow_web.case_workspace import case_workspace_dir

        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            workspace = case_workspace_dir(case_dir)
            try:
                self.api._current_case_dir = case_dir
                saved = self.api.save_current_manual_case_context({
                    "company_name": "测试单位",
                    "confirmed_primary_business": "建材批发",
                    "confirmed_products_or_services": "护栏",
                    "confirmation_note": "人工补充",
                })
                self.assertTrue(saved["ok"])
                cleared = self.api.clear_current_manual_case_context()
                self.assertTrue(cleared["ok"])
                reloaded = self.api.get_current_manual_case_context()
                self.assertTrue(reloaded["ok"])
                self.assertEqual(reloaded["data"]["confirmed_primary_business"], "")
                self.assertEqual(reloaded["data"]["confirmed_products_or_services"], "")
                self.assertEqual(reloaded["data"]["confirmation_note"], "")
            finally:
                self.api._current_case_dir = None
                if workspace.exists():
                    shutil.rmtree(workspace)

    def test_reanalyze_recent_case_returns_opaque_handle_or_stable_error(self):
        from bankflow_web.case_workspace import recent_cases_path
        from recent_cases import RecentCaseStore

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RecentCaseStore(root / "recent.json")
            api = WebView2Api(recent_store=store)
            unknown = api.reanalyze_recent_case("missing")
            self.assertEqual(unknown["error"]["code"], "RECENT_CASE_NOT_FOUND")

            result_only = root / "result.json"
            result_only.write_text("{}", encoding="utf-8")
            record = store.upsert(
                {"case_name": "仅结果"},
                result_path=result_only,
            )
            no_dir = api.reanalyze_recent_case(str(record["record_id"]))
            self.assertEqual(
                no_dir["error"]["code"],
                "RECENT_CASE_DIRECTORY_UNAVAILABLE",
            )

            case_dir = root / "case"
            case_dir.mkdir()
            (case_dir / "flow.pdf").write_bytes(b"%PDF-1.4 fixture")
            record = store.upsert(
                {"case_name": "可重分析"},
                case_dir=case_dir,
            )
            selection = api.reanalyze_recent_case(str(record["record_id"]))
            self.assertTrue(selection["ok"])
            self.assertEqual(selection["data"]["case_display_name"], "case")
            handle = selection["data"]["case_handle"]
            self.assertTrue(handle)
            inspected = api.inspect_case_directory(handle)
            self.assertTrue(inspected["ok"])
            encoded = json.dumps(selection, ensure_ascii=False)
            self.assertNotIn(str(case_dir), encoded)

    def test_start_case_analysis_uses_offline_ai_replay_when_runtime_available(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case"
            case_dir.mkdir()
            (case_dir / "flow.pdf").write_bytes(b"%PDF-1.4 fixture")
            api = WebView2Api()
            selection = api._case_directories.register(case_dir)
            api.inspect_case_directory(selection.case_handle)
            captured = {}

            class RecordingTasks:
                def start(self, *_args, **_kwargs):
                    captured.update(_kwargs)
                    return {"analysis_task_id": "task-a", "state": "running"}

            api._tasks = RecordingTasks()
            runtime_calls = []

            def fake_runtime(*args, **kwargs):
                runtime_calls.append(kwargs)
                return {"enabled": True}, lambda _payload: {"results": []}

            with patch(
                "bankflow_webview2.api.load_deepseek_runtime",
                side_effect=fake_runtime,
            ):
                api.start_case_analysis(selection.case_handle)
            self.assertEqual(runtime_calls, [{"replay_only": True}])
            self.assertFalse(captured["allow_external_network"])
            self.assertIsNotNone(captured["ai_evaluator"])
            captured.clear()
            with patch(
                "bankflow_webview2.api.load_deepseek_runtime",
                return_value=({"enabled": False}, None),
            ):
                api.start_case_analysis(selection.case_handle)
            self.assertFalse(captured["allow_external_network"])
            self.assertIsNone(captured["ai_evaluator"])

    def test_state_summary_page_and_evidence_reuse_existing_session(self):
        state = self.api.get_app_state()
        summary = self.api.get_purchase_summary()
        page = self.api.list_purchase_transactions(1, 50, {"status": "all"})
        evidence = self.api.get_evidence("tx:purchase")
        self.assertTrue(state["data"]["case_loaded"])
        self.assertEqual(summary["data"]["direct_count"], 1)
        self.assertEqual(page["data"]["page_size"], 50)
        self.assertEqual(evidence["data"]["transaction_id"], "tx:purchase")
        self.assertIn("138****5678", " ".join(evidence["data"]["masked_original_fields"]))

    def test_payload_has_no_full_result_or_absolute_path(self):
        page = self.api.list_purchase_transactions(1, 50, {"status": "all"})
        encoded = json.dumps(page, ensure_ascii=False)
        self.assertNotIn("original_transactions", encoded)
        self.assertNotIn("D:\\Investigator PDF", encoded)

    def test_invalid_arguments_and_no_case_are_stable(self):
        invalid = self.api.list_purchase_transactions(0, 50, {"status": "all"})
        self.assertEqual(invalid["error"]["code"], "INVALID_ARGUMENT")
        self.api.close_case()
        no_case = self.api.get_case_header()
        self.assertEqual(no_case["error"]["code"], "NO_CASE")

    def test_file_load_errors_and_switching_do_not_leak_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            value = self.api.load_standard_result(str(invalid))
            self.assertEqual(value["error"]["code"], "INVALID_JSON")
            wrong_type = self.api.load_standard_result(str(root / "result.txt"))
            self.assertEqual(wrong_type["error"]["code"], "INVALID_ARGUMENT")
            encoded = json.dumps(value, ensure_ascii=False)
            self.assertNotIn(str(root), encoded)

    def test_file_dialog_accepts_single_string_result(self):
        class FakeWindow:
            def __init__(self, path: Path) -> None:
                self.path = path
                self.directory = ""
                self.file_types = ()

            def create_file_dialog(self, *_args, **kwargs):
                self.directory = kwargs.get("directory", "")
                self.file_types = kwargs.get("file_types", ())
                return str(self.path)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            path.write_text(
                json.dumps(_fixture_result(), ensure_ascii=False),
                encoding="utf-8",
            )
            window = FakeWindow(path)
            self.api._attach_window(window)
            fake_webview = SimpleNamespace(
                FileDialog=SimpleNamespace(OPEN=10),
            )
            with patch.dict("sys.modules", {"webview": fake_webview}):
                response = self.api.select_standard_result()

        self.assertTrue(response["ok"])
        self.assertTrue(Path(window.directory).is_absolute())
        self.assertEqual(window.file_types, (STANDARD_RESULT_FILE_FILTER,))


if __name__ == "__main__":
    unittest.main()
