"""One in-memory, read-only schema 1.16 case session."""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from bankflow_v2.standard_result_view import StandardResultError, load_standard_result

from .contracts import ApplicationError
from .result_adapter import PurchaseResultAdapter


class CaseSession:
    def __init__(self) -> None:
        self._result: dict[str, object] | None = None
        self._result_path: Path | None = None
        self._adapter: PurchaseResultAdapter | None = None

    @property
    def loaded(self) -> bool:
        return self._result is not None

    @property
    def result_path(self) -> Path | None:
        return self._result_path

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
        self.bind(result, candidate.stem, candidate)

    def bind(self, result: Mapping[str, object], case_name: str = "测试案件", path: Path | None = None) -> None:
        self.close()
        self._result = dict(result)
        self._result_path = path
        self._adapter = PurchaseResultAdapter(self._result, case_name)

    def adapter(self) -> PurchaseResultAdapter:
        if self._adapter is None:
            raise ApplicationError("NO_CASE")
        return self._adapter

    def close(self) -> None:
        self._adapter = None
        self._result = None
        self._result_path = None
