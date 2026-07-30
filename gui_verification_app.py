"""Standalone entry point for the schema 1.16 verification workbench."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
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
    transactions_from_standard_result,
)
from bankflow_v2.result_export import (
    rebuild_business_context_result,
    write_bankflow_json,
)
from bankflow_v2.verification_worker import (
    SUPPORTED_INPUTS,
    VerificationWorker,
)
from gui_verification import VerificationWorkspace


MANUAL_CASE_CONTEXT_FILENAME = "manual_case_context.json"
STANDARD_RESULT_FILENAME = "bankflow_verification_result.json"


def load_manual_case_context(case_dir: Path) -> dict[str, object]:
    path = case_dir / MANUAL_CASE_CONTEXT_FILENAME
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_manual_case_context(
    case_dir: Path,
    extracted_context: dict[str, object],
    confirmation: dict[str, object],
) -> dict[str, object]:
    confirmed_at = datetime.now(timezone.utc).isoformat()
    record = {
        "schema_version": "1.0",
        "case_id": case_dir.name,
        "original_extracted_information": {
            "sources": extracted_context.get("sources", []),
            "work_units": extracted_context.get("search_context", {}).get(
                "work_units",
                [],
            ),
            "business_context": extracted_context.get("business_context", {}),
        },
        "manual_confirmation": {
            "confirmed_primary_business": confirmation.get(
                "confirmed_primary_business",
                "",
            ),
            "confirmed_products_or_services": confirmation.get(
                "confirmed_products_or_services",
                "",
            ),
            "confirmation_note": confirmation.get("confirmation_note", ""),
            "confirmation_status": confirmation.get(
                "confirmation_status",
                "unconfirmed",
            ),
        },
        "source": {
            "type": "gui_manual_confirmation",
            "file": MANUAL_CASE_CONTEXT_FILENAME,
        },
        "confirmation_status": confirmation.get(
            "confirmation_status",
            "unconfirmed",
        ),
        "confirmed_by": confirmation.get("confirmed_by", ""),
        "confirmed_at": confirmed_at,
        "ai_business_assistance_enabled": bool(
            confirmation.get("ai_business_assistance_enabled")
        ),
    }
    path = case_dir / MANUAL_CASE_CONTEXT_FILENAME
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return record


def business_confirmation_from_record(
    record: dict[str, object],
) -> dict[str, object]:
    value = record.get("manual_confirmation")
    return dict(value) if isinstance(value, dict) else {}


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
        self._pending_paths: list[Path] = []
        self._base_case_context: dict[str, object] = {}
        self._manual_context: dict[str, object] = {}
        self._transactions: list = []
        self._preparation_reanalysis = False
        self.workspace = VerificationWorkspace()
        self.workspace.legacy_button.hide()
        self.workspace.selectCaseRequested.connect(self.select_case_directory)
        self.workspace.openCaseRequested.connect(self.open_existing_case)
        self.workspace.loadResultRequested.connect(self.load_standard_result_file)
        self.workspace.cancelRequested.connect(self.cancel_current_task)
        self.workspace.settingsRequested.connect(
            lambda: self.workspace.navigate("settings")
        )
        self.workspace.preparationConfirmed.connect(
            self.confirm_case_preparation
        )
        self.workspace.preparationSkipped.connect(
            self.skip_case_preparation
        )
        self.workspace.preparationBackRequested.connect(
            self.back_from_case_preparation
        )
        self.workspace.businessPreparationRequested.connect(
            self.open_business_preparation
        )
        self.setCentralWidget(self.workspace)
        self.setStatusBar(QStatusBar())

    def select_case_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择客户资料目录")
        if not folder:
            return
        self.start_case_directory(Path(folder))

    def start_case_directory(self, case_dir: Path) -> None:
        paths = sorted(
            path
            for path in case_dir.rglob("*")
            if path.suffix.lower() in SUPPORTED_INPUTS
        )
        self.case_dir = case_dir
        self._pending_paths = paths
        if not paths:
            self.workspace.show_result_error(
                "目录中未找到支持的 PDF/Excel 流水文件。"
            )
            return
        try:
            self._base_case_context = build_case_context_from_directory(
                case_dir
            )
        except OSError as exc:
            self._base_case_context = {}
            self.workspace.add_source_error("客户资料", str(exc))
        self._manual_context = load_manual_case_context(case_dir)
        self._preparation_reanalysis = False
        self.workspace.show_case_preparation(
            self._base_case_context,
            self._manual_context,
        )

    def confirm_case_preparation(self, confirmation: object) -> None:
        if self.case_dir is None or not isinstance(confirmation, dict):
            return
        self._manual_context = save_manual_case_context(
            self.case_dir,
            self._base_case_context,
            confirmation,
        )
        case_context = build_case_context_from_directory(
            self.case_dir,
            business_confirmation=business_confirmation_from_record(
                self._manual_context
            ),
        )
        ai_enabled = bool(
            self._manual_context.get("ai_business_assistance_enabled")
        )
        ai_api_key = str(confirmation.get("ai_api_key") or "")
        if self._preparation_reanalysis:
            self._rebuild_business_context(
                case_context,
                ai_enabled,
                ai_api_key,
            )
            return
        self._start_full_analysis(case_context, ai_enabled, ai_api_key)

    def skip_case_preparation(self) -> None:
        if self.case_dir is None:
            return
        existing_confirmation = business_confirmation_from_record(
            self._manual_context
        )
        if existing_confirmation.get("confirmation_status") == "confirmed":
            case_context = build_case_context_from_directory(
                self.case_dir,
                business_confirmation=existing_confirmation,
            )
            self._start_full_analysis(case_context, False)
            return
        confirmation = {
            "confirmed_primary_business": "",
            "confirmed_products_or_services": "",
            "confirmation_note": "用户选择暂不补充，继续分析。",
            "confirmation_status": "unconfirmed",
            "confirmed_by": "",
            "ai_business_assistance_enabled": False,
        }
        self._manual_context = save_manual_case_context(
            self.case_dir,
            self._base_case_context,
            confirmation,
        )
        self._start_full_analysis(self._base_case_context, False)

    def back_from_case_preparation(self) -> None:
        self._preparation_reanalysis = False
        self.workspace.navigate("home")

    def _explicit_ai_runtime(
        self,
        enabled: bool,
        api_key: str = "",
    ):
        if not enabled:
            return {}, None
        from bankflow_v2.deepseek_adapter import load_deepseek_runtime

        explicit_environment = dict(os.environ)
        explicit_environment.update(
            {
                "BANKFLOW_AI_ENABLED": "true",
                "BANKFLOW_AI_DATA_AUTHORIZED": "true",
                "BANKFLOW_AI_RETENTION_CONFIRMED": "true",
                "BANKFLOW_AI_ALLOW_BUSINESS_NAMES": "true",
            }
        )
        if api_key:
            explicit_environment["BANKFLOW_AI_API_KEY"] = api_key
        return load_deepseek_runtime(explicit_environment)

    def _start_full_analysis(
        self,
        case_context: dict[str, object],
        ai_enabled: bool,
        ai_api_key: str = "",
    ) -> None:
        if self.case_dir is None:
            return
        paths = self._pending_paths
        self.workspace.set_busy(self.case_dir.name, len(paths))
        passwords = self.collect_pdf_passwords(paths)
        if passwords is None:
            self.workspace.set_cancelled()
            return
        ai_config, ai_evaluator = self._explicit_ai_runtime(
            ai_enabled,
            ai_api_key,
        )
        self.worker = VerificationWorker(
            paths,
            pdf_passwords=passwords,
            case_context=case_context,
            ai_config=ai_config,
            ai_evaluator=ai_evaluator,
        )
        self.worker.progress.connect(self.statusBar().showMessage)
        self.worker.stage_progress.connect(self.workspace.set_progress)
        self.worker.source_error.connect(self.workspace.add_source_error)
        self.worker.cancelled.connect(self.workspace.set_cancelled)
        self.worker.failed.connect(self.on_task_failed)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def open_business_preparation(self) -> None:
        if self.case_dir is None:
            QMessageBox.information(
                self,
                "无法保存经营上下文",
                "当前结果不是从案件工作区打开，无法持久化人工经营信息。"
                "请从案件目录打开或新建案件。",
            )
            return
        self._base_case_context = build_case_context_from_directory(
            self.case_dir
        )
        self._manual_context = load_manual_case_context(self.case_dir)
        self._preparation_reanalysis = True
        self.workspace.show_case_preparation(
            self._base_case_context,
            self._manual_context,
            reanalysis=True,
        )

    def _rebuild_business_context(
        self,
        case_context: dict[str, object],
        ai_enabled: bool,
        ai_api_key: str = "",
    ) -> None:
        if self.workspace._result is None or self.case_dir is None:
            return
        if not self._transactions:
            self._transactions = transactions_from_standard_result(
                self.workspace._result
            )
        ai_config, ai_evaluator = self._explicit_ai_runtime(
            ai_enabled,
            ai_api_key,
        )
        rebuilt = rebuild_business_context_result(
            dict(self.workspace._result),
            self._transactions,
            case_context,
            ai_config=ai_config,
            ai_evaluator=ai_evaluator,
        )
        write_bankflow_json(
            rebuilt,
            self.case_dir / STANDARD_RESULT_FILENAME,
        )
        self.workspace.set_result(rebuilt, self.case_dir.name)
        self.workspace.open_module("business")
        self._preparation_reanalysis = False
        self.statusBar().showMessage("经营关联及相关核实事项已重新分析")

    def open_existing_case(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "打开已有案件")
        if not folder:
            return
        case_dir = Path(folder)
        candidates = sorted(
            case_dir.rglob("*.json"),
            key=lambda path: (
                path.name == STANDARD_RESULT_FILENAME,
                path.stat().st_mtime,
            ),
            reverse=True,
        )
        errors: list[str] = []
        for candidate in candidates:
            try:
                result = load_standard_result(candidate)
            except (OSError, StandardResultError) as exc:
                errors.append(str(exc))
                continue
            self.case_dir = case_dir
            self._pending_paths = sorted(
                path
                for path in case_dir.rglob("*")
                if path.suffix.lower() in SUPPORTED_INPUTS
            )
            self._base_case_context = build_case_context_from_directory(
                case_dir
            )
            self._manual_context = load_manual_case_context(case_dir)
            self._transactions = transactions_from_standard_result(result)
            self.workspace.set_result(result, case_dir.name)
            self.statusBar().showMessage(
                f"已读取已有标准结果：{candidate.name}"
            )
            return
        message = "该案件目录中没有可读取的 schema 1.16 标准结果。"
        if errors:
            message += " 已发现JSON，但版本或结构不兼容。"
        answer = QMessageBox.question(
            self,
            "未找到已有标准结果",
            f"{message}\n\n是否改为解析该目录并新建流水核查？",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.start_case_directory(case_dir)

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
            "打开schema 1.16标准结果JSON",
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
        self._transactions = transactions_from_standard_result(result)
        self.workspace.set_result(result, Path(filename).stem)

    def cancel_current_task(self) -> None:
        if self.worker is None or not self.worker.isRunning():
            return
        self.worker.requestInterruption()
        self.workspace.set_cancel_pending()

    def on_finished(self, results, issues, standard_result) -> None:
        case_name = self.case_dir.name if self.case_dir else "当前案例"
        self._transactions = [
            transaction
            for source_result in results
            for transaction in source_result.transactions
        ]
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
        if self.case_dir is not None:
            write_bankflow_json(
                standard_result,
                self.case_dir / STANDARD_RESULT_FILENAME,
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
