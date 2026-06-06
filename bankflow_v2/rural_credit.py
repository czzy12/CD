import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction


BANK_NAME = "农村信用社"
MONEY_RE = re.compile(r"[\d,]+\.\d{2}")


def _cell(row: list[str], index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def _money(text: str) -> Decimal | None:
    match = MONEY_RE.search(text or "")
    if not match:
        return None
    return Decimal(match.group(0).replace(",", "")).quantize(Decimal("0.01"))


def _time(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def extract_rural_credit(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 6 or _cell(row, 1) == "交易日期":
                        continue

                    tx_time = _time(_cell(row, 1))
                    amount = _money(_cell(row, 4))
                    balance = _money(_cell(row, 5))
                    direction = _cell(row, 3)
                    if tx_time is None or amount is None or balance is None:
                        continue
                    if direction not in ("收入", "支出"):
                        continue

                    sequence += 1
                    # The PDF is printed newest-first. Microseconds make rows
                    # with the same second sort back into balance-chain order.
                    sort_time = tx_time.replace(microsecond=max(0, 999999 - sequence))
                    income = amount if direction == "收入" else Decimal("0.00")
                    expense = amount if direction == "支出" else Decimal("0.00")
                    tx = Transaction(
                        transaction_time=sort_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=sequence,
                        raw_time=_cell(row, 1),
                        raw_amount=_cell(row, 4),
                        raw_balance=_cell(row, 5),
                        raw_text=" ".join(_cell(row, index) for index in range(min(len(row), 11))),
                        raw_fields=[_cell(row, index) for index in range(len(row))],
                        raw_headers=["交易流水号", "交易日期", "交易网点", "收入/支出", "交易金额", "实时余额", "交易渠道", "对方户名", "对方账号", "对方行名称", "备注"],
                    )
                    tx.merge_key = "|".join([_cell(row, 0), _cell(row, 1), direction, _cell(row, 4), _cell(row, 5), str(page_no), str(sequence)])
                    rows.append(tx)

    return rows
