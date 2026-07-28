"""Replay a previously rendered acceptance report through current local validators."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.ai_business_observation import build_ai_business_observation
from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.case_context import (
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)
from bankflow_v2.pipeline import extract_transactions


_CLASSIFICATIONS = {
    "直接相关": "directly_related",
    "可能相关": "possibly_related",
    "未发现关联依据": "no_relation_evidence",
    "无法判断": "undetermined",
}


def _sources(case_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(case_dir.glob("*.txt")):
        rows.append(
            {
                "source_ref": path.name,
                "source_role": (
                    SOURCE_ROLE_RISK_INVESTIGATION_REPORT
                    if "调查报告" in path.name
                    else SOURCE_ROLE_SYSTEM_CUSTOMER_DATA
                ),
                "text": path.read_text(encoding="utf-8"),
            }
        )
    return rows


def _report_results(report_path: Path) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for line in report_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| tx:"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 9:
            continue
        transaction_id, _, _, _, field_text, label, strength, reason, _ = cells
        classification = _CLASSIFICATIONS.get(label)
        semantic_judgement = (
            "undetermined"
            if classification == "undetermined"
            else strength
        )
        if (
            not classification
            or semantic_judgement
            not in {"strong", "medium", "weak", "none", "undetermined"}
        ):
            continue
        used_fields = []
        for field_part in field_text.split("；"):
            field_name, separator, _ = field_part.partition("=")
            if separator and field_name.strip():
                used_fields.append(field_name.strip())
        results.append(
            {
                "transaction_id": transaction_id,
                "semantic_judgement": semantic_judgement,
                "reason": reason,
                "used_fields": used_fields,
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("historical_report", type=Path)
    parser.add_argument("output_json", type=Path)
    args = parser.parse_args()
    if not args.case_dir.is_dir() or not args.historical_report.is_file():
        print("status=not_started")
        print("reason=input_not_found")
        return 2

    context = build_case_context(args.case_dir.name, _sources(args.case_dir))
    transactions = []
    for path in sorted(args.case_dir.glob("*.pdf")):
        detection = detect_bank_type(str(path))
        if detection.bank_id:
            transactions.extend(
                extract_transactions(str(path), detection.bank_id)
            )
    historical_results = _report_results(args.historical_report)
    observation = build_ai_business_observation(
        transactions,
        context,
        {
            "enabled": True,
            "data_authorized": True,
            "retention_policy_confirmed": True,
            "allow_business_names": True,
            "provider": "historical-report-replay",
            "model": "historical-rendered-result",
            "api_key_available": True,
        },
        evaluator=lambda _payload: historical_results,
    )
    value = observation["value"]
    output = {
        "replay_source": str(args.historical_report),
        "source_kind": (
            "rendered_acceptance_report_not_raw_provider_response"
        ),
        "historical_result_count": len(historical_results),
        "current_ai_input_candidate_count": value[
            "ai_input_candidate_count"
        ],
        "available": value["available"],
        "reason": value["reason"],
        "validation_failure_summary": value[
            "validation_failure_summary"
        ],
        "provisional_valid_result_count": len(
            value["provisional_ai_candidates"]
        ),
        "adopted_result_count": len(value["ai_candidates"]),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("status=ok")
    print(f"historical_results={len(historical_results)}")
    print(
        "validation_failures="
        f"{output['validation_failure_summary']['total']}"
    )
    print(f"output={args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
