from __future__ import annotations

import json
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
        })

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
