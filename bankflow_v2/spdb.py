from datetime import datetime
from decimal import Decimal
import re

import pdfplumber

from .models import Transaction
from .number_parser import choose_amount_and_balance, money_to_decimal


SPDB_NAME = "上海浦东发展银行"
SPDB_CORP_NAME = "上海浦东发展银行对公"


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_personal_time(raw_date: str | None, raw_time: str | None) -> datetime | None:
    date_text = re.sub(r"\D", "", _clean_cell(raw_date))
    time_text = re.sub(r"\D", "", _clean_cell(raw_time)) or "000000"
    if len(date_text) != 8 or len(time_text) != 6:
        return None
    try:
        return datetime(
            int(date_text[:4]),
            int(date_text[4:6]),
            int(date_text[6:8]),
            int(time_text[:2]),
            int(time_text[2:4]),
            int(time_text[4:6]),
        )
    except ValueError:
        return None


def _parse_corp_time(raw_date: str | None) -> datetime | None:
    text = _clean_cell(raw_date)
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def extract_spdb(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if not row or len(row) < 6:
                        continue
                    tx_time = _parse_personal_time(row[0], row[1])
                    if tx_time is None:
                        continue

                    amount, balance, issues = choose_amount_and_balance(row[4], row[5], previous_balance)
                    if amount is None:
                        amount = Decimal("0.00")

                    income = amount if amount > 0 else Decimal("0.00")
                    expense = -amount if amount < 0 else Decimal("0.00")
                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=SPDB_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=f"{_clean_cell(row[0])} {_clean_cell(row[1])}".strip(),
                            raw_amount=_clean_cell(row[4]),
                            raw_balance=_clean_cell(row[5]),
                            raw_fields=[_clean_cell(cell) for cell in row],
                            status="ok" if not issues else "review",
                            issues=issues,
                        )
                    )
                    if balance is not None:
                        previous_balance = balance

    return transactions


def extract_spdb_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if not row or len(row) < 5:
                        continue
                    tx_time = _parse_corp_time(row[0])
                    if tx_time is None:
                        continue

                    debit = money_to_decimal(_clean_cell(row[2]))
                    credit = money_to_decimal(_clean_cell(row[3]))
                    balance = money_to_decimal(_clean_cell(row[4]))
                    issues: list[str] = []

                    if debit is not None and credit is not None:
                        issues.append("借方和贷方同时存在")
                    if debit is None and credit is None:
                        issues.append("借方/贷方金额无法解析")
                    if balance is None:
                        issues.append("余额无法解析")

                    income = credit or Decimal("0.00")
                    expense = debit or Decimal("0.00")
                    raw_amount = _clean_cell(row[3] if credit is not None else row[2])

                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=SPDB_CORP_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=_clean_cell(row[0]),
                            raw_amount=raw_amount,
                            raw_balance=_clean_cell(row[4]),
                            raw_fields=[_clean_cell(cell) for cell in row],
                            status="ok" if not issues else "review",
                            issues=issues,
                        )
                    )

    return transactions
