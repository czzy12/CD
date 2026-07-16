from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

from .models import Transaction


BANK_NAME = "重庆银行"
CENT = Decimal("0.01")
HEADERS = [
    "序号",
    "交易日期",
    "交易金额",
    "活期账面余额",
    "交易类型/摘要",
    "交易网点/交易渠道/附言",
    "交易对手信息(对方账号|对方户名|对方银行)",
    "凭证信息(凭证种类|凭证号码)",
]


def _cell(row: list[Any], index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).replace("\n", "").strip()


def _money(value: Any) -> Decimal | None:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
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
    return len(row) >= 4 and _cell(row, 0).isdigit() and _date(row[1]) is not None and _money(row[2]) is not None


def extract_chongqing(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for table_row_no, row in enumerate(table, start=1):
                    if not _is_transaction_row(row):
                        continue

                    tx_time = _date(row[1])
                    amount = _money(row[2])
                    balance = _money(row[3])
                    if tx_time is None or amount is None or balance is None:
                        continue

                    income = amount if amount >= Decimal("0.00") else Decimal("0.00")
                    expense = -amount if amount < Decimal("0.00") else Decimal("0.00")
                    raw_fields = [_cell(row, index) for index in range(len(row))]
                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_no,
                            row_no=len(transactions) + 1,
                            raw_time=_cell(row, 1),
                            raw_amount=_cell(row, 2),
                            raw_balance=_cell(row, 3),
                            raw_text=" | ".join(raw_fields),
                            raw_fields=raw_fields,
                            raw_headers=HEADERS,
                        )
                    )

    return transactions
