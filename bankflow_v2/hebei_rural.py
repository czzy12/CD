import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


HEADERS = ["序号", "交易日期", "交易金额", "金额", "对方户名", "对方账号", "摘要", "网点", "来源"]


def _order_daily_balance_chain(transactions: list[Transaction]) -> list[Transaction]:
    groups = defaultdict(list)
    for tx in transactions:
        groups[tx.transaction_time].append(tx)
    ordered = []
    previous_balance = None
    for tx_time in sorted(groups):
        remaining = list(reversed(groups[tx_time]))
        while remaining:
            match = next((tx for tx in remaining if tx.balance is not None and
                          tx.balance - tx.amount == previous_balance), None)
            if match is None and previous_balance is None:
                balances = {tx.balance for tx in remaining}
                match = next((tx for tx in remaining if tx.balance is not None and
                              tx.balance - tx.amount not in balances), None)
            if match is None:
                # Keep an unmatched source row, allowing normal validation to
                # report a gap rather than changing its amount or balance.
                match = remaining[0]
            remaining.remove(match)
            ordered.append(match)
            previous_balance = match.balance
    for row_no, tx in enumerate(ordered, start=1):
        tx.page_no = 0
        tx.row_no = row_no
    return ordered


def extract_hebei_rural(pdf_path: str) -> list[Transaction]:
    transactions = []
    expected_count = None
    account_no = account_name = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            if page_no == 1:
                text = page.extract_text() or ""
                account = re.search(r"账号\s*[:：]\s*(\d+)", text)
                name = re.search(r"户名\s*[:：]\s*(\S+)", text)
                count = re.search(r"总条数\s*[:：]\s*(\d+)", text)
                account_no = account.group(1) if account else ""
                account_name = name.group(1) if name else ""
                expected_count = int(count.group(1)) if count else None
            for table in page.extract_tables():
                for row_no, row in enumerate(table, start=1):
                    if len(row) != 9:
                        continue
                    fields = [str(value or "").replace("\n", "").strip() for value in row]
                    if not fields[0].isdigit():
                        continue
                    try:
                        tx_time = datetime.strptime(fields[1], "%Y%m%d")
                    except ValueError:
                        continue
                    amount = money_to_decimal(fields[2])
                    balance = money_to_decimal(fields[3])
                    if amount is None:
                        raise ValueError(f"交易金额无法读取：{fields[2]}")
                    tx = Transaction(
                        tx_time, income=max(amount, Decimal("0.00")),
                        expense=max(-amount, Decimal("0.00")), balance=balance,
                        bank="河北省农村信用社", page_no=page_no, row_no=row_no,
                        raw_time=fields[1], raw_amount=fields[2], raw_balance=fields[3],
                        raw_text=" | ".join(fields), raw_fields=fields, raw_headers=HEADERS,
                    )
                    tx.account_no = account_no
                    tx.account_name = account_name
                    transactions.append(tx)
    ordered = _order_daily_balance_chain(transactions)
    if ordered and expected_count is not None and len(ordered) != expected_count:
        ordered[0].issues.append(f"明细笔数与打印总条数不一致：识别 {len(ordered)}，打印 {expected_count}")
        ordered[0].status = "review"
    return ordered
