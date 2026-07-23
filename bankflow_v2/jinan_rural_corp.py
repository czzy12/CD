from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "济南农商银行对公"
RAW_HEADERS = ["记账日期", "交易金额", "账户余额", "交易摘要", "交易对手信息"]
ZERO = Decimal("0.00")


def _cell(row: list, index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).replace("\n", " ").strip()


def extract_jinan_rural_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 9:
                        continue
                    raw_date = _cell(row, 0)
                    raw_amount = _cell(row, 1)
                    raw_balance = _cell(row, 3)
                    try:
                        tx_time = datetime.strptime(raw_date, "%Y-%m-%d")
                    except ValueError:
                        continue
                    signed_amount = money_to_decimal(raw_amount)
                    balance = money_to_decimal(raw_balance)
                    if signed_amount is None or balance is None:
                        continue

                    income = signed_amount if signed_amount > ZERO else ZERO
                    expense = abs(signed_amount) if signed_amount < ZERO else ZERO
                    raw_fields = [
                        raw_date,
                        raw_amount,
                        raw_balance,
                        _cell(row, 5),
                        _cell(row, 8),
                    ]
                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_no,
                            row_no=len(transactions) + 1,
                            raw_time=raw_date,
                            raw_amount=raw_amount,
                            raw_balance=raw_balance,
                            raw_text=" | ".join(raw_fields),
                            raw_fields=raw_fields,
                            raw_headers=RAW_HEADERS,
                        )
                    )
    return transactions
