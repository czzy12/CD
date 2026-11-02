from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "山西银行对公"
HEADERS = ["交易日期", "摘要", "交易金额", "账户余额", "现转标志", "对方户名", "对方行名", "备注"]


def _cell(row: list, index: int) -> str:
    return str(row[index] or "").replace("\n", " ").strip() if index < len(row) else ""


def extract_shanxi_bank_corp(pdf_path: str) -> list[Transaction]:
    printed_rows: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 4:
                        continue
                    raw_date = _cell(row, 0)
                    try:
                        tx_date = datetime.strptime(raw_date, "%Y%m%d")
                    except ValueError:
                        continue
                    amount = money_to_decimal(_cell(row, 2))
                    balance = money_to_decimal(_cell(row, 3))
                    if amount is None or balance is None:
                        continue
                    fields = [_cell(row, index) for index in range(len(row))]
                    printed_rows.append(Transaction(
                        transaction_time=tx_date,
                        income=amount if amount > 0 else Decimal("0.00"),
                        expense=-amount if amount < 0 else Decimal("0.00"),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(printed_rows) + 1,
                        raw_time=raw_date,
                        raw_amount=fields[2],
                        raw_balance=fields[3],
                        raw_text=" | ".join(fields),
                        raw_fields=fields,
                        raw_headers=HEADERS,
                    ))

    rows = list(reversed(printed_rows))
    for row_no, tx in enumerate(rows, start=1):
        tx.page_no = 1
        tx.row_no = row_no
    return rows
