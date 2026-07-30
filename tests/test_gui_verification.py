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
from PyQt6.QtWidgets import QApplication, QLabel, QProgressBar

from bankflow_v2.models import Transaction
from bankflow_v2.case_context import (
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)
from bankflow_v2.result_export import (
    build_bankflow_result,
    rebuild_business_context_result,
)
from bankflow_v2.verification_worker import VerificationWorker
from gui_verification import (
    AttentionItemCard,
    CandidateCategoryButton,
    CasePreparationPage,
    CaseDashboardPage,
    EvidencePanel,
    KeyFindingCard,
    KeyMetricsPanel,
    ModuleDetailPage,
    ModuleSummaryHeader,
    ModuleSummaryPage,
    PagedTable,
    ProcessingPage,
    ResultListModel,
    SummaryMetric,
    TransactionListPanel,
    VerificationWorkspace,
    WelcomePage,
)
from gui_verification_app import (
    MANUAL_CASE_CONTEXT_FILENAME,
    VerificationMainWindow,
    apply_workbench_palette,
    load_manual_case_context,
    save_manual_case_context,
)


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

    def test_business_table_keeps_deterministic_rows_when_ai_is_unavailable(self):
        transactions = [sensitive_transaction(1), sensitive_transaction(2)]
        result = build_bankflow_result(transactions, ai_config={})
        observation = next(
            item
            for item in result["result"]["observations"]
            if item.get("observation_type") == "ai_business_relevance_candidates"
        )
        observation["value"].update(
            {
                "available": False,
                "reason": "ai_data_authorization_missing",
                "deterministic_candidates": [
                    {
                        "transaction_id": "tx:gui:1",
                        "classification": "directly_related",
                        "decision_source": "deterministic_exact_match",
                        "reason": "可靠字段直接命中申报单位。",
                        "used_fields": ["counterparty_name"],
                    }
                ],
                "ai_candidates": [],
                "deterministic_non_business_candidates": [
                    {
                        "transaction_id": "tx:gui:2",
                        "classification": "no_relation_evidence",
                        "evidence_strength": "none",
                        "decision_source": "deterministic_non_business_rule",
                        "reason": "本地确定性规则排除。",
                        "used_fields": ["purpose"],
                    }
                ],
            }
        )
        detail = ModuleDetailPage()
        detail.set_result(result)
        detail.set_module("business", "经营关联摘要")

        model = detail.business_table.model
        self.assertIs(detail.tables.currentWidget(), detail.business_table)
        self.assertEqual(model.total_count(), 1)
        self.assertEqual(model.transaction_id_at(0), "tx:gui:1")
        self.assertEqual(
            model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole),
            "确定性文字/名称候选",
        )
        self.assertIn("本次分析未获得 GUI 明确授权", detail.business_notice.text())
        self.assertIn("已有确定性结果仍单独展示", detail.business_notice.text())
        self.assertIn("确定性排除 1 项", detail.business_notice.text())

    def test_business_table_distinguishes_accepted_ai_observation(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        observation = next(
            item
            for item in result["result"]["observations"]
            if item.get("observation_type") == "ai_business_relevance_candidates"
        )
        observation["value"].update(
            {
                "available": True,
                "reason": "",
                "deterministic_candidates": [],
                "ai_candidates": [
                    {
                        "transaction_id": "tx:gui:1",
                        "classification": "possibly_related",
                        "evidence_strength": "medium",
                        "decision_source": "ai_model",
                        "reason": "可靠用途文字与已确认经营内容可能相关。",
                        "used_fields": ["purpose"],
                    }
                ],
                "deterministic_non_business_candidates": [],
            }
        )
        model = ResultListModel("business")
        model.set_result(result)

        self.assertEqual(model.total_count(), 1)
        self.assertEqual(
            model.data(model.index(0, 0), Qt.ItemDataRole.DisplayRole),
            "AI 观察",
        )
        self.assertEqual(
            model.data(model.index(0, 1), Qt.ItemDataRole.DisplayRole),
            "可能关联",
        )
        self.assertEqual(
            model.data(model.index(0, 2), Qt.ItemDataRole.DisplayRole),
            "中",
        )

    def test_business_row_opens_indexed_transaction_evidence(self):
        result = build_bankflow_result(
            [sensitive_transaction(1)],
            case_context={
                "search_context": {
                    "work_units": ["甲公司"],
                    "declared_industries": [],
                },
                "business_context": {
                    "ai_business_relevance_eligible": False,
                    "confirmation_reason": "company_name_only",
                    "confirmation_prompt": (
                        "请人工确认客户实际主要经营内容和主要产品或服务。"
                    ),
                },
            },
            ai_config={},
        )
        workspace = VerificationWorkspace()
        workspace.set_result(result, "测试案例")

        workspace.open_module("business")
        self.assertIs(
            workspace.case_content_pages.currentWidget(),
            workspace.module_summary_page,
        )
        workspace.module_summary_page.choice_buttons[
            ("business", "positive")
        ].click()
        self.assertGreater(workspace.business_table.model.total_count(), 0)
        workspace.business_table._clicked(
            workspace.business_table.model.index(0, 0)
        )

        self.assertFalse(workspace.evidence_panel.isHidden())
        self.assertIn("来源文件：sample.pdf", workspace.evidence_panel.details.toPlainText())

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
        self.assertIs(workspace.main_pages.currentWidget(), workspace.current_case_page)
        self.assertIs(
            workspace.case_content_pages.currentWidget(),
            workspace.dashboard_page,
        )
        self.assertFalse(workspace.evidence_panel.isVisible())
        self.assertTrue(workspace.navigation_by_route["case"].isEnabled())

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
                "当前案件",
                "历史案件",
                "设置",
            ],
        )
        self.assertNotIn("分析结果", navigation)
        self.assertFalse(workspace.navigation_by_route["case"].isEnabled())
        self.assertFalse(hasattr(workspace.welcome_page, "settings_button"))

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

    def test_dashboard_uses_four_combined_cards_and_compact_amounts(self):
        result = build_bankflow_result(
            [
                Transaction(
                    transaction_time=datetime(2026, 1, 2, 9, 30),
                    income=Decimal("24590800.00"),
                    balance=Decimal("100800.00"),
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

        self.assertEqual(
            list(dashboard.module_cards),
            [
                "verification_declaration",
                "purchase_business",
                "funds_balance",
                "counterparty",
            ],
        )
        self.assertEqual(len(dashboard.module_cards), 4)
        self.assertNotIn("evidence", dashboard.module_cards)
        self.assertEqual(
            dashboard.metrics["income_sum"].value_label.text(),
            "2459.08万",
        )
        self.assertEqual(
            dashboard.metrics["income_sum"].value_label.toolTip(),
            "24,590,800.00 元",
        )
        self.assertEqual(dashboard.header.title.text(), "韩鹏飞")
        self.assertEqual(dashboard.key_metrics_panel._columns, 3)
        dashboard.resize(800, 900)
        dashboard.show()
        self.app.processEvents()
        self.assertEqual(dashboard._columns, 1)
        dashboard.resize(1200, 900)
        self.app.processEvents()
        self.assertEqual(dashboard._columns, 2)
        dashboard.close()
        responsive_panel = KeyMetricsPanel()
        responsive_panel.resize(1400, 176)
        responsive_panel.show()
        self.app.processEvents()
        self.assertEqual(responsive_panel._columns, 6)
        responsive_panel.resize(560, 176)
        self.app.processEvents()
        self.assertEqual(responsive_panel._columns, 2)
        responsive_panel.close()
        card_text = [
            label.text()
            for card in dashboard.module_cards.values()
            for label in card.findChildren(QLabel)
        ]
        self.assertFalse(any("ANALYSIS" in text for text in card_text))
        self.assertEqual(dashboard.life_status.text(), "生活轨迹：当前未分析")
        self.assertEqual(dashboard.vehicle_status.text(), "用车信息：当前未分析")
        self.assertIn("笔交易已建立唯一索引", dashboard.evidence_summary.detail_label.text())
        self.assertIn("条有效证据引用", dashboard.evidence_summary.detail_label.text())
        self.assertIn(
            "余额日期：2026-01-02",
            dashboard.module_cards["funds_balance"].body_label.text(),
        )

    def test_dashboard_business_card_surfaces_deterministic_count_when_ai_is_off(self):
        result = build_bankflow_result(
            [sensitive_transaction(1)],
            case_context={
                "search_context": {
                    "work_units": ["甲公司"],
                    "declared_industries": [],
                },
                "business_context": {
                    "ai_business_relevance_eligible": False,
                    "confirmation_reason": "company_name_only",
                    "confirmation_prompt": (
                        "请人工确认客户实际主要经营内容和主要产品或服务。"
                    ),
                },
            },
            ai_config={},
        )
        dashboard = CaseDashboardPage()

        dashboard.set_result(result, "测试案例")

        card = dashboard.module_cards["purchase_business"]
        self.assertIn("工作单位对照：直接命中", card.body_label.text())
        self.assertIn("经营内容对照：未提供申报项", card.body_label.text())
        self.assertIn("经营上下文：待人工补充", card.body_label.text())
        self.assertIn("确定性文字/企业名称候选", card.body_label.text())
        self.assertIn("未执行完整行业语义判断", card.status_label.text())
        self.assertFalse(card.secondary_button.isHidden())
        self.assertEqual(card.open_button.text(), "查看概要 →")

    def test_dashboard_restores_confirmed_business_context_without_second_model(self):
        extracted = build_case_context(
            "测试案例",
            [
                {
                    "source_ref": "客户资料.txt",
                    "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                    "text": "工作单位全称：甲公司",
                }
            ],
            business_confirmation={
                "confirmation_status": "confirmed",
                "confirmed_primary_business": "食品销售",
                "confirmed_products_or_services": "预包装食品",
            },
        )
        result = build_bankflow_result(
            [sensitive_transaction(1)],
            case_context=extracted,
            ai_config={},
        )
        manual = {
            "manual_confirmation": {
                "confirmation_status": "confirmed",
                "confirmed_primary_business": "食品销售",
                "confirmed_products_or_services": "预包装食品",
            }
        }
        dashboard = CaseDashboardPage()

        dashboard.set_result(
            result,
            "测试案例",
            case_context=extracted,
            manual_context=manual,
        )

        card = dashboard.module_cards["purchase_business"]
        self.assertIn("经营上下文：已人工确认", card.body_label.text())
        self.assertIn("经营内容：食品销售", card.body_label.text())
        self.assertTrue(card.secondary_button.isHidden())

    def test_dashboard_header_attention_and_common_summary_components(self):
        result = build_bankflow_result(
            [sensitive_transaction(1)],
            ai_config={},
        )
        questions = next(
            item
            for item in result["result"]["observations"]
            if item.get("observation_type") == "manual_verification_questions"
        )["value"]["questions"]
        self.assertTrue(questions)
        questions[:] = [
            {
                **questions[0],
                "question_id": f"question:dashboard:{index}",
            }
            for index in range(6)
        ]
        dashboard = CaseDashboardPage()
        attention_opened = []
        dashboard.attentionRequested.connect(
            lambda: attention_opened.append(True)
        )

        dashboard.set_result(result, "测试案例")

        self.assertIn("资料覆盖期间：", dashboard.header.subtitle.text())
        self.assertIn("资料来源：1 个", dashboard.header.facts.text())
        self.assertIn("交易笔数：1 笔", dashboard.header.facts.text())
        self.assertEqual(dashboard.completed_badge.text(), "已完成")
        self.assertEqual(dashboard.findChildren(QProgressBar), [])
        self.assertEqual(len(dashboard.attention_cards), 1)
        self.assertTrue(
            all(
                isinstance(card, AttentionItemCard)
                for card in dashboard.attention_cards
            )
        )
        first = dashboard.attention_cards[0]
        self.assertIn("1 项待核实", first.module_badge.text())
        self.assertIn("客观触发事实：", first.fact_label.text())
        self.assertIn("建议核实内容：", first.verification_label.text())
        self.assertIn("对应证据：", first.evidence_label.text())
        self.assertEqual(first.availability_badge.text(), "数据可用")
        first.open_button.click()
        self.assertEqual(attention_opened, [True])
        self.assertNotIn(
            "重点：",
            dashboard.module_cards[
                "verification_declaration"
            ].body_label.text(),
        )
        self.assertNotIn(
            "最值得注意",
            dashboard.module_cards["funds_balance"].body_label.text(),
        )
        self.assertTrue(
            all(
                isinstance(metric, SummaryMetric)
                for metric in dashboard.metrics.values()
            )
        )
        self.assertTrue(
            all(
                isinstance(card, KeyFindingCard)
                for card in dashboard.module_cards.values()
            )
        )

        workspace = VerificationWorkspace()
        workspace.set_result(result, "测试案例")
        workspace.dashboard_page.module_cards[
            "verification_declaration"
        ].open_button.click()
        self.assertIsInstance(
            workspace.module_summary_page.summary_header,
            ModuleSummaryHeader,
        )
        self.assertTrue(
            all(
                isinstance(button, CandidateCategoryButton)
                for button in workspace.module_summary_page.choice_buttons.values()
            )
        )
        workspace.navigate("dashboard")
        workspace.dashboard_page.attention_cards[0].open_button.click()
        self.assertIs(
            workspace.case_content_pages.currentWidget(),
            workspace.transaction_list_panel,
        )
        self.assertEqual(
            workspace.transaction_list_panel.title.text(),
            "人工核实",
        )

    def test_case_preparation_requires_primary_business_when_context_is_missing(self):
        context = build_case_context(
            "测试案例",
            [
                {
                    "source_ref": "客户资料.txt",
                    "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                    "text": "工作单位全称：甲公司",
                }
            ],
        )
        page = CasePreparationPage()
        payloads = []
        page.confirmed.connect(payloads.append)
        page.set_context(context)
        page.ai_enabled.setChecked(True)
        page.resize(1200, 700)
        page.show()
        self.app.processEvents()

        self.assertEqual(page.case_name.text(), "测试案例")
        self.assertIn("只有工作单位名称", page.context_status.text())
        self.assertIn("实际主要经营内容", page.missing_information.text())
        self.assertIn("客户资料.txt", page.source_text.toPlainText())
        self.assertGreater(
            page.form_card.geometry().left(),
            page.extracted_card.geometry().left(),
        )
        self.assertLessEqual(
            page.ai_scope.geometry().bottom(),
            page.form_card.contentsRect().bottom(),
        )
        self.assertGreaterEqual(
            page.ai_scope.height(),
            page.ai_scope.minimumHeight(),
        )
        page.confirm_button.click()
        self.assertEqual(payloads, [])
        self.assertIn("实际主要经营内容", page.error_label.text())
        self.assertFalse(page.error_label.isHidden())
        self.assertTrue(page.primary_business.property("invalid"))

        page.primary_business.setText("环保工程")
        page.products_services.setText("环境治理服务")
        page.confirm_button.click()
        self.assertIn("确认人", page.error_label.text())
        self.assertTrue(page.confirmed_by.property("invalid"))
        self.assertTrue(page.confirmed_by.hasFocus())
        page.confirmed_by.setText("调查员A")
        page.confirm_button.click()
        self.assertEqual(payloads[0]["confirmation_status"], "confirmed")
        self.assertEqual(payloads[0]["confirmed_by"], "调查员A")
        self.assertTrue(payloads[0]["enable_ai_business_analysis"])
        page.close()

    def test_manual_case_context_is_separate_and_restorable(self):
        context = build_case_context(
            "测试案例",
            [
                {
                    "source_ref": "客户资料.txt",
                    "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                    "text": "工作单位全称：甲公司",
                }
            ],
        )
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            original = case_dir / "客户资料.txt"
            original.write_text("工作单位全称：甲公司", encoding="utf-8")
            record = save_manual_case_context(
                case_dir,
                context,
                {
                    "confirmed_primary_business": "环保工程",
                    "confirmed_products_or_services": "环境治理服务",
                    "confirmation_note": "现场确认",
                    "confirmation_status": "confirmed",
                    "confirmed_by": "调查员A",
                    "enable_ai_business_analysis": False,
                },
            )

            restored = load_manual_case_context(case_dir)

            self.assertEqual(original.read_text(encoding="utf-8"), "工作单位全称：甲公司")
            self.assertTrue((case_dir / MANUAL_CASE_CONTEXT_FILENAME).exists())
            self.assertEqual(restored, record)
            self.assertEqual(restored["confirmed_by"], "调查员A")
            self.assertTrue(restored["confirmed_at"])
            self.assertIn("original_extracted_information", restored)
            self.assertFalse(restored["enable_ai_business_analysis"])

    def test_scoped_business_rebuild_preserves_original_transactions(self):
        transaction = sensitive_transaction(1)
        initial_context = build_case_context(
            "测试案例",
            [
                {
                    "source_ref": "客户资料.txt",
                    "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                    "text": "工作单位全称：甲公司",
                }
            ],
        )
        result = build_bankflow_result(
            [transaction],
            case_context=initial_context,
            ai_config={},
        )
        original_records = json.loads(
            json.dumps(result["result"]["original_transactions"])
        )
        confirmed_context = build_case_context(
            "测试案例",
            [
                {
                    "source_ref": "客户资料.txt",
                    "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                    "text": "工作单位全称：甲公司",
                }
            ],
            business_confirmation={
                "confirmed_primary_business": "环保工程",
                "confirmed_products_or_services": "环境治理服务",
                "confirmation_note": "现场确认",
                "confirmation_status": "confirmed",
            },
        )

        rebuilt = rebuild_business_context_result(
            result,
            [transaction],
            confirmed_context,
            ai_config={},
        )

        self.assertEqual(
            rebuilt["result"]["original_transactions"],
            original_records,
        )
        business = next(
            item
            for item in rebuilt["result"]["observations"]
            if item.get("observation_type") == "ai_business_relevance_candidates"
        )
        self.assertEqual(
            business["value"]["reason"],
            "ai_data_authorization_missing",
        )

    def test_ai_runtime_is_never_loaded_without_gui_opt_in(self):
        window = VerificationMainWindow()
        with patch(
            "bankflow_v2.deepseek_adapter.load_deepseek_runtime",
            return_value=({"enabled": True}, object()),
        ) as mocked:
            config, evaluator = window._explicit_ai_runtime(False)
            self.assertEqual(config, {})
            self.assertIsNone(evaluator)
            mocked.assert_not_called()

            window._explicit_ai_runtime(True, "session-secret")
            mocked.assert_called_once()
            self.assertEqual(
                mocked.call_args.args[0]["BANKFLOW_AI_API_KEY"],
                "session-secret",
            )

    def test_new_case_stops_on_preparation_before_pdf_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            (case_dir / "客户资料.txt").write_text(
                "工作单位全称：甲公司",
                encoding="utf-8",
            )
            (case_dir / "流水.pdf").write_bytes(b"%PDF-placeholder")
            window = VerificationMainWindow()

            window.start_case_directory(case_dir)

            self.assertIsNone(window.worker)
            self.assertIs(
                window.workspace.main_pages.currentWidget(),
                window.workspace.preparation_page,
            )
            self.assertIn(
                "只有工作单位名称",
                window.workspace.preparation_page.context_status.text(),
            )

    def test_preparation_confirmation_persists_before_analysis(self):
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            (case_dir / "客户资料.txt").write_text(
                "工作单位全称：甲公司",
                encoding="utf-8",
            )
            (case_dir / "流水.pdf").write_bytes(b"%PDF-placeholder")
            window = VerificationMainWindow()
            window.start_case_directory(case_dir)
            page = window.workspace.preparation_page
            page.primary_business.setText("环保工程")
            page.products_services.setText("环境治理服务")
            page.confirmed_by.setText("调查员A")

            with patch.object(window, "_start_full_analysis") as start:
                page.confirm_button.click()

            start.assert_called_once()
            context, ai_enabled, ai_api_key = start.call_args.args
            self.assertFalse(ai_enabled)
            self.assertEqual(ai_api_key, "")
            self.assertTrue(
                context["business_context"]["ai_business_relevance_eligible"]
            )
            record = load_manual_case_context(case_dir)
            self.assertEqual(record["confirmed_by"], "调查员A")
            self.assertEqual(
                record["manual_confirmation"][
                    "confirmed_primary_business"
                ],
                "环保工程",
            )

    def test_preparation_ai_opt_in_reaches_analysis_start(self):
        with tempfile.TemporaryDirectory() as directory:
            case_dir = Path(directory)
            (case_dir / "客户资料.txt").write_text(
                "工作单位全称：甲公司",
                encoding="utf-8",
            )
            (case_dir / "流水.pdf").write_bytes(b"%PDF-placeholder")
            window = VerificationMainWindow()
            window.start_case_directory(case_dir)
            page = window.workspace.preparation_page
            page.primary_business.setText("食品销售")
            page.confirmed_by.setText("调查员A")
            page.ai_enabled.setChecked(True)
            page.ai_api_key.setText("session-secret")

            with patch.object(window, "_start_full_analysis") as start:
                page.confirm_button.click()

            start.assert_called_once()
            self.assertTrue(start.call_args.args[1])
            self.assertEqual(start.call_args.args[2], "session-secret")
            saved_text = (
                case_dir / MANUAL_CASE_CONTEXT_FILENAME
            ).read_text(encoding="utf-8")
            self.assertNotIn("session-secret", saved_text)
            self.assertNotIn("ai_api_key", saved_text)
            self.assertTrue(
                load_manual_case_context(case_dir)[
                    "enable_ai_business_analysis"
                ]
            )

    def test_preparation_restores_legacy_ai_opt_in_field(self):
        context = build_case_context(
            "测试案例",
            [
                {
                    "source_ref": "客户资料.txt",
                    "source_role": SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
                    "text": "工作单位全称：甲公司",
                }
            ],
        )
        page = CasePreparationPage()
        page.set_context(
            context,
            {
                "case_id": "测试案例",
                "manual_confirmation": {
                    "confirmation_status": "confirmed",
                    "confirmed_primary_business": "食品销售",
                },
                "confirmed_by": "调查员A",
                "ai_business_assistance_enabled": True,
            },
        )

        self.assertTrue(page.ai_enabled.isChecked())
        self.assertEqual(
            page.missing_information.text(),
            "无必填缺口（已恢复人工确认）",
        )

    def test_hidden_analysis_route_redirects_to_dashboard(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        workspace = VerificationWorkspace()
        workspace.set_result(result, "测试案例")

        workspace.navigate("analysis")

        self.assertIs(workspace.main_pages.currentWidget(), workspace.current_case_page)
        self.assertIs(
            workspace.case_content_pages.currentWidget(),
            workspace.dashboard_page,
        )
        self.assertTrue(workspace.navigation_by_route["case"].isChecked())

    def test_dashboard_cards_and_evidence_summary_open_shared_detail_page(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        workspace = VerificationWorkspace()
        workspace.set_result(result, "测试案例")

        workspace.dashboard_page.module_cards[
            "verification_declaration"
        ].open_button.click()
        self.assertIs(
            workspace.case_content_pages.currentWidget(),
            workspace.module_summary_page,
        )
        self.assertEqual(
            workspace.module_summary_page.title.text(),
            "核实与申报概要",
        )
        self.assertFalse(workspace.evidence_panel.isVisible())
        workspace.module_summary_page.choice_buttons[
            ("sensitive", "all")
        ].click()
        self.assertIs(
            workspace.case_content_pages.currentWidget(),
            workspace.transaction_list_panel,
        )
        self.assertEqual(workspace.transaction_list_panel.title.text(), "敏感交易")

        workspace.navigate("dashboard")
        workspace.dashboard_page.evidence_summary.open_button.click()
        self.assertIs(
            workspace.case_content_pages.currentWidget(),
            workspace.module_summary_page,
        )
        self.assertEqual(workspace.module_summary_page.title.text(), "证据中心")
        self.assertIn(
            "证据中心",
            workspace.module_summary_page.breadcrumb_label.text(),
        )
        self.assertFalse(workspace.evidence_panel.isVisible())

    def test_module_detail_reuses_manual_and_sensitive_paged_tables(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        detail = ModuleDetailPage()
        detail.set_result(result)

        detail.set_module("manual", "人工核实摘要")
        self.assertIs(detail.tables.currentWidget(), detail.manual_table)
        self.assertIn("当前案件 > 人工核实", detail.breadcrumb_label.text())
        detail.set_module("sensitive", "敏感交易摘要")
        self.assertIs(detail.tables.currentWidget(), detail.sensitive_table)
        self.assertEqual(detail.sensitive_table.model.total_count(), 1)

    def test_top_navigation_and_combined_cards_build_three_level_skeleton(self):
        result = build_bankflow_result([sensitive_transaction(1)], ai_config={})
        workspace = VerificationWorkspace()
        workspace.set_result(result, "测试案例")

        self.assertIsInstance(workspace.module_summary_page, ModuleSummaryPage)
        self.assertIsInstance(
            workspace.transaction_list_panel,
            TransactionListPanel,
        )
        self.assertFalse(hasattr(workspace, "case_tab_buttons"))
        workspace.dashboard_page.module_cards[
            "purchase_business"
        ].open_button.click()
        self.assertIs(
            workspace.case_content_pages.currentWidget(),
            workspace.module_summary_page,
        )
        self.assertEqual(
            workspace.module_summary_page.title.text(),
            "购车与经营概要",
        )
        preparation_requests = []
        workspace.businessPreparationRequested.connect(
            lambda: preparation_requests.append(True)
        )
        workspace.module_summary_page.business_prepare_button.click()
        self.assertEqual(preparation_requests, [True])
        self.assertEqual(
            workspace.dashboard_page.life_status.text(),
            "生活轨迹：当前未分析",
        )
        self.assertEqual(
            workspace.dashboard_page.vehicle_status.text(),
            "用车信息：当前未分析",
        )
        self.assertFalse(workspace.evidence_panel.isVisible())

    def test_business_default_filter_hides_none_and_exposes_all_categories(self):
        transactions = [
            sensitive_transaction(index)
            for index in range(1, 6)
        ]
        result = build_bankflow_result(transactions, ai_config={})
        observation = next(
            item
            for item in result["result"]["observations"]
            if item.get("observation_type") == "ai_business_relevance_candidates"
        )
        observation["value"].update(
            {
                "available": True,
                "reason": "",
                "deterministic_candidates": [
                    {
                        "transaction_id": "tx:gui:1",
                        "classification": "directly_related",
                        "evidence_strength": "strong",
                        "reason": "确定性正向。",
                    }
                ],
                "ai_candidates": [
                    {
                        "transaction_id": "tx:gui:2",
                        "classification": "possibly_related",
                        "evidence_strength": "medium",
                        "reason": "AI 中强度候选。",
                    },
                    {
                        "transaction_id": "tx:gui:3",
                        "classification": "undetermined",
                        "evidence_strength": "none",
                        "reason": "待人工判断。",
                    },
                    {
                        "transaction_id": "tx:gui:5",
                        "classification": "no_relation_evidence",
                        "evidence_strength": "none",
                        "reason": "AI 未发现关联依据。",
                    },
                ],
                "deterministic_non_business_candidates": [
                    {
                        "transaction_id": "tx:gui:4",
                        "classification": "no_relation_evidence",
                        "evidence_strength": "none",
                        "reason": "确定性排除。",
                    }
                ],
            }
        )
        table = PagedTable("business")
        table.set_result(result)

        self.assertEqual(table.model.total_count(), 2)
        displayed_sources = {
            table.model.data(table.model.index(row, 0))
            for row in range(table.model.rowCount())
        }
        self.assertNotIn("确定性排除", displayed_sources)
        table.set_view_filter("manual")
        self.assertEqual(table.model.total_count(), 1)
        table.set_view_filter("excluded")
        self.assertEqual(table.model.total_count(), 2)
        table.set_view_filter("all")
        self.assertEqual(table.model.total_count(), 5)

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
