"""Case-folder discovery matching the current formal Qt workflow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import secrets
import threading
import time

from bankflow_web.contracts import ApplicationError

from .contracts import CasePreflightDTO, CaseSelectionDTO, PreflightSourceDTO


SUPPORTED_INPUTS = {".pdf", ".xlsx", ".xlsm"}


@dataclass(frozen=True)
class SourceSelection:
    source_ref: str
    path: Path
    source_type: str


@dataclass(frozen=True)
class CaseSelection:
    case_handle: str
    path: Path
    sources: tuple[SourceSelection, ...]


class CaseDirectoryRegistry:
    """Stores selected paths only in Python and exposes opaque handles."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._cases: dict[str, CaseSelection] = {}

    def register(self, directory: str | Path) -> CaseSelectionDTO:
        path = Path(directory).resolve()
        if not path.is_dir():
            raise ApplicationError("CASE_DIRECTORY_NOT_FOUND")
        handle = secrets.token_hex(16)
        selection = CaseSelection(handle, path, ())
        with self._lock:
            self._cases = {handle: selection}
        return CaseSelectionDTO(handle, path.name or "未命名案件")

    def get(self, case_handle: str) -> CaseSelection:
        if not isinstance(case_handle, str) or not case_handle:
            raise ApplicationError("INVALID_ARGUMENT")
        with self._lock:
            selection = self._cases.get(case_handle)
        if selection is None:
            raise ApplicationError("CASE_HANDLE_INVALID")
        return selection

    def inspect(self, case_handle: str) -> tuple[CaseSelection, CasePreflightDTO]:
        started = time.perf_counter()
        selection = self.get(case_handle)
        discovered: list[SourceSelection] = []
        items: list[PreflightSourceDTO] = []
        warnings: list[str] = []
        try:
            paths = sorted(path for path in selection.path.rglob("*") if path.is_file())
        except OSError as exc:
            raise ApplicationError("CASE_DIRECTORY_READ_FAILED") from exc
        for path in paths:
            extension = path.suffix.lower()
            supported = extension in SUPPORTED_INPUTS
            source_type = "pdf" if extension == ".pdf" else "excel" if extension in {".xlsx", ".xlsm"} else "unsupported"
            source_ref = secrets.token_hex(12)
            bank_type = ""
            warning = ""
            may_fallback = False
            if supported and source_type == "pdf":
                from bankflow_v2.auto_detect import detect_bank_type

                detection = detect_bank_type(str(path))
                bank_type = detection.bank_id or "generic_pdf"
                warning = detection.reason if not detection.bank_id else ""
                may_fallback = not bool(detection.bank_id)
            elif supported:
                bank_type = "excel"
            else:
                warning = "当前正式流程不处理此文件类型"
            if supported:
                discovered.append(SourceSelection(source_ref, path, source_type))
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            items.append(PreflightSourceDTO(
                source_ref=source_ref,
                display_name=path.name,
                extension=extension,
                detected_source_type=source_type,
                detected_bank_type=bank_type,
                supported=supported,
                initial_status="ready" if supported else "unsupported",
                warning=warning,
                size=size,
                may_use_generic_fallback=may_fallback,
            ))
        supported_count = len(discovered)
        unsupported_count = len(items) - supported_count
        if not supported_count:
            warnings.append("目录中未找到支持的 PDF/Excel 流水文件。")
        if unsupported_count:
            warnings.append(f"有 {unsupported_count} 个文件不属于当前正式分析输入，将跳过。")
        updated = CaseSelection(selection.case_handle, selection.path, tuple(discovered))
        with self._lock:
            self._cases[case_handle] = updated
        dto = CasePreflightDTO(
            case_handle=case_handle,
            case_display_name=selection.path.name or "未命名案件",
            source_count=len(items),
            supported_source_count=supported_count,
            unsupported_source_count=unsupported_count,
            sources=items,
            warnings=warnings,
            can_start=supported_count > 0,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return updated, dto
