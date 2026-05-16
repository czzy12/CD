import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QAction, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
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
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.summary import Issue, money, monthly_summaries, summarize


@dataclass
class FileResult:
    path: Path
    bank_id: str
    bank_label: str
    summary: object
    transactions: list
    status: str
    message: str


class DropTable(QTableWidget):
    filesDropped = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)

    def dragEnterEvent(self, event):
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


class Worker(QThread):
    finished = pyqtSignal(list, list)
    progress = pyqtSignal(str)

    def __init__(self, paths: list[Path]):
        super().__init__()
        self.paths = paths

    def run(self):
        results: list[FileResult] = []
        all_issues: list[Issue] = []

        for path in self.paths:
            self.progress.emit(f"处理中: {path.name}")
            detection = detect_bank_type(str(path))
            if not detection.bank_id:
                issue = Issue("需复核", path.name, "", detection.reason)
                all_issues.append(issue)
                results.append(FileResult(path, "", "未识别", summarize([]), [], "需复核", detection.reason))
                continue

            try:
                transactions = extract_transactions(str(path), detection.bank_id)
                for tx in transactions:
                    tx.source_file = path.name
                    tx.bank_label = detection.label
                file_summary = summarize(transactions, path.name)
                all_issues.extend(file_summary.issues)
                status = "正常" if transactions and not file_summary.issues else "需复核"
                message = "" if transactions else "未解析到流水"
                if message:
                    all_issues.append(Issue("需复核", path.name, "", message))
                results.append(
                    FileResult(
                        path,
                        detection.bank_id,
                        detection.label,
                        file_summary,
                        transactions,
                        status,
                        message,
                    )
                )
            except Exception as exc:
                issue = Issue("需复核", path.name, "", f"解析失败: {exc}")
                all_issues.append(issue)
                results.append(FileResult(path, detection.bank_id, detection.label, summarize([]), [], "需复核", str(exc)))

        self.finished.emit(results, all_issues)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("银行流水 PDF 解析")
        self.resize(1280, 760)
        self.paths: list[Path] = []
        self.results: list[FileResult] = []
        self.issues: list[Issue] = []
        self.worker: Worker | None = None

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

        self.overview = DropTable()
        self.monthly = DropTable()
        self.details = DropTable()
        self.issue_table = DropTable()
        for table in (self.overview, self.monthly, self.details, self.issue_table):
            table.filesDropped.connect(self.add_paths)

        tabs = QTabWidget()
        tabs.addTab(self.overview, "文件汇总")
        tabs.addTab(self.monthly, "月度统计")
        tabs.addTab(self.details, "流水明细")
        tabs.addTab(self.issue_table, "异常提示")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(toolbar)
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
        files, _ = QFileDialog.getOpenFileNames(self, "选择银行流水 PDF", "", "PDF 文件 (*.pdf)")
        self.add_paths([Path(file) for file in files])

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择包含 PDF 的文件夹")
        if folder:
            self.add_paths([Path(folder)])

    def add_paths(self, paths: list[Path]):
        pdfs: list[Path] = []
        for path in paths:
            if path.is_dir():
                pdfs.extend(sorted(path.rglob("*.pdf")))
            elif path.suffix.lower() == ".pdf":
                pdfs.append(path)
        known = {p.resolve() for p in self.paths}
        for pdf in pdfs:
            resolved = pdf.resolve()
            if resolved not in known:
                self.paths.append(pdf)
                known.add(resolved)
        self.render_selected()

    def clear(self):
        self.paths = []
        self.results = []
        self.issues = []
        self.render_empty()

    def run(self):
        if not self.paths:
            QMessageBox.information(self, "提示", "请先选择 PDF 文件或文件夹。")
            return
        self.worker = Worker(self.paths)
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def on_finished(self, results: list[FileResult], issues: list[Issue]):
        self.results = results
        self.issues = issues
        self.render_results()
        self.statusBar().showMessage("处理完成")

    def render_empty(self):
        self.summary_label.setText("选择 PDF 文件或文件夹后开始处理；可直接拖入文件/文件夹。")
        self._set_table(self.overview, ["文件", "状态"], [])
        self._set_table(self.monthly, ["月份", "收入", "支出"], [])
        self._set_table(self.details, ["时间", "收入", "支出", "余额"], [])
        self._set_table(self.issue_table, ["级别", "来源", "时间", "提示"], [])

    def render_selected(self):
        rows = [[str(path), "待处理"] for path in self.paths]
        self._set_table(self.overview, ["文件", "状态"], rows)
        self.summary_label.setText(f"已选择 {len(self.paths)} 个 PDF，点击开始处理。")

    def render_results(self):
        all_transactions, duplicate_issues = dedupe_transactions([tx for result in self.results for tx in result.transactions])
        shown_issues = self.issues + duplicate_issues
        total = summarize(all_transactions, "全部文件")
        self.summary_label.setText(
            f"文件 {len(self.results)} 个，流水 {total.count} 笔，收入 {total.income_count} 笔/{money(total.income_sum)}，"
            f"支出 {total.expense_count} 笔/{money(total.expense_sum)}，净额 {money(total.net)}，"
            f"异常提示 {len(shown_issues)} 条。"
        )

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

        monthly_rows = build_monthly_rows(all_transactions)
        self._set_table(self.monthly, ["月份", "流水笔数", "收入笔数", "收入", "支出笔数", "支出", "净额", "期初余额", "期末余额"], monthly_rows)

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
        file_name, _ = QFileDialog.getSaveFileName(self, "导出 Excel", "银行流水解析结果.xlsx", "Excel 文件 (*.xlsx)")
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


def write_workbook(path: Path, results: list[FileResult], issues: list[Issue]):
    wb = Workbook()
    overview = wb.active
    overview.title = "汇总"
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

    monthly = wb.create_sheet("月度统计")
    monthly_rows = build_monthly_rows(all_transactions, for_excel=True)
    write_sheet(monthly, ["月份", "流水笔数", "收入笔数", "收入", "支出笔数", "支出", "净额", "期初余额", "期末余额"], monthly_rows)

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


def _summary_row(label: str, s, for_excel: bool) -> list:
    if for_excel:
        return [
            label,
            s.count,
            s.income_count,
            float(s.income_sum),
            s.expense_count,
            float(s.expense_sum),
            float(s.net),
            float(s.opening_balance) if s.opening_balance is not None else None,
            float(s.closing_balance) if s.closing_balance is not None else None,
        ]
    return [
        label,
        s.count,
        s.income_count,
        money(s.income_sum),
        s.expense_count,
        money(s.expense_sum),
        money(s.net),
        money(s.opening_balance),
        money(s.closing_balance),
    ]


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
