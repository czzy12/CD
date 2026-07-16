from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

from .models import Transaction


BANK_NAME = "农村商业银行对公"
CENT = Decimal("0.01")
HEADERS = ["交易日期", "摘要", "借方金额", "贷方金额", "余额", "币种", "对方账号/户名", "用途"]


def _cell(row: list[Any], index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).replace("\n", "").strip()


def _money(value: Any) -> Decimal | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return Decimal("0.00")
    try:
        return Decimal(text).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _date(value: Any) -> datetime | None:
    text = _cell([value], 0)
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None


def _is_transaction_row(row: list[Any]) -> bool:
    if len(row) < 5 or _date(row[0]) is None:
        return False
    debit = _money(row[2])
    credit = _money(row[3])
    balance = _money(row[4])
    return debit is not None and credit is not None and balance is not None and (debit != 0 or credit != 0)


def extract_customer_account_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if not _is_transaction_row(row):
                        continue

                    tx_time = _date(row[0])
                    debit = _money(row[2])
                    credit = _money(row[3])
                    balance = _money(row[4])
                    if tx_time is None or debit is None or credit is None or balance is None:
                        continue

                    raw_fields = [_cell(row, index) for index in range(len(row))]
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=credit,
                        expense=debit,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(transactions) + 1,
                        raw_time=_cell(row, 0),
                        raw_amount=f"借方:{_cell(row, 2)} 贷方:{_cell(row, 3)}",
                        raw_balance=_cell(row, 4),
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=HEADERS,
                    )
                    tx.preserve_signed_columns = True
                    transactions.append(tx)

    return transactions
