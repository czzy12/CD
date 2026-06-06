import sys
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

from PyQt6.QtCore import QDate, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bankflow_v2.adjustment import AdjustmentConfig, AdjustmentResult, apply_adjustments, parse_amount_wan
from bankflow_v2.income_proof_export import balance_wechat_summaries, flow_type as income_flow_type, write_income_proof_input
from bankflow_v2.summary import Issue, Summary, money, monthly_summaries, sort_transactions, summarize


SUPPORTED_INPUTS = {".pdf", ".xlsx", ".xlsm"}
DATE_RANGE_EMPTY_MESSAGE = "日期范围内没有流水"
SALARY_KEYWORDS = ("工资", "代发", "薪资", "薪酬", "奖金")
ACCOUNT_NAME_PATTERNS = (
    r"户名\s*(?:Account Name)?\s*[:：]\s*([^\s，,]+)",
    r"客户姓名\s*[:：]\s*([^\s，,]+)",
    r"账户名称\s*[:：]\s*([^\s，,]+)",
    r"户主\s*[:：]\s*([^\s，,]+)",
    r"Account Name\s*[:：]\s*([^\s，,]+)",
)
ACCOUNT_NO_PATTERNS = (
    r"客户账号\s*(?:Account No\.?|Account Number)?\s*[:：]?\s*([0-9][0-9\s-]{6,30}[0-9])",
    r"账号/卡号\s*(?:Account/Card No\.?)?\s*[:：]?\s*([0-9][0-9\s-]{6,30}[0-9])",
    r"Account/Card\s*No\.?\s*[:：]?\s*([0-9][0-9\s-]{6,30}[0-9])",
    r"账号\s*(?:Account No\.?|Account Number)?\s*[:：]?\s*([0-9][0-9\s-]{6,30}[0-9])",
    r"账户\s*(?:Account No\.?|Account Number)?\s*[:：]?\s*([0-9][0-9\s-]{6,30}[0-9])",
    r"卡号\s*[:：]?\s*([0-9][0-9\s-]{6,30}[0-9])",
    r"银行卡号\s*[:：]?\s*([0-9][0-9\s-]{6,30}[0-9])",
    r"Account\s*(?:No\.?|Number)\s*[:：]?\s*([0-9][0-9\s-]{6,30}[0-9])",
)


@dataclass
class FileResult:
    path: Path
    bank_id: str
    bank_label: str
    bank_confidence: int
    bank_reason: str
    summary: object
    transactions: list
    status: str
    message: str
    account_name: str = ""
    account_no: str = ""


@dataclass
class ConfidenceInfo:
    score: int
    level: str
    tone: str
    reason: str


class DropTable(QTableWidget):
    filesDropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        self.filesDropped.emit(paths)

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.StandardKey.Copy):
            self.copy_selection()
            return
        super().keyPressEvent(event)

    def copy_selection(self):
        ranges = self.selectedRanges()
        if not ranges:
            return

        lines: list[str] = []
        for selected in ranges:
            for row in range(selected.topRow(), selected.bottomRow() + 1):
                values = []
                for col in range(selected.leftColumn(), selected.rightColumn() + 1):
                    item = self.item(row, col)
                    values.append(item.text() if item else "")
                lines.append("\t".join(values))
        QApplication.clipboard().setText("\n".join(lines))


class DropWidget(QWidget):
    filesDropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        self.filesDropped.emit(paths)


