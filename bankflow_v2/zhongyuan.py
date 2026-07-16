from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

from .models import Transaction


BANK_NAME = "中原银行"
CENT = Decimal("0.01")
HEADERS = ["交易日期", "交易时间", "金额", "收支状态", "余额", "对方行名", "对方户名", "对方账号", "交易渠道", "交易类型", "币种", "附言"]


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


def _time(raw_date: str, raw_time: str) -> datetime | None:
    try:
        return datetime.strptime(f"{raw_date} {raw_time}", "%Y%m%d %H:%M:%S")
    except ValueError:
        return None


def _is_transaction_row(row: list[Any]) -> bool:
    return (
        len(row) >= 5
        and _cell(row, 0).isdigit()
        and len(_cell(row, 0)) == 8
        and _cell(row, 1).count(":") == 2
        and _cell(row, 3) in {"收入", "支出"}
    )


def extract_zhongyuan(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if not _is_transaction_row(row):
                        continue

                    tx_time = _time(_cell(row, 0), _cell(row, 1))
                    amount = _money(row[2])
                    balance = _money(row[4])
                    if tx_time is None or amount is None or balance is None:
                        continue

                    direction = _cell(row, 3)
                    sequence += 1
                    # The statement is printed newest-first. Reversing same-second
                    # rows restores the balance chain when duplicate timestamps exist.
                    tx_time = tx_time.replace(microsecond=max(0, 999999 - sequence))
                    raw_fields = [_cell(row, index) for index in range(len(row))]
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=amount if direction == "收入" else Decimal("0.00"),
                        expense=amount if direction == "支出" else Decimal("0.00"),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=sequence,
                        raw_time=f"{_cell(row, 0)} {_cell(row, 1)}",
                        raw_amount=_cell(row, 2),
                        raw_balance=_cell(row, 4),
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=HEADERS,
                    )
                    tx.preserve_signed_columns = True
                    transactions.append(tx)

    return transactions
