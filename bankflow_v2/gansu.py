import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal
from .psbc import _restore_same_time_order


BANK_NAME = "甘肃银行个人"
HEADERS = ["交易时间", "交易金额", "余额", "对方账号/卡号", "对方户名", "收入/支出", "用途", "附言"]
WATERMARK = str.maketrans("", "", "甘肃银行\n\r ")
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}\d{2}:\d{2}:\d{2}")


def _compact(value) -> str:
    return str(value or "").translate(WATERMARK)


def _find_row_fields(row: list) -> tuple[datetime, str, str, str] | None:
    compact = [_compact(cell) for cell in row]
    date_index = next((i for i, cell in enumerate(compact) if DATE_RE.search(cell)), None)
    if date_index is None:
        return None
    match = DATE_RE.search(compact[date_index])
    if match is None:
        return None
    try:
        tx_time = datetime.strptime(match.group(), "%Y-%m-%d%H:%M:%S")
    except ValueError:
        return None

    money_cells: list[str] = []
    for cell in compact[date_index + 1:]:
        if money_to_decimal(cell) is not None:
            money_cells.append(cell)
            if len(money_cells) == 2:
                break
    if len(money_cells) != 2:
        return None
    joined = "|".join(compact)
    direction = "收入" if "收入" in joined else "支出" if "支出" in joined else ""
    if not direction:
        return None
    return tx_time, money_cells[0], money_cells[1], direction


def extract_gansu(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    found = _find_row_fields(row)
                    if found is None:
                        continue
                    tx_time, amount_raw, balance_raw, direction = found
                    amount = money_to_decimal(amount_raw)
                    balance = money_to_decimal(balance_raw)
                    if amount is None or balance is None:
                        continue
                    amount = abs(amount)
                    raw_fields = [str(cell or "").replace("\n", " ").strip() for cell in row]
                    transactions.append(Transaction(
                        transaction_time=tx_time,
                        income=amount if direction == "收入" else Decimal("0.00"),
                        expense=amount if direction == "支出" else Decimal("0.00"),
                        balance=balance, bank=BANK_NAME, page_no=page_no,
                        row_no=len(transactions) + 1, raw_time=tx_time.strftime("%Y-%m-%d %H:%M:%S"),
                        raw_amount=amount_raw, raw_balance=balance_raw,
                        raw_text=" | ".join(raw_fields), raw_fields=raw_fields, raw_headers=HEADERS,
                    ))
    _restore_same_time_order(transactions)
    return transactions
