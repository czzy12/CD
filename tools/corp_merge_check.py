import argparse
import sys
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.ccb_corp import extract_ccb_corp, merge_transactions


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def load_gold(excel_path: str, sheet_name: str = "Sheet1") -> list[dict]:
    ws = openpyxl.load_workbook(excel_path, data_only=True)[sheet_name]
    rows: list[dict] = []

    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[1] is None and row[2] is None and row[3] is None:
            continue
        rows.append(
            {
                "month": str(row[0]).zfill(2),
                "debit": money(row[1] or 0),
                "credit": money(row[2] or 0),
                "balance": money(row[3]),
            }
        )

    return rows


def summarize(rows: list[dict]) -> dict:
    debit_sum = sum((row["debit"] for row in rows), Decimal("0.00"))
    credit_sum = sum((row["credit"] for row in rows), Decimal("0.00"))
    return {
        "count": len(rows),
        "debit_count": sum(1 for row in rows if row["debit"] > 0),
        "debit_sum": debit_sum,
        "credit_count": sum(1 for row in rows if row["credit"] > 0),
        "credit_sum": credit_sum,
        "net": credit_sum - debit_sum,
        "first_balance": rows[0]["balance"] if rows else None,
        "last_balance": rows[-1]["balance"] if rows else None,
    }


def main():
    parser = argparse.ArgumentParser(description="对公多PDF合并黄金样本对账")
    parser.add_argument("--dir", required=True, help="包含多份PDF和人工确认Excel的目录")
    parser.add_argument("--gold", default="合计.xlsx", help="人工确认Excel文件名")
    args = parser.parse_args()

    base_dir = Path(args.dir)
    gold_rows = load_gold(str(base_dir / args.gold))
    gold_months = {row["month"] for row in gold_rows}

    parsed = []
    for pdf_path in sorted(base_dir.glob("*.pdf")):
        parsed.extend(extract_ccb_corp(str(pdf_path)))

    parsed = [tx for tx in parsed if tx.transaction_time.strftime("%m") in gold_months]
    merged = merge_transactions(parsed)
    parsed_rows = [
        {
            "debit": tx.expense,
            "credit": tx.income,
            "balance": tx.balance,
            "status": tx.status,
            "raw_time": tx.raw_time,
            "raw_amount": tx.raw_amount,
            "raw_balance": tx.raw_balance,
        }
        for tx in merged
    ]

    print("Dir:", base_dir)
    print("PDF rows after month filter:", len(parsed))
    print("PDF rows after merge:", len(parsed_rows))
    print("Gold:", base_dir / args.gold)
    print("gold summary:", summarize(gold_rows))
    print("parsed summary:", summarize(parsed_rows))
    print("statuses:", Counter(row["status"] for row in parsed_rows))

    diffs = []
    if len(gold_rows) != len(parsed_rows):
        diffs.append(f"笔数不一致 gold={len(gold_rows)} parsed={len(parsed_rows)}")

    for idx, (gold, parsed_row) in enumerate(zip(gold_rows, parsed_rows), start=1):
        for key in ["debit", "credit", "balance"]:
            if gold[key] != parsed_row[key]:
                diffs.append(
                    f"第 {idx} 行 {key} 不一致 gold={gold[key]} parsed={parsed_row[key]} "
                    f"raw=({parsed_row['raw_time']} | {parsed_row['raw_amount']} | {parsed_row['raw_balance']})"
                )
                break

    if diffs:
        print("\nDIFFS")
        for diff in diffs[:50]:
            print("-", diff)
        raise SystemExit(1)

    print("\nPASS")


if __name__ == "__main__":
    main()
