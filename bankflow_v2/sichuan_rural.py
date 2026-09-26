from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "四川省农村信用社个人"
HEADERS = ["交易日期", "交易时间", "币种", "交易金额", "账户余额", "对方户名", "对方账号", "对方银行/机构", "用途", "备注", "记账日期"]


def _cell(row: list, index: int) -> str:
    return str(row[index] or "").replace("\n", " ").strip() if index < len(row) else ""


def extract_sichuan_rural(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 5:
                        continue
                    try:
                        tx_time = datetime.strptime(f"{_cell(row, 0)} {_cell(row, 1)}", "%Y%m%d %H:%M:%S")
                    except ValueError:
                        continue
                    amount = money_to_decimal(_cell(row, 3))
                    balance = money_to_decimal(_cell(row, 4))
                    if amount is None or balance is None:
                        continue
                    raw_fields = [_cell(row, i) for i in range(len(row))]
                    transactions.append(Transaction(
                        transaction_time=tx_time,
                        income=amount if amount > 0 else Decimal("0.00"),
                        expense=-amount if amount < 0 else Decimal("0.00"),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(transactions) + 1,
                        raw_time=f"{raw_fields[0]} {raw_fields[1]}",
                        raw_amount=raw_fields[3], raw_balance=raw_fields[4],
                        raw_text=" | ".join(raw_fields[5:]), raw_fields=raw_fields, raw_headers=HEADERS,
                    ))
    # The PDF explicitly excludes reversed postings from its printed totals.
    # Remove only a proven adjacent debit/reversal pair whose balances restore
    # exactly; ordinary refund income remains untouched.
    excluded: set[int] = set()
    for index, tx in enumerate(transactions):
        if index == 0 or "抹账" not in tx.raw_text or tx.income <= 0:
            continue
        original = transactions[index - 1]
        if (
            original.expense == tx.income
            and original.balance is not None
            and tx.balance is not None
            and original.balance + tx.income == tx.balance
        ):
            excluded.update((index - 1, index))
    return [tx for index, tx in enumerate(transactions) if index not in excluded]
