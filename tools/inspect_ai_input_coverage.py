"""Inspect real-case AI input fields without making a provider call."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.ai_business_observation import build_ai_input_profile
from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.case_context import (
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)
from bankflow_v2.pipeline import extract_transactions


def _sources(case_dir: Path) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for text_path in sorted(case_dir.glob("*.txt")):
        role = (
            SOURCE_ROLE_RISK_INVESTIGATION_REPORT
            if "调查报告" in text_path.name
            else SOURCE_ROLE_SYSTEM_CUSTOMER_DATA
        )
        sources.append(
            {
                "source_ref": text_path.name,
                "source_role": role,
                "text": text_path.read_text(encoding="utf-8"),
            }
        )
    return sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_dir", type=Path)
    args = parser.parse_args()
    if not args.case_dir.is_dir():
        print("status=not_started")
        print("reason=case_directory_not_found")
        return 2

    case_context = build_case_context(args.case_dir.name, _sources(args.case_dir))
    transactions = []
    for pdf_path in sorted(args.case_dir.glob("*.pdf")):
        detection = detect_bank_type(str(pdf_path))
        if not detection.bank_id:
            continue
        transactions.extend(extract_transactions(str(pdf_path), detection.bank_id))
    print(
        json.dumps(
            build_ai_input_profile(
                transactions,
                case_context,
                allow_business_names=True,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
