import argparse
import json
import os
import sys
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.summary import summarize


CENT = Decimal("0.01")
DEFAULT_CASES = Path(__file__).with_name("regression_cases.json")


@dataclass
class RegressionResult:
    status: str
    name: str
    detail: str
    failures: list[str]


def _assets_root() -> str:
    return os.environ.get("CD_ASSETS", r"D:\Codex data\CD_assets")


def _expand_path(value: str) -> Path:
    expanded = value.replace("${CD_ASSETS}", _assets_root())
    expanded = os.path.expandvars(expanded)
    return Path(expanded).expanduser().resolve()


def _load_cases(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, list):
        raise ValueError(f"Cases file must contain a list: {path}")
    return data


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.00")
    text = str(value).replace(",", "").strip()
    return Decimal(text).quantize(CENT)


def _compare_decimal(label: str, actual: Any, expected: Any) -> str | None:
    try:
        actual_value = _to_decimal(actual)
        expected_value = _to_decimal(expected)
    except (InvalidOperation, ValueError) as exc:
        return f"{label}: invalid decimal ({exc})"
    if actual_value != expected_value:
        return f"{label}: expected {expected_value}, got {actual_value}"
    return None


def _compare_int(label: str, actual: int, expected: Any) -> str | None:
    expected_value = int(expected)
    if actual != expected_value:
        return f"{label}: expected {expected_value}, got {actual}"
    return None


def _summary_values(summary) -> dict[str, Any]:
    return {
        "count": summary.count,
        "income_count": summary.income_count,
        "income_sum": summary.income_sum,
        "expense_count": summary.expense_count,
        "expense_sum": summary.expense_sum,
        "net": summary.net,
        "opening_balance": summary.opening_balance,
        "closing_balance": summary.closing_balance,
        "issues": len(summary.issues),
    }


def _matches_filters(case: dict[str, Any], names: set[str], tags: set[str]) -> bool:
    if names and case.get("name") not in names:
        return False
    if tags and not (tags & set(case.get("tags", []))):
        return False
    return True


def run_case(case: dict[str, Any], allow_missing: bool = False) -> RegressionResult:
    name = str(case.get("name", "unnamed"))
    pdf_path = _expand_path(str(case["path"]))
    if not pdf_path.exists():
        status = "SKIP" if allow_missing else "FAIL"
        return RegressionResult(status, name, f"missing file: {pdf_path}", [] if allow_missing else [str(pdf_path)])

    bank = case.get("bank")
    if not bank or bank == "auto":
        detection = detect_bank_type(str(pdf_path))
        bank = detection.bank_id
        if not bank:
            return RegressionResult("FAIL", name, f"unrecognized bank: {detection.reason}", [detection.reason])

    try:
        rows = extract_transactions(str(pdf_path), str(bank))
        summary = summarize(rows, pdf_path.name)
    except Exception as exc:
        return RegressionResult("FAIL", name, f"{type(exc).__name__}: {exc}", [str(exc)])

    expected = case.get("expected", {})
    actual = _summary_values(summary)
    failures: list[str] = []
    for key in ("count", "income_count", "expense_count", "issues"):
        if key in expected:
            failure = _compare_int(key, actual[key], expected[key])
            if failure:
                failures.append(failure)
    for key in ("income_sum", "expense_sum", "net", "opening_balance", "closing_balance"):
        if key in expected:
            failure = _compare_decimal(key, actual[key], expected[key])
            if failure:
                failures.append(failure)

    detail = f"{actual['count']}笔, {actual['issues']}异常"
    if failures and summary.issues:
        detail = f"{detail}, 首个异常: {summary.issues[0].message}"
    return RegressionResult("FAIL" if failures else "PASS", name, detail, failures)


def _print_cases(cases: list[dict[str, Any]]) -> None:
    for case in cases:
        tags = ",".join(case.get("tags", []))
        print(f"{case.get('name', 'unnamed')}\t{case.get('bank', '')}\t{tags}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bank statement regression cases.")
    parser.add_argument("--all", action="store_true", help="Run all configured regression cases.")
    parser.add_argument("--case", action="append", default=[], help="Run one named case. Can be repeated.")
    parser.add_argument("--tag", action="append", default=[], help="Run cases with a tag. Can be repeated.")
    parser.add_argument("--cases", default=str(DEFAULT_CASES), help="Path to regression_cases.json.")
    parser.add_argument("--list", action="store_true", help="List configured cases.")
    parser.add_argument("--allow-missing", action="store_true", help="Skip missing sample files instead of failing.")
    args = parser.parse_args()

    cases_path = Path(args.cases).expanduser().resolve()
    cases = _load_cases(cases_path)
    if args.list:
        _print_cases(cases)
        return 0

    names = set(args.case)
    tags = set(args.tag)
    if not args.all and not names and not tags:
        parser.error("Use --all, --case, --tag, or --list.")

    selected = [case for case in cases if args.all or _matches_filters(case, names, tags)]
    if not selected:
        print("No regression cases selected.")
        return 1

    failed = 0
    skipped = 0
    for case in selected:
        result = run_case(case, allow_missing=args.allow_missing)
        print(f"{result.status}: {result.name} ({result.detail})")
        for failure in result.failures:
            print(f"  - {failure}")
        if result.status == "FAIL":
            failed += 1
        elif result.status == "SKIP":
            skipped += 1

    passed = len(selected) - failed - skipped
    print(f"SUMMARY: pass={passed}, fail={failed}, skip={skipped}, total={len(selected)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
