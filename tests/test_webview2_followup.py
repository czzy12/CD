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
from bankflow_web.case_workspace import manual_context_path, standard_result_path
from bankflow_webview2.api import WebView2Api
from recent_cases import RecentCaseStore


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


class WebView2FollowUpTests(unittest.TestCase):
    def setUp(self):
        self.session = CaseSession()
        self.session.bind(_fixture_result(), "fixture")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = RecentCaseStore(self.root / "recent_cases.json")
        self.api = WebView2Api(self.session, recent_store=self.store)
        self.workspace_patch = patch(
            "bankflow_web.case_workspace.web_output_root",
            return_value=self.root / "out",
        )
        self.workspace_patch.start()
        self.addCleanup(self.workspace_patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_recent_cases_roundtrip_without_paths(self):
        result_path = self.root / "case.json"
        result_path.write_text(
            json.dumps(_fixture_result(), ensure_ascii=False),
            encoding="utf-8",
        )
        loaded = self.api.load_standard_result(str(result_path))
        self.assertTrue(loaded["ok"], str(loaded))

        cases = self.api.list_recent_cases()
        self.assertTrue(cases["ok"])
        self.assertEqual(cases["data"]["corrupt_index"], False)
        self.assertEqual(len(cases["data"]["cases"]), 1)
        record = cases["data"]["cases"][0]
        self.assertEqual(record["case_name"], "case")
        encoded = json.dumps(cases)
        self.assertNotIn("case_dir", encoded)
        self.assertNotIn("result_path", encoded)
        self.assertNotIn(str(self.root), encoded)

        opened = self.api.open_recent_case(record["record_id"])
        self.assertTrue(opened["ok"], str(opened))
        self.assertEqual(opened["data"]["case_name"], "case")

        removed = self.api.remove_recent_case(record["record_id"])
        self.assertTrue(removed["ok"])
        self.assertEqual(len(self.api.list_recent_cases()["data"]["cases"]), 0)

    def test_open_recent_case_missing_returns_stable_error(self):
        response = self.api.open_recent_case("missing")
        self.assertEqual(response["error"]["code"], "RECENT_CASE_NOT_FOUND")
        bad = self.api.open_recent_case("")
        self.assertEqual(bad["error"]["code"], "INVALID_ARGUMENT")

    def test_manual_context_roundtrip(self):
        case_dir = self.root / "caseA"
        case_dir.mkdir()
        handle = self.api._case_directories.register(case_dir).case_handle

        initial = self.api.get_manual_case_context(handle)
        self.assertTrue(initial["ok"])
        self.assertEqual(initial["data"]["saved"], False)

        saved = self.api.save_manual_case_context(
            handle,
            {
                "company_name": "测试单位",
                "confirmed_primary_business": "建材销售",
                "confirmed_products_or_services": "护栏、围栏",
                "confirmation_note": "QA 说明",
                "confirmation_status": "confirmed",
            },
        )
        self.assertTrue(saved["ok"], str(saved))
        self.assertEqual(saved["data"]["confirmation_status"], "confirmed")

        path = manual_context_path(case_dir)
        self.assertTrue(path.exists())
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            record["manual_confirmation"]["confirmed_primary_business"],
            "建材销售",
        )
        business = record["original_extracted_information"]["business_context"]
        self.assertEqual(business["company_name"], "测试单位")

        fetched = self.api.get_manual_case_context(handle)
        self.assertEqual(fetched["data"]["company_name"], "测试单位")
        self.assertEqual(fetched["data"]["confirmed_products_or_services"], "护栏、围栏")
        self.assertEqual(fetched["data"]["source_names"], [])

    def test_extracted_txt_context_is_surfaced(self):
        case_dir = self.root / "caseTxt"
        case_dir.mkdir()
        (case_dir / "客户资料.txt").write_text("测试文本", encoding="utf-8")
        handle = self.api._case_directories.register(case_dir).case_handle

        fetched = self.api.get_manual_case_context(handle)
        self.assertTrue(fetched["ok"])
        self.assertEqual(fetched["data"]["source_names"], ["客户资料.txt"])
        self.assertIsInstance(fetched["data"]["work_units"], list)
        self.assertIsInstance(fetched["data"]["declared_work_status"], str)

    def test_promote_saves_workspace_result_and_history_can_open_it(self):
        case_dir = self.root / "caseC"
        case_dir.mkdir()
        self.api._current_case_dir = case_dir
        session_id, revision, count = self.api._promote_analysis_result(
            _fixture_result(),
            "caseC",
        )
        self.assertTrue(session_id)
        saved = standard_result_path(case_dir)
        self.assertTrue(saved.exists())

        records = self.store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["case_name"], "caseC")
        self.assertEqual(Path(str(records[0]["case_dir"])), case_dir)
        self.assertEqual(Path(str(records[0]["result_path"])), saved)

        record_id = records[0]["record_id"]
        opened = self.api.open_recent_case(record_id)
        self.assertTrue(opened["ok"], str(opened))
        self.assertEqual(opened["data"]["case_name"], "caseC")

    def test_rebuild_context_observations(self):
        case_dir = self.root / "caseB"
        case_dir.mkdir()
        handle = self.api._case_directories.register(case_dir).case_handle
        self.api.save_manual_case_context(
            handle,
            {
                "company_name": "测试单位",
                "confirmed_primary_business": "建材销售",
                "confirmation_status": "confirmed",
            },
        )
        self.api._current_case_dir = case_dir
        self.api._session.load_result_dict(
            _fixture_result(),
            case_name="caseB",
            origin="analysis",
        )
        before = self.api.get_app_state()["data"]["case_session_id"]

        rebuilt = self.api.rebuild_context_observations()
        self.assertTrue(rebuilt["ok"], str(rebuilt))
        after = self.api.get_app_state()["data"]["case_session_id"]
        self.assertNotEqual(before, after)
        result = self.api._session.current_result()
        types = {
            observation.get("observation_type")
            for observation in result["result"]["observations"]
        }
        self.assertIn("ai_business_relevance_candidates", types)
        self.assertIn("declaration_flow_cross_checks", types)
        self.assertIn("manual_verification_questions", types)

    def test_rebuild_unavailable_without_case_dir(self):
        self.api._session.bind(_fixture_result(), "file case")
        self.api._current_case_dir = None
        response = self.api.rebuild_context_observations()
        self.assertEqual(response["error"]["code"], "REBUILD_UNAVAILABLE")

    def test_export_report(self):
        class FakeWindow:
            def __init__(self, path: Path) -> None:
                self.path = path
                self.file_types = ()

            def create_file_dialog(self, *_args, **kwargs):
                self.file_types = kwargs.get("file_types", ())
                return str(self.path)

        self.api._session.bind(_fixture_result(), "export case")
        target = self.root / "report.md"
        self.api._attach_window(FakeWindow(target))
        fake_webview = SimpleNamespace(FileDialog=SimpleNamespace(SAVE=20))
        with patch.dict("sys.modules", {"webview": fake_webview}):
            response = self.api.export_report()

        self.assertTrue(response["ok"], str(response))
        self.assertTrue(target.exists())
        content = target.read_text(encoding="utf-8")
        self.assertIn("# 流水核查 MVP 验收报告", content)


if __name__ == "__main__":
    unittest.main()
