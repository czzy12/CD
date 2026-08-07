from __future__ import annotations

import json
import unittest

from bankflow_v2.standard_result_view import observation_by_type
from bankflow_web.case_session import CaseSession
from bankflow_web.contracts import ApplicationError, to_dict
from bankflow_web.module_registry import (
    BusinessModuleAdapter,
    DeclarationCompareModuleAdapter,
    PurchaseModuleAdapter,
)
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


class ModuleDisplayContentTests(unittest.TestCase):
    def test_business_declaration_and_purchase_rows_show_chinese_content(self):
        result = {
            "schema_version": "1.16",
            "module": "bankflow",
            "result": {
                "observations": [
                    {
                        "observation_type": "declaration_flow_cross_checks",
                        "value": {
                            "items": [
                                {
                                    "check_type": "work_unit",
                                    "declared_values": ["某某公司"],
                                    "status": "no_evidence_in_reliable_fields",
                                    "reason": "在当前可靠文字字段和流水期间内未发现对应文字依据",
                                    "evidence_transaction_ids": [],
                                }
                            ],
                            "display_only_items": [],
                        },
                    },
                    {
                        "observation_type": "ai_business_relevance_candidates",
                        "value": {
                            "available": True,
                            "deterministic_candidates": [
                                {
                                    "transaction_id": "tx:business",
                                    "classification": "possibly_related",
                                    "reason": "行业语义弱提示",
                                    "transaction_context": {
                                        "direction": "expense",
                                        "income": "0",
                                        "expense": "100.00",
                                        "source_file": "a.pdf",
                                        "transaction_time": "2026-01-01T00:00:00",
                                        "reliable_standard_fields": {
                                            "counterparty_name": "某商户",
                                            "summary": "购买护栏",
                                        },
                                    },
                                }
                            ],
                            "ai_candidates": [],
                        },
                    },
                    {
                        "observation_type": "purchase_prepayment_funding_candidates",
                        "value": {
                            "purchase_candidates": [
                                {
                                    "purchase_transaction_id": "tx:purchase",
                                    "direction": "expense",
                                    "income": "0",
                                    "expense": "10000.00",
                                    "matched_terms": ["订金"],
                                    "transaction_context": {
                                        "direction": "expense",
                                        "income": "0",
                                        "expense": "10000.00",
                                        "source_file": "a.pdf",
                                        "transaction_time": "2026-01-02T00:00:00",
                                        "reliable_standard_fields": {
                                            "counterparty_name": "某经销商",
                                            "summary": "购车订金",
                                        },
                                    },
                                    "prior_income_candidates": [
                                        {
                                            "transaction_id": "tx:prior",
                                            "income": "10000.00",
                                            "counterparty_name": "",
                                            "transaction_context": {
                                                "direction": "income",
                                                "income": "10000.00",
                                                "expense": "0",
                                                "source_file": "a.pdf",
                                                "transaction_time": "2026-01-01T00:00:00",
                                                "reliable_standard_fields": {
                                                    "summary": "工资收入"
                                                },
                                            },
                                        }
                                    ],
                                }
                            ]
                        },
                    },
                ],
                "facts": [],
                "indicators": [],
                "evidence": {
                    "transaction_index": {},
                    "references": [],
                    "coverage": {},
                    "integrity": {},
                },
            },
            "manual_review": {"required": True, "items": []},
            "source_files": [],
            "warnings": [],
            "notes": [],
            "created_at": "",
        }

        declaration = DeclarationCompareModuleAdapter(result, "case").items[0]
        self.assertEqual(declaration.primary_text, "某某公司")
        self.assertIsNone(declaration.matched_text)
        self.assertIsNone(declaration.interpretation)
        self.assertEqual(declaration.category, "工作单位")
        self.assertIn("未发现对应文字依据", declaration.secondary_text or "")

        business = BusinessModuleAdapter(result, "case").items[0]
        self.assertEqual(business.matched_text, "可能相关")
        self.assertEqual(business.category, "可能相关")
        self.assertEqual(business.direction, "支出")
        self.assertEqual(business.amount, "100.00")
        self.assertIn("某商户", business.primary_text)
        self.assertIn("确定性候选：可能相关", business.interpretation)

        purchase_rows = PurchaseModuleAdapter(result, "case").items
        prior = next(row for row in purchase_rows if row.item_id == "tx:prior")
        self.assertEqual(prior.matched_text, "此前收入")
        self.assertEqual(prior.primary_text, "工资收入")

    def test_business_rows_fill_context_from_original_transactions(self):
        from tests.test_web_result_adapter import fixture_result

        result = fixture_result()
        observation = observation_by_type(
            result,
            "ai_business_relevance_candidates",
        )
        if not observation:
            observation = {
                "observation_type": "ai_business_relevance_candidates",
                "value": {},
            }
            result["result"]["observations"].append(observation)
        observation["value"]["available"] = True
        observation["value"]["deterministic_candidates"] = [{
            "transaction_id": "tx:purchase",
            "classification": "directly_related",
            "reason": "申报单位词精确命中",
            "matched_anchors": ["测试汽车公司"],
        }]
        observation["value"]["ai_candidates"] = []
        business = BusinessModuleAdapter(result, "case").items[0]
        self.assertEqual(business.direction, "支出")
        self.assertEqual(business.amount, "10000.00")
        self.assertEqual(business.category, "直接相关")
        self.assertIn("测试汽车公司", business.primary_text)

    def test_manual_review_rows_use_chinese_categories_and_evidence_amount(self):
        from tests.test_web_result_adapter import fixture_result

        from bankflow_web.module_registry import ManualReviewModuleAdapter

        result = fixture_result()
        observation = observation_by_type(result, "manual_verification_questions")
        if not observation:
            observation = {
                "observation_type": "manual_verification_questions",
                "value": {},
            }
            result["result"]["observations"].append(observation)
        observation["value"]["questions"] = [{
            "question_id": "question:q1",
            "question_text": "请确认该主要交易对手与客户的关系。",
            "trigger_reason": "该对手在当前方向流水中的金额或占比较高。",
            "attention_category": "transaction_structure_attention",
            "evidence_transaction_ids": ["tx:purchase"],
        }]
        question = ManualReviewModuleAdapter(result, "case").items[0]
        self.assertEqual(question.category, "交易结构")
        self.assertEqual(question.direction, "支出")
        self.assertEqual(question.amount, "10000.00")
        self.assertEqual(question.matched_text, "涉及 1 笔证据")
        self.assertIsNone(question.interpretation)
        self.assertEqual(
            question.secondary_text,
            "该对手在当前方向流水中的金额或占比较高。",
        )

    def test_evidence_fields_no_longer_expose_raw_field_index_labels(self):
        from tests.test_web_result_adapter import fixture_result

        from bankflow_web.result_adapter import PurchaseResultAdapter

        adapter = PurchaseResultAdapter(fixture_result(), "case")
        evidence = adapter.evidence("tx:purchase")
        self.assertNotIn("raw_fields[", " ".join(evidence.full_original_fields))
        self.assertTrue(
            any(line.startswith("raw_text：") for line in evidence.full_original_fields)
        )

    def test_business_rows_mark_source_kind_and_anchor_hits(self):
        from tests.test_web_result_adapter import fixture_result

        result = fixture_result()
        observation = observation_by_type(
            result,
            "ai_business_relevance_candidates",
        )
        if not observation:
            observation = {
                "observation_type": "ai_business_relevance_candidates",
                "value": {},
            }
            result["result"]["observations"].append(observation)
        observation["value"]["available"] = True
        observation["value"]["deterministic_candidates"] = [{
            "transaction_id": "tx:purchase",
            "classification": "directly_related",
            "reason": "申报单位词精确命中",
            "matched_anchors": ["测试汽车公司", "某行业词"],
        }]
        observation["value"]["ai_candidates"] = [{
            "transaction_id": "tx:prior",
            "classification": "possibly_related",
            "reason": "行业语义弱提示",
        }]
        adapter = BusinessModuleAdapter(result, "case")
        deterministic = next(
            item for item in adapter.items if item.source_kind == "deterministic"
        )
        ai = next(item for item in adapter.items if item.source_kind == "ai")
        self.assertEqual(deterministic.matched_text, "命中：测试汽车公司、某行业词")
        self.assertEqual(deterministic.source_kind, "deterministic")
        self.assertEqual(ai.source_kind, "ai")
        self.assertEqual(ai.matched_text, "可能相关")
        supported = {definition.key for definition in adapter.descriptor().supported_filters}
        self.assertIn("source_kind", supported)
        filtered = adapter.list_items(
            "session",
            1,
            50,
            {"source_kind": "ai"},
            "default",
        )
        self.assertEqual(filtered.total, 1)
        self.assertEqual(filtered.items[0].source_kind, "ai")

    def test_declaration_display_only_items_get_explicit_label(self):
        result = {
            "schema_version": "1.16",
            "module": "bankflow",
            "result": {
                "observations": [
                    {
                        "observation_type": "declaration_flow_cross_checks",
                        "value": {
                            "items": [],
                            "display_only_items": [{
                                "check_type": "work_location",
                                "declared_values": ["某市某区某路 1 号"],
                                "handling": "system_information_display_only",
                                "reason": "仅展示系统资料，不与流水匹配或生成不一致结论。",
                            }],
                        },
                    }
                ],
                "facts": [],
                "indicators": [],
                "evidence": {
                    "transaction_index": {},
                    "references": [],
                    "coverage": {},
                    "integrity": {},
                },
            },
            "manual_review": {"required": True, "items": []},
            "source_files": [],
            "warnings": [],
            "notes": [],
            "created_at": "",
        }
        item = DeclarationCompareModuleAdapter(result, "case").items[0]
        self.assertEqual(item.category, "工作地点")
        self.assertEqual(item.review_status, "display_only")
        self.assertIn("仅展示系统资料", item.secondary_text or "")


if __name__ == "__main__":
    unittest.main()
