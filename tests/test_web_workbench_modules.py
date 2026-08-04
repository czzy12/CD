from __future__ import annotations

import json
import unittest

from bankflow_v2.standard_result_view import observation_by_type
from bankflow_web.case_session import CaseSession
from bankflow_web.contracts import ApplicationError, to_dict
from bankflow_webview2.api import WebView2Api
from tests.test_web_result_adapter import fixture_result


def workbench_result() -> dict[str, object]:
    result = fixture_result()
    sensitive = observation_by_type(result, "sensitive_transaction_context_candidates")["value"]
    sensitive["available"] = True
    sensitive["candidates"] = [{
        "transaction_id": "tx:purchase",
        "matched_terms": ["测试敏感词"],
        "transaction_context": {
            "transaction_time": "2026-01-10T12:00:00",
            "direction": "expense",
            "expense": "10000.00",
            "source_file": r"D:\private\fixture.pdf",
            "reliable_standard_fields": {
                "counterparty_name": "测试汽车公司",
                "purpose": "测试敏感词",
            },
        },
    }]
    result["source_files"].append({
        "source_file_id": "sha256:review",
        "source_file": r"D:\private\review.pdf",
        "status": "review",
        "review_reason": "未解析到流水",
        "parser_name": "fixture_parser",
        "transaction_count": 0,
    })
    return result


class WorkbenchModuleTests(unittest.TestCase):
    def setUp(self):
        self.session = CaseSession()
        self.session.bind(workbench_result(), "工作台 fixture")
        self.session_id = self.session.case_session_id
        assert self.session_id

    def test_registry_reports_available_empty_unavailable_and_not_implemented(self):
        modules = {item.module_id: item for item in self.session.registry().catalogue(self.session_id).modules}
        self.assertEqual(modules["purchase"].availability, "available")
        self.assertEqual(modules["sensitive"].availability, "available")
        self.assertIn(modules["declaration"].availability, {"empty", "available"})
        self.assertIn(modules["business"].availability, {"unavailable", "available"})
        self.assertEqual(modules["vehicle_records"].availability, "not_implemented")
        self.assertEqual(modules["vehicle_records"].display_kind, "disabled")

    def test_counts_and_summary_come_from_existing_observations(self):
        sensitive = self.session.registry().adapter("sensitive")
        descriptor = sensitive.descriptor()
        summary = sensitive.summary(self.session_id)
        self.assertEqual(descriptor.total_count, 1)
        self.assertEqual(summary.total_count, 1)
        self.assertEqual(summary.category_counts, {"敏感文字": 1})
        self.assertEqual(summary.source_count, 1)

    def test_unified_paging_filtering_and_page_size_validation(self):
        adapter = self.session.registry().adapter("sensitive")
        page = adapter.list_items(self.session_id, 1, 25, {"keyword": "测试敏感词"}, "default")
        empty = adapter.list_items(self.session_id, 1, 50, {"keyword": "不存在"}, "default")
        self.assertEqual(page.total, 1)
        self.assertEqual(page.case_session_id, self.session_id)
        self.assertEqual(empty.total, 0)
        for size in (20, 101):
            with self.subTest(size=size), self.assertRaises(ApplicationError) as raised:
                adapter.list_items(self.session_id, 1, size, {}, "default")
            self.assertEqual(raised.exception.code, "INVALID_ARGUMENT")

    def test_module_dto_excludes_full_result_original_record_and_absolute_path(self):
        page = self.session.registry().adapter("sensitive").list_items(self.session_id, 1, 50, {}, "default")
        encoded = json.dumps(to_dict(page), ensure_ascii=False)
        self.assertNotIn("original_transactions", encoded)
        self.assertNotIn("raw_fields", encoded)
        self.assertNotIn(r"D:\private", encoded)

    def test_source_review_is_sanitized_and_uses_schema_reason(self):
        review = self.session.adapter().source_review_summary()
        self.assertEqual(review.total, 1)
        self.assertEqual(review.items[0].display_name, "review.pdf")
        self.assertEqual(review.items[0].review_reason, "未解析到流水")
        self.assertFalse(review.items[0].generated_transactions)
        self.assertNotIn(r"D:\private", json.dumps(to_dict(review), ensure_ascii=False))

    def test_session_revision_switch_stale_request_and_close(self):
        first_id = self.session_id
        first_revision = self.session.revision
        self.session.bind(fixture_result(), "第二案件")
        self.assertNotEqual(self.session.case_session_id, first_id)
        self.assertGreater(self.session.revision, first_revision)
        with self.assertRaises(ApplicationError) as raised:
            self.session.assert_current(first_id)
        self.assertEqual(raised.exception.code, "STALE_CASE")
        self.session.close()
        self.assertIsNone(self.session.case_session_id)
        with self.assertRaises(ApplicationError) as closed:
            self.session.registry()
        self.assertEqual(closed.exception.code, "NO_CASE")

    def test_formal_api_returns_session_bound_modules_and_evidence(self):
        api = WebView2Api(self.session)
        state = api.get_app_state()
        modules = api.get_review_modules(self.session_id)
        page = api.list_module_items("sensitive", 1, 50, {}, "default", self.session_id)
        evidence = api.get_evidence("tx:purchase", self.session_id)
        self.assertTrue(modules["ok"])
        self.assertEqual(state["data"]["api_version"], "1")
        self.assertEqual(state["data"]["schema_versions_supported"], ["1.16"])
        self.assertEqual(state["data"]["renderer"], "edgechromium")
        self.assertEqual(state["data"]["case_session_id"], self.session_id)
        self.assertNotIn("ai", " ".join(state["data"]["capabilities"]).lower())
        self.assertEqual(page["data"]["case_session_id"], self.session_id)
        self.assertEqual(evidence["data"]["case_session_id"], self.session_id)
        stale = api.list_module_items("sensitive", 1, 50, {}, "default", "old-session")
        self.assertEqual(stale["error"]["code"], "STALE_CASE")

    def test_source_review_api_returns_only_review_items(self):
        api = WebView2Api(self.session)
        response = api.list_source_reviews(self.session_id)
        self.assertTrue(response["ok"])
        self.assertEqual(response["data"]["total"], 1)
        self.assertEqual(response["data"]["items"][0]["status"], "review")


if __name__ == "__main__":
    unittest.main()
