from datetime import datetime
from decimal import Decimal
import re

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国邮政储蓄银行"
TIME_COL = 0
AMOUNT_COL = 5
BALANCE_COL = 6
CORP_HEADERS = [
    "序号",
    "交易时间",
    "记账日期",
    "支出金额",
    "收入金额",
    "余额",
    "对方账号",
    "对方户名",
    "对方行名",
    "用途",
    "附言",
    "摘要",
    "交易流水号",
    "全局路由号",
]
CORP_DATE_COL = 2
CORP_EXPENSE_COL = 3
CORP_INCOME_COL = 4
CORP_BALANCE_COL = 5


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", " ").strip()


def _parse_time(raw: str | None) -> datetime | None:
    text = _clean_cell(raw)
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_corp_time(raw_time: str | None, raw_date: str | None) -> datetime | None:
    date_text = _clean_cell(raw_date)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
        return None

    time_text = _clean_cell(raw_time)
    match = re.search(r"\d{4}-\d{2}-\d{2}\s*(\d?)\s*([0-9]:\d{2}:\d{2})", time_text)
    if match:
        hour_prefix = match.group(1)
        time_part = match.group(2)
        if hour_prefix:
            time_part = f"{hour_prefix}{time_part}"
        if len(time_part.split(":", 1)[0]) == 1:
            time_part = f"0{time_part}"
        try:
            return datetime.strptime(f"{date_text} {time_part}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    return datetime.strptime(date_text, "%Y-%m-%d")


def _is_corp_header(row: list) -> bool:
    joined = "".join(_clean_cell(cell) for cell in row)
    return "交易时间" in joined and "支出金额" in joined and "收入金额" in joined and "全局路由号" in joined


def _is_corp_row(row: list) -> bool:
    return len(row) > CORP_BALANCE_COL and _clean_cell(row[0]).isdigit()


def _parse_corp_row(row: list, page_no: int, row_no: int) -> Transaction | None:
    if not _is_corp_row(row):
        return None

    tx_time = _parse_corp_time(row[1], row[CORP_DATE_COL])
    if tx_time is None:
        return None

    expense_raw = _clean_cell(row[CORP_EXPENSE_COL])
    income_raw = _clean_cell(row[CORP_INCOME_COL])
    balance_raw = _clean_cell(row[CORP_BALANCE_COL])
    expense = money_to_decimal(expense_raw) or Decimal("0.00")
    income = money_to_decimal(income_raw) or Decimal("0.00")
    balance = money_to_decimal(balance_raw)

    issues = []
    if income > 0 and expense > 0:
        issues.append("收入和支出同时有金额")
    if income == 0 and expense == 0:
        issues.append("收入和支出均为零")
    if balance is None:
        issues.append("余额无法解析")

    raw_text_parts = []
    for index in (7, 8, 9, 10, 11):
        if index < len(row):
            value = _clean_cell(row[index])
            if value:
                raw_text_parts.append(value)

    tx = Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_clean_cell(row[1]),
        raw_amount=f"{expense_raw}|{income_raw}",
        raw_balance=balance_raw,
        raw_text=" | ".join(raw_text_parts),
        raw_fields=[_clean_cell(cell) for cell in row],
        raw_headers=CORP_HEADERS,
        source_fields={
            field_name: _clean_cell(row[index])
            for field_name, index in (("posting_date", 2), ("transaction_reference", 12), ("global_routing_number", 13))
            if index < len(row) and _clean_cell(row[index])
        },
        field_sources={
            field_name: f"raw_headers[{index}]:{CORP_HEADERS[index]}"
            for field_name, index in (("posting_date", 2), ("transaction_reference", 12), ("global_routing_number", 13))
            if index < len(row) and _clean_cell(row[index])
        },
        field_confidence={
            field_name: 1.0
            for field_name, index in (("posting_date", 2), ("transaction_reference", 12), ("global_routing_number", 13))
            if index < len(row) and _clean_cell(row[index])
        },
        status="ok" if not issues else "review",
        issues=issues,
    )
    tx.merge_key = "|".join([_clean_cell(row[0]), tx.raw_time, expense_raw, income_raw, balance_raw, str(page_no), str(row_no)])
    return tx


def extract_psbc(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                table_has_corp_header = any(_is_corp_header(row) for row in table)
                for row_index, row in enumerate(table, start=1):
                    if table_has_corp_header or _is_corp_row(row):
                        tx = _parse_corp_row(row, page_index, row_index)
                        if tx is not None:
                            transactions.append(tx)
                        continue

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
