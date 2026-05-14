from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "交通银行"
DATE_COL = 1
TIME_COL = 2
TYPE_COL = 3
DIRECTION_COL = 4
AMOUNT_COL = 5
BALANCE_COL = 6


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_time(date_raw: str | None, time_raw: str | None) -> datetime | None:
    date_text = _clean_cell(date_raw)
    time_text = _clean_cell(time_raw)
    try:
        return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _row_is_transaction(row: list) -> bool:
    if len(row) <= BALANCE_COL:
        return False
    return _clean_cell(row[0]).isdigit() and _parse_time(row[DATE_COL], row[TIME_COL]) is not None


def extract_bocom(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if not row or not _row_is_transaction(row):
                        continue

                    tx_time = _parse_time(row[DATE_COL], row[TIME_COL])
                    amount = money_to_decimal(_clean_cell(row[AMOUNT_COL])) or Decimal("0.00")
                    balance = money_to_decimal(_clean_cell(row[BALANCE_COL]))
                    direction = _clean_cell(row[DIRECTION_COL])
                    issues: list[str] = []

                    if "贷" in direction or "Cr" in direction:
                        income = amount
                        expense = Decimal("0.00")
                    elif "借" in direction or "Dr" in direction:
                        income = Decimal("0.00")
                        expense = amount
                    else:
                        income = Decimal("0.00")
                        expense = Decimal("0.00")
                        issues.append("借贷方向无法解析")

                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=f"{_clean_cell(row[DATE_COL])} {_clean_cell(row[TIME_COL])}",
                            raw_amount=_clean_cell(row[AMOUNT_COL]),
                            raw_balance=_clean_cell(row[BALANCE_COL]),
                            status="ok" if not issues else "review",
                            issues=issues,
                        )
                    )

    return transactions