class Worker(QThread):
    finished = pyqtSignal(list, list)
    progress = pyqtSignal(str)

    def __init__(self, paths: list[Path], start_date: datetime | None = None, end_date: datetime | None = None):
        super().__init__()
        self.paths = paths
        self.start_date = start_date
        self.end_date = end_date

    def _filter_transactions(self, transactions: list) -> list:
        if self.start_date is None and self.end_date is None:
            return transactions

        filtered = []
        for tx in transactions:
            if self.start_date is not None and tx.transaction_time < self.start_date:
                continue
            if self.end_date is not None and tx.transaction_time > self.end_date:
                continue
            filtered.append(tx)
        return filtered

    def _generic_pdf_label(self, detection) -> str:
        if detection.bank_id and detection.label not in ("未识别", ""):
            return f"{detection.label}（通用识别）"
        return "通用PDF识别"

    def _extract_with_fallback(self, path: Path, detection) -> tuple[list, str, str, bool]:
        if path.suffix.lower() in (".xlsx", ".xlsm"):
            from bankflow_v2.excel_input import extract_excel_transactions

            return extract_excel_transactions(str(path)), "Excel导入", "Excel文件导入", False

        if not detection.bank_id:
            from bankflow_v2.generic_pdf import extract_generic_pdf

            transactions = extract_generic_pdf(str(path))
            if transactions:
                return transactions, "通用PDF识别", f"{detection.reason}，已使用通用识别", True
            return [], "未识别", detection.reason, False

        if detection.bank_id in ("cmbc", "cib", "generic_pdf"):
            from bankflow_v2.pipeline import extract_transactions

            transactions = extract_transactions(str(path), detection.bank_id)
            return transactions, self._generic_pdf_label(detection), "已使用通用识别", True

        try:
            from bankflow_v2.pipeline import extract_transactions

            transactions = extract_transactions(str(path), detection.bank_id)
        except Exception as exc:
            from bankflow_v2.generic_pdf import extract_generic_pdf

            fallback = extract_generic_pdf(str(path))
            if fallback:
                return fallback, self._generic_pdf_label(detection), f"专用解析失败：{exc}；已使用通用识别", True
            raise

        if transactions:
            return transactions, detection.label, "", False

        from bankflow_v2.generic_pdf import extract_generic_pdf

        fallback = extract_generic_pdf(str(path))
        if fallback:
            return fallback, self._generic_pdf_label(detection), "专用解析未得到流水，已使用通用识别", True
        return transactions, detection.label, "未解析到流水", False

    def run(self):
        results: list[FileResult] = []
        all_issues: list[Issue] = []

        for path in self.paths:
            self.progress.emit(f"处理中: {path.name}")
            if path.suffix.lower() in (".xlsx", ".xlsm"):
                detection = type("Detection", (), {
                    "bank_id": "excel",
                    "label": "Excel导入",
                    "confidence": 100,
                    "reason": "Excel文件导入",
                })()
            else:
                from bankflow_v2.auto_detect import detect_bank_type

                detection = detect_bank_type(str(path))

            try:
                transactions, bank_label, fallback_message, used_generic = self._extract_with_fallback(path, detection)
                account_name = extract_account_name(path)
                account_no = extract_account_no(path)
                original_count = len(transactions)
                transactions = self._filter_transactions(transactions)
                for tx in transactions:
                    tx.source_file = path.name
                    tx.bank_label = bank_label
                    tx.flow_type = income_flow_type(detection.bank_id)
                file_summary = summarize(transactions, path.name)
                all_issues.extend(file_summary.issues)
                review_issues = [issue for issue in file_summary.issues if issue.level == "需复核"]
                if transactions and not review_issues:
                    status = "通用识别" if used_generic else "正常"
                else:
                    status = "需复核"
                message = fallback_message if transactions else (fallback_message or "未解析到流水")
                if original_count and not transactions:
                    message = DATE_RANGE_EMPTY_MESSAGE
                if message and (not transactions or review_issues):
                    all_issues.append(Issue("需复核", path.name, "", message))
                results.append(
                    FileResult(
                        path,
                        detection.bank_id,
                        bank_label,
                        detection.confidence,
                        detection.reason,
                        file_summary,
                        transactions,
                        status,
                        message,
                        account_name,
                        account_no,
                    )
                )
            except Exception as exc:
                issue = Issue("需复核", path.name, "", f"解析失败: {exc}")
                all_issues.append(issue)
                results.append(FileResult(path, detection.bank_id, detection.label, detection.confidence, detection.reason, summarize([]), [], "需复核", str(exc), extract_account_name(path), extract_account_no(path)))

        self.finished.emit(results, all_issues)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("银行流水 PDF/Excel 解析")
        self.resize(1280, 760)
        self.paths: list[Path] = []
        self.results: list[FileResult] = []
        self.issues: list[Issue] = []
        self.worker: Worker | None = None
        self.adjustment_result = AdjustmentResult()
        self.setAcceptDrops(True)

        self.summary_label = QLabel("选择 PDF 文件或文件夹后开始处理")
        self.summary_label.setObjectName("summaryLabel")
        self.summary_metrics = {
            "files": self.create_metric("文件", "0", "neutral"),
            "flows": self.create_metric("流水", "0", "neutral"),
            "income": self.create_metric("收入", "0 / 0.00", "income"),
            "expense": self.create_metric("支出", "0 / 0.00", "expense"),
            "issues": self.create_metric("异常", "0", "warning"),
            "confidence": self.create_metric("可信度", "-", "neutral"),
        }
        self.adjust_preview_label = QLabel("启用调整后显示预览")
        self.adjust_preview_label.setObjectName("adjustPreviewLabel")
        self.adjust_net_value = QLabel("0.00")
        self.adjust_net_value.setObjectName("adjustResultValue")
        self.adjust_check_value = QLabel("未启用")
        self.adjust_check_value.setObjectName("adjustResultValue")
        self.drop_hint_label = QLabel("拖入 PDF/Excel 文件，或点击选择文件\n支持多文件同时导入")
        self.drop_hint_label.setObjectName("dropHint")
        self.drop_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        add_files = QPushButton("选择文件")
        add_folder = QPushButton("选择文件夹")
        clear = QPushButton("清空")
        run = QPushButton("开始处理")
        export_income_json = QPushButton("佐证填写")
        run.setObjectName("primaryButton")
        export_income_json.setObjectName("exportButton")
        add_files.clicked.connect(self.add_files)
        add_folder.clicked.connect(self.add_folder)
        clear.clicked.connect(self.clear)
        run.clicked.connect(self.run)
        export_income_json.clicked.connect(self.export_income_proof_json)

        self.date_filter = QCheckBox("筛选日期")
        self.date_filter.setChecked(True)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.start_date.setFixedWidth(142)
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date.setFixedWidth(142)
        start_date, end_date = default_recent_month_range()
        self.start_date.setDate(start_date)
        self.end_date.setDate(end_date)

        date_filter_panel = QFrame()
        date_filter_panel.setObjectName("inlineFilterPanel")
        date_filter_layout = QHBoxLayout(date_filter_panel)
        date_filter_layout.setContentsMargins(14, 7, 14, 7)
        date_filter_layout.setSpacing(8)
        date_filter_layout.addWidget(self.date_filter)
        date_filter_layout.addWidget(QLabel("从"))
        date_filter_layout.addWidget(self.start_date)
        date_filter_layout.addWidget(QLabel("到"))
        date_filter_layout.addWidget(self.end_date)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        toolbar.addWidget(run)
        toolbar.addWidget(add_files)
        toolbar.addWidget(add_folder)
        toolbar.addWidget(clear)
        toolbar.addSpacing(14)
        toolbar.addWidget(date_filter_panel)
        toolbar.addStretch(1)
        toolbar.addWidget(export_income_json)

        self.income_adjust = QCheckBox("启用收入调整（微信）")
        self.balance_adjust = QCheckBox("启用收支平衡调整（个/公）")
        self.adjust_amount = QLineEdit()
        self.adjust_amount.setPlaceholderText("万元")
        self.adjust_start_month = QDateEdit()
        self.adjust_start_month.setCalendarPopup(True)
        self.adjust_start_month.setDisplayFormat("yyyy-MM")
        self.adjust_start_month.setFixedWidth(108)
        self.adjust_end_month = QDateEdit()
        self.adjust_end_month.setCalendarPopup(True)
        self.adjust_end_month.setDisplayFormat("yyyy-MM")
        self.adjust_end_month.setFixedWidth(108)
        self.adjust_start_month.setDate(start_date)
        self.adjust_end_month.setDate(end_date)
        self.random_adjust = QCheckBox("固定分配")

        self.income_adjust.stateChanged.connect(self.on_adjustment_mode_changed)
        self.balance_adjust.stateChanged.connect(self.on_adjustment_mode_changed)
        self.random_adjust.stateChanged.connect(self.refresh_adjustment)
        self.adjust_amount.textChanged.connect(self.refresh_adjustment)
        self.adjust_start_month.dateChanged.connect(self.refresh_adjustment)
        self.adjust_end_month.dateChanged.connect(self.refresh_adjustment)

        self.overview = DropTable()
        self.monthly = DropTable()
        self.details = DropTable()
        self.issue_table = DropTable()
        for table in (self.overview, self.monthly, self.details, self.issue_table):
            table.filesDropped.connect(self.add_paths)

        self.tabs = QTabWidget()
        self.monthly_tab_index = self.tabs.addTab(self.monthly, "月度统计")
        self.tabs.addTab(self.overview, "文件汇总")
        self.tabs.addTab(self.issue_table, "异常提示")

        central = DropWidget()
        central.filesDropped.connect(self.add_paths)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(14, 12, 14, 10)
        layout.setSpacing(12)
        layout.addLayout(toolbar)

        file_card = QFrame()
        file_card.setObjectName("card")
        file_layout = QVBoxLayout(file_card)
        file_layout.setSpacing(10)
        file_title = QLabel("文件导入")
        file_title.setObjectName("cardTitle")
        file_layout.addWidget(file_title)
        file_layout.addWidget(self.drop_hint_label)

        main_panel = QFrame()
        main_panel.setObjectName("card")
        main_layout = QVBoxLayout(main_panel)
        main_layout.setSpacing(10)
        metrics_bar = QFrame()
        metrics_bar.setObjectName("metricsBar")
        metrics_layout = QHBoxLayout(metrics_bar)
        metrics_layout.setContentsMargins(16, 10, 16, 10)
        metrics_layout.setSpacing(0)
        for index, metric in enumerate(self.summary_metrics.values()):
            metrics_layout.addWidget(metric, 1)
            if index < len(self.summary_metrics) - 1:
                divider = QFrame()
                divider.setObjectName("metricDivider")
                divider.setFrameShape(QFrame.Shape.VLine)
                metrics_layout.addWidget(divider)
        main_layout.addWidget(metrics_bar)
        main_layout.addWidget(self.summary_label)
        main_layout.addWidget(self.tabs)

        left_area = QVBoxLayout()
        left_area.setSpacing(12)
        left_area.addWidget(file_card)
        left_area.addWidget(main_panel, 1)

        adjustment_panel = QFrame()
        adjustment_panel.setObjectName("sidePanel")
        adjustment_panel.setFixedWidth(290)
        adjustment_layout = QVBoxLayout(adjustment_panel)
        adjustment_layout.setContentsMargins(14, 14, 14, 14)
        adjustment_layout.setSpacing(9)
        adjustment_title = QLabel("流水调整")
        adjustment_title.setObjectName("cardTitle")
        adjustment_layout.addWidget(adjustment_title)
        adjustment_layout.addWidget(self.income_adjust)
        adjustment_layout.addWidget(self.balance_adjust)
        amount_label = QLabel("调整金额（万元）")
        amount_label.setObjectName("fieldLabel")
        adjustment_layout.addWidget(amount_label)
        adjustment_layout.addWidget(self.adjust_amount)
        month_row = QHBoxLayout()
        month_row.addWidget(self.adjust_start_month)
        month_row.addWidget(QLabel("至"))
        month_row.addWidget(self.adjust_end_month)
        adjustment_layout.addLayout(month_row)
        adjustment_layout.addWidget(self.random_adjust)
        preview_card = QFrame()
        preview_card.setObjectName("adjustResultCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(10, 8, 10, 8)
        preview_layout.setSpacing(7)
        preview_title = QLabel("调整预览（所选期间）")
        preview_title.setObjectName("fieldLabel")
        result_row = QHBoxLayout()
        net_box = QVBoxLayout()
        net_label = QLabel("调整后净额(万元)")
        net_label.setObjectName("fieldLabel")
        net_box.addWidget(net_label)
        net_box.addWidget(self.adjust_net_value)
        check_box = QVBoxLayout()
        check_label = QLabel("平衡校验")
        check_label.setObjectName("fieldLabel")
        check_box.addWidget(check_label)
        check_box.addWidget(self.adjust_check_value)
        result_row.addLayout(net_box)
        divider = QFrame()
        divider.setObjectName("metricDivider")
        divider.setFrameShape(QFrame.Shape.VLine)
        result_row.addWidget(divider)
        result_row.addLayout(check_box)
        preview_layout.addWidget(preview_title)
        preview_layout.addLayout(result_row)
        adjustment_layout.addWidget(preview_card)
        adjustment_layout.addWidget(self.adjust_preview_label)

        content = QHBoxLayout()
        content.setSpacing(14)
        content.addLayout(left_area, 1)
        side_column = QVBoxLayout()
        side_column.addWidget(adjustment_panel, 0, Qt.AlignmentFlag.AlignTop)
        side_column.addStretch(1)
        content.addLayout(side_column)
        layout.addLayout(content, 1)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self._apply_style()
        self.render_empty()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls()]
        self.add_paths(paths)

    def _apply_style(self):
        self.setStyleSheet(
            """
            QMainWindow { background: #f5f7fb; }
            QPushButton {
                min-height: 34px;
                padding: 0 14px;
                border: 1px solid #d5dbe5;
                border-radius: 7px;
                background: #ffffff;
                color: #263243;
            }
            QPushButton:hover { background: #eef3f8; }
            QPushButton#primaryButton {
                background: #1769e0;
                color: #ffffff;
                border-color: #1769e0;
                font-weight: 700;
                padding: 0 20px;
            }
            QPushButton#primaryButton:hover { background: #0f5ccc; }
            QPushButton#exportButton {
                background: #ffffff;
                color: #1769e0;
                border-color: #9bbff2;
                font-size: 14px;
                font-weight: 500;
            }
            QFrame#card, QFrame#sidePanel {
                background: #ffffff;
                border: 1px solid #e3e8f0;
                border-radius: 8px;
            }
            QFrame#sidePanel { background: #fbfcfe; }
            QFrame#inlineFilterPanel {
                background: #ffffff;
                border: 1px solid #dfe6f1;
                border-radius: 8px;
                min-height: 42px;
            }
            QFrame#metricsBar {
                background: #ffffff;
                border: 1px solid #dfe6f1;
                border-radius: 8px;
            }
            QFrame#metricItem { border: 0; background: transparent; }
            QFrame#metricDivider {
                color: #e1e7f0;
                background: #e1e7f0;
                max-width: 1px;
            }
            QLabel#metricLabel {
                color: #5f6b7a;
                font-size: 13px;
                font-weight: 500;
            }
            QLabel#metricValue {
                color: #162033;
                font-size: 22px;
                font-weight: 600;
            }
            QLabel#metricValue[tone="income"] { color: #138a4b; }
            QLabel#metricValue[tone="expense"] { color: #d93f2f; }
            QLabel#metricValue[tone="income"], QLabel#metricValue[tone="expense"] {
                font-size: 19px;
            }
            QLabel#metricValue[tone="warning"] { color: #e07a1f; }
            QLabel#metricValue[tone="confidenceVeryHigh"] { color: #0b6f3a; }
            QLabel#metricValue[tone="confidenceHigh"] { color: #138a4b; }
            QLabel#metricValue[tone="confidenceMedium"] { color: #e07a1f; }
            QLabel#metricValue[tone="confidenceLow"] { color: #d93f2f; }
            QLabel#metricValue[tone="neutral"] { color: #162033; }
            QLabel {
                font-family: "Microsoft YaHei UI", "Segoe UI", Arial;
            }
            QLabel#cardTitle {
                font-size: 16px;
                font-weight: 700;
                color: #1f2d3d;
            }
            QLabel#fieldLabel {
                color: #5f6b7a;
                font-weight: 600;
            }
            QLabel#dropHint {
                min-height: 88px;
                color: #4b5b6d;
                border: 1px dashed #9bbff2;
                border-radius: 8px;
                background: #f8fbff;
                font-size: 14px;
                font-weight: 400;
            }
            QTableWidget {
                gridline-color: #d8dde6;
                selection-background-color: #cfe5ff;
                background: #ffffff;
                border: 1px solid #e3e8f0;
                border-radius: 6px;
            }
            QHeaderView::section {
                background: #f0f3f7;
                padding: 7px;
                border: 0;
                border-right: 1px solid #d8dde6;
                border-bottom: 1px solid #d8dde6;
                font-family: "Microsoft YaHei UI", "Segoe UI", Arial;
                font-size: 13px;
                font-weight: 500;
                color: #1f2d3d;
            }
            QTabWidget::pane { border: 0; top: -1px; }
            QTabBar::tab {
                background: transparent;
                border: 0;
                border-bottom: 3px solid transparent;
                padding: 10px 20px;
                margin-right: 8px;
                color: #5f6b7a;
                font-size: 15px;
                font-weight: 400;
            }
            QTabBar::tab:selected {
                color: #1769e0;
                font-weight: 500;
                border-bottom-color: #1769e0;
            }
            QLineEdit, QDateEdit {
                min-height: 28px;
                padding: 0 8px;
                border: 1px solid #d5dbe5;
                border-radius: 6px;
                background: #ffffff;
            }
            QDateEdit::drop-down {
                width: 24px;
                border: 0;
                background: transparent;
                subcontrol-origin: padding;
                subcontrol-position: top right;
            }
            QDateEdit::down-arrow {
                image: url(assets/down_arrow.svg);
                width: 10px;
                height: 10px;
                margin-right: 7px;
            }
            QLabel#summaryLabel {
                padding: 10px 12px;
                background: #f8fbff;
                border: 1px solid #dbe8fb;
                border-radius: 6px;
                color: #1f2d3d;
            }
            QLabel#adjustPreviewLabel {
                color: #5f6b7a;
            }
            QFrame#adjustResultCard {
                padding: 8px;
                background: #f8fbff;
                border: 1px solid #dbe8fb;
                border-radius: 8px;
            }
            QLabel#adjustResultValue {
                color: #1f9d55;
                font-size: 28px;
                font-weight: 600;
            }
            QFrame#adjustResultCard QLabel#fieldLabel {
                font-size: 14px;
                font-weight: 500;
            }
            """
        )

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择银行流水文件", "", "支持的文件 (*.pdf *.xlsx *.xlsm);;PDF 文件 (*.pdf);;Excel 文件 (*.xlsx *.xlsm)")
        self.add_paths([Path(file) for file in files])

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含 PDF 的文件夹")
        if folder:
            self.add_paths([Path(folder)])

    def add_paths(self, paths: list[Path]):
        inputs: list[Path] = []
        for path in paths:
            if path.is_dir():
                for suffix in SUPPORTED_INPUTS:
                    inputs.extend(sorted(path.rglob(f"*{suffix}")))
            elif path.suffix.lower() in SUPPORTED_INPUTS:
                inputs.append(path)
        self.paths = []
        self.results = []
        self.issues = []
        known = set()
        for input_path in inputs:
            resolved = input_path.resolve()
            if resolved not in known:
                self.paths.append(input_path)
                known.add(resolved)
        self.render_selected()

    def clear(self):
        self.paths = []
        self.results = []
        self.issues = []
        self.adjustment_result = AdjustmentResult()
        self.render_empty()

    def create_metric(self, label: str, value: str, tone: str) -> QFrame:
        frame = QFrame()
        frame.setObjectName("metricItem")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 4, 12, 4)
        title = QLabel(label)
        title.setObjectName("metricLabel")
        number = QLabel(value)
        number.setObjectName("metricValue")
        number.setProperty("tone", tone)
        number.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)
        layout.addWidget(number)
        frame.value_label = number
        return frame

    def set_metric(self, key: str, value: str, tone: str | None = None):
        metric = self.summary_metrics.get(key)
        if metric is not None:
            if tone is not None:
                metric.value_label.setProperty("tone", tone)
                metric.value_label.style().unpolish(metric.value_label)
                metric.value_label.style().polish(metric.value_label)
            metric.value_label.setText(self.format_metric_value(key, value))

    def format_metric_value(self, key: str, value: str) -> str:
        if key not in ("income", "expense") or " / " not in value:
            return value
        count, amount = value.split(" / ", 1)
        return f'<span style="font-weight:700;">{count}</span><span style="font-weight:400; font-size:16px;"> / {amount}</span>'

    def run(self):
        if not self.paths:
            QMessageBox.information(self, "提示", "请先选择 PDF/Excel 文件或文件夹。")
            return
        start_date, end_date = self.selected_date_range()
        if start_date is not None and end_date is not None and start_date > end_date:
            QMessageBox.warning(self, "日期范围错误", "开始日期不能晚于结束日期。")
            return
        self.worker = Worker(self.paths, start_date, end_date)
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def selected_date_range(self) -> tuple[datetime | None, datetime | None]:
        if not self.date_filter.isChecked():
            return None, None
        start = self.start_date.date().toPyDate()
        end = self.end_date.date().toPyDate()
        return datetime.combine(start, time.min), datetime.combine(end, time.max)

    def on_finished(self, results: list[FileResult], issues: list[Issue]):
        self.results = results
        self.issues = issues
        self.render_results()
        self.statusBar().showMessage("处理完成")

    def on_adjustment_mode_changed(self, *_args):
        sender = self.sender()
        if sender is self.income_adjust and self.income_adjust.isChecked() and self.balance_adjust.isChecked():
            self.balance_adjust.setChecked(False)
        elif sender is self.balance_adjust and self.balance_adjust.isChecked() and self.income_adjust.isChecked():
            self.income_adjust.setChecked(False)
        self.refresh_adjustment()

    def refresh_adjustment(self, *_args):
        if self.results:
            self.render_results()
            if any(config.enabled for config in self.adjustment_configs()):
                self.tabs.setCurrentWidget(self.monthly)
                self.statusBar().showMessage("月度统计已按调整后数据刷新")

    def update_monthly_tab_label(self, adjusted: bool):
        self.tabs.setTabText(self.monthly_tab_index, "调整月度统计" if adjusted else "月度统计")

    def update_adjustment_preview(self):
        if not self.adjustment_result.enabled:
            self.adjust_net_value.setText("0.00")
            self.adjust_check_value.setText("未启用")
            self.adjust_preview_label.setText("原始统计保持不变")
            return
        total_row = next((row for row in self.adjustment_result.rows if row.month == "总计"), None)
        if total_row is None:
            self.adjust_net_value.setText("0.00")
            self.adjust_check_value.setText("需复核")
            self.adjust_preview_label.setText("暂无可调整月份")
            return
        check = balance_check(total_row, self.adjustment_result)
        self.adjust_net_value.setText(f"{money_wan(total_row.adjusted_net)}")
        self.adjust_check_value.setText(check)
        self.adjust_preview_label.setText(
            f"收入调整 {money_wan(total_row.income_adjustment)} 万元  "
            f"支出调整 {money_wan(total_row.expense_adjustment)} 万元"
        )

    def render_empty(self):
        self.update_monthly_tab_label(False)
        self.adjustment_result = AdjustmentResult()
        self.update_adjustment_preview()
        for key, value in {
            "files": "0",
            "flows": "0",
            "income": "0 / 0.00",
            "expense": "0 / 0.00",
            "issues": "0",
            "confidence": "-",
        }.items():
            self.set_metric(key, value, "neutral" if key == "confidence" else None)
        self.summary_label.setText("选择 PDF/Excel 文件或文件夹后开始处理；默认输出近半年，可手动修改日期范围。")
        self._set_table(self.overview, ["文件", "状态"], [])
        self._set_table(self.monthly, ["月份", "收入(万元)", "支出(万元)"], [])
        self._set_table(self.details, ["时间", "收入", "支出", "余额"], [])
        self._set_table(self.issue_table, ["级别", "来源", "时间", "提示"], [])

    def render_selected(self):
        self.update_monthly_tab_label(False)
        self.adjustment_result = AdjustmentResult()
        self.update_adjustment_preview()
        self.set_metric("files", str(len(self.paths)))
        self.set_metric("flows", "待处理")
        self.set_metric("income", "待处理")
        self.set_metric("expense", "待处理")
        self.set_metric("issues", "待处理")
        self.set_metric("confidence", "待处理", "neutral")
        rows = [[str(path), "待处理"] for path in self.paths]
        self._set_table(self.overview, ["文件", "状态"], rows)
        self.summary_label.setText(f"已选择 {len(self.paths)} 个文件，点击开始处理。")

    def render_results(self):
        all_transactions, duplicate_issues = dedupe_transactions([tx for result in self.results for tx in result.transactions])
        shown_issues = self.issues + duplicate_issues
        total = summarize(all_transactions, "全部文件")
        type_counts = flow_type_counts(self.results)
        self.set_metric("files", str(len(self.results)))
        self.set_metric("flows", str(total.count))
        self.set_metric("income", f"{total.income_count} / {money(total.income_sum)}")
        self.set_metric("expense", f"{total.expense_count} / {money(total.expense_sum)}")
        self.set_metric("issues", str(len(shown_issues)))
        confidence = calculate_confidence(self.results, shown_issues, self.selected_date_range())
        self.set_metric("confidence", confidence.level, confidence.tone)
        self.summary_label.setText(
            f"文件 {len(self.results)} 个，流水 {total.count} 笔，收入 {total.income_count} 笔/{money(total.income_sum)}，"
            f"支出 {total.expense_count} 笔/{money(total.expense_sum)}，净额 {money(total.net)}，"
            f"异常提示 {len(shown_issues)} 条，可信度 {confidence.level}。类型：{type_counts}。"
        )

        self.adjustment_result = apply_adjustments(all_transactions, self.adjustment_configs())
        self.update_monthly_tab_label(self.adjustment_result.enabled)
        self.update_adjustment_preview()
        self._set_table(
            self.monthly,
            monthly_headers(self.adjustment_result.enabled, include_balances=False),
            build_monthly_display_rows(all_transactions, self.adjustment_result, include_balances=False),
        )
        if self.adjustment_result.enabled:
            self.summary_label.setText(self.summary_label.text() + " 已启用调整，月度统计显示调整后数据。")
            if self.adjustment_result.warnings:
                self.statusBar().showMessage("；".join(self.adjustment_result.warnings))

        overview_rows = []
        for result in self.results:
            s = result.summary
            overview_rows.append(
                [
                    result.path.name,
                    result_flow_type(result),
                    result_bank_label(result),
                    s.count,
                    s.income_count,
                    money(s.income_sum),
                    s.expense_count,
                    money(s.expense_sum),
                    money(s.net),
                    money(s.opening_balance),
                    money(s.closing_balance),
                    result.status,
                    result.message,
                ]
            )
        self._set_table(
            self.overview,
            ["文件", "流水类型", "银行", "流水笔数", "收入笔数", "收入", "支出笔数", "支出", "净额", "期初余额", "期末余额", "状态", "说明"],
            overview_rows,
        )

        detail_rows = []
        for tx in sort_transactions(all_transactions):
            detail_rows.append(
                [
                    tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S"),
                    getattr(tx, "source_file", ""),
                    transaction_flow_type(tx),
                    getattr(tx, "bank_label", tx.bank),
                    money(tx.income),
                    money(tx.expense),
                    money(tx.balance),
                    tx.status,
                    "; ".join(tx.issues),
                    tx.raw_amount,
                    tx.raw_balance,
                ]
            )
        self._set_table(self.details, ["时间", "文件", "流水类型", "银行", "收入", "支出", "余额", "状态", "提示", "原始金额", "原始余额"], detail_rows)

        issue_rows = [[issue.level, issue.source, issue.time, issue.message, issue.raw_amount, issue.raw_balance] for issue in shown_issues]
        self._set_table(self.issue_table, ["级别", "来源", "时间", "提示", "原始金额", "原始余额"], issue_rows)

    def _set_table(self, table: QTableWidget, headers: list[str], rows: list[list]):
        table.setSortingEnabled(False)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            row = list(row)
            if len(row) < len(headers):
                row.extend([""] * (len(headers) - len(row)))
            elif len(row) > len(headers):
                row = row[:len(headers)]
            is_warning = any(str(value) == "需复核" for value in row)
            for col_index, value in enumerate(row):
                item = QTableWidgetItem(str(value))
                if isinstance(value, (int, Decimal)):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                if is_warning:
                    item.setBackground(Qt.GlobalColor.yellow)
                table.setItem(row_index, col_index, item)
        table.resizeColumnsToContents()
        table.setSortingEnabled(True)

    def export_excel(self):
        if not self.results:
            QMessageBox.information(self, "提示", "请先处理流水后再导出。")
            return
        file_name, _ = QFileDialog.getSaveFileName(self, "导出 Excel", default_export_path(self.results), "Excel 文件 (*.xlsx)")
        if not file_name:
            return
        path = Path(file_name)
        if path.suffix.lower() != ".xlsx":
            path = path.with_suffix(".xlsx")
        path.parent.mkdir(parents=True, exist_ok=True)
        write_workbook(path, self.results, self.issues, self.adjustment_configs())
        QMessageBox.information(self, "完成", f"已导出: {path}")

    def export_income_proof_json(self):
        if not self.results:
            QMessageBox.information(self, "提示", "请先处理流水后再导出。")
            return
        default_path = Path(default_export_path(self.results)).with_suffix(".income_proof.json")
        path = default_path
        path.parent.mkdir(parents=True, exist_ok=True)
        write_income_proof_input(path, self.results)
        opened = open_income_proof_form(path)
        if not opened:
            QMessageBox.warning(self, "未打开填表", f"已导出: {path}\n未找到 Word 填写表入口，请手动打开后选择该 JSON。")

    def adjustment_configs(self) -> list[AdjustmentConfig]:
        return [
            AdjustmentConfig(
                enabled=self.income_adjust.isChecked(),
                amount_wan=self.safe_amount_wan(self.adjust_amount.text()),
                start_month=self.adjust_start_month.date().toString("yyyy-MM"),
                end_month=self.adjust_end_month.date().toString("yyyy-MM"),
                balanced=False,
                label="收入调整（微信）",
                randomized=not self.random_adjust.isChecked(),
            ),
            AdjustmentConfig(
                enabled=self.balance_adjust.isChecked(),
                amount_wan=self.safe_amount_wan(self.adjust_amount.text()),
                start_month=self.adjust_start_month.date().toString("yyyy-MM"),
                end_month=self.adjust_end_month.date().toString("yyyy-MM"),
                balanced=True,
                label="收支平衡调整（个/公）",
                randomized=not self.random_adjust.isChecked(),
            ),
        ]

    def safe_amount_wan(self, text: str) -> Decimal:
        try:
            return parse_amount_wan(text)
        except Exception:
            return Decimal("0.00")


