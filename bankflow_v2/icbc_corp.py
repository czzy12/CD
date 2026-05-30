import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国工商银行对公"


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_time(raw: str | None) -> datetime | None:
    text = _clean_cell(raw)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _header_index(row: list) -> dict[str, int]:
    return {_clean_cell(cell): idx for idx, cell in enumerate(row or [])}


def _cell(row: list, index: dict[str, int], name: str) -> str:
    idx = index.get(name)
    if idx is None or idx >= len(row):
        return ""
    return _clean_cell(row[idx])


def _parse_format_a(row: list, index: dict[str, int], page_no: int, row_no: int) -> Transaction | None:
    tx_time = _parse_time(_cell(row, index, "交易时间"))
    if tx_time is None:
        return None

    amount = money_to_decimal(_cell(row, index, "发生额"))
    balance = money_to_decimal(_cell(row, index, "余额"))
    direction = _cell(row, index, "借贷标志")
    issues: list[str] = []

    if amount is None:
        issues.append("金额无法解析")
        amount = Decimal("0.00")
    if balance is None:
        issues.append("余额无法解析")

    if direction == "贷":
        income = amount
        expense = Decimal("0.00")
    elif direction == "借":
        income = Decimal("0.00")
        expense = amount
    else:
        income = Decimal("0.00")
        expense = Decimal("0.00")
        issues.append("借贷方向无法解析")

    return Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_cell(row, index, "交易时间"),
        raw_amount=_cell(row, index, "发生额"),
        raw_balance=_cell(row, index, "余额"),
        status="ok" if not issues else "review",
        issues=issues,
    )


def _parse_format_b(row: list, index: dict[str, int], page_no: int, row_no: int) -> Transaction | None:
    tx_time = _parse_time(_cell(row, index, "交易时间"))
    if tx_time is None:
        return None

    debit = money_to_decimal(_cell(row, index, "借方发生额"))
    credit = money_to_decimal(_cell(row, index, "贷方发生额"))
    balance = money_to_decimal(_cell(row, index, "余额"))
    direction = _cell(row, index, "借/贷")
    issues: list[str] = []

    if direction == "贷":
        income = credit or Decimal("0.00")
        expense = Decimal("0.00")
        raw_amount = _cell(row, index, "贷方发生额")
        if credit is None:
            issues.append("贷方金额无法解析")
    elif direction == "借":
        income = Decimal("0.00")
        expense = debit or Decimal("0.00")
        raw_amount = _cell(row, index, "借方发生额")
        if debit is None:
            issues.append("借方金额无法解析")
    else:
        income = Decimal("0.00")
        expense = Decimal("0.00")
        raw_amount = ""
        issues.append("借贷方向无法解析")

    if balance is None:
        issues.append("余额无法解析")

    return Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_cell(row, index, "交易时间"),
        raw_amount=raw_amount,
        raw_balance=_cell(row, index, "余额"),
        status="ok" if not issues else "review",
        issues=issues,
    )


def _parse_format_c(row: list, index: dict[str, int], page_no: int, row_no: int) -> Transaction | None:
    tx_time = _parse_time(_cell(row, index, "交易时间"))
    if tx_time is None:
        return None

    debit = money_to_decimal(_cell(row, index, "借方发生额"))
    credit = money_to_decimal(_cell(row, index, "贷方发生额"))
    balance = money_to_decimal(_cell(row, index, "余额"))
    issues: list[str] = []

    if debit is None:
        issues.append("借方金额无法解析")
        debit = Decimal("0.00")
    if credit is None:
        issues.append("贷方金额无法解析")
        credit = Decimal("0.00")
    if balance is None:
        issues.append("余额无法解析")

    if debit != Decimal("0.00") and credit != Decimal("0.00"):
        issues.append("借贷金额同时存在")

    income = credit
    expense = debit
    raw_amount = _cell(row, index, "贷方发生额") if credit != Decimal("0.00") else _cell(row, index, "借方发生额")

    return Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_cell(row, index, "交易时间"),
        raw_amount=raw_amount,
        raw_balance=_cell(row, index, "余额"),
        raw_text=" | ".join(_clean_cell(cell) for cell in row),
        raw_fields=[_clean_cell(cell) for cell in row],
        raw_headers=[name for name, _ in sorted(index.items(), key=lambda item: item[1])],
        status="ok" if not issues else "review",
        issues=issues,
    )


def _looks_like_header(row: list) -> bool:
    text = "|".join(_clean_cell(cell) for cell in row or [])
    return bool(re.search(r"交易时间.*余额", text)) and (
        "借贷标志" in text or "借/贷" in text or ("借方发生额" in text and "贷方发生额" in text)
    )


def extract_icbc_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                index: dict[str, int] | None = None
                parser = None

                for row_index, row in enumerate(table, start=1):
                    if not row:
                        continue
                    if _looks_like_header(row):
                        index = _header_index(row)
                        if "借/贷" in index:
                            parser = _parse_format_b
                        elif "借方发生额" in index and "贷方发生额" in index:
                            parser = _parse_format_c
                        else:
                            parser = _parse_format_a
                        continue
                    if index is None or parser is None:
                        continue

                    tx = parser(row, index, page_index, row_index)
                    if tx is not None:
                        transactions.append(tx)

    return transactions
