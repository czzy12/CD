from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国银行个人"
DATE_COL = 0
TIME_COL = 1
AMOUNT_COL = 3
BALANCE_COL = 4
RAW_HEADERS = [
    "记账日期",
    "记账时间",
    "币别",
    "金额",
    "余额",
    "交易名称",
    "渠道",
    "网点名称",
    "附言",
    "对方账户名",
    "对方卡号/账号",
    "对方开户行",
]


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_time(date_raw: str | None, time_raw: str | None) -> datetime | None:
    try:
        return datetime.strptime(f"{_clean_cell(date_raw)} {_clean_cell(time_raw)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _row_is_transaction(row: list) -> bool:
    if len(row) <= BALANCE_COL:
        return False
    return _parse_time(row[DATE_COL], row[TIME_COL]) is not None


def _amounts(raw_amount: str, transaction_name: str = "") -> tuple[Decimal, Decimal, list[str]]:
    issues: list[str] = []
    amount = money_to_decimal(raw_amount)
    if amount is None:
        return Decimal("0.00"), Decimal("0.00"), ["金额无法解析"]
    if amount > 0:
        return amount, Decimal("0.00"), issues
    if amount < 0:
        if "冲正" in transaction_name:
            return -amount, Decimal("0.00"), issues
        return Decimal("0.00"), -amount, issues
    issues.append("金额为零")
    return Decimal("0.00"), Decimal("0.00"), issues


def _restore_duplicate_order(transactions: list[Transaction]) -> None:
    groups: dict[datetime, list[Transaction]] = {}
    for tx in transactions:
        groups.setdefault(tx.transaction_time, []).append(tx)

    for items in groups.values():
        if len(items) < 2:
            continue
        for index, tx in enumerate(items):
            tx.transaction_time = tx.transaction_time.replace(microsecond=len(items) - index - 1)


def extract_boc(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if not row or not _row_is_transaction(row):
                        continue

                    raw_amount = _clean_cell(row[AMOUNT_COL])
                    raw_balance = _clean_cell(row[BALANCE_COL])
                    transaction_name = _clean_cell(row[5]) if len(row) > 5 else ""
                    income, expense, issues = _amounts(raw_amount, transaction_name)
                    balance = money_to_decimal(raw_balance)
                    if balance is None:
                        issues.append("余额无法解析")

                    fields = [_clean_cell(cell) for cell in row]
                    transactions.append(
                        Transaction(
                            transaction_time=_parse_time(row[DATE_COL], row[TIME_COL]),
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=f"{fields[DATE_COL]} {fields[TIME_COL]}",
                            raw_amount=raw_amount,
                            raw_balance=raw_balance,
                            raw_text=" | ".join(fields),
                            raw_fields=fields,
                            raw_headers=RAW_HEADERS,
                            status="ok" if not issues else "review",
                            issues=issues,
                        )
                    )

    _restore_duplicate_order(transactions)
    return transactions
