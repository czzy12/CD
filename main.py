"""
银行流水PDF批量处理 v2
用法:
    python main.py file1.pdf
    python main.py file1.pdf --date-range "2025-11~2026-04"
    python main.py file1.pdf --date-range all
    python main.py *.pdf
"""
import argparse
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path


sys.path.insert(0, str(Path(__file__).parent))

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.income_proof_export import flow_type as income_flow_type
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.summary import money, monthly_summaries, summarize
from gui_v2 import FileResult, write_workbook


def _add_months(dt: datetime, months: int) -> datetime:
    y, m = dt.year, dt.month + months
    y += (m - 1) // 12
    m = ((m - 1) % 12) + 1
    return datetime(y, m, dt.day, dt.hour, dt.minute, dt.second)


def _last_day_of_month(dt: datetime) -> datetime:
    next_month = _add_months(datetime(dt.year, dt.month, 1), 1)
    return next_month - timedelta(days=1)


def get_default_date_range() -> tuple[datetime, datetime]:
    today = datetime.now()
    end = _last_day_of_month(today)
    start = _add_months(datetime(today.year, today.month, 1), -5)
    return start, end


def parse_date_range(range_str: str) -> tuple[datetime, datetime] | None:
    match = re.match(r"(\d{4})-(\d{2})[~\-](\d{4})-(\d{2})", range_str)
    if match:
        y1, m1, y2, m2 = match.groups()
        return (
            datetime(int(y1), int(m1), 1),
            _last_day_of_month(datetime(int(y2), int(m2), 1)),
        )

    match = re.match(r"(\d{2})年(\d{1,2})月[~\-](\d{2})年(\d{1,2})月", range_str)
    if match:
        y1, m1, y2, m2 = match.groups()
        year1 = 2000 + int(y1) if int(y1) < 100 else int(y1)
        year2 = 2000 + int(y2) if int(y2) < 100 else int(y2)
        return (
            datetime(year1, int(m1), 1),
            _last_day_of_month(datetime(year2, int(m2), 1)),
        )

    match = re.match(r"(\d{4})[~\-](\d{4})", range_str)
    if match:
        y1, m1 = int(match.group(1)[:2]), int(match.group(1)[2:])
        y2, m2 = int(match.group(2)[:2]), int(match.group(2)[2:])
        year1 = 2000 + y1 if y1 < 100 else y1
        year2 = 2000 + y2 if y2 < 100 else y2
        return (
            datetime(year1, m1, 1),
            _last_day_of_month(datetime(year2, m2, 1)),
        )

    return None


def filter_transactions(transactions: list, date_range: tuple[datetime, datetime] | None) -> list:
    if date_range is None:
        return transactions
    start, end = date_range
    return [
        tx
        for tx in transactions
        if start.date() <= tx.transaction_time.date() <= end.date()
    ]


def process_pdf(pdf_path: str, date_range_str: str | None = None) -> dict:
    path = Path(pdf_path)
    detection = detect_bank_type(str(path))
    if not detection.bank_id:
        raise ValueError(f"无法识别该PDF的银行格式: {path}\n{detection.reason}")

    transactions = extract_transactions(str(path), detection.bank_id)
    detected_flow_type = income_flow_type(detection.bank_id)
    for tx in transactions:
        tx.source_file = path.name
        tx.bank_label = detection.label
        tx.flow_type = detected_flow_type

    if date_range_str and date_range_str.lower() == "all":
        date_range = None
    elif date_range_str:
        date_range = parse_date_range(date_range_str)
        if date_range is None:
            raise ValueError(f"日期范围无法解析: {date_range_str}")
    else:
        date_range = get_default_date_range()

    shown_transactions = filter_transactions(transactions, date_range)
    summary = summarize(shown_transactions, path.name)
    review_issues = [issue for issue in summary.issues if issue.level == "需复核"]
    status = "通过" if shown_transactions and not review_issues else "需复核"
    message = detection.reason if shown_transactions else "未解析到流水"
    result = FileResult(
        path,
        detection.bank_id,
        detection.label,
        detection.confidence,
        detection.reason,
        summary,
        shown_transactions,
        status,
        message,
    )
    output_path = path.with_name(f"{path.stem}_解析结果.xlsx")
    write_workbook(output_path, [result], summary.issues, [])
    return {"result": result, "output_path": output_path, "date_range": date_range}


def print_result(processed: dict) -> None:
    result = processed["result"]
    summary = result.summary
    date_range = processed["date_range"]

    print(f"\n  银行: {result.bank_label}")
    print(f"  流水类型: {income_flow_type(result.bank_id)}")
    if date_range is None:
        print("  日期范围: 全部")
    else:
        print(f"  日期范围: {date_range[0].strftime('%Y-%m')} ~ {date_range[1].strftime('%Y-%m')}")
    print(
        f"  总笔数: {summary.count}，收入 {summary.income_count} 笔/{money(summary.income_sum)}，"
        f"支出 {summary.expense_count} 笔/{money(summary.expense_sum)}，净额 {money(summary.net)}"
    )
    print(f"  期初余额: {money(summary.opening_balance)}，期末余额: {money(summary.closing_balance)}")
    if summary.issues:
        for issue in summary.issues[:5]:
            print(f"    [{issue.level}] {issue.time} {issue.message}")

    rows = monthly_summaries(result.transactions)
    if rows:
        print(f"  {'月份':<10} {'收入笔数':>6} {'收入':>14} {'支出笔数':>6} {'支出':>14}")
        for month, month_summary in rows:
            print(
                f"  {month:<10} {month_summary.income_count:>6} "
                f"{money(month_summary.income_sum):>14} {month_summary.expense_count:>6} "
                f"{money(month_summary.expense_sum):>14}"
            )
    print(f"  输出文件: {processed['output_path']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="银行流水PDF批量处理 v2")
    parser.add_argument("pdfs", nargs="+", help="PDF文件路径")
    parser.add_argument(
        "--date-range",
        "-d",
        default=None,
        help='日期范围: "2025-11~2026-04" / "all"(全部)',
    )
    args = parser.parse_args()

    success = 0
    failed: list[str] = []

    for pdf_path in args.pdfs:
        pdf_path = str(pdf_path)
        if not os.path.isfile(pdf_path):
            print(f"  [跳过] 文件不存在: {pdf_path}")
            continue
        if not pdf_path.lower().endswith(".pdf"):
            print(f"  [跳过] 非PDF: {pdf_path}")
            continue

        try:
            print(f"\n{'=' * 60}")
            print(f"  处理: {os.path.basename(pdf_path)}")
            print(f"{'=' * 60}")
            processed = process_pdf(pdf_path, date_range_str=args.date_range)
            if processed["result"].summary.count == 0:
                print("  [警告] 未提取到流水数据")
                failed.append(pdf_path)
                continue
            print_result(processed)
            success += 1
        except Exception as exc:
            print(f"  [错误] {exc}")
            failed.append(pdf_path)

    print(f"\n{'=' * 60}")
    print(f"  处理完成: 成功 {success} 份, 失败 {len(failed)} 份")
    if failed:
        for path in failed:
            print(f"    失败: {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
