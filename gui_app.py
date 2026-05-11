"""
银行流水PDF提取工具 GUI v2
"""
import sys
import os
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QTabWidget,
    QCheckBox, QComboBox, QGroupBox, QFileDialog, QMessageBox,
    QHeaderView, QFrame, QProgressBar, QStatusBar,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QDragEnterEvent, QDropEvent, QKeyEvent


class CopyableTable(QTableWidget):
    """支持 Ctrl+C 复制选中区域（制表符分隔，可直接粘贴到Excel）"""
    def keyPressEvent(self, event: QKeyEvent):
        if event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_C:
            self._copy_selection()
        else:
            super().keyPressEvent(event)

    def _copy_selection(self):
        selected = self.selectedRanges()
        if not selected:
            return
        # 收集所有选中单元格
        rows = set()
        cols = set()
        for rng in selected:
            for r in range(rng.topRow(), rng.bottomRow() + 1):
                for c in range(rng.leftColumn(), rng.rightColumn() + 1):
                    rows.add(r)
                    cols.add(c)
        if not rows or not cols:
            return
        rows = sorted(rows)
        cols = sorted(cols)
        lines = []
        for r in rows:
            line = []
            for c in cols:
                item = self.item(r, c)
                line.append(item.text() if item else "")
            lines.append("\t".join(line))
        QApplication.clipboard().setText("\n".join(lines))

from core.pipeline import process_pdf, get_default_date_range
from output.aggregator import build_summary_rows, build_balance_text, build_verify_text


