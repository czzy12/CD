from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

from .models import Transaction


BANK_NAME = "天津农村商业银行对公"
CENT = Decimal("0.01")
HEADERS = ["交易日期", "收入", "支出", "余额", "对方户名", "对方账号", "对方开户行", "摘要", "备注"]


def _cell(row: list[Any], index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).replace("\n", "").strip()


def _money(value: Any) -> Decimal:
    text = str(value or "").replace(",", "").strip()
    if not text or text == "--":
        return Decimal("0.00")
    try:
        return Decimal(text).quantize(CENT)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _time(value: Any) -> datetime | None:
    text = _cell([value], 0)
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def extract_tianjin_rural_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table[1:]:
                    tx_time = _time(row[0] if row else None)
                    if tx_time is None or len(row) < 4:
                        continue

                    income = _money(row[1])
                    expense = _money(row[2])
                    balance = _money(row[3])
                    raw_fields = [_cell(row, index) for index in range(len(row))]
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(transactions) + 1,
                        raw_time=_cell(row, 0),
                        raw_amount=f"收入:{_cell(row, 1)} 支出:{_cell(row, 2)}",
                        raw_balance=_cell(row, 3),
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=HEADERS,
                    )
                    tx.preserve_signed_columns = True
                    transactions.append(tx)

    return transactions
