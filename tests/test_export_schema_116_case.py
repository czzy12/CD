import json
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bankflow_v2.models import Transaction
from bankflow_v2.result_export import build_bankflow_result
from tools.export_schema_116_case import (
    _run_formal_worker,
    export_case,
)


def _result() -> dict[str, object]:
    transactions = []
    for index in range(3):
        transactions.append(
            Transaction(
                transaction_time=datetime(2026, 7, 20 + index, 10, 30),
                income=Decimal("100.00"),
                balance=Decimal(str(100 * (index + 1))),
                bank="测试银行",
                page_no=1,
                row_no=index + 1,
                raw_time=f"2026-07-{20 + index} 10:30:00",
                raw_amount="100.00",
                raw_balance=str(100 * (index + 1)),
                raw_fields=["测试交易"],
                source_file="statement.xlsx",
                source_file_id="sha256:source",
                evidence_locator=f"sheet=1;row={index + 1}",
                transaction_id=f"tx:source:{index}",
            )
        )
    return build_bankflow_result(
        transactions,
        case_context={},
        ai_config={},
        ai_evaluator=None,
    )


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback

    def emit(self, *args) -> None:
        if self.callback:
            self.callback(*args)


class ExportSchema116CaseTests(unittest.TestCase):
    def test_export_uses_formal_result_writer_and_keeps_case_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case_dir = root / "case"
            case_dir.mkdir()
            source = case_dir / "statement.xlsx"
            source.write_bytes(b"fixture")
            output = root / "output" / "case.json"
            before = source.read_bytes()
            source_result = SimpleNamespace(status="已纳入", transactions=[object()])

            with patch(
                "tools.export_schema_116_case._run_formal_worker",
                return_value=([source_result], [], _result()),
            ):
                summary = export_case(case_dir, output)

            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], "1.17")
            self.assertEqual(payload["module"], "bankflow")
            self.assertEqual(summary["transaction_count"], 3)
            self.assertEqual(len(summary["checked_transaction_ids"]), 3)
            self.assertEqual(source.read_bytes(), before)

    def test_rejects_output_inside_customer_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            (case_dir / "statement.xlsx").write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "不得位于客户资料目录"):
                export_case(case_dir, case_dir / "result.json")

    def test_rejects_non_json_output(self):
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory) / "case"
            case_dir.mkdir()
            (case_dir / "statement.xlsx").write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, r"\.json"):
                export_case(case_dir, Path(directory) / "result.txt")

    def test_worker_is_called_with_ai_disabled(self):
        captured = {}

        class FakeWorker:
            def __init__(self, paths, **kwargs):
                captured.update(kwargs)
                self.finished = _Signal()
                self.failed = _Signal()

            def run(self):
                self.finished.emit([], [], _result())

        with patch(
            "tools.export_schema_116_case.VerificationWorker",
            FakeWorker,
        ):
            _run_formal_worker([Path("statement.xlsx")], {})

        self.assertEqual(captured["ai_config"], {})
        self.assertIsNone(captured["ai_evaluator"])


if __name__ == "__main__":
    unittest.main()
