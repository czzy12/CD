"""Generate a local Markdown MVP acceptance report for one case directory."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.case_context import (
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)
from bankflow_v2.mvp_report import render_mvp_markdown
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.result_export import build_bankflow_result


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


def generate(case_dir: Path, output_path: Path) -> Path:
    case_context = build_case_context(case_dir.name, _sources(case_dir))
    transactions = []
    for pdf_path in sorted(case_dir.glob("*.pdf")):
        detection = detect_bank_type(str(pdf_path))
        if not detection.bank_id:
            continue
        transactions.extend(extract_transactions(str(pdf_path), detection.bank_id))
    result = build_bankflow_result(
        transactions,
        case_context=case_context,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        render_mvp_markdown(result, case_context) + "\n",
        encoding="utf-8",
    )
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("output_path", type=Path)
    args = parser.parse_args()
    generated = generate(args.case_dir, args.output_path)
    print(generated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
