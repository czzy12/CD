"""One in-memory, read-only schema 1.16 case session."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping
import uuid

from bankflow_v2.standard_result_view import StandardResultError, load_standard_result, validate_standard_result

from .contracts import ApplicationError
from .module_registry import ModuleRegistry
from .result_adapter import PurchaseResultAdapter


class CaseSession:
    def __init__(self) -> None:
        self._result: dict[str, object] | None = None
        self._result_path: Path | None = None
        self._adapter: PurchaseResultAdapter | None = None
        self._registry: ModuleRegistry | None = None
        self._case_session_id: str | None = None
        self._revision = 0
        self._case_name = ""
        self._origin = ""

    @property
    def loaded(self) -> bool:
        return self._result is not None

    @property
    def result_path(self) -> Path | None:
        return self._result_path

    @property
    def case_session_id(self) -> str | None:
        return self._case_session_id

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def case_name(self) -> str:
        return self._case_name

    @property
    def origin(self) -> str:
        return self._origin

    def load(self, path: str | Path) -> None:
        candidate = Path(path)
        if not candidate.exists():
            raise ApplicationError("FILE_NOT_FOUND")
        try:
            result = load_standard_result(candidate)
        except StandardResultError as exc:
            if exc.code == "standard_result_read_failed":
                raise ApplicationError("INVALID_JSON", "无法读取所选JSON文件") from exc
            raise ApplicationError("SCHEMA_INCOMPATIBLE") from exc
        self.load_result_dict(result, case_name=candidate.stem, origin="file", path=candidate)

    def load_result_dict(
        self,
        result: Mapping[str, object],
        *,
        case_name: str,
        origin: str = "analysis",
        path: Path | None = None,
    ) -> None:
        try:
            validated = validate_standard_result(dict(result))
        except StandardResultError as exc:
            raise ApplicationError("SCHEMA_INCOMPATIBLE") from exc
        if validated.get("module") != "bankflow":
            raise ApplicationError("SCHEMA_INCOMPATIBLE", "标准结果模块不是 bankflow")
        self.bind(validated, case_name, path, origin=origin)

    def bind(self, result: Mapping[str, object], case_name: str = "测试案件", path: Path | None = None, *, origin: str = "memory") -> None:
        next_result = dict(result)
        next_revision = self._revision + 1
        next_session_id = uuid.uuid4().hex
        next_adapter = PurchaseResultAdapter(next_result, case_name, next_session_id, next_revision)
        next_registry = ModuleRegistry(next_result, case_name)
        self._result = next_result
        self._result_path = path
        self._case_name = case_name
        self._origin = origin
        self._case_session_id = next_session_id
        self._revision = next_revision
        self._adapter = next_adapter
        self._registry = next_registry

    def adapter(self) -> PurchaseResultAdapter:
        if self._adapter is None:
            raise ApplicationError("NO_CASE")
        return self._adapter

    def registry(self) -> ModuleRegistry:
        if self._registry is None:
            raise ApplicationError("NO_CASE")
        return self._registry

    def assert_current(self, case_session_id: str | None) -> str:
        if not self._case_session_id:
            raise ApplicationError("NO_CASE")
        if case_session_id and case_session_id != self._case_session_id:
            raise ApplicationError("STALE_CASE")
        return self._case_session_id

    def close(self) -> None:
        if self.loaded:
            self._revision += 1
        self._clear()

    def current_result(self) -> dict[str, object]:
        if self._result is None:
            raise ApplicationError("NO_CASE")
        return self._result

    def _clear(self) -> None:
        self._registry = None
        self._adapter = None
        self._result = None
        self._result_path = None
        self._case_session_id = None
        self._case_name = ""
        self._origin = ""
