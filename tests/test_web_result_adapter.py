from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from bankflow_v2.models import Transaction
from bankflow_v2.result_export import build_bankflow_result
from bankflow_web.case_session import CaseSession
from bankflow_web.contracts import ApplicationError


def tx(transaction_id: str, when: datetime, *, income: str = "0", expense: str = "0", purpose: str = "", counterparty: str = "") -> Transaction:
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
        counterparty_name=counterparty,
        raw_text=f"{counterparty} {purpose} 13812345678",
        raw_fields=[counterparty, purpose, "6222021234567890"],
        field_confidence={"purpose": 1.0, "counterparty_name": 1.0},
    )


def fixture_result() -> dict[str, object]:
    purchase_time = datetime(2026, 1, 10, 12)
    return build_bankflow_result([
        tx("tx:prior", purchase_time - timedelta(days=1), income="10000", counterparty="测试收入方"),
        tx("tx:purchase", purchase_time, expense="10000", purpose="订金", counterparty="测试汽车公司"),
    ], ai_config={})


class WebResultAdapterTests(unittest.TestCase):
    def setUp(self):
        self.session = CaseSession()
        self.session.bind(fixture_result(), "契约测试fixture")

    def test_schema_117_fixture_loads_and_purchase_summary_reads_existing_observation(self):
        header = self.session.adapter().case_header()
        summary = self.session.adapter().purchase_summary()
        self.assertEqual(header.schema_version, "1.17")
        self.assertEqual(summary.direct_count, 1)
        self.assertGreaterEqual(summary.prior_income_count, 1)
        self.assertIn("不表示资金来源", summary.boundary_note)

    def test_case_header_exposes_only_formal_review_source_dto(self):
        result = fixture_result()
        result["source_files"].append({
            "source_file_id": "",
            "source_file": "unparsed.pdf",
            "transaction_count": 0,
            "status": "review",
            "review_reason": "未解析到流水",
        })
        self.session.bind(result, "来源复核fixture")

        header = self.session.adapter().case_header()

        self.assertEqual(header.source_count, 2)
        self.assertEqual(header.review_source_count, 1)
        self.assertEqual(header.review_sources[0].source_name, "unparsed.pdf")
        self.assertEqual(header.review_sources[0].reason, "未解析到流水")

    def test_default_page_size_is_50_and_filter_uses_existing_category(self):
        page = self.session.adapter().list_transactions()
        deposit = self.session.adapter().list_transactions(filters={"status": "deposit"})
        self.assertEqual(page.page_size, 50)
        self.assertEqual(deposit.items[0].category, "订金/定金")

    def test_page_and_page_size_validation(self):
        for page, size in ((0, 50), (1, 20), (1, 101)):
            with self.subTest(page=page, size=size), self.assertRaises(ApplicationError) as raised:
                self.session.adapter().list_transactions(page, size)
            self.assertEqual(raised.exception.code, "INVALID_ARGUMENT")

    def test_unrelated_original_transaction_is_not_promoted_to_purchase_candidate(self):
        result = build_bankflow_result([tx("tx:plain", datetime(2026, 1, 1), expense="10", purpose="普通消费")], ai_config={})
        self.session.bind(result, "无候选fixture")
        self.assertEqual(self.session.adapter().list_transactions().items, [])

    def test_paged_dto_does_not_contain_full_original_transactions_or_absolute_path(self):
        encoded = json.dumps(self.session.adapter().list_transactions().__dict__, default=lambda value: value.__dict__, ensure_ascii=False)
        self.assertNotIn("original_transactions", encoded)
        self.assertNotIn("D:\\\\Investigator PDF", encoded)

    def test_exact_evidence_lookup_and_default_redaction(self):
        evidence = self.session.adapter().evidence("tx:purchase")
        self.assertEqual(evidence.page_no, 2)
        self.assertIn("138****5678", " ".join(evidence.masked_original_fields))
        self.assertIn("13812345678", " ".join(evidence.full_original_fields))

    def test_missing_id_and_broken_index_fail_closed(self):
        with self.assertRaises(ApplicationError) as missing:
            self.session.adapter().evidence("tx:missing")
        self.assertEqual(missing.exception.code, "TRANSACTION_NOT_FOUND")
        result = fixture_result()
        result["result"]["evidence"]["transaction_index"]["tx:purchase"]["original_transaction_index"] = 99
        self.session.bind(result, "坏索引fixture")
        with self.assertRaises(ApplicationError) as broken:
            self.session.adapter().evidence("tx:purchase")
        self.assertEqual(broken.exception.code, "EVIDENCE_UNAVAILABLE")

    def test_mismatched_transaction_id_fails_closed(self):
        result = fixture_result()
        index = result["result"]["evidence"]["transaction_index"]["tx:purchase"]["original_transaction_index"]
        result["result"]["original_transactions"][index]["transaction_id"] = "tx:other"
        self.session.bind(result, "ID不一致fixture")
        with self.assertRaises(ApplicationError) as raised:
            self.session.adapter().evidence("tx:purchase")
        self.assertEqual(raised.exception.code, "EVIDENCE_UNAVAILABLE")

    def test_close_and_switch_do_not_retain_old_case(self):
        self.session.close()
        with self.assertRaises(ApplicationError) as raised:
            self.session.adapter()
        self.assertEqual(raised.exception.code, "NO_CASE")
        self.session.bind(fixture_result(), "第二案件")
        self.assertEqual(self.session.adapter().case_header().case_name, "第二案件")

    def test_file_errors_have_stable_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ApplicationError) as missing:
                CaseSession().load(root / "missing.json")
            self.assertEqual(missing.exception.code, "FILE_NOT_FOUND")
            invalid = root / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            with self.assertRaises(ApplicationError) as broken:
                CaseSession().load(invalid)
            self.assertEqual(broken.exception.code, "INVALID_JSON")
            incompatible = root / "old.json"
            incompatible.write_text(json.dumps({"schema_version": "1.15"}), encoding="utf-8")
            with self.assertRaises(ApplicationError) as old:
                CaseSession().load(incompatible)
            self.assertEqual(old.exception.code, "SCHEMA_INCOMPATIBLE")


if __name__ == "__main__":
    unittest.main()