class ProcessWorker(QThread):
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, pdf_path: str, date_range_str: str = None):
        super().__init__()
        self.pdf_path = pdf_path
        self.date_range_str = date_range_str

    def run(self):
        try:
            self.progress.emit("正在识别银行...")
            result = process_pdf(self.pdf_path, date_range_str=self.date_range_str)
            self.progress.emit(f"提取完成: {len(result['df'])} 笔")
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.result_data = None
        self.setWindowTitle("银行流水PDF提取工具")
        self.setMinimumSize(900, 600)
        self._setup_ui()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(15, 12, 15, 12)

        # === 文件拖拽 ===
        drop_frame = QFrame()
        drop_frame.setAcceptDrops(True)
        drop_frame.dragEnterEvent = self._on_drag_enter
        drop_frame.dragLeaveEvent = self._on_drag_leave
        drop_frame.dropEvent = self._on_drop
        drop_frame.setMinimumHeight(80)
        drop_frame.setMaximumHeight(90)
        drop_frame.setStyleSheet("""
            QFrame { background: #f8f9fa; border: 2px dashed #adb5bd; border-radius: 6px; }
            QFrame:hover { border-color: #4361ee; background: #eef0ff; }
        """)
        drop_inner = QVBoxLayout(drop_frame)
        drop_inner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.drop_label = QLabel("拖拽PDF文件到此处，或点击选择")
        self.drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.drop_label.setStyleSheet("color: #6c757d; font-size: 14px; border: none;")
        drop_inner.addWidget(self.drop_label)

        self.file_label = QLabel("")
        self.file_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.file_label.setStyleSheet("color: #495057; font-size: 11px; border: none;")
        drop_inner.addWidget(self.file_label)
        layout.addWidget(drop_frame)

        # === 日期范围 + 按钮 ===
        ctrl_layout = QHBoxLayout()

        self.default_range_cb = QCheckBox("近6个月")
        self.default_range_cb.setChecked(True)
        self.default_range_cb.toggled.connect(self._on_range_toggle)
        ctrl_layout.addWidget(self.default_range_cb)

        # 月份下拉：当年 ± 1 年
        now = datetime.now()
        self._month_options = []
        for y in range(now.year - 1, now.year + 2):
            for m in range(1, 13):
                self._month_options.append(f"{y}年{m:02d}月")

        default_start, default_end = get_default_date_range()
        default_start_str = f"{default_start.year}年{default_start.month:02d}月"
        default_end_str = f"{default_end.year}年{default_end.month:02d}月"

        ctrl_layout.addWidget(QLabel("从"))
        self.start_combo = QComboBox()
        self.start_combo.addItems(self._month_options)
        self.start_combo.setCurrentText(default_start_str)
        self.start_combo.setEnabled(False)
        self.start_combo.setMinimumWidth(100)
        ctrl_layout.addWidget(self.start_combo)

        ctrl_layout.addWidget(QLabel("至"))
        self.end_combo = QComboBox()
        self.end_combo.addItems(self._month_options)
        self.end_combo.setCurrentText(default_end_str)
        self.end_combo.setEnabled(False)
        self.end_combo.setMinimumWidth(100)
        ctrl_layout.addWidget(self.end_combo)

        self.process_btn = QPushButton("开始处理")
        self.process_btn.setEnabled(False)
        self.process_btn.clicked.connect(self._on_process)
        self.process_btn.setStyleSheet("""
            QPushButton { padding: 6px 24px; background: #4361ee; color: white;
                          border: none; border-radius: 4px; font-size: 13px; font-weight: bold; }
            QPushButton:hover { background: #3a56d4; }
            QPushButton:disabled { background: #adb5bd; }
        """)
        ctrl_layout.addWidget(self.process_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumWidth(150)
        ctrl_layout.addWidget(self.progress_bar)
        ctrl_layout.addStretch()
        layout.addLayout(ctrl_layout)

        # === 结果区 ===
        self.result_tabs = QTabWidget()
        self.result_tabs.setVisible(False)

        # Tab: 月度汇总
        self.summary_widget = QWidget()
        summary_layout = QVBoxLayout(self.summary_widget)

        self.balance_label = QLabel()
        self.balance_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.balance_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.balance_label.setStyleSheet("""
            font-size: 16px; font-weight: bold; padding: 8px;
            color: #2b2d42; background: #edf2f4; border-radius: 4px;
        """)
        summary_layout.addWidget(self.balance_label)

        self.verify_label = QLabel()
        self.verify_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.verify_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.verify_label.setStyleSheet("""
            font-size: 13px; padding: 4px; color: #495057;
        """)
        summary_layout.addWidget(self.verify_label)

        self.summary_table = CopyableTable()
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionMode(QTableWidget.SelectionMode.ContiguousSelection)
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        summary_layout.addWidget(self.summary_table)

        self.result_tabs.addTab(self.summary_widget, "月度汇总")

        # Tab: 明细（保留备用）
        self.detail_table = CopyableTable()
        self.detail_table.setAlternatingRowColors(True)
        self.detail_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.result_tabs.addTab(self.detail_table, "交易明细")

        layout.addWidget(self.result_tabs)

        # === 状态栏 ===
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

        # 拖拽区域点击选文件
        drop_frame.mousePressEvent = lambda e: self._on_select_file()

    def _on_drag_enter(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
            self.drop_label.setText("释放以加载PDF")
            self.drop_label.setStyleSheet("color: #4361ee; font-size: 14px; font-weight: bold; border: none;")

    def _on_drag_leave(self, event):
        self.drop_label.setText("拖拽PDF文件到此处，或点击选择")
        self.drop_label.setStyleSheet("color: #6c757d; font-size: 14px; border: none;")

    def _on_drop(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.lower().endswith(".pdf"):
                self._set_pdf_path(path)
        self._on_drag_leave(event)

    def _on_select_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择PDF文件", "", "PDF (*.pdf);;所有文件 (*)")
        if path:
            self._set_pdf_path(path)

    def _set_pdf_path(self, path: str):
        self.pdf_path = path
        fname = Path(path).name
        fsize = os.path.getsize(path) / 1024
        self.file_label.setText(f"{fname} ({fsize:.0f} KB)")
        self.process_btn.setEnabled(True)

    def _on_range_toggle(self, checked):
        self.start_combo.setEnabled(not checked)
        self.end_combo.setEnabled(not checked)

    def _get_date_range_str(self) -> str:
        if self.default_range_cb.isChecked():
            return None
        import re
        s = self.start_combo.currentText()
        e = self.end_combo.currentText()
        sm = re.match(r"(\d{4})年(\d{2})月", s)
        em = re.match(r"(\d{4})年(\d{2})月", e)
        if sm and em:
            return f"{sm.group(1)}-{sm.group(2)}~{em.group(1)}-{em.group(2)}"
        return None

    def _on_process(self):
        if not hasattr(self, "pdf_path"):
            return
        self.process_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_bar.showMessage("处理中...")

        self.worker = ProcessWorker(self.pdf_path, self._get_date_range_str())
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, msg: str):
        self.status_bar.showMessage(msg)

    def _on_finished(self, result: dict):
        self.progress_bar.setVisible(False)
        self.process_btn.setEnabled(True)
        self.result_data = result
        df = result["df"]

        if df.empty:
            QMessageBox.warning(self, "无数据", "未提取到流水数据")
            return

        balance_text = build_balance_text(df)
        self.balance_label.setText(f"收入 {balance_text}")

        verify_text = build_verify_text(df)
        self.verify_label.setText(verify_text)
        self.verify_label.setVisible(bool(verify_text))

        # 月度汇总表
        rows = build_summary_rows(df)
        headers = ["月份", "收入(笔数)", "收入", "支出(笔数)", "支出"]
        self._set_table(self.summary_table, headers, rows)

        # 明细表
        detail_cols = ["日期", "交易类型", "金额", "收支方向", "收入金额", "支出金额", "对方名称"]
        available = [c for c in detail_cols if c in df.columns]
        detail_rows = [[str(row.get(c, "")) for c in available] for _, row in df.iterrows()]
        self._set_table(self.detail_table, available, detail_rows)

        self.result_tabs.setVisible(True)

        dr = result.get("date_range")
        dr_text = f"{dr[0]}~{dr[1]}" if dr else "全部"
        self.status_bar.showMessage(f"{result['bank_name']} | {len(df)}笔 | {dr_text}")

    def _on_error(self, msg: str):
        self.progress_bar.setVisible(False)
        self.process_btn.setEnabled(True)
        QMessageBox.critical(self, "错误", f"处理失败:\n{msg}")
        self.status_bar.showMessage("失败")

    def _set_table(self, table: QTableWidget, headers: list, rows: list):
        table.clear()
        table.setRowCount(len(rows))
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setSortingEnabled(True)

        for r, row_data in enumerate(rows):
            for c, val in enumerate(row_data):
                item = QTableWidgetItem(str(val) if val is not None else "")
                # 合计行和月均行加粗
                if r >= len(rows) - 2:
                    font = item.font()
                    font.setBold(True)
                    item.setFont(font)
                table.setItem(r, c, item)

        table.resizeColumnsToContents()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet("""
        QMainWindow { background: #ffffff; }
        QGroupBox { font-weight: bold; border: 1px solid #dee2e6; border-radius: 4px;
                    margin-top: 6px; padding-top: 16px; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
        QTableWidget { gridline-color: #dee2e6; font-size: 12px; }
        QTableWidget::item { padding: 3px 8px; }
        QHeaderView::section { background: #e9ecef; padding: 5px; font-weight: bold; }
        QComboBox { padding: 2px 6px; }
    """)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
