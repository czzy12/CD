"""Case workspace helpers for the WebView2 workbench.

Keeps runtime-only user data (recent-case index, manual business context)
outside the Git repository and outside customer source folders, so customer
paths and edited context never enter the repository.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Mapping


MANUAL_CASE_CONTEXT_FILENAME = "manual_case_context.json"
STANDARD_RESULT_FILENAME = "bankflow_verification_result.json"


def web_output_root() -> Path:
    """Repository-adjacent ignored output directory (``outputs/``)."""
    return Path(__file__).resolve().parents[2] / "outputs" / "web-gui-12b2"


def recent_cases_path() -> Path:
    return web_output_root() / "recent_cases.json"


def workspace_key(case_dir: str | Path) -> str:
    normalized = os.path.normcase(str(Path(case_dir).resolve(strict=False)))
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    safe_name = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff_-]+", "_", Path(case_dir).name).strip("_")
    safe_name = safe_name or "case"
    return f"{safe_name}-{digest}"


def case_workspace_dir(case_dir: str | Path) -> Path:
    return web_output_root() / "workspaces" / workspace_key(case_dir)


def manual_context_path(case_dir: str | Path) -> Path:
    return case_workspace_dir(case_dir) / MANUAL_CASE_CONTEXT_FILENAME


def load_manual_case_context(case_dir: str | Path) -> dict[str, object]:
    path = manual_context_path(case_dir)
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def save_manual_case_context(
    case_dir: str | Path,
    extracted_context: Mapping[str, object],
    confirmation: Mapping[str, object],
) -> dict[str, object]:
    directory = Path(case_dir)
    record = {
        "schema_version": "1.0",
        "case_id": directory.name,
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
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "enable_ai_business_analysis": bool(
            confirmation.get("enable_ai_business_analysis")
        ),
    }
    path = manual_context_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    return record


def business_confirmation_from_record(
    record: Mapping[str, object],
) -> dict[str, object]:
    value = record.get("manual_confirmation")
    return dict(value) if isinstance(value, dict) else {}


def business_context_from_record(
    record: Mapping[str, object],
) -> dict[str, object]:
    value = record.get("original_extracted_information")
    if not isinstance(value, dict):
        return {}
    context = value.get("business_context")
    return dict(context) if isinstance(context, dict) else {}
