from datetime import datetime
from decimal import Decimal
from typing import Any

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "支付宝交易流水"
ZERO = Decimal("0.00")


def _clean(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def _parse_time(value: Any) -> datetime | None:
    text = _clean(value).replace("/", "-")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _parse_amount(value: Any) -> Decimal | None:
    return money_to_decimal(_clean(value).replace("￥", "").replace("¥", "").replace(" ", ""))


def _direction(value: Any) -> str | None:
    text = _clean(value).replace(" ", "")
    if "不计收支" in text:
        return "neutral"
    if "收入" in text:
        return "income"
    if "支出" in text:
        return "expense"
    return None


def extract_alipay(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                header_index = None
                for index, row in enumerate(table[:10]):
                    headers = [_clean(cell).replace(" ", "") for cell in row]
                    if "收/支" in headers and "金额" in headers and "交易时间" in headers:
                        header_index = index
                        break
                if header_index is None:
                    first_col = _clean(table[0][0]) if table and table[0] else ""
                    if table and len(table[0]) >= 8 and _direction(first_col) is not None:
                        header_index = -1
                    else:
                        continue

                for row_no, row in enumerate(table[header_index + 1 :], start=header_index + 2):
                    if len(row) < 8:
                        continue
                    tx_time = _parse_time(row[7])
                    amount = _parse_amount(row[4])
                    direction = _direction(row[0])
                    if tx_time is None or amount is None or direction is None:
                        continue

                    income = amount if direction == "income" else ZERO
                    expense = amount if direction == "expense" else ZERO
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=None,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=row_no,
                        raw_time=_clean(row[7]),
                        raw_amount=_clean(row[4]),
                        raw_balance="",
                        raw_text=" | ".join(_clean(cell) for cell in row),
                        raw_fields=[_clean(cell) for cell in row],
                        raw_headers=["收/支", "交易对方", "商品说明", "收/付款方式", "金额", "交易订单号", "商家订单号", "交易时间"],
                    )
                    tx.balance_optional = True
                    tx.neutral = direction == "neutral"
                    transactions.append(tx)

    return transactions
