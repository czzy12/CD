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
RAW_HEADERS = ["序号", "交易日期", "交易时间", "交易类型", "借贷标志", "交易金额", "账户余额", "对方账号", "对方户名", "交易渠道", "摘要"]
DATE_ONLY_HEADERS = ["交易日期", "交易地点", "交易方式", "借贷状态", "交易金额", "余额"]


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_time(date_raw: str | None, time_raw: str | None) -> datetime | None:
    date_text = _clean_cell(date_raw)
    time_text = _clean_cell(time_raw)
    try:
        return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_date(date_raw: str | None) -> datetime | None:
    try:
        return datetime.strptime(_clean_cell(date_raw), "%Y-%m-%d")
    except ValueError:
        return None


def _row_is_transaction(row: list) -> bool:
    if len(row) <= BALANCE_COL:
        return False
    return _clean_cell(row[0]).isdigit() and _parse_time(row[DATE_COL], row[TIME_COL]) is not None


def _row_is_date_only_transaction(row: list) -> bool:
    if len(row) < 6:
        return False
    return _parse_date(row[0]) is not None


def _amounts_from_direction(direction: str, amount: Decimal) -> tuple[Decimal, Decimal, list[str]]:
    issues: list[str] = []
    if "贷" in direction or "Cr" in direction:
        return amount, Decimal("0.00"), issues
    if "借" in direction or "Dr" in direction:
        return Decimal("0.00"), amount, issues
    issues.append("借贷方向无法解析")
    return Decimal("0.00"), Decimal("0.00"), issues


def extract_bocom(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if not row:
                        continue

                    if _row_is_transaction(row):
                        tx_time = _parse_time(row[DATE_COL], row[TIME_COL])
                        amount = money_to_decimal(_clean_cell(row[AMOUNT_COL])) or Decimal("0.00")
                        balance = money_to_decimal(_clean_cell(row[BALANCE_COL]))
                        direction = _clean_cell(row[DIRECTION_COL])
                        income, expense, issues = _amounts_from_direction(direction, amount)

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
                                raw_text=" | ".join(_clean_cell(cell) for cell in row),
                                raw_fields=[_clean_cell(cell) for cell in row],
                                raw_headers=RAW_HEADERS,
                                status="ok" if not issues else "review",
                                issues=issues,
                            )
                        )
                    elif _row_is_date_only_transaction(row):
                        tx_time = _parse_date(row[0])
                        amount = money_to_decimal(_clean_cell(row[4])) or Decimal("0.00")
                        balance = money_to_decimal(_clean_cell(row[5]))
                        direction = _clean_cell(row[3])
                        income, expense, issues = _amounts_from_direction(direction, amount)

                        transactions.append(
                            Transaction(
                                transaction_time=tx_time,
                                income=income,
                                expense=expense,
                                balance=balance,
                                bank=BANK_NAME,
                                page_no=page_index,
                                row_no=row_index,
                                raw_time=_clean_cell(row[0]),
                                raw_amount=_clean_cell(row[4]),
                                raw_balance=_clean_cell(row[5]),
                                raw_text=" | ".join(_clean_cell(cell) for cell in row),
                                raw_fields=[_clean_cell(cell) for cell in row],
                                raw_headers=DATE_ONLY_HEADERS,
                                status="ok" if not issues else "review",
                                issues=issues,
                            )
                        )

    return transactions
