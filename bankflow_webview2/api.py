"""Whitelisted pywebview JavaScript API backed by the existing read-only session."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from bankflow_web.case_session import CaseSession
from bankflow_web.case_workspace import (
    STANDARD_RESULT_FILENAME,
    business_confirmation_from_record,
    load_manual_case_context as load_workspace_manual_context,
    save_manual_case_context as save_workspace_manual_context,
    standard_result_path,
)
from bankflow_web.contracts import (
    AiRuntimeStatusDTO,
    AppStateDTO,
    ApplicationError,
    ExportReportDTO,
    ManualContextDTO,
    ManualContextSaveDTO,
    RecentCaseDTO,
    RecentCasesDTO,
    to_dict,
)
from bankflow_web.analysis.source_discovery import CaseDirectoryRegistry
from bankflow_web.analysis.task_manager import AnalysisTaskManager
from bankflow_v2.deepseek_adapter import load_deepseek_runtime
from bankflow_v2.mvp_report import render_mvp_markdown
from bankflow_v2.result_export import rebuild_business_context_result, write_bankflow_json
from bankflow_v2.standard_result_view import (
    StandardResultError,
    build_case_context_from_directory,
    load_standard_result,
    transactions_from_standard_result,
)
from recent_cases import RecentCaseStore
from bankflow_web.case_workspace import recent_cases_path

from .bridge_adapter import PyWebviewBridgeAdapter


STANDARD_RESULT_FILE_FILTER = "JSON 标准结果 (*.json)"
STANDARD_RESULT_SAVE_FILTER = "JSON 标准结果 (*.json)"
REPORT_SAVE_FILTER = "Markdown 报告 (*.md)"


class WebView2Api:
    """Only public methods on this class are exposed to JavaScript."""

    def __init__(
        self,
        session: CaseSession | None = None,
        *,
        recent_store: RecentCaseStore | None = None,
    ) -> None:
        self._session = session or CaseSession()
        self._bridge = PyWebviewBridgeAdapter()
        self._lock = threading.RLock()
        self._window: Any = None
        self._loading = False
        self._closed = threading.Event()
        self._frontend_ready = threading.Event()
        self._frontend_ready_at: float | None = None
        self._case_directories = CaseDirectoryRegistry()
        self._inspected_cases: set[str] = set()
        self._current_case_dir: Path | None = None
        self._recent_store = recent_store or RecentCaseStore(recent_cases_path())
        self._tasks = AnalysisTaskManager(self._promote_analysis_result)

    def _attach_window(self, window: Any) -> None:
        self._window = window

    def _promote_analysis_result(self, result: dict[str, object], case_name: str) -> tuple[str, int, int]:
        with self._lock:
            if self._closed.is_set():
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口正在关闭")
            self._session.load_result_dict(result, case_name=case_name, origin="analysis")
            header = self._session.adapter().case_header()
            saved_result_path = None
            if self._current_case_dir is not None:
                saved_result_path = standard_result_path(self._current_case_dir)
                write_bankflow_json(result, saved_result_path)
            self._record_recent_case(
                to_dict(header),
                header.case_name,
                case_dir=self._current_case_dir,
                result_path=saved_result_path,
            )
            return header.case_session_id, header.case_revision, header.transaction_count

    def _load(self, path: str) -> object:
        if not isinstance(path, str) or not path.strip():
            raise ApplicationError("INVALID_ARGUMENT")
        candidate = Path(path)
        if candidate.suffix.lower() != ".json":
            raise ApplicationError("INVALID_ARGUMENT", "只允许打开 JSON 标准结果")
        with self._lock:
            if self._closed.is_set():
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口正在关闭")
            self._loading = True
            try:
                self._session.load(candidate)
                self._current_case_dir = None
                header = self._session.adapter().case_header()
                self._record_recent_case(to_dict(header), header.case_name, result_path=candidate)
                return self._session.adapter().case_header()
            finally:
                self._loading = False

    def get_app_state(self) -> dict[str, object]:
        if self._frontend_ready_at is None:
            self._frontend_ready_at = time.perf_counter()
        self._frontend_ready.set()
        with self._lock:
            return self._bridge.invoke(
                lambda: AppStateDTO(
                    True,
                    self._session.loaded,
                    self._loading,
                    "webview2",
                    case_session_id=self._session.case_session_id,
                    case_revision=self._session.revision,
                )
            )

    def select_standard_result(self) -> dict[str, object]:
        def select() -> object:
            if self._window is None:
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口尚未初始化")
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.OPEN,
                directory=str(Path.home()),
                allow_multiple=False,
                file_types=(STANDARD_RESULT_FILE_FILTER,),
            )
            if not selected:
                raise ApplicationError("CANCELLED", "未选择文件")
            if isinstance(selected, (str, Path)):
                filename = str(selected)
            else:
                try:
                    filename = str(next(iter(selected)))
                except (TypeError, StopIteration) as exc:
                    raise ApplicationError("CANCELLED", "未选择文件") from exc
            return self._load(filename)

        return self._bridge.invoke(select)

    def choose_case_directory(self) -> dict[str, object]:
        def choose() -> object:
            if self._window is None:
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口尚未初始化")
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.FOLDER,
                directory=str(Path.home()),
                allow_multiple=False,
            )
            if not selected:
                raise ApplicationError("CANCELLED", "未选择目录")
            if isinstance(selected, (str, Path)):
                folder = str(selected)
            else:
                try:
                    folder = str(next(iter(selected)))
                except (TypeError, StopIteration) as exc:
                    raise ApplicationError("CANCELLED", "未选择目录") from exc
            return self._case_directories.register(folder)

        return self._bridge.invoke(choose)

    def inspect_case_directory(self, case_handle: str) -> dict[str, object]:
        def inspect() -> object:
            _selection, dto = self._case_directories.inspect(case_handle)
            self._inspected_cases.add(case_handle)
            return dto

        return self._bridge.invoke(inspect)

    def start_case_analysis(self, case_handle: str, options: object | None = None) -> dict[str, object]:
        def start() -> object:
            if options is not None and not isinstance(options, dict):
                raise ApplicationError("INVALID_ARGUMENT")
            if isinstance(options, dict) and options:
                raise ApplicationError("INVALID_ARGUMENT", "当前分析不接受额外运行选项")
            if case_handle not in self._inspected_cases:
                raise ApplicationError("CASE_HANDLE_INVALID", "请先完成来源预检")
            selection = self._case_directories.get(case_handle)
            if not selection.sources:
                raise ApplicationError("NO_SUPPORTED_SOURCES")
            try:
                case_context = build_case_context_from_directory(selection.path)
            except OSError as exc:
                raise ApplicationError("CASE_DIRECTORY_READ_FAILED") from exc
            manual = load_workspace_manual_context(selection.path)
            confirmation = business_confirmation_from_record(manual)
            if confirmation:
                case_context = build_case_context_from_directory(
                    selection.path,
                    business_confirmation=confirmation,
                )
            self._current_case_dir = selection.path
            paths = [source.path for source in selection.sources]
            refs = {source.path: source.source_ref for source in selection.sources}
            ai_config, ai_evaluator = load_deepseek_runtime(replay_only=True)
            return self._tasks.start(
                selection.path.name or "未命名案件",
                paths,
                case_context,
                refs,
                ai_config=ai_config,
                ai_evaluator=ai_evaluator,
                allow_external_network=False,
            )

        return self._bridge.invoke(start)

    def get_analysis_status(self, analysis_task_id: str) -> dict[str, object]:
        return self._bridge.invoke(lambda: self._tasks.status(analysis_task_id))

    def cancel_analysis(self, analysis_task_id: str) -> dict[str, object]:
        return self._bridge.invoke(lambda: self._tasks.cancel(analysis_task_id))

    def dismiss_analysis_task(self, analysis_task_id: str) -> dict[str, object]:
        return self._bridge.invoke(lambda: self._tasks.dismiss(analysis_task_id))

    def list_recent_cases(self) -> dict[str, object]:
        def query() -> object:
            records = self._recent_store.load()
            return RecentCasesDTO(
                cases=[
                    RecentCaseDTO(
                        record_id=str(record.get("record_id") or ""),
                        case_name=str(record.get("case_name") or "未命名案件"),
                        updated_at=str(record.get("updated_at") or ""),
                        period_start=str(record.get("period_start") or ""),
                        period_end=str(record.get("period_end") or ""),
                        source_count=int(record.get("source_count") or 0),
                        transaction_count=int(record.get("transaction_count") or 0),
                        analysis_status=str(record.get("analysis_status") or ""),
                        schema_version=str(record.get("schema_version") or ""),
                        available=bool(record.get("available")),
                    )
                    for record in records
                ],
                corrupt_index=self._recent_store.last_load_was_corrupt,
            )

        return self._bridge.invoke(query)

    def open_recent_case(self, record_id: str) -> dict[str, object]:
        def open() -> object:
            if not isinstance(record_id, str) or not record_id:
                raise ApplicationError("INVALID_ARGUMENT")
            record = next(
                (
                    item
                    for item in self._recent_store.load()
                    if str(item.get("record_id") or "") == record_id
                ),
                None,
            )
            if record is None:
                raise ApplicationError("RECENT_CASE_NOT_FOUND")
            case_dir = Path(str(record.get("case_dir") or ""))
            if str(record.get("case_dir") or "") and case_dir.is_dir():
                return self._open_case_directory(
                    case_dir,
                    case_name=str(record.get("case_name") or case_dir.name),
                )
            result_path = Path(str(record.get("result_path") or ""))
            if str(record.get("result_path") or "") and result_path.is_file():
                return self._load(str(result_path))
            raise ApplicationError("RECENT_CASE_NOT_FOUND")

        return self._bridge.invoke(open)

    def remove_recent_case(self, record_id: str) -> dict[str, object]:
        def remove() -> object:
            if not isinstance(record_id, str) or not record_id:
                raise ApplicationError("INVALID_ARGUMENT")
            self._recent_store.remove(record_id)
            return {"removed": True}

        return self._bridge.invoke(remove)

    def reanalyze_recent_case(self, record_id: str) -> dict[str, object]:
        def reanalyze() -> object:
            if not isinstance(record_id, str) or not record_id:
                raise ApplicationError("INVALID_ARGUMENT")
            record = next(
                (
                    item
                    for item in self._recent_store.load()
                    if str(item.get("record_id") or "") == record_id
                ),
                None,
            )
            if record is None:
                raise ApplicationError("RECENT_CASE_NOT_FOUND")
            case_dir = Path(str(record.get("case_dir") or ""))
            if not str(record.get("case_dir") or "") or not case_dir.is_dir():
                raise ApplicationError(
                    "RECENT_CASE_DIRECTORY_UNAVAILABLE",
                    "该历史记录没有可重新分析的案件目录。",
                )
            return self._case_directories.register(case_dir)

        return self._bridge.invoke(reanalyze)

    def get_manual_case_context(self, case_handle: str) -> dict[str, object]:
        def query() -> object:
            selection = self._case_directories.get(case_handle)
            return self._manual_context_dto(selection.path)

        return self._bridge.invoke(query)

    def get_current_manual_case_context(self) -> dict[str, object]:
        def query() -> object:
            if self._current_case_dir is None:
                raise ApplicationError(
                    "CURRENT_CASE_CONTEXT_UNAVAILABLE",
                    "当前案件没有关联目录，无法读取经营上下文。",
                )
            return self._manual_context_dto(self._current_case_dir)

        return self._bridge.invoke(query)

    def save_manual_case_context(
        self,
        case_handle: str,
        fields: object | None = None,
    ) -> dict[str, object]:
        def save() -> object:
            selection = self._case_directories.get(case_handle)
            return self._save_manual_context(selection.path, fields)

        return self._bridge.invoke(save)

    def save_current_manual_case_context(
        self,
        fields: object | None = None,
    ) -> dict[str, object]:
        def save() -> object:
            if self._current_case_dir is None:
                raise ApplicationError(
                    "CURRENT_CASE_CONTEXT_UNAVAILABLE",
                    "当前案件没有关联目录，无法保存经营上下文。",
                )
            return self._save_manual_context(self._current_case_dir, fields)

        return self._bridge.invoke(save)

    def clear_current_manual_case_context(self) -> dict[str, object]:
        def clear() -> object:
            if self._current_case_dir is None:
                raise ApplicationError(
                    "CURRENT_CASE_CONTEXT_UNAVAILABLE",
                    "当前案件没有关联目录，无法清空经营上下文。",
                )
            try:
                base = build_case_context_from_directory(self._current_case_dir)
            except OSError as exc:
                raise ApplicationError("CASE_DIRECTORY_READ_FAILED") from exc
            record = save_workspace_manual_context(
                self._current_case_dir,
                base,
                {
                    "confirmed_primary_business": "",
                    "confirmed_products_or_services": "",
                    "confirmation_note": "",
                    "confirmation_status": "unconfirmed",
                    "confirmed_by": "",
                    "enable_ai_business_analysis": False,
                },
            )
            return ManualContextSaveDTO(
                saved=True,
                case_name=self._current_case_dir.name or "未命名案件",
                confirmation_status=str(
                    record.get("confirmation_status") or "unconfirmed"
                ),
            )

        return self._bridge.invoke(clear)

    def get_ai_runtime_status(self) -> dict[str, object]:
        def query() -> object:
            from bankflow_v2.deepseek_adapter import load_deepseek_settings

            settings = load_deepseek_settings()
            cache_dir = str(settings.cache_dir or "")
            cache_file_count = 0
            if cache_dir:
                try:
                    cache_file_count = sum(
                        1
                        for item in Path(cache_dir).rglob("*")
                        if item.is_file()
                    )
                except OSError:
                    cache_file_count = 0
            return AiRuntimeStatusDTO(
                runtime_loaded=bool(
                    settings.api_key
                    and settings.enabled
                    and settings.data_authorized
                    and settings.retention_policy_confirmed
                ),
                replay_only=True,
                cache_file_count=cache_file_count,
                model=str(settings.model),
            )

        return self._bridge.invoke(query)

    def _manual_context_dto(self, case_dir: Path) -> ManualContextDTO:
        record = load_workspace_manual_context(case_dir)
        confirmation = business_confirmation_from_record(record)
        if record:
            value = record.get("original_extracted_information")
            extracted = dict(value) if isinstance(value, dict) else {}
            search = extracted.get("search_context")
            search = dict(search) if isinstance(search, dict) else {}
            business = extracted.get("business_context")
            business = dict(business) if isinstance(business, dict) else {}
            source_names = [
                str(source.get("source_ref") or "")
                for source in extracted.get("sources", [])
                if isinstance(source, dict) and source.get("source_ref")
            ]
        else:
            try:
                base = build_case_context_from_directory(case_dir)
            except OSError:
                base = {}
            business = base.get("business_context")
            business = dict(business) if isinstance(business, dict) else {}
            search = base.get("search_context")
            search = dict(search) if isinstance(search, dict) else {}
            source_names = [
                str(source.get("source_ref") or "")
                for source in base.get("sources", [])
                if isinstance(source, dict) and source.get("source_ref")
            ]
        return ManualContextDTO(
            case_name=case_dir.name or "未命名案件",
            saved=bool(record),
            has_file=bool(record),
            company_name=str(
                business.get("company_name")
                or confirmation.get("company_name")
                or ""
            ),
            declared_work_description=str(
                business.get("declared_work_description") or ""
            ),
            declared_work_status=str(
                business.get("declared_work_status") or ""
            ),
            work_units=[
                str(value)
                for value in search.get("work_units", [])
                if str(value)
            ],
            work_locations=[
                str(value)
                for value in search.get("work_locations", [])
                if str(value)
            ],
            residence_locations=[
                str(value)
                for value in search.get("residence_locations", [])
                if str(value)
            ],
            source_names=source_names,
            confirmed_primary_business=str(
                confirmation.get("confirmed_primary_business") or ""
            ),
            confirmed_products_or_services=str(
                confirmation.get("confirmed_products_or_services") or ""
            ),
            confirmation_note=str(confirmation.get("confirmation_note") or ""),
            confirmation_status=str(
                confirmation.get("confirmation_status") or "unconfirmed"
            ),
            enable_ai_business_analysis=False,
        )

    def _save_manual_context(
        self,
        case_dir: Path,
        fields: object | None,
    ) -> ManualContextSaveDTO:
        if not isinstance(fields, dict):
            raise ApplicationError("INVALID_ARGUMENT")
        confirmation = {
            "confirmed_primary_business": str(
                fields.get("confirmed_primary_business") or ""
            ),
            "confirmed_products_or_services": str(
                fields.get("confirmed_products_or_services") or ""
            ),
            "confirmation_note": str(fields.get("confirmation_note") or ""),
            # 使用者为审核人员本人，填写即视为已确认，不再要求单独确认动作。
            "confirmation_status": "confirmed",
            "confirmed_by": str(fields.get("confirmed_by") or ""),
            "enable_ai_business_analysis": False,
        }
        try:
            base = build_case_context_from_directory(case_dir)
        except OSError as exc:
            raise ApplicationError("CASE_DIRECTORY_READ_FAILED") from exc
        company_name = str(fields.get("company_name") or "")
        if company_name:
            business = base.get("business_context")
            if isinstance(business, dict):
                updated = dict(business)
                updated["company_name"] = company_name
                base["business_context"] = updated
        record = save_workspace_manual_context(case_dir, base, confirmation)
        return ManualContextSaveDTO(
            saved=True,
            case_name=case_dir.name or "未命名案件",
            confirmation_status=str(record.get("confirmation_status") or "unconfirmed"),
        )

    def rebuild_context_observations(self) -> dict[str, object]:
        def rebuild() -> object:
            if self._current_case_dir is None:
                raise ApplicationError("REBUILD_UNAVAILABLE")
            result = self._session.current_result()
            manual = load_workspace_manual_context(self._current_case_dir)
            case_context = build_case_context_from_directory(
                self._current_case_dir,
                business_confirmation=business_confirmation_from_record(manual),
            )
            transactions = transactions_from_standard_result(result)
            rebuilt = rebuild_business_context_result(
                dict(result),
                transactions,
                case_context,
                ai_config={},
            )
            with self._lock:
                self._session.load_result_dict(
                    rebuilt,
                    case_name=self._session.case_name,
                    origin="analysis",
                )
                header = self._session.adapter().case_header()
            self._record_recent_case(
                to_dict(header),
                header.case_name,
                case_dir=self._current_case_dir,
            )
            return header

        return self._bridge.invoke(rebuild)

    def export_report(self) -> dict[str, object]:
        def export() -> object:
            if self._window is None:
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口尚未初始化")
            result = self._session.current_result()
            if self._current_case_dir is not None:
                manual = load_workspace_manual_context(self._current_case_dir)
                case_context = build_case_context_from_directory(
                    self._current_case_dir,
                    business_confirmation=business_confirmation_from_record(manual),
                )
            else:
                case_context = {
                    "case_id": self._session.case_name,
                    "search_context": {},
                }
            try:
                markdown = render_mvp_markdown(result, case_context)
            except Exception as exc:
                raise ApplicationError("REPORT_EXPORT_FAILED", str(exc)) from exc
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=str(Path.home()),
                save_filename=f"{self._session.case_name}_验收报告.md",
                file_types=(REPORT_SAVE_FILTER,),
            )
            if not selected:
                raise ApplicationError("CANCELLED", "已取消导出")
            if isinstance(selected, (str, Path)):
                filename = str(selected)
            else:
                try:
                    filename = str(next(iter(selected)))
                except (TypeError, StopIteration) as exc:
                    raise ApplicationError("CANCELLED", "已取消导出") from exc
            target = Path(filename)
            if target.suffix.lower() != ".md":
                target = target.with_suffix(".md")
            try:
                target.write_text(markdown, encoding="utf-8")
            except OSError as exc:
                raise ApplicationError("REPORT_EXPORT_FAILED", str(exc)) from exc
            return ExportReportDTO(saved=True, display_name=target.name)

        with self._lock:
            return self._bridge.invoke(export)

    def save_current_standard_result(self) -> dict[str, object]:
        def save() -> object:
            if self._window is None:
                raise ApplicationError("INTERNAL_ERROR", "桌面窗口尚未初始化")
            result = self._session.current_result()
            import webview

            selected = self._window.create_file_dialog(
                webview.FileDialog.SAVE,
                directory=str(Path.home()),
                save_filename="bankflow_standard_result.json",
                file_types=(STANDARD_RESULT_SAVE_FILTER,),
            )
            if not selected:
                raise ApplicationError("CANCELLED", "已取消保存")
            if isinstance(selected, (str, Path)):
                filename = str(selected)
            else:
                try:
                    filename = str(next(iter(selected)))
                except (TypeError, StopIteration) as exc:
                    raise ApplicationError("CANCELLED", "已取消保存") from exc
            target = Path(filename)
            if target.suffix.lower() != ".json":
                target = target.with_suffix(".json")
            input_path = self._session.result_path
            if input_path is not None and target.resolve() == input_path.resolve():
                raise ApplicationError("SAVE_INPUT_OVERWRITE_FORBIDDEN")
            write_bankflow_json(result, target)
            return {"saved": True, "display_name": target.name}

        with self._lock:
            return self._bridge.invoke(save)

    def load_standard_result(self, path: str) -> dict[str, object]:
        return self._bridge.invoke(lambda: self._load(path))

    def get_case_header(self) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: self._session.adapter().case_header())

    def get_purchase_summary(self) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: self._session.adapter().purchase_summary())

    def list_purchase_transactions(
        self,
        page: int,
        page_size: int,
        filters: object | None = None,
    ) -> dict[str, object]:
        def query() -> object:
            parsed = filters
            if isinstance(filters, str):
                try:
                    parsed = json.loads(filters or "{}")
                except json.JSONDecodeError as exc:
                    raise ApplicationError("INVALID_ARGUMENT") from exc
            if parsed is None:
                parsed = {}
            if not isinstance(parsed, dict):
                raise ApplicationError("INVALID_ARGUMENT")
            return self._session.adapter().list_transactions(page, page_size, parsed)

        with self._lock:
            return self._bridge.invoke(query)

    def get_evidence(self, transaction_id: str, case_session_id: str | None = None) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: (
                self._session.assert_current(case_session_id),
                self._session.adapter().evidence(transaction_id),
            )[1])

    def get_review_modules(self, case_session_id: str | None = None) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: self._session.registry().catalogue(
                self._session.assert_current(case_session_id)
            ))

    def get_module_summary(self, module_id: str, case_session_id: str | None = None) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: self._session.registry().adapter(module_id).summary(
                self._session.assert_current(case_session_id)
            ))

    def list_module_items(
        self,
        module_id: str,
        page: int,
        page_size: int,
        filters: object | None = None,
        sort: str = "default",
        case_session_id: str | None = None,
    ) -> dict[str, object]:
        def query() -> object:
            parsed = filters
            if isinstance(filters, str):
                try:
                    parsed = json.loads(filters or "{}")
                except json.JSONDecodeError as exc:
                    raise ApplicationError("INVALID_ARGUMENT") from exc
            if parsed is None:
                parsed = {}
            if not isinstance(parsed, dict) or not isinstance(sort, str):
                raise ApplicationError("INVALID_ARGUMENT")
            session_id = self._session.assert_current(case_session_id)
            return self._session.registry().adapter(module_id).list_items(
                session_id, page, page_size, parsed, sort
            )

        with self._lock:
            return self._bridge.invoke(query)

    def list_source_reviews(self, case_session_id: str | None = None) -> dict[str, object]:
        with self._lock:
            return self._bridge.invoke(lambda: (
                self._session.assert_current(case_session_id),
                self._session.adapter().source_review_summary(),
            )[1])

    def close_case(self) -> dict[str, object]:
        def close() -> None:
            with self._lock:
                self._session.close()
                self._current_case_dir = None
            return None

        return self._bridge.invoke(close)

    def _record_recent_case(
        self,
        header: dict[str, object],
        case_name: str,
        *,
        case_dir: Path | str | None = None,
        result_path: Path | str | None = None,
    ) -> None:
        summary = {
            "case_name": case_name,
            "period_start": str(header.get("period_start") or ""),
            "period_end": str(header.get("period_end") or ""),
            "source_count": int(header.get("source_count") or 0),
            "transaction_count": int(header.get("transaction_count") or 0),
            "analysis_status": str(header.get("analysis_status") or "已完成"),
            "schema_version": str(header.get("schema_version") or ""),
        }
        try:
            self._recent_store.upsert(
                summary,
                case_dir=case_dir,
                result_path=result_path,
            )
        except OSError:
            pass

    def _open_case_directory(self, case_dir: Path, *, case_name: str | None = None) -> object:
        def sort_key(path: Path) -> tuple[object, float]:
            try:
                return (path.name == STANDARD_RESULT_FILENAME, path.stat().st_mtime)
            except OSError:
                return (False, 0.0)

        candidates = sorted(case_dir.rglob("*.json"), key=sort_key, reverse=True)
        fallback = standard_result_path(case_dir)
        if not candidates and fallback.is_file():
            candidates = [fallback]
        for candidate in candidates:
            try:
                result = load_standard_result(candidate)
            except (OSError, StandardResultError):
                continue
            with self._lock:
                if self._closed.is_set():
                    raise ApplicationError("INTERNAL_ERROR", "桌面窗口正在关闭")
                self._session.load_result_dict(
                    result,
                    case_name=case_name or case_dir.name,
                    origin="file",
                    path=candidate,
                )
                header = self._session.adapter().case_header()
            self._current_case_dir = case_dir
            self._record_recent_case(
                to_dict(header),
                case_name or case_dir.name,
                case_dir=case_dir,
                result_path=candidate,
            )
            return header
        raise ApplicationError(
            "RECENT_CASE_NOT_FOUND",
            "该历史案件还没有保存标准结果，请重新分析后再打开。",
        )

    def _shutdown(self) -> None:
        self._closed.set()
        self._tasks.shutdown(5.0)
        with self._lock:
            self._session.close()

    def _on_closing(self) -> bool | None:
        if not self._tasks.has_active_task():
            return None
        import ctypes

        answer = ctypes.windll.user32.MessageBoxW(
            None,
            "分析仍在进行，关闭后本次分析结果不会保留。\n\n选择“是”请求停止并关闭；选择“否”继续分析。",
            "流水核查工作台",
            0x24,
        )
        if answer != 6:
            return False
        if not self._tasks.shutdown(5.0):
            ctypes.windll.user32.MessageBoxW(None, "正在停止，当前文件处理完成后即可关闭。", "流水核查工作台", 0x40)
            return False
        return None
