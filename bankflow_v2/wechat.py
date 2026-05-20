import re
from datetime import datetime
from decimal import Decimal
from typing import Any

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "微信流水"
TIME_RE = re.compile(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{1,2}(?::\d{1,2})?")
AMOUNT_RE = re.compile(r"[￥¥]?\s*[+-]?\d[\d,]*\.\d{2}")


def _clean(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def _norm(value: Any) -> str:
    return _clean(value).replace(" ", "").replace("　", "")


def _parse_time(value: Any) -> datetime | None:
    text = _clean(value).replace("/", "-")
    match = TIME_RE.search(text)
    if not match:
        return None
    raw = match.group(0)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return None


def _parse_amount(value: Any) -> Decimal | None:
    text = _clean(value).replace("￥", "").replace("¥", "").replace(" ", "")
    match = AMOUNT_RE.search(text)
    if not match:
        return None
    return money_to_decimal(match.group(0).replace("￥", "").replace("¥", "").replace(" ", ""))


def _direction(value: Any) -> str | None:
    text = _norm(value)
    if "其他" in text:
        return "neutral"
    if any(word in text for word in ("收入", "收款", "转入", "退款", "+")):
        return "income"
    if any(word in text for word in ("支出", "付款", "转出", "提现", "-")):
        return "expense"
    return None


def _find_col(headers: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        for index, header in enumerate(headers):
            if header == name:
                return index
    for name in names:
        for index, header in enumerate(headers):
            if name in header:
                return index
    return None


def _parse_table(table: list[list[Any]], page_no: int) -> list[Transaction]:
    transactions: list[Transaction] = []
    header_index = None
    cols: dict[str, int | None] = {}

    for row_index, row in enumerate(table[:20]):
        headers = [_norm(cell) for cell in row]
        time_col = _find_col(headers, ("交易时间", "时间"))
        amount_col = _find_col(headers, ("金额(元)", "金额", "交易金额"))
        direction_col = _find_col(headers, ("收/支", "收支", "收入/支出", "交易方向"))
        if time_col is not None and amount_col is not None:
            header_index = row_index
            cols = {"time": time_col, "amount": amount_col, "direction": direction_col}
            break

    if header_index is None:
        cols = {"time": 1, "amount": 5, "direction": 3}
        header_index = -1

    for row_no, row in enumerate(table[header_index + 1 :], start=header_index + 2):
        tx_time = _parse_time(row[cols["time"]]) if cols["time"] is not None and cols["time"] < len(row) else None
        if tx_time is None:
            continue

        raw_amount = _clean(row[cols["amount"]]) if cols["amount"] is not None and cols["amount"] < len(row) else ""
        amount = _parse_amount(raw_amount)
        row_text = " ".join(_clean(cell) for cell in row)
        raw_direction = _clean(row[cols["direction"]]) if cols["direction"] is not None and cols["direction"] < len(row) else row_text
        direction = _direction(f"{raw_direction} {row_text}")
        issues: list[str] = []

        if amount is None:
            amount = Decimal("0.00")
            issues.append("金额无法解析")
        if direction == "income":
            income = amount
            expense = Decimal("0.00")
        elif direction == "expense":
            income = Decimal("0.00")
            expense = amount
        elif direction == "neutral":
            income = Decimal("0.00")
            expense = Decimal("0.00")
        else:
            income = Decimal("0.00")
            expense = Decimal("0.00")
            issues.append("收支方向无法解析")

        tx = Transaction(
            transaction_time=tx_time,
            income=income,
            expense=expense,
            balance=None,
            bank=BANK_NAME,
            page_no=page_no,
            row_no=row_no,
            raw_time=_clean(row[cols["time"]]),
            raw_amount=raw_amount,
            raw_balance="",
            raw_text=row_text,
            raw_fields=[_clean(cell) for cell in row],
            status="ok" if not issues else "review",
            issues=issues,
        )
        tx.balance_optional = True
        tx.neutral = direction == "neutral"
        transactions.append(tx)

    return transactions


def _parse_text_line(line: str, page_no: int, row_no: int) -> Transaction | None:
    tx_time = _parse_time(line)
    if tx_time is None:
        return None

    amount = _parse_amount(line)
    direction = _direction(line)
    if amount is None or direction is None:
        return None

    if direction == "income":
        income = amount
        expense = Decimal("0.00")
    elif direction == "expense":
        income = Decimal("0.00")
        expense = amount
    else:
        income = Decimal("0.00")
        expense = Decimal("0.00")

    tx = Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=None,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=tx_time.strftime("%Y-%m-%d %H:%M:%S"),
        raw_amount=_clean(line),
        raw_balance="",
        raw_text=_clean(line),
    )
    tx.balance_optional = True
    tx.neutral = direction == "neutral"
    return tx


def extract_wechat(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            before = len(transactions)
            for table in page.extract_tables():
                transactions.extend(_parse_table(table, page_no))

            if len(transactions) > before:
                continue

            for row_no, line in enumerate((page.extract_text() or "").splitlines(), start=1):
                tx = _parse_text_line(line, page_no, row_no)
                if tx is not None:
                    transactions.append(tx)

    return transactions
