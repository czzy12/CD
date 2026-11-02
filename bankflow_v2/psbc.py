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
    date_text = re.sub(r"\s+", "", str(raw_date or ""))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
        return None

    time_text = _clean_cell(raw_time)
    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", time_text):
        return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S")
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
    if len(row) <= CORP_BALANCE_COL:
        return False
    return _clean_cell(row[0]).isdigit() or bool(re.fullmatch(r"20\d{2}-\d{2}-\d{2}", re.sub(r"\s+", "", str(row[0] or ""))))


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
        raw_headers=(["交易日期", *CORP_HEADERS[1:12], "全局路由号"] if len(row) == 13 else CORP_HEADERS),
        status="ok" if not issues else "review",
        issues=issues,
    )
    tx.merge_key = "|".join([_clean_cell(row[0]), tx.raw_time, expense_raw, income_raw, balance_raw, str(page_no), str(row_no)])
    tx.preserve_signed_columns = True
    return tx


def _restore_same_time_order(transactions: list[Transaction]) -> None:
    """Restore newest-first ties only when the original balances prove the order."""
    groups: dict[datetime, list[Transaction]] = {}
    for tx in transactions:
        groups.setdefault(tx.transaction_time, []).append(tx)

    def follows(older: Transaction, newer: Transaction) -> bool:
        return (
            older.balance is not None
            and newer.balance is not None
            and older.balance + newer.amount == newer.balance
        )

    for items in groups.values():
        if len(items) < 2:
            continue
        if all(follows(a, b) for a, b in zip(items, items[1:])):
            continue
        if all(follows(b, a) for a, b in zip(items, items[1:])):
            for index, tx in enumerate(items):
                # Internal tie-break only; raw_time retains the PDF's timestamp.
                tx.transaction_time = tx.transaction_time.replace(microsecond=len(items) - index - 1)


def extract_psbc(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    header_text = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            if page_index == 1:
                header_text = page.extract_text() or ""
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

    _restore_same_time_order(transactions)
    if any(getattr(tx, "preserve_signed_columns", False) for tx in transactions):
        from .regional_statements import _check_totals
        _check_totals(transactions, header_text, {
            "income": r"收入总金额([\d,.]+)", "expense": r"支出总金额([\d,.]+)",
            "income_count": r"收入总笔数(\d+)笔", "expense_count": r"支出总笔数(\d+)笔",
        })
    return transactions
