from __future__ import annotations

import os
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from bankflow_v2.models import Transaction
from bankflow_v2.result_export import build_bankflow_result
from bankflow_v2.verification_worker import VerificationWorker
from gui_verification import EvidencePanel, ResultListModel, VerificationWorkspace


def sensitive_transaction(index: int) -> Transaction:
    return Transaction(
        transaction_time=datetime(2026, 1, 2, 9, 30),
        expense=Decimal("1000.00"),
        balance=Decimal("2234.00"),
        source_file="sample.pdf",
        source_file_id="sha256:sample",
        transaction_id=f"tx:gui:{index}",
        page_no=2,
        row_no=index + 1,
        evidence_locator=f"page=2;row={index + 1}",
        counterparty_name="甲公司",
        counterparty_account="6222021234567890",
        purpose="信用卡套现还款",
        raw_text="甲公司 13812345678 信用卡套现还款",
        raw_fields=["6222021234567890", "甲公司", "信用卡套现还款"],
        field_confidence={
            "counterparty_name": 1.0,
            "counterparty_account": 1.0,
            "purpose": 1.0,
        },
    )


class GuiVerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_model_keeps_result_reference_and_pages_rows(self):
        result = build_bankflow_result(
            [sensitive_transaction(index) for index in range(55)],
            ai_config={},
        )
        model = ResultListModel("sensitive", page_size=50)

        model.set_result(result)

        self.assertIs(model._result, result)
        self.assertIsInstance(model._row_indices, range)
        self.assertEqual(model.rowCount(), 50)
        self.assertEqual(model.page_count(), 2)
        model.set_page(1)
        self.assertEqual(model.rowCount(), 5)

    def test_sensitive_table_exposes_transaction_id_without_transaction_copy(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        model = ResultListModel("sensitive")
        model.set_result(result)

        self.assertEqual(model.transaction_id_at(0), "tx:gui:1")
        self.assertEqual(
            model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole),
            "候选命中",
        )

    def test_evidence_panel_uses_index_and_masks_sensitive_values(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        panel = EvidencePanel()

        panel.show_transaction(result, "tx:gui:1")
        text = panel.details.toPlainText()

        self.assertIn("来源文件：sample.pdf", text)
        self.assertIn("页码：2", text)
        self.assertIn("行号：2", text)
        self.assertIn("对手账号：•••• 7890", text)
        self.assertIn("甲公司", text)
        self.assertNotIn("13812345678", text)
        self.assertNotIn("6222021234567890", text)

    def test_workspace_accepts_schema_116_result(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        workspace = VerificationWorkspace()

        workspace.set_result(result, "测试案例")

        self.assertIs(workspace._result, result)
        self.assertEqual(workspace.header.title.text(), "测试案例")
        self.assertEqual(workspace.sensitive_table.model.total_count(), 1)
        self.assertEqual(workspace.progress.value(), 100)

    def test_worker_explicitly_disables_ai_runtime(self):
        class StubWorker(VerificationWorker):
            def _extract(self, path):
                return [sensitive_transaction(1)], ""

        captured = {}
        worker = StubWorker([Path("missing.xlsx")], case_context={"case_id": "case"})
        worker.finished.connect(
            lambda results, issues, result: captured.update(result=result)
        )
        from bankflow_v2.result_export import build_bankflow_result

        with patch(
            "bankflow_v2.result_export.build_bankflow_result",
            wraps=build_bankflow_result,
        ) as mocked:
            worker.run()

        self.assertIn("result", captured)
        self.assertEqual(mocked.call_args.kwargs["ai_config"], {})
        self.assertIsNone(mocked.call_args.kwargs["ai_evaluator"])


if __name__ == "__main__":
    unittest.main()
