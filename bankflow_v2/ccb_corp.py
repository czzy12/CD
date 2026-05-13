from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国建设银行"
TIME_COL = 1
DEBIT_COL = 2
CREDIT_COL = 3
BALANCE_COL = 4
SERIAL_COL = 12


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_time(raw: str | None) -> datetime | None:
    text = _clean_cell(raw)
    if len(text) == 16 and text[8] != " ":
        text = f"{text[:8]} {text[8:]}"
    try:
        return datetime.strptime(text, "%Y%m%d %H:%M:%S")
    except ValueError:
        return None


def _parse_money(raw: str | None) -> Decimal:
    return money_to_decimal(_clean_cell(raw)) or Decimal("0.00")


def _transaction_key(row: list) -> str:
    serial = _clean_cell(row[SERIAL_COL]) if len(row) > SERIAL_COL else ""
    if serial:
        return serial
    return "|".join(
        _clean_cell(row[index])
        for index in (TIME_COL, DEBIT_COL, CREDIT_COL, BALANCE_COL)
        if len(row) > index
    )


def extract_ccb_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if len(row) <= BALANCE_COL:
                        continue

                    tx_time = _parse_time(row[TIME_COL])
                    if tx_time is None:
                        continue

                    debit = _parse_money(row[DEBIT_COL])
                    credit = _parse_money(row[CREDIT_COL])
                    balance = money_to_decimal(_clean_cell(row[BALANCE_COL]))
                    income = credit
                    expense = debit
                    issues = []

                    if debit > 0 and credit > 0:
                        issues.append("借方和贷方同时有金额")
                    if debit == 0 and credit == 0:
                        issues.append("借方和贷方均为零")

                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=_clean_cell(row[TIME_COL]),
                            raw_amount=f"{_clean_cell(row[DEBIT_COL])}|{_clean_cell(row[CREDIT_COL])}",
                            raw_balance=_clean_cell(row[BALANCE_COL]),
                            status="ok" if not issues else "review",
                            issues=issues,
                        )
                    )

                    transactions[-1].merge_key = _transaction_key(row)

    return transactions


def merge_transactions(transactions: list[Transaction]) -> list[Transaction]:
    merged: list[Transaction] = []
    seen: set[str] = set()

    for tx in sorted(transactions, key=lambda item: (item.transaction_time, getattr(item, "merge_key", ""))):
        key = getattr(tx, "merge_key", "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(tx)

    return merged
