from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国邮政储蓄银行"
TIME_COL = 0
AMOUNT_COL = 5
BALANCE_COL = 6


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", " ").strip()


def _parse_time(raw: str | None) -> datetime | None:
    text = _clean_cell(raw)
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def extract_psbc(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if len(row) <= BALANCE_COL:
                        continue
                    tx_time = _parse_time(row[TIME_COL])
                    if tx_time is None:
                        continue

                    amount = money_to_decimal(_clean_cell(row[AMOUNT_COL]))
                    balance = money_to_decimal(_clean_cell(row[BALANCE_COL]))
                    issues = []
                    if amount is None:
                        issues.append("金额无法解析")
                        amount = Decimal("0.00")
                    if balance is None:
                        issues.append("余额无法解析")

                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=amount if amount > 0 else Decimal("0.00"),
                            expense=-amount if amount < 0 else Decimal("0.00"),
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=_clean_cell(row[TIME_COL]),
                            raw_amount=_clean_cell(row[AMOUNT_COL]),
                            raw_balance=_clean_cell(row[BALANCE_COL]),
                            status="ok" if not issues else "review",
                            issues=issues,
                        )
                    )

    return transactions
