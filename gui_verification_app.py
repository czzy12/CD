"""Standalone entry point for the schema 1.16 verification workbench."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QStatusBar,
)

from bankflow_v2.standard_result_view import (
    StandardResultError,
    build_case_context_from_directory,
    load_standard_result,
)
from bankflow_v2.verification_worker import (
    SUPPORTED_INPUTS,
    VerificationWorker,
)
from gui_verification import VerificationWorkspace


def apply_workbench_palette(app: QApplication) -> None:
    """Keep the workbench light even when Windows uses a dark application theme."""
    app.setStyle("Fusion")
    palette = QPalette()
    roles = QPalette.ColorRole
    groups = QPalette.ColorGroup
    palette.setColor(roles.Window, QColor("#F3EDDF"))
    palette.setColor(roles.WindowText, QColor("#171713"))
    palette.setColor(roles.Base, QColor("#FFF9EC"))
    palette.setColor(roles.AlternateBase, QColor("#F7EBCF"))
    palette.setColor(roles.Text, QColor("#171713"))
    palette.setColor(roles.Button, QColor("#FFF9EC"))
    palette.setColor(roles.ButtonText, QColor("#171713"))
    palette.setColor(roles.Highlight, QColor("#F4C84A"))
    palette.setColor(roles.HighlightedText, QColor("#171713"))
    palette.setColor(groups.Disabled, roles.WindowText, QColor("#8F8A80"))
    palette.setColor(groups.Disabled, roles.Text, QColor("#8F8A80"))
    palette.setColor(groups.Disabled, roles.ButtonText, QColor("#8F8A80"))
    app.setPalette(palette)


class VerificationMainWindow(QMainWindow):
    """Independent shell that shares only the existing parsing backend."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("流水核查工作台")
        self.resize(1500, 900)
        self.setMinimumSize(1180, 720)
        self.worker: VerificationWorker | None = None
        self.case_dir: Path | None = None
        self.workspace = VerificationWorkspace()
        self.workspace.legacy_button.hide()
        self.workspace.selectCaseRequested.connect(self.select_case_directory)
        self.workspace.loadResultRequested.connect(self.load_standard_result_file)
        self.workspace.cancelRequested.connect(self.cancel_current_task)
        self.setCentralWidget(self.workspace)
        self.setStatusBar(QStatusBar())

    def select_case_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择客户资料目录")
        if not folder:
            return
        case_dir = Path(folder)
        paths = sorted(
            path
            for path in case_dir.rglob("*")
            if path.suffix.lower() in SUPPORTED_INPUTS
        )
        self.case_dir = case_dir
        self.workspace.set_busy(case_dir.name, len(paths))
        if not paths:
            self.workspace.show_result_error(
                "目录中未找到支持的 PDF/Excel 流水文件。"
            )
            return
        try:
            case_context = build_case_context_from_directory(case_dir)
        except OSError as exc:
            case_context = {}
            self.workspace.add_source_error("客户资料", str(exc))
        passwords = self.collect_pdf_passwords(paths)
        if passwords is None:
            self.workspace.set_cancelled()
            return
        self.worker = VerificationWorker(
            paths,
            pdf_passwords=passwords,
            case_context=case_context,
        )
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.stage_progress.connect(self.workspace.set_progress)
        self.worker.source_error.connect(self.workspace.add_source_error)
        self.worker.cancelled.connect(self.workspace.set_cancelled)
        self.worker.failed.connect(self.on_task_failed)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def collect_pdf_passwords(
        self,
        paths: list[Path],
    ) -> dict[Path, str] | None:
        from bankflow_v2.pdf_password import (
            pdf_requires_password,
            validate_pdf_password,
        )

        passwords: dict[Path, str] = {}
        last_password = ""
        for path in paths:
            if path.suffix.lower() != ".pdf":
                continue
            try:
                needs_password = pdf_requires_password(path)
            except Exception:
                needs_password = False
            if not needs_password:
                continue
            if last_password and validate_pdf_password(path, last_password):
                passwords[path] = last_password
                continue
            while True:
                password, accepted = QInputDialog.getText(
                    self,
                    "PDF密码",
                    f"{path.name} 需要密码，请输入后继续解析。",
                    QLineEdit.EchoMode.Password,
                    last_password,
                )
                if not accepted:
                    return None
                if validate_pdf_password(path, password):
                    passwords[path] = password
                    last_password = password
                    break
                QMessageBox.warning(
                    self,
                    "密码错误",
                    f"{path.name} 密码不正确，请重新输入。",
                )
        return passwords

    def load_standard_result_file(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "打开历史标准结果",
            "",
            "schema 1.16 标准结果 (*.json);;JSON 文件 (*.json)",
        )
        if not filename:
            return
        try:
            result = load_standard_result(Path(filename))
        except StandardResultError as exc:
            self.workspace.show_result_error(str(exc))
            QMessageBox.warning(self, "标准结果不兼容", str(exc))
            return
        self.case_dir = None
        self.workspace.set_result(result, Path(filename).stem)

    def cancel_current_task(self) -> None:
        if self.worker is None or not self.worker.isRunning():
            return
        self.worker.requestInterruption()
        self.workspace.set_cancel_pending()

    def on_finished(self, results, issues, standard_result) -> None:
        case_name = self.case_dir.name if self.case_dir else "当前案例"
        source_messages = [
            f"{result.path.name}: {result.status}"
            + (f" - {result.message}" if result.message else "")
            for result in results
        ]
        self.workspace.set_result(
            standard_result,
            case_name,
            source_messages=source_messages,
        )
        self.statusBar().showMessage("处理完成")

    def on_task_failed(self, message: str) -> None:
        self.workspace.show_result_error(message)
        self.statusBar().showMessage(message)


def main() -> int:
    app = QApplication(sys.argv)
    apply_workbench_palette(app)
    window = VerificationMainWindow()
    if "--smoke-test" in sys.argv:
        window.show()
        app.processEvents()
        print("verification-workbench-started")
        window.close()
        return 0
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
