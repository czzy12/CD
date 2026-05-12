import argparse
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2 import extract_transactions


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def load_gold(excel_path: str, sheet_name: str = "Sheet1") -> list[dict]:
    wb = openpyxl.load_workbook(excel_path, data_only=True)
    ws = wb[sheet_name]
    rows: list[dict] = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        if not row[0]:
            continue
        amount = money(row[1])
        rows.append(
            {
                "transaction_time": row[0],
                "amount": amount,
                "income": amount if amount > 0 else Decimal("0.00"),
                "expense": -amount if amount < 0 else Decimal("0.00"),
                "balance": money(row[2]),
            }
        )
    return rows


def filter_range(transactions, start: datetime, end: datetime):
    start_day = datetime(start.year, start.month, start.day)
    end_day = datetime(end.year, end.month, end.day, 23, 59, 59, 999999)
    return [tx for tx in transactions if start_day <= tx.transaction_time <= end_day]


def summarize(rows: list[dict]) -> dict:
    income_count = sum(1 for row in rows if row["income"] > 0)
    expense_count = sum(1 for row in rows if row["expense"] > 0)
    income_sum = sum((row["income"] for row in rows), Decimal("0.00"))
    expense_sum = sum((row["expense"] for row in rows), Decimal("0.00"))
    return {
        "count": len(rows),
        "income_count": income_count,
        "income_sum": income_sum,
        "expense_count": expense_count,
        "expense_sum": expense_sum,
        "net": income_sum - expense_sum,
        "first_balance": rows[0]["balance"] if rows else None,
        "last_balance": rows[-1]["balance"] if rows else None,
    }


def tx_to_row(tx) -> dict:
    return {
        "transaction_time": tx.transaction_time,
        "amount": tx.amount,
        "income": tx.income,
        "expense": tx.expense,
        "balance": tx.balance,
        "status": tx.status,
        "issues": tx.issues,
        "raw_time": tx.raw_time,
        "raw_amount": tx.raw_amount,
        "raw_balance": tx.raw_balance,
    }


def compare(gold_rows: list[dict], parsed_rows: list[dict]) -> list[str]:
    diffs: list[str] = []
    if len(gold_rows) != len(parsed_rows):
        diffs.append(f"笔数不一致: gold={len(gold_rows)} parsed={len(parsed_rows)}")

    for idx, (gold, parsed) in enumerate(zip(gold_rows, parsed_rows), start=1):
        checks = ["amount", "income", "expense", "balance"]
        for key in checks:
            if gold[key] != parsed[key]:
                diffs.append(
                    f"第 {idx} 行 {key} 不一致: gold={gold[key]} parsed={parsed[key]} "
                    f"raw=({parsed.get('raw_time')} | {parsed.get('raw_amount')} | {parsed.get('raw_balance')})"
                )
        if gold["transaction_time"].date() != parsed["transaction_time"].date():
            diffs.append(
                f"第 {idx} 行日期不一致: gold={gold['transaction_time']} parsed={parsed['transaction_time']}"
            )
    return diffs


def main():
    parser = argparse.ArgumentParser(description="黄金样本对账")
    parser.add_argument("--pdf", default=r"C:\Users\czzy1\Desktop\流水测试\流水测试\陈洁银行卡.pdf")
    parser.add_argument("--gold", default=r"C:\Users\czzy1\Desktop\陈洁银行卡.xlsx")
    parser.add_argument("--bank", default="icbc")
    args = parser.parse_args()

    gold_rows = load_gold(args.gold)
    start = gold_rows[0]["transaction_time"]
    end = gold_rows[-1]["transaction_time"]

    parsed = extract_transactions(args.pdf, bank=args.bank)
    parsed_rows = [tx_to_row(tx) for tx in filter_range(parsed, start, end)]

    print("PDF:", Path(args.pdf))
    print("Gold:", Path(args.gold))
    print("gold summary:", summarize(gold_rows))
    print("parsed summary:", summarize(parsed_rows))
    print("statuses:", Counter(row["status"] for row in parsed_rows))

    diffs = compare(gold_rows, parsed_rows)
    if diffs:
        print("\nDIFFS")
        for diff in diffs[:50]:
            print("-", diff)
        raise SystemExit(1)

    review_rows = [row for row in parsed_rows if row["status"] != "ok"]
    if review_rows:
        print("\nREVIEW")
        for row in review_rows[:20]:
            print(asdict(row) if hasattr(row, "__dataclass_fields__") else row)

    print("\nPASS")


if __name__ == "__main__":
    main()
