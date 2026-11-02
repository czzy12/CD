from datetime import datetime
from decimal import Decimal

import pdfplumber

from .icbc_corp import _restore_same_time_order
from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "青岛银行对公"
HEADERS = ["交易日期", "交易类型", "收入金额", "支出金额", "余额", "对方账号", "对方户名", "备注"]


def _cell(row: list, index: int) -> str:
    return str(row[index] or "").replace("\n", " ").strip() if index < len(row) else ""


def _restore_amounts_from_balance(rows: list[Transaction]) -> None:
    ordered = sorted(rows, key=lambda tx: (tx.transaction_time, tx.page_no, tx.row_no))
    previous: Transaction | None = None
    for tx in ordered:
        if previous is not None:
            delta = (tx.balance - previous.balance).quantize(Decimal("0.01"))
            tx.income = delta if delta > 0 else Decimal("0.00")
            tx.expense = -delta if delta < 0 else Decimal("0.00")
        previous = tx


def extract_qingdao_corp(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 5:
                        continue
                    raw_time = _cell(row, 0)
                    try:
                        tx_time = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
                    except ValueError:
                        continue
                    income = money_to_decimal(_cell(row, 2)) or Decimal("0.00")
                    expense = money_to_decimal(_cell(row, 3)) or Decimal("0.00")
                    balance = money_to_decimal(_cell(row, 4))
                    fields = [_cell(row, index) for index in range(len(row))]
                    rows.append(Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(rows) + 1,
                        raw_time=raw_time,
                        raw_amount=f"{fields[2]}|{fields[3]}",
                        raw_balance=fields[4],
                        raw_text=" | ".join(fields),
                        raw_fields=fields,
                        raw_headers=HEADERS,
                    ))
    rows = _restore_same_time_order(rows)
    _restore_amounts_from_balance(rows)
    return rows
