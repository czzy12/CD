import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from bankflow_v2.models import StatementMetadata, Transaction, TransactionList
from bankflow_v2.result_export import build_bankflow_result, write_bankflow_json


def transaction() -> Transaction:
    return Transaction(
        transaction_time=datetime(2026, 7, 26, 10, 30),
        income=Decimal("100.00"),
        balance=Decimal("100.00"),
        bank="测试银行",
        page_no=2,
        row_no=5,
        raw_time="2026-07-26 10:30:00",
        raw_amount="100.00",
        raw_balance="100.00",
        raw_headers=["摘要"],
        raw_fields=["测试入账"],
        source_file="statement.pdf",
        source_file_id="sha256:source",
        evidence_locator="page=2;row=5",
        transaction_id="tx:source:transaction",
    )


class ResultExportTests(unittest.TestCase):
    def test_exports_only_original_transactions_with_evidence(self):
        row = transaction()
        transactions = TransactionList([row], metadata=StatementMetadata(account_name="张三", account_number="6222"))

        result = build_bankflow_result(transactions)
        exported = result["result"]["original_transactions"][0]

        self.assertEqual(result["schema_version"], "1.0")
        self.assertEqual(result["module"], "bankflow")
        self.assertEqual(result["analysis_source"], "original_transactions")
        self.assertEqual(result["statement_metadata"]["account_name"], "张三")
        self.assertEqual(result["source_files"], [{"source_file_id": "sha256:source", "source_file": "statement.pdf", "transaction_count": 1}])
        self.assertEqual(exported["transaction_id"], "tx:source:transaction")
        self.assertEqual(exported["evidence_locator"], "page=2;row=5")
        self.assertEqual(exported["original"]["raw_fields"], ["测试入账"])
        self.assertEqual(exported["income"], "100.00")
        self.assertFalse(result["manual_review"]["required"])

    def test_marks_missing_evidence_for_manual_review(self):
        row = transaction()
        row.transaction_id = ""
        row.source_file_id = ""

        result = build_bankflow_result([row])

        self.assertTrue(result["manual_review"]["required"])
        self.assertEqual(result["manual_review"]["items"][0]["reasons"], ["缺少交易 ID", "缺少来源文件 ID"])

    def test_writes_utf8_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = write_bankflow_json(build_bankflow_result([transaction()]), Path(directory) / "evidence.json")
            loaded = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(loaded["result"]["original_transactions"][0]["bank"], "测试银行")


if __name__ == "__main__":
    unittest.main()