def write_sheet(ws, headers: list[str], rows: list[list]):
    from openpyxl.styles import Font, PatternFill

    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill(start_color="E9EEF5", end_color="E9EEF5", fill_type="solid")
    for row in rows:
        ws.append(row)
    for column in ws.columns:
        width = max(len(str(cell.value or "")) for cell in column) + 2
        ws.column_dimensions[column[0].column_letter].width = min(max(width, 10), 42)


def default_export_filename(results: list[FileResult]) -> str:
    names: list[str] = []
    for result in results:
        name = safe_filename_part(result.account_name)
        if name and name not in names:
            names.append(name)
    if not names:
        return "银行流水解析结果.xlsx"
    return f"银行流水解析结果_{'_'.join(names[:3])}.xlsx"


def default_export_path(results: list[FileResult]) -> str:
    filename = default_export_filename(results)
    export_dir = default_export_dir()
    if export_dir:
        return str(export_dir / filename)
    return filename


def default_export_dir() -> Path | None:
    desktop = Path.home() / "Desktop"
    if not desktop.exists():
        return None
    return desktop / "银行流水解析结果"


def safe_filename_part(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", value or "").strip()[:30]


def extract_account_name(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return extract_pdf_account_name(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return extract_excel_account_name(path)
    return ""


def extract_account_no(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return extract_pdf_account_no(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return extract_excel_account_no(path)
    return ""


def extract_pdf_account_name(path: Path) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return ""
            return parse_account_name(pdf.pages[0].extract_text() or "")
    except Exception:
        return ""


def extract_pdf_account_no(path: Path) -> str:
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return ""
            chunks = []
            for page in pdf.pages[:2]:
                chunks.append(page.extract_text() or "")
            return parse_account_no("\n".join(chunks))
    except Exception:
        return ""


def extract_excel_account_name(path: Path) -> str:
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            worksheet = workbook.worksheets[0]
            chunks = []
            for row in worksheet.iter_rows(min_row=1, max_row=30, values_only=True):
                chunks.append(" ".join(str(cell or "") for cell in row))
            return parse_account_name("\n".join(chunks))
        finally:
            workbook.close()
    except Exception:
        return ""


def extract_excel_account_no(path: Path) -> str:
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        try:
            worksheet = workbook.worksheets[0]
            chunks = []
            for row in worksheet.iter_rows(min_row=1, max_row=30, values_only=True):
                chunks.append(" ".join(str(cell or "") for cell in row))
            return parse_account_no("\n".join(chunks))
        finally:
            workbook.close()
    except Exception:
        return ""


def parse_account_name(text: str) -> str:
    for pattern in ACCOUNT_NAME_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def normalize_account_no(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def valid_account_no(value: str) -> bool:
    return 8 <= len(value) <= 22


def parse_account_no(text: str) -> str:
    header_lines = []
    for raw_line in (text or "").splitlines()[:80]:
        line = raw_line.strip()
        if not line or "对方账号" in line or "对手账号" in line:
            continue
        header_lines.append(line)
    header_text = "\n".join(header_lines)
    for pattern in ACCOUNT_NO_PATTERNS:
        match = re.search(pattern, header_text, re.I)
        if match:
            account_no = normalize_account_no(match.group(1))
            if valid_account_no(account_no):
                return account_no
    return ""


def write_workbook(path: Path, results: list[FileResult], issues: list[Issue], adjustment_configs: list[AdjustmentConfig] | None = None):
    from openpyxl import Workbook

    wb = Workbook()
    monthly = wb.active
    monthly.title = "原始月度统计"
    overview = wb.create_sheet("汇总")
    overview_rows = []
    all_transactions = []
    for result in results:
        s = result.summary
        overview_rows.append(
            [
                result.path.name,
                result_flow_type(result),
                result.bank_label,
                s.count,
                s.income_count,
                float(s.income_sum),
                s.expense_count,
                float(s.expense_sum),
                float(s.net),
                float(s.opening_balance) if s.opening_balance is not None else None,
                float(s.closing_balance) if s.closing_balance is not None else None,
                result.status,
                result.message,
            ]
        )
        all_transactions.extend(result.transactions)
    write_sheet(overview, ["文件", "流水类型", "银行", "流水笔数", "收入笔数", "收入", "支出笔数", "支出", "净额", "期初余额", "期末余额", "状态", "说明"], overview_rows)

    all_transactions, duplicate_issues = dedupe_transactions(all_transactions)
    shown_issues = issues + duplicate_issues
    monthly_rows = build_monthly_display_rows(all_transactions, AdjustmentResult(), for_excel=True)
    write_sheet(monthly, monthly_headers(False), monthly_rows)

    adjustment_result = apply_adjustments(all_transactions, adjustment_configs or [])
    adjusted = wb.create_sheet("调整后月度统计")
    write_sheet(adjusted, monthly_headers(True), [["全部"] + row for row in build_adjusted_rows(adjustment_result, for_excel=True)])

    parameters = wb.create_sheet("调整参数")
    write_sheet(parameters, ["参数", "值"], adjustment_result.parameters)

    instruction_rows = [
        ["说明", "调整功能属于识别后的测算层，不修改原始明细。"],
        ["收入调整（微信）", "只增加收入，适合微信或需要测算收入补充的流水。"],
        ["收支平衡调整（个/公）", "收入和支出同步增加，期末余额保持原值。"],
        ["月份范围", "只调整已有流水的月份，不生成没有流水的月份。"],
        ["余额判断", "调整后余额 >= 0 为正常，否则需复核。"],
        ["微信其他", "微信“其他”在原始统计中默认排除。"],
    ]
    instructions = wb.create_sheet("调整说明")
    write_sheet(instructions, ["项目", "说明"], instruction_rows)

    details = wb.create_sheet("原始明细")
    detail_rows = []
    for tx in sort_transactions(all_transactions):
        detail_rows.append(
            [
                tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S"),
                getattr(tx, "source_file", ""),
                transaction_flow_type(tx),
                getattr(tx, "bank_label", tx.bank),
                float(tx.income),
                float(tx.expense),
                float(tx.balance) if tx.balance is not None else None,
                tx.status,
                "; ".join(tx.issues),
                tx.raw_amount,
                tx.raw_balance,
            ]
        )
    write_sheet(details, ["时间", "文件", "流水类型", "银行", "收入", "支出", "余额", "状态", "提示", "原始金额", "原始余额"], detail_rows)

    issue_sheet = wb.create_sheet("异常提示")
    issue_rows = [[issue.level, issue.source, issue.time, issue.message, issue.raw_amount, issue.raw_balance] for issue in shown_issues]
    write_sheet(issue_sheet, ["级别", "来源", "时间", "提示", "原始金额", "原始余额"], issue_rows)

    wb.save(path)


def dedupe_transactions(transactions: list) -> tuple[list, list[Issue]]:
    unique = []
    seen: dict[tuple, object] = {}
    issues: list[Issue] = []

    for tx in sorted(transactions, key=lambda item: (item.transaction_time, getattr(item, "source_file", ""), item.row_no)):
        key = getattr(tx, "merge_key", None)
        if key:
            signature = (tx.bank, key)
        else:
            signature = (
                tx.bank,
                tx.transaction_time,
                tx.income,
                tx.expense,
                tx.balance,
                tx.raw_amount,
                tx.raw_balance,
            )

        if signature in seen and (key or getattr(seen[signature], "source_file", "") != getattr(tx, "source_file", "")):
            first = seen[signature]
            issues.append(
                Issue(
                    "需复核",
                    getattr(tx, "source_file", ""),
                    tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S"),
                    f"疑似重复流水，已在合并明细中去重；首次来源: {getattr(first, 'source_file', '')}",
                    tx.raw_amount,
                    tx.raw_balance,
                )
            )
            continue

        if signature not in seen:
            seen[signature] = tx
        unique.append(tx)

    return unique, issues


def result_flow_type(result: FileResult) -> str:
    return income_flow_type(result.bank_id)


def result_bank_label(result: FileResult) -> str:
    if result.bank_label:
        return result.bank_label
    from bankflow_v2.auto_detect import BANK_LABELS

    return BANK_LABELS.get(result.bank_id, "")


def transaction_flow_type(tx) -> str:
    value = getattr(tx, "flow_type", "")
    return value or "个人"


def flow_type_counts(results: list[FileResult]) -> str:
    counts = {"个人": 0, "微信": 0, "对公": 0}
    for result in results:
        counts[result_flow_type(result)] = counts.get(result_flow_type(result), 0) + 1
    return "，".join(f"{key}{value}份" for key, value in counts.items() if value) or "无"


def calculate_confidence(results: list[FileResult], issues: list[Issue], date_range: tuple[datetime | None, datetime | None]) -> ConfidenceInfo:
    if not results:
        return ConfidenceInfo(0, "-", "neutral", "暂无结果")

    scored_results = [result for result in results if not is_date_range_empty_result(result)]
    scored_issues = [issue for issue in issues if not is_date_range_empty_issue(issue)]
    if not scored_results:
        return ConfidenceInfo(0, "-", "neutral", DATE_RANGE_EMPTY_MESSAGE)
    if not any(int(getattr(result.summary, "count", 0)) > 0 for result in scored_results):
        return ConfidenceInfo(0, "未识别", "confidenceLow", "未识别到流水")

    weighted_score = 0
    total_weight = 0
    reasons: list[str] = []
    for result in scored_results:
        score, reason = result_confidence_score(result, date_range)
        weight = max(int(getattr(result.summary, "count", 0)), 1)
        weighted_score += score * weight
        total_weight += weight
        reasons.append(reason)

    score = round(weighted_score / total_weight) if total_weight else 0
    review_count = sum(1 for issue in scored_issues if issue.level == "需复核")
    low_risk_count = sum(1 for issue in scored_issues if issue.level != "需复核")
    score -= min(18, review_count * 4)
    score -= min(6, low_risk_count)
    score = max(0, min(100, score))

    if is_extremely_high_confidence(scored_results, scored_issues):
        level = "极高"
        tone = "confidenceVeryHigh"
    elif score >= 90:
        level = "高"
        tone = "confidenceHigh"
    elif score >= 70:
        level = "中"
        tone = "confidenceMedium"
    else:
        level = "低"
        tone = "confidenceLow"
    return ConfidenceInfo(score, level, tone, "；".join(reasons))


def result_confidence_score(result: FileResult, date_range: tuple[datetime | None, datetime | None]) -> tuple[int, str]:
    summary = result.summary
    count = int(getattr(summary, "count", 0))
    if count <= 0:
        return 0, "未识别到流水"

    used_generic = is_generic_confidence_result(result)
    if used_generic:
        score = 68
        reason = "通用识别"
    elif result.bank_id == "excel":
        score = 86
        reason = "Excel导入"
    else:
        score = min(94, max(78, int(result.bank_confidence or 80)))
        reason = "专用解析"

    review_issues = [issue for issue in getattr(summary, "issues", []) if issue.level == "需复核"]
    low_risk_issues = [issue for issue in getattr(summary, "issues", []) if issue.level != "需复核"]
    score -= min(22, len(review_issues) * 6)
    score -= min(8, len(low_risk_issues) * 2)

    if not confidence_needs_balance(result):
        score += 6
    elif getattr(summary, "opening_balance", None) is not None and getattr(summary, "closing_balance", None) is not None:
        has_balance_break = has_review_balance_break(summary)
        if summary_balance_closed(summary):
            score += 18 if not has_balance_break else 6
        else:
            score -= 14
    else:
        score -= 6

    if last_two_months_have_flows(result.transactions, date_range):
        score += 5
        if last_two_months_closed_without_review(result.transactions, date_range):
            score += 8

    if result.message and result.status == "需复核" and result.message != DATE_RANGE_EMPTY_MESSAGE:
        score -= 8

    return max(0, min(100, score)), reason


def is_extremely_high_confidence(results: list[FileResult], issues: list[Issue]) -> bool:
    if issues:
        return False
    for result in results:
        if int(getattr(result.summary, "count", 0)) <= 0:
            return False
        if is_generic_confidence_result(result) or result.bank_id == "excel":
            return False
        if getattr(result.summary, "issues", []):
            return False
        if result.message and result.message != DATE_RANGE_EMPTY_MESSAGE:
            return False
    return True


def is_generic_confidence_result(result: FileResult) -> bool:
    return (
        result.status == "通用识别"
        or "通用识别" in (result.bank_label or "")
        or result.bank_id in ("generic_pdf", "cmbc", "cib")
    )


def summary_balance_closed(summary) -> bool:
    opening = getattr(summary, "opening_balance", None)
    closing = getattr(summary, "closing_balance", None)
    if opening is None or closing is None:
        return False
    expected_change = (closing - opening).quantize(Decimal("0.01"))
    return getattr(summary, "net", Decimal("0.00")).quantize(Decimal("0.01")) == expected_change


def has_review_balance_break(summary) -> bool:
    return any(
        "余额不连续" in issue.message and issue.level == "需复核"
        for issue in getattr(summary, "issues", [])
    )


def confidence_needs_balance(result: FileResult) -> bool:
    if result.bank_id == "wechat":
        return False
    if result.transactions and all(getattr(tx, "balance_optional", False) for tx in result.transactions):
        return False
    return True


def is_date_range_empty_result(result: FileResult) -> bool:
    return int(getattr(result.summary, "count", 0)) == 0 and result.message == DATE_RANGE_EMPTY_MESSAGE


def is_date_range_empty_issue(issue: Issue) -> bool:
    return issue.message == DATE_RANGE_EMPTY_MESSAGE


def last_two_months_have_flows(transactions: list, date_range: tuple[datetime | None, datetime | None]) -> bool:
    target_months = last_two_month_keys(date_range)
    if len(target_months) < 2 and transactions:
        latest = max(tx.transaction_time for tx in transactions)
        month_start = datetime(latest.year, latest.month, 1)
        target_months = [add_months(month_start, -1).strftime("%Y-%m"), month_start.strftime("%Y-%m")]
    if len(target_months) < 2:
        return False
    seen = {tx.transaction_time.strftime("%Y-%m") for tx in transactions}
    return all(month in seen for month in target_months)


def last_two_months_closed_without_review(transactions: list, date_range: tuple[datetime | None, datetime | None]) -> bool:
    target_months = last_two_month_keys(date_range)
    if len(target_months) < 2 and transactions:
        latest = max(tx.transaction_time for tx in transactions)
        month_start = datetime(latest.year, latest.month, 1)
        target_months = [add_months(month_start, -1).strftime("%Y-%m"), month_start.strftime("%Y-%m")]
    if len(target_months) < 2:
        return False

    for month in target_months:
        month_transactions = [tx for tx in transactions if tx.transaction_time.strftime("%Y-%m") == month]
        if not month_transactions:
            return False
        month_summary = summarize(month_transactions, month)
        if any(issue.level == "需复核" for issue in month_summary.issues):
            return False
        if confidence_needs_balance_for_transactions(month_transactions) and not summary_balance_closed(month_summary):
            return False
    return True


def confidence_needs_balance_for_transactions(transactions: list) -> bool:
    if not transactions:
        return True
    if all(getattr(tx, "bank", "") == "微信流水" for tx in transactions):
        return False
    if all(getattr(tx, "balance_optional", False) for tx in transactions):
        return False
    return True


def last_two_month_keys(date_range: tuple[datetime | None, datetime | None]) -> list[str]:
    _start, end = date_range
    if end is None:
        if not date_range[0]:
            return []
        end = max(date_range[0], datetime.now())
    month_start = datetime(end.year, end.month, 1)
    previous = add_months(month_start, -1)
    return [previous.strftime("%Y-%m"), month_start.strftime("%Y-%m")]


def add_months(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + value.month - 1 + months
    year = month_index // 12
    month = month_index % 12 + 1
    return datetime(year, month, 1)


def grouped_transactions(transactions: list) -> list[tuple[str, list]]:
    order = ["个人", "微信", "对公"]
    groups = []
    for flow_type in order:
        items = [tx for tx in transactions if transaction_flow_type(tx) == flow_type]
        if items:
            groups.append((flow_type, items))
    return groups


def build_monthly_rows(transactions: list, for_excel: bool = False, balance_wechat: bool = False) -> list[list]:
    rows = []
    month_pairs = monthly_summaries(transactions)
    if balance_wechat:
        month_pairs = list(balance_wechat_summaries(month_pairs).items())
    for month, s in month_pairs:
        rows.append(_summary_row("", month, s, for_excel))

    if rows:
        if balance_wechat:
            total = sum_summaries([s for _month, s in month_pairs])
        else:
            total = summarize(transactions, "总计")
        rows.append(_summary_row("", "总计", total, for_excel))
        rows.append(_monthly_average_row(total, len(rows) - 1, for_excel, adjusted=False))
    return rows


def monthly_headers(adjusted: bool = False, include_balances: bool = True) -> list[str]:
    headers = [
        "流水类型",
        "月份",
        "收入笔数",
        "收入(万元)",
        "支出笔数",
        "支出(万元)",
        "净额(万元)",
        "流水笔数",
    ]
    if include_balances:
        headers[7:7] = ["期初余额(万元)", "期末余额(万元)"]
    if adjusted:
        headers.extend([
            "收入调整(万元)",
            "支出调整(万元)",
            "调整后余额变动(万元)",
            "调整后收支差额(万元)",
            "平衡校验",
            "说明",
        ])
    return headers


def build_monthly_display_rows(
    transactions: list,
    adjustment: AdjustmentResult,
    for_excel: bool = False,
    include_balances: bool = True,
) -> list[list]:
    if not adjustment.enabled:
        rows = build_grouped_monthly_display_rows(transactions, for_excel)
    else:
        rows = build_grouped_monthly_display_rows(transactions, for_excel, include_combined=False)
        rows.extend([["全部"] + row for row in build_adjusted_rows(adjustment, for_excel)])
    if not include_balances:
        rows = [without_monthly_balance_columns(row) for row in rows]
    return rows


def build_grouped_monthly_display_rows(transactions: list, for_excel: bool = False, include_combined: bool = True) -> list[list]:
    rows = []
    groups = grouped_transactions(transactions)
    for flow_type, items in groups:
        group_rows = build_monthly_rows(items, for_excel, balance_wechat=flow_type == "微信")
        for row in group_rows:
            row[0] = flow_type
        rows.extend(group_rows)
    if include_combined and len(groups) > 1:
        total_rows = build_combined_monthly_rows(groups, for_excel)
        for row in total_rows:
            row[0] = "全部"
        rows.extend(total_rows)
    return rows


def without_monthly_balance_columns(row: list) -> list:
    return [value for index, value in enumerate(row) if index not in (7, 8)]


def build_combined_monthly_rows(groups: list[tuple[str, list]], for_excel: bool = False) -> list[list]:
    summaries_by_month: dict[str, list[Summary]] = {}
    for flow_type, items in groups:
        month_pairs = monthly_summaries(items)
        if flow_type == "微信":
            month_pairs = list(balance_wechat_summaries(month_pairs).items())
        for month, summary in month_pairs:
            summaries_by_month.setdefault(month, []).append(summary)

    rows = []
    combined_pairs = [(month, sum_summaries(summaries)) for month, summaries in sorted(summaries_by_month.items())]
    for month, summary in combined_pairs:
        rows.append(_summary_row("", month, summary, for_excel))
    if rows:
        total = sum_summaries([summary for _month, summary in combined_pairs])
        rows.append(_summary_row("", "总计", total, for_excel))
        rows.append(_monthly_average_row(total, len(rows) - 1, for_excel, adjusted=False))
    return rows


def sum_summaries(summaries: list[Summary]) -> Summary:
    total = Summary()
    for summary in summaries:
        total.count += summary.count
        total.income_count += summary.income_count
        total.income_sum += summary.income_sum
        total.expense_count += summary.expense_count
        total.expense_sum += summary.expense_sum
    total.income_sum = total.income_sum.quantize(Decimal("0.01"))
    total.expense_sum = total.expense_sum.quantize(Decimal("0.01"))
    total.net = (total.income_sum - total.expense_sum).quantize(Decimal("0.01"))
    return total


def build_adjusted_rows(adjustment: AdjustmentResult, for_excel: bool = False) -> list[list]:
    rows = []
    for row in adjustment.rows:
        if row.month == "总计":
            continue
        values = [
            row.adjusted_income_sum,
            row.adjusted_expense_sum,
            row.adjusted_net,
            row.adjusted_opening_balance,
            row.adjusted_closing_balance,
            row.income_adjustment,
            row.expense_adjustment,
            balance_delta(row.adjusted_opening_balance, row.adjusted_closing_balance),
            row.adjusted_net,
        ]
        if for_excel:
            money_values = [float(to_wan(value)) if value is not None else None for value in values]
        else:
            money_values = [money_wan(value) for value in values]
        rows.append(
            [
                row.month,
                row.original_income_count,
                money_values[0],
                row.original_expense_count,
                money_values[1],
                money_values[2],
                money_values[3],
                money_values[4],
                row.original_count,
                money_values[5],
                money_values[6],
                money_values[7],
                money_values[8],
                balance_check(row, adjustment),
                row.note,
            ]
        )
    for warning in adjustment.warnings:
        rows.append(["提示", "", "", "", "", "", "", "", "", "", "", "", "", "", warning])
    total_row = next((row for row in adjustment.rows if row.month == "总计"), None)
    if total_row is not None:
        rows.append(_adjusted_row(total_row, for_excel, label="总计", adjustment=adjustment))
        month_count = max(len([row for row in adjustment.rows if row.month != "总计"]), 1)
        rows.append(_monthly_average_row(total_row, month_count, for_excel, adjusted=True))
    return rows


def _adjusted_row(row, for_excel: bool, label: str | None = None, adjustment: AdjustmentResult | None = None) -> list:
    values = [
        row.adjusted_income_sum,
        row.adjusted_expense_sum,
        row.adjusted_net,
        row.adjusted_opening_balance,
        row.adjusted_closing_balance,
        row.income_adjustment,
        row.expense_adjustment,
        balance_delta(row.adjusted_opening_balance, row.adjusted_closing_balance),
        row.adjusted_net,
    ]
    if for_excel:
        money_values = [float(to_wan(value)) if value is not None else None for value in values]
    else:
        money_values = [money_wan(value) for value in values]
    return [
        label or row.month,
        row.original_income_count,
        money_values[0],
        row.original_expense_count,
        money_values[1],
        money_values[2],
        money_values[3],
        money_values[4],
        row.original_count,
        money_values[5],
        money_values[6],
        money_values[7],
        money_values[8],
        balance_check(row, adjustment or AdjustmentResult(balanced=row.expense_adjustment != Decimal("0.00"))),
        row.note,
    ]


def _monthly_average_row(total, month_count: int, for_excel: bool, adjusted: bool) -> list:
    divisor = Decimal(max(month_count, 1))
    income_average = (total.adjusted_income_sum if adjusted else total.income_sum) / divisor
    expense_average = (total.adjusted_expense_sum if adjusted else total.expense_sum) / divisor
    income_average = income_average.quantize(Decimal("0.01"))
    expense_average = expense_average.quantize(Decimal("0.01"))
    if for_excel:
        income_value = float(to_wan(income_average))
        expense_value = float(to_wan(expense_average))
    else:
        income_value = money_wan(income_average)
        expense_value = money_wan(expense_average)
    if adjusted:
        return ["月均", "", income_value, "", expense_value, "", "", "", "", "", "", "", "", "", f"按 {month_count} 个月平均"]
    return ["", "月均", "", income_value, "", expense_value, "", "", "", ""]


def balance_delta(opening: Decimal | None, closing: Decimal | None) -> Decimal | None:
    if opening is None or closing is None:
        return None
    return (closing - opening).quantize(Decimal("0.01"))


def balance_check(row, adjustment: AdjustmentResult) -> str:
    if not adjustment.balanced:
        return "模拟"
    delta = balance_delta(row.adjusted_opening_balance, row.adjusted_closing_balance)
    if delta is None:
        return "需复核"
    return "正常" if delta == row.adjusted_net else "需复核"

def build_salary_sheet(transactions: list, for_excel: bool = False) -> tuple[list[str], list[list]]:
    salary_transactions = [tx for tx in sort_transactions(transactions) if is_salary_transaction(tx)]
    if not salary_transactions:
        return [], []

    headers = salary_headers(salary_transactions)
    amount_col = salary_amount_col(headers)
    rows = []
    for tx in salary_transactions:
        fields = salary_fields(tx)
        rows.append((fields + [""] * len(headers))[:len(headers)])

    total = sum((tx.income for tx in salary_transactions), Decimal("0.00")).quantize(Decimal("0.01"))
    months = {tx.transaction_time.strftime("%Y-%m") for tx in salary_transactions}
    average = (total / Decimal(len(months))).quantize(Decimal("0.01")) if months else Decimal("0.00")
    rows.append([""] * len(headers))
    rows.append(salary_summary_row(headers, amount_col, "工资总额", total, for_excel))
    rows.append(salary_summary_row(headers, amount_col, "统计月份数", Decimal(len(months)), for_excel))
    rows.append(salary_summary_row(headers, amount_col, "月均", average, for_excel))
    return headers, rows


def salary_headers(transactions: list) -> list[str]:
    headers = next((list(getattr(tx, "raw_headers", []) or []) for tx in transactions if getattr(tx, "raw_headers", None)), [])
    max_len = max(len(salary_fields(tx)) for tx in transactions)
    if not headers:
        headers = [f"原始字段{index}" for index in range(1, max_len + 1)]
    if len(headers) < max_len:
        headers.extend(f"原始字段{index}" for index in range(len(headers) + 1, max_len + 1))
    return headers


def salary_fields(tx) -> list:
    fields = list(getattr(tx, "raw_fields", []) or [])
    if fields:
        return fields
    text = salary_match_text(tx)
    return text.split(" | ") if " | " in text else [text]


def salary_amount_col(headers: list[str]) -> int:
    preferred = ("交易金额", "收入金额", "贷方发生额", "贷方", "金额")
    for name in preferred:
        for index, header in enumerate(headers):
            if name in header:
                return index
    return min(3, len(headers) - 1)


def salary_summary_row(headers: list[str], amount_col: int, label: str, value: Decimal, for_excel: bool) -> list:
    row = [""] * len(headers)
    row[0] = label
    if label == "统计月份数":
        row[amount_col] = int(value)
    else:
        row[amount_col] = float(value) if for_excel else money(value)
    return row


def is_salary_transaction(tx) -> bool:
    if tx.income <= Decimal("0.00"):
        return False
    text = salary_match_text(tx)
    return any(keyword in text for keyword in SALARY_KEYWORDS)


def salary_match_text(tx) -> str:
    raw_fields = " | ".join(str(field) for field in getattr(tx, "raw_fields", []) or [])
    return f"{getattr(tx, 'raw_text', '')} | {raw_fields} | {getattr(tx, 'raw_amount', '')}".strip()


def build_combined_summary_rows(results: list[FileResult], transactions: list, for_excel: bool = False) -> list[list]:
    rows = []
    for result in results:
        rows.append(_combined_summary_row(
            "文件",
            result.path.name,
            result_bank_label(result),
            result.summary,
            result.status,
            result.message,
            for_excel,
        ))

    for month, summary in monthly_summaries(transactions):
        rows.append(_combined_summary_row("月份", month, "全部文件", summary, "", "", for_excel))

    if transactions:
        rows.append(_combined_summary_row("总计", "总计", "全部文件", summarize(transactions, "总计"), "", "", for_excel))
    return rows


def _combined_summary_row(
    row_type: str,
    name: str,
    scope: str,
    s,
    status: str,
    message: str,
    for_excel: bool,
) -> list:
    values = [
        s.income_sum,
        s.expense_sum,
        s.net,
        s.opening_balance,
        s.closing_balance,
    ]
    if for_excel:
        money_values = [float(to_wan(value)) if value is not None else None for value in values]
    else:
        money_values = [money_wan(value) for value in values]
    return [
        row_type,
        name,
        scope,
        s.count,
        s.income_count,
        money_values[0],
        s.expense_count,
        money_values[1],
        money_values[2],
        money_values[3],
        money_values[4],
        status,
        message,
    ]


def _summary_row(flow_type: str, label: str, s, for_excel: bool) -> list:
    if for_excel:
        return [
            flow_type,
            label,
            s.income_count,
            float(to_wan(s.income_sum)),
            s.expense_count,
            float(to_wan(s.expense_sum)),
            float(to_wan(s.net)),
            float(to_wan(s.opening_balance)) if s.opening_balance is not None else None,
            float(to_wan(s.closing_balance)) if s.closing_balance is not None else None,
            s.count,
        ]
    return [
        flow_type,
        label,
        s.income_count,
        money_wan(s.income_sum),
        s.expense_count,
        money_wan(s.expense_sum),
        money_wan(s.net),
        money_wan(s.opening_balance),
        money_wan(s.closing_balance),
        s.count,
    ]


def to_wan(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return (value / Decimal("10000")).quantize(Decimal("0.01"))


def money_wan(value: Decimal | None) -> str:
    converted = to_wan(value)
    return "" if converted is None else f"{converted:,.2f}"


def default_recent_month_range() -> tuple[QDate, QDate]:
    today = QDate.currentDate()
    month_start = QDate(today.year(), today.month(), 1)
    end_month = month_start.addMonths(-1)
    start = end_month.addMonths(-5)
    end = QDate(end_month.year(), end_month.month(), end_month.daysInMonth())
    return start, end


def open_income_proof_form(json_path: Path) -> bool:
    launcher = Path(r"D:\report workflow\启动收入佐证填表.bat")
    if not launcher.exists():
        return False
    subprocess.Popen(
        ["cmd", "/c", "start", "", str(launcher), str(json_path)],
        cwd=str(launcher.parent),
    )
    return True


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
