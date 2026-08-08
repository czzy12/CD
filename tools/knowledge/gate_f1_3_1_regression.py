"""Gate F1.3.1: small development regression over routing boundaries.

Fail-visible: any mismatch between expected and actual routing exits non-zero.
This is development regression, not holdout accuracy.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge.evidence import BusinessEvidenceResolver
from bankflow_v2.knowledge.models import IndustryProfile


def profile51() -> IndustryProfile:
    return IndustryProfile(
        primary_industry_ids=("51",),
        normalized_products_services=(
            "铝锭大宗贸易",
            "金属材料销售",
        ),
        profile_name="dev-51-wholesale",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--regression-json",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-3-1-local-ai-boundary-20260808/routing_regression.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-3-1-ai-validation-20260808"
        ),
    )
    args = parser.parse_args()
    data = json.loads(args.regression_json.read_text(encoding="utf-8"))
    resolver = BusinessEvidenceResolver()
    profile = profile51()
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case in data["cases"]:
        fields = {
            str(name): str(value)
            for name, value in case.get("fields", {}).items()
            if str(value).strip()
        }
        result = resolver.resolve(
            fields,
            profile=profile if case.get("profile") else None,
        )
        actual_routing = str(result["routing_state"])
        expected_routing = str(case["expected_routing"])
        actual_role = str(result["role"])
        expected_role = str(case.get("expected_role", ""))
        ok = actual_routing == expected_routing and (
            not expected_role or actual_role == expected_role
        )
        row = {
            "case_id": case["case_id"],
            "category": case["category"],
            "expected_routing": expected_routing,
            "actual_routing": actual_routing,
            "expected_role": expected_role,
            "actual_role": actual_role,
            "trace_strength": result["trace_strength"],
            "unresolved_reason": result["unresolved_reason"],
            "ok": ok,
        }
        rows.append(row)
        if not ok:
            failures.append(row)
    summary = {
        "purpose": "development regression for routing boundary; not holdout",
        "total_cases": len(rows),
        "passed": len(rows) - len(failures),
        "failed": len(failures),
        "failures": failures,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "development_regression_results.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md = [
        "# Development Regression（Gate F1.3.1）",
        "",
        f"- total：{summary['total_cases']}",
        f"- passed：{summary['passed']}",
        f"- failed：{summary['failed']}",
        "- 明确：development regression，不是 holdout accuracy",
        "",
        "| case | category | expected | actual | role | trace | ok |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        md.append(
            f"| {row['case_id']} | {row['category']} | "
            f"{row['expected_routing']} | {row['actual_routing']} | "
            f"{row['actual_role']} | {row['trace_strength']} | {row['ok']} |"
        )
    (args.output_dir / "development_regression_report.md").write_text(
        "\n".join(md) + "\n",
        encoding="utf-8",
    )
    print(
        "development_regression="
        f"passed {summary['passed']} failed {summary['failed']}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
