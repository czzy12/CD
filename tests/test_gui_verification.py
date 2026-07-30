from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication

from bankflow_v2.models import Transaction
from bankflow_v2.result_export import build_bankflow_result
from bankflow_v2.verification_worker import VerificationWorker
from gui_verification import (
    CaseDashboardPage,
    EvidencePanel,
    ModuleDetailPage,
    PagedTable,
    ProcessingPage,
    ResultListModel,
    VerificationWorkspace,
    WelcomePage,
)
from gui_verification_app import VerificationMainWindow, apply_workbench_palette


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
        self.assertNotIn("交易ID", model.headers)
        self.assertEqual(model.columnCount(), 7)
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
        self.assertNotIn("交易ID：", text)
        self.assertNotIn("证据定位：", text)
        self.assertNotIn("原始字段", text)

        panel.expand_button.setChecked(True)
        expanded = panel.details.toPlainText()

        self.assertIn("交易ID：", expanded)
        self.assertIn("证据定位：page=2;row=2", expanded)
        self.assertIn("引用状态：resolved", expanded)
        self.assertIn("原始字段（已脱敏）", expanded)

    def test_evidence_panel_explains_that_selection_happens_in_lists(self):
        panel = EvidencePanel()

        text = panel.details.toPlainText()

        self.assertIn("不是候选列表", text)
        self.assertIn("点击带交易ID的表格行", text)

    def test_clicking_item_without_transaction_id_shows_reason(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        manual_observation = next(
            item
            for item in result["result"]["observations"]
            if item.get("observation_type") == "manual_verification_questions"
        )
        manual_observation["value"]["questions"] = [
            {
                "question_text": "请人工核实资料范围。",
                "trigger_reason": "当前事项没有单笔交易证据。",
                "evidence_transaction_ids": [],
            }
        ]
        table = PagedTable("manual")
        table.set_result(result)
        messages = []
        table.selectionUnavailable.connect(messages.append)

        table._clicked(table.model.index(0, 0))

        self.assertEqual(len(messages), 1)
        self.assertIn("没有直接关联的交易ID", messages[0])
        self.assertNotIn("交易ID", table.model.headers)
        self.assertEqual(table.model.columnCount(), 4)

    def test_workspace_accepts_schema_116_result(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        workspace = VerificationWorkspace()

        workspace.set_result(result, "测试案例")

        self.assertIs(workspace._result, result)
        self.assertEqual(workspace.header.title.text(), "测试案例")
        self.assertEqual(workspace.sensitive_table.model.total_count(), 1)
        self.assertEqual(workspace.progress.value(), 100)
        self.assertEqual(workspace.load_result_button.text(), "导入标准结果")
        self.assertIs(workspace.main_pages.currentWidget(), workspace.dashboard_page)
        self.assertFalse(workspace.evidence_panel.isVisible())

    def test_workspace_starts_on_welcome_without_empty_case_or_evidence(self):
        workspace = VerificationWorkspace()

        self.assertIsInstance(workspace.welcome_page, WelcomePage)
        self.assertIs(workspace.main_pages.currentWidget(), workspace.welcome_page)
        self.assertFalse(workspace.evidence_panel.isVisible())
        navigation = [button.text() for button in workspace.navigation_buttons]
        self.assertEqual(
            navigation,
            [
                "首页",
                "当前案件  ·  案件概览",
                "当前案件  ·  人工核实",
                "当前案件  ·  分析结果",
                "当前案件  ·  证据中心",
                "历史案件",
                "设置",
            ],
        )
        self.assertFalse(any("后续" in text for text in navigation))

    def test_processing_page_only_shows_cancel_while_running(self):
        page = ProcessingPage()

        self.assertTrue(page.cancel_button.isHidden())
        page.start("测试案例", 3)
        self.assertFalse(page.cancel_button.isHidden())
        page.set_progress(1, 3, "正在解析 sample.pdf")
        self.assertEqual(page.current_file.text(), "sample.pdf")
        self.assertEqual(page.file_count.text(), "1 / 3")
        page.stop("已完成")
        self.assertTrue(page.cancel_button.isHidden())

    def test_dashboard_uses_nine_summary_cards_and_compact_amounts(self):
        result = build_bankflow_result(
            [
                Transaction(
                    transaction_time=datetime(2026, 1, 2, 9, 30),
                    income=Decimal("24590800.00"),
                    source_file="sample.pdf",
                    source_file_id="sha256:sample",
                    transaction_id="tx:dashboard:1",
                    page_no=1,
                    row_no=1,
                    evidence_locator="page=1;row=1",
                )
            ],
            ai_config={},
        )
        dashboard = CaseDashboardPage()

        dashboard.set_result(result, "韩鹏飞")

        self.assertEqual(len(dashboard.module_cards), 9)
        self.assertEqual(
            dashboard.metrics["income_sum"].value_label.text(),
            "2459.08万",
        )
        self.assertEqual(
            dashboard.metrics["income_sum"].value_label.toolTip(),
            "24,590,800.00 元",
        )
        self.assertEqual(dashboard.header.title.text(), "韩鹏飞")

    def test_module_detail_reuses_manual_and_sensitive_paged_tables(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        detail = ModuleDetailPage()
        detail.set_result(result)

        detail.set_module("manual", "人工核实摘要")
        self.assertIs(detail.tables.currentWidget(), detail.manual_table)
        self.assertIn("案件概览 > 人工核实", detail.breadcrumb_label.text())
        detail.set_module("sensitive", "敏感交易摘要")
        self.assertIs(detail.tables.currentWidget(), detail.sensitive_table)
        self.assertEqual(detail.sensitive_table.model.total_count(), 1)

    def test_evidence_panel_supports_sequence_navigation(self):
        result = build_bankflow_result(
            [sensitive_transaction(1), sensitive_transaction(2)],
            ai_config={},
        )
        panel = EvidencePanel()

        panel.set_context(
            result,
            ["tx:gui:1", "tx:gui:2"],
            "tx:gui:1",
        )
        self.assertFalse(panel.previous_button.isEnabled())
        self.assertTrue(panel.next_button.isEnabled())
        panel.next_button.click()
        self.assertTrue(panel.previous_button.isEnabled())
        self.assertFalse(panel.next_button.isEnabled())
        self.assertIn("行号：3", panel.details.toPlainText())

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

    def test_open_existing_case_prefers_schema_result_without_worker(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        with tempfile.TemporaryDirectory() as directory:
            result_path = Path(directory) / "case-result.json"
            result_path.write_text(
                json.dumps(result, ensure_ascii=False),
                encoding="utf-8",
            )
            window = VerificationMainWindow()
            with patch(
                "gui_verification_app.QFileDialog.getExistingDirectory",
                return_value=directory,
            ):
                window.open_existing_case()

            self.assertIsNone(window.worker)
            self.assertEqual(
                window.workspace._result["schema_version"],
                "1.16",
            )
            self.assertEqual(
                window.workspace.header.title.text(),
                Path(directory).name,
            )

    def test_workbench_palette_overrides_system_dark_theme(self):
        dark = QPalette()
        dark.setColor(QPalette.ColorRole.Window, QColor("#1E1E1E"))
        self.app.setPalette(dark)

        apply_workbench_palette(self.app)

        palette = self.app.palette()
        self.assertEqual(
            palette.color(QPalette.ColorRole.Window).name().upper(),
            "#F3EDDF",
        )
        self.assertEqual(
            palette.color(QPalette.ColorRole.Base).name().upper(),
            "#FFF9EC",
        )


if __name__ == "__main__":
    unittest.main()
