import sys
import re
from dataclasses import dataclass
from datetime import datetime, time
from decimal import Decimal
from pathlib import Path

import pdfplumber
from openpyxl import Workbook
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill
from PyQt6.QtCore import QDate, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from bankflow_v2.auto_detect import BANK_LABELS, detect_bank_type
from bankflow_v2.excel_input import extract_excel_transactions
from bankflow_v2.generic_pdf import extract_generic_pdf
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.summary import Issue, money, monthly_summaries, summarize


SUPPORTED_INPUTS = {".pdf", ".xlsx", ".xlsm"}
SALARY_KEYWORDS = ("工资", "代发", "薪资", "薪酬", "奖金")
ACCOUNT_NAME_PATTERNS = (
    r"户名\s*(?:Account Name)?\s*[:：]\s*([^\s，,]+)",
    r"客户姓名\s*[:：]\s*([^\s，,]+)",
    r"账户名称\s*[:：]\s*([^\s，,]+)",
    r"户主\s*[:：]\s*([^\s，,]+)",
    r"Account Name\s*[:：]\s*([^\s，,]+)",
)


@dataclass
class FileResult:
    path: Path
    bank_id: str
    bank_label: str
    summary: object
    transactions: list
    status: str
    message: str
    account_name: str = ""


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
            return extract_excel_transactions(str(path)), "Excel导入", "Excel文件导入", False

        if not detection.bank_id:
            transactions = extract_generic_pdf(str(path))
            if transactions:
                return transactions, "通用PDF识别", f"{detection.reason}，已使用通用识别", True
            return [], "未识别", detection.reason, False

        if detection.bank_id in ("cmbc", "cib", "generic_pdf"):
            transactions = extract_transactions(str(path), detection.bank_id)
            return transactions, self._generic_pdf_label(detection), "已使用通用识别", True

        try:
            transactions = extract_transactions(str(path), detection.bank_id)
        except Exception as exc:
            fallback = extract_generic_pdf(str(path))
            if fallback:
                return fallback, self._generic_pdf_label(detection), f"专用解析失败：{exc}；已使用通用识别", True
            raise

        if transactions:
            return transactions, detection.label, "", False

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
                    "reason": "Excel文件导入",
                })()
            else:
                detection = detect_bank_type(str(path))

            try:
                transactions, bank_label, fallback_message, used_generic = self._extract_with_fallback(path, detection)
                account_name = extract_account_name(path)
                original_count = len(transactions)
                transactions = self._filter_transactions(transactions)
                for tx in transactions:
                    tx.source_file = path.name
                    tx.bank_label = bank_label
                file_summary = summarize(transactions, path.name)
                all_issues.extend(file_summary.issues)
                if transactions and not file_summary.issues:
                    status = "通用识别" if used_generic else "正常"
                else:
                    status = "需复核"
                message = fallback_message if transactions else (fallback_message or "未解析到流水")
                if original_count and not transactions:
                    message = "日期范围内没有流水"
                if message and (not transactions or file_summary.issues):
                    all_issues.append(Issue("需复核", path.name, "", message))
                results.append(
                    FileResult(
                        path,
                        detection.bank_id,
                        bank_label,
                        file_summary,
                        transactions,
                        status,
                        message,
                        account_name,
                    )
                )
            except Exception as exc:
                issue = Issue("需复核", path.name, "", f"解析失败: {exc}")
                all_issues.append(issue)
                results.append(FileResult(path, detection.bank_id, detection.label, summarize([]), [], "需复核", str(exc), extract_account_name(path)))

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
        self.setAcceptDrops(True)

        self.summary_label = QLabel("选择 PDF 文件或文件夹后开始处理")
        self.summary_label.setObjectName("summaryLabel")

        add_files = QPushButton("选择文件")
        add_folder = QPushButton("选择文件夹")
        clear = QPushButton("清空")
        run = QPushButton("开始处理")
        export = QPushButton("导出 Excel")
        add_files.clicked.connect(self.add_files)
        add_folder.clicked.connect(self.add_folder)
        clear.clicked.connect(self.clear)
        run.clicked.connect(self.run)
        export.clicked.connect(self.export_excel)

        toolbar = QHBoxLayout()
        for button in (add_files, add_folder, clear, run, export):
            toolbar.addWidget(button)
        toolbar.addStretch(1)

        self.date_filter = QCheckBox("筛选日期")
        self.date_filter.setChecked(True)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        start_date, end_date = default_recent_month_range()
        self.start_date.setDate(start_date)
        self.end_date.setDate(end_date)

        datebar = QHBoxLayout()
        datebar.addWidget(self.date_filter)
        datebar.addWidget(QLabel("从"))
        datebar.addWidget(self.start_date)
        datebar.addWidget(QLabel("到"))
        datebar.addWidget(self.end_date)
        datebar.addStretch(1)

        self.overview = DropTable()
        self.monthly = DropTable()
        self.details = DropTable()
        self.issue_table = DropTable()
        for table in (self.overview, self.monthly, self.details, self.issue_table):
            table.filesDropped.connect(self.add_paths)

        tabs = QTabWidget()
        tabs.addTab(self.monthly, "月度统计")
        tabs.addTab(self.overview, "文件汇总")
        tabs.addTab(self.details, "流水明细")
        tabs.addTab(self.issue_table, "异常提示")

        central = DropWidget()
        central.filesDropped.connect(self.add_paths)
        layout = QVBoxLayout(central)
        layout.addLayout(toolbar)
        layout.addLayout(datebar)
        layout.addWidget(self.summary_label)
        layout.addWidget(tabs)
        self.setCentralWidget(central)
        self.setStatusBar(QStatusBar())

        self._setup_menu()
        self._apply_style()
        self.render_empty()

    def _setup_menu(self):
        export_action = QAction("导出 Excel", self)
        export_action.triggered.connect(self.export_excel)
        self.menuBar().addMenu("文件").addAction(export_action)

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
            QMainWindow { background: #f7f8fa; }
            QPushButton {
                padding: 7px 12px;
                border: 1px solid #c9ced6;
                border-radius: 6px;
                background: #ffffff;
            }
            QPushButton:hover { background: #eef3f8; }
            QTableWidget {
                gridline-color: #d8dde6;
                selection-background-color: #cfe5ff;
                background: #ffffff;
            }
            QHeaderView::section {
                background: #eef1f5;
                padding: 6px;
                border: 0;
                border-right: 1px solid #d8dde6;
                border-bottom: 1px solid #d8dde6;
                font-weight: 600;
            }
            QLabel#summaryLabel {
                padding: 8px 10px;
                background: #ffffff;
                border: 1px solid #d8dde6;
                border-radius: 6px;
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
        self.render_empty()

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

    def render_empty(self):
        self.summary_label.setText("选择 PDF/Excel 文件或文件夹后开始处理；默认输出近半年，可手动修改日期范围。")
        self._set_table(self.overview, ["文件", "状态"], [])
        self._set_table(self.monthly, ["月份", "收入(万元)", "支出(万元)"], [])
        self._set_table(self.details, ["时间", "收入", "支出", "余额"], [])
        self._set_table(self.issue_table, ["级别", "来源", "时间", "提示"], [])

    def render_selected(self):
        rows = [[str(path), "待处理"] for path in self.paths]
        self._set_table(self.overview, ["文件", "状态"], rows)
        self.summary_label.setText(f"已选择 {len(self.paths)} 个文件，点击开始处理。")

    def render_results(self):
        all_transactions, duplicate_issues = dedupe_transactions([tx for result in self.results for tx in result.transactions])
        shown_issues = self.issues + duplicate_issues
        total = summarize(all_transactions, "全部文件")
        self.summary_label.setText(
            f"文件 {len(self.results)} 个，流水 {total.count} 笔，收入 {total.income_count} 笔/{money(total.income_sum)}，"
            f"支出 {total.expense_count} 笔/{money(total.expense_sum)}，净额 {money(total.net)}，"
            f"异常提示 {len(shown_issues)} 条。"
        )

        monthly_rows = build_monthly_rows(all_transactions)
        self._set_table(self.monthly, ["月份", "流水笔数", "收入笔数", "收入(万元)", "支出笔数", "支出(万元)", "净额(万元)", "期初余额(万元)", "期末余额(万元)"], monthly_rows)

        overview_rows = []
        for result in self.results:
            s = result.summary
            overview_rows.append(
                [
                    result.path.name,
                    result.bank_label or BANK_LABELS.get(result.bank_id, ""),
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
            ["文件", "银行", "流水笔数", "收入笔数", "收入", "支出笔数", "支出", "净额", "期初余额", "期末余额", "状态", "说明"],
            overview_rows,
        )

        detail_rows = []
        for tx in sorted(all_transactions, key=lambda item: item.transaction_time):
            detail_rows.append(
                [
                    tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S"),
                    getattr(tx, "source_file", ""),
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
        self._set_table(self.details, ["时间", "文件", "银行", "收入", "支出", "余额", "状态", "提示", "原始金额", "原始余额"], detail_rows)

        issue_rows = [[issue.level, issue.source, issue.time, issue.message, issue.raw_amount, issue.raw_balance] for issue in shown_issues]
        self._set_table(self.issue_table, ["级别", "来源", "时间", "提示", "原始金额", "原始余额"], issue_rows)

    def _set_table(self, table: QTableWidget, headers: list[str], rows: list[list]):
        table.setSortingEnabled(False)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        warn_fill = PatternFill(start_color="FFF3CD", end_color="FFF3CD", fill_type="solid")
        del warn_fill
        for row_index, row in enumerate(rows):
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
        write_workbook(path, self.results, self.issues)
        QMessageBox.information(self, "完成", f"已导出: {path}")


def write_sheet(ws, headers: list[str], rows: list[list]):
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
    desktop = Path.home() / "Desktop"
    if desktop.exists():
        return str(desktop / filename)
    return filename


def safe_filename_part(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", value or "").strip()[:30]


def extract_account_name(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        return extract_pdf_account_name(path)
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        return extract_excel_account_name(path)
    return ""


def extract_pdf_account_name(path: Path) -> str:
    try:
        with pdfplumber.open(str(path)) as pdf:
            if not pdf.pages:
                return ""
            return parse_account_name(pdf.pages[0].extract_text() or "")
    except Exception:
        return ""


def extract_excel_account_name(path: Path) -> str:
    try:
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


def parse_account_name(text: str) -> str:
    for pattern in ACCOUNT_NAME_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
    return ""


def write_workbook(path: Path, results: list[FileResult], issues: list[Issue]):
    wb = Workbook()
    monthly = wb.active
    monthly.title = "月度统计"
    overview = wb.create_sheet("汇总")
    overview_rows = []
    all_transactions = []
    for result in results:
        s = result.summary
        overview_rows.append(
            [
                result.path.name,
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
    write_sheet(overview, ["文件", "银行", "流水笔数", "收入笔数", "收入", "支出笔数", "支出", "净额", "期初余额", "期末余额", "状态", "说明"], overview_rows)

    all_transactions, duplicate_issues = dedupe_transactions(all_transactions)
    shown_issues = issues + duplicate_issues
    monthly_rows = build_monthly_rows(all_transactions, for_excel=True)
    write_sheet(monthly, ["月份", "流水笔数", "收入笔数", "收入(万元)", "支出笔数", "支出(万元)", "净额(万元)", "期初余额(万元)", "期末余额(万元)"], monthly_rows)

    details = wb.create_sheet("明细")
    detail_rows = []
    for tx in sorted(all_transactions, key=lambda item: item.transaction_time):
        detail_rows.append(
            [
                tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S"),
                getattr(tx, "source_file", ""),
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
    write_sheet(details, ["时间", "文件", "银行", "收入", "支出", "余额", "状态", "提示", "原始金额", "原始余额"], detail_rows)

    issue_sheet = wb.create_sheet("异常提示")
    issue_rows = [[issue.level, issue.source, issue.time, issue.message, issue.raw_amount, issue.raw_balance] for issue in shown_issues]
    write_sheet(issue_sheet, ["级别", "来源", "时间", "提示", "原始金额", "原始余额"], issue_rows)

    salary_headers, salary_rows = build_salary_sheet(all_transactions, for_excel=True)
    if salary_rows:
        salary_sheet = wb.create_sheet("工资核算")
        write_sheet(salary_sheet, salary_headers, salary_rows)
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

        if signature in seen:
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

        seen[signature] = tx
        unique.append(tx)

    return unique, issues


def build_monthly_rows(transactions: list, for_excel: bool = False) -> list[list]:
    rows = []
    for month, s in monthly_summaries(transactions):
        rows.append(_summary_row(month, s, for_excel))

    if rows:
        rows.append(_summary_row("总计", summarize(transactions, "总计"), for_excel))
    return rows


def build_salary_sheet(transactions: list, for_excel: bool = False) -> tuple[list[str], list[list]]:
    salary_transactions = [tx for tx in sorted(transactions, key=lambda item: item.transaction_time) if is_salary_transaction(tx)]
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
            result.bank_label or BANK_LABELS.get(result.bank_id, ""),
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


def _summary_row(label: str, s, for_excel: bool) -> list:
    if for_excel:
        return [
            label,
            s.count,
            s.income_count,
            float(to_wan(s.income_sum)),
            s.expense_count,
            float(to_wan(s.expense_sum)),
            float(to_wan(s.net)),
            float(to_wan(s.opening_balance)) if s.opening_balance is not None else None,
            float(to_wan(s.closing_balance)) if s.closing_balance is not None else None,
        ]
    return [
        label,
        s.count,
        s.income_count,
        money_wan(s.income_sum),
        s.expense_count,
        money_wan(s.expense_sum),
        money_wan(s.net),
        money_wan(s.opening_balance),
        money_wan(s.closing_balance),
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
    start = month_start.addMonths(-5)
    end = QDate(today.year(), today.month(), today.daysInMonth())
    return start, end


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
