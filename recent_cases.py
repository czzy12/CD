"""Privacy-minimal persistent index for recently opened bank-flow cases."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


RECENT_CASES_FILENAME = "recent_cases.json"
_SAFE_FIELDS = (
    "record_id",
    "case_name",
    "case_dir",
    "result_path",
    "updated_at",
    "period_start",
    "period_end",
    "source_count",
    "transaction_count",
    "analysis_status",
    "schema_version",
    "available",
)


def _normalized_path(value: str | Path | None) -> str:
    if value in (None, ""):
        return ""
    return os.path.normcase(str(Path(value).expanduser().resolve(strict=False)))


def recent_case_id(
    case_dir: str | Path | None = None,
    result_path: str | Path | None = None,
) -> str:
    normalized_case = _normalized_path(case_dir)
    if normalized_case:
        return f"case:{normalized_case}"
    normalized_result = _normalized_path(result_path)
    return f"result:{normalized_result}" if normalized_result else ""


class RecentCaseStore:
    """Stores summaries only; standard-result contents never enter the index."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.last_load_was_corrupt = False

    def load(self) -> list[dict[str, object]]:
        self.last_load_was_corrupt = False
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self.last_load_was_corrupt = True
            return []
        if not isinstance(payload, list):
            self.last_load_was_corrupt = True
            return []
        records: list[dict[str, object]] = []
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            record = {field: item.get(field) for field in _SAFE_FIELDS}
            record_id = str(record.get("record_id") or "")
            if not record_id:
                record_id = recent_case_id(
                    record.get("case_dir"), record.get("result_path")
                )
            if not record_id:
                continue
            record["record_id"] = record_id
            record["available"] = self._is_available(record)
            records.append(record)
        return sorted(
            records,
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )

    def upsert(
        self,
        summary: Mapping[str, object],
        *,
        case_dir: str | Path | None = None,
        result_path: str | Path | None = None,
        updated_at: str | None = None,
    ) -> dict[str, object]:
        normalized_case = _normalized_path(case_dir)
        normalized_result = _normalized_path(result_path)
        record_id = recent_case_id(normalized_case, normalized_result)
        if not record_id:
            raise ValueError("最近案件必须包含案件目录或标准结果路径。")
        record = {
            "record_id": record_id,
            "case_name": str(summary.get("case_name") or "未命名案件"),
            "case_dir": normalized_case,
            "result_path": normalized_result,
            "updated_at": updated_at
            or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "period_start": str(summary.get("period_start") or "")[:10],
            "period_end": str(summary.get("period_end") or "")[:10],
            "source_count": int(summary.get("source_count") or 0),
            "transaction_count": int(summary.get("transaction_count") or 0),
            "analysis_status": str(summary.get("analysis_status") or "已完成"),
            "schema_version": str(summary.get("schema_version") or ""),
            "available": True,
        }
        records = [
            item for item in self.load()
            if str(item.get("record_id") or "") != record_id
        ]
        records.insert(0, record)
        self._write(records)
        return record

    def remove(self, record_id: str) -> None:
        records = [
            item for item in self.load()
            if str(item.get("record_id") or "") != record_id
        ]
        self._write(records)

    def _write(self, records: list[Mapping[str, object]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        safe_records = [
            {field: item.get(field) for field in _SAFE_FIELDS}
            for item in records
        ]
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(safe_records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @staticmethod
    def _is_available(record: Mapping[str, object]) -> bool:
        case_dir = str(record.get("case_dir") or "")
        result_path = str(record.get("result_path") or "")
        return bool(
            (case_dir and Path(case_dir).is_dir())
            or (result_path and Path(result_path).is_file())
        )
