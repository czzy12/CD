import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from bankflow_v2.evidence import attach_source_evidence, source_file_id
from bankflow_v2.models import Transaction
from bankflow_v2.pipeline import extract_transactions


def transaction(page_no: int, row_no: int) -> Transaction:
    return Transaction(
        transaction_time=datetime(2026, 7, 26, 10, 30),
        income=Decimal("100.00"),
        balance=Decimal("100.00"),
        bank="测试银行",
        page_no=page_no,
        row_no=row_no,
        raw_time="2026-07-26 10:30:00",
        raw_amount="100.00",
        raw_balance="100.00",
        raw_text="测试交易",
    )


class EvidenceTests(unittest.TestCase):
    def test_source_file_id_uses_content_not_file_name(self):
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.pdf"
            second = Path(directory) / "renamed.pdf"
            first.write_bytes(b"same source")
            second.write_bytes(b"same source")

            self.assertEqual(source_file_id(first), source_file_id(second))

    def test_attaches_stable_transaction_id_and_locator(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "statement.pdf"
            source.write_bytes(b"statement source")
            first = attach_source_evidence([transaction(2, 5)], source)[0]
            second = attach_source_evidence([transaction(2, 5)], source)[0]

            self.assertEqual(first.source_file, "statement.pdf")
            self.assertTrue(first.source_file_id.startswith("sha256:"))
            self.assertEqual(first.evidence_locator, "page=2;row=5")
            self.assertEqual(first.transaction_id, second.transaction_id)

    def test_different_rows_receive_different_transaction_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "statement.pdf"
            source.write_bytes(b"statement source")
            first, second = attach_source_evidence([transaction(1, 1), transaction(1, 2)], source)

            self.assertNotEqual(first.transaction_id, second.transaction_id)

    def test_pipeline_adds_evidence_after_bank_parser(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "statement.pdf"
            source.write_bytes(b"statement source")
            with patch("bankflow_v2.pipeline._extract_transactions", return_value=[transaction(3, 7)]):
                parsed = extract_transactions(str(source), "huaxia")

            self.assertEqual(parsed[0].source_file, "statement.pdf")
            self.assertEqual(parsed[0].evidence_locator, "page=3;row=7")
            self.assertTrue(parsed[0].transaction_id.startswith("tx:"))


if __name__ == "__main__":
    unittest.main()
