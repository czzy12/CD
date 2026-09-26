import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction


BANK_NAME = "朝阳银行对公"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
ROW_RE = re.compile(
    r"^(?P<date>20\d{2}-\d{2}-\d{2})\s+"
    r"(?P<time>\d{2}:\d{2}:\d{2})\s+"
    r"(?P<direction>收入|支出)\s+"
    r"(?P<amount>[+-]?[\d,]+\.\d{2})\s+"
    r"(?P<balance>[\d,]+\.\d{2})(?:\s+(?P<detail>.*))?$"
)


def _money(value: str) -> Decimal:
    return Decimal(value.replace(",", "").replace("+", "")).copy_abs().quantize(CENT)


def extract_chaoyang_rows(text: str, page_no: int = 1) -> list[Transaction]:
    transactions: list[Transaction] = []
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        match = ROW_RE.match(line)
        if not match:
            continue
        tx_time = datetime.strptime(
            f"{match.group('date')} {match.group('time')}",
            "%Y-%m-%d %H:%M:%S",
        )
        amount = _money(match.group("amount"))
        balance = _money(match.group("balance"))
        income = amount if match.group("direction") == "收入" else ZERO
        expense = amount if match.group("direction") == "支出" else ZERO
        tx = Transaction(
            transaction_time=tx_time,
            income=income,
            expense=expense,
            balance=balance,
            bank=BANK_NAME,
            page_no=page_no,
            # The statement is printed newest-first. A negative source row keeps
            # equal-second principal/fee pairs in their true balance-chain order.
            row_no=-line_no,
            raw_time=f"{match.group('date')} {match.group('time')}",
            raw_amount=match.group("amount"),
            raw_balance=match.group("balance"),
            raw_text=line,
            raw_fields=[
                match.group("date"),
                match.group("time"),
                match.group("direction"),
                match.group("amount"),
                match.group("balance"),
                match.group("detail") or "",
            ],
            raw_headers=["交易日期", "交易时间", "收入/支出", "交易金额", "账户余额", "交易详情"],
        )
        tx.preserve_signed_columns = True
        tx.merge_key = "|".join([
            tx.raw_time,
            str(tx.income),
            str(tx.expense),
            str(tx.balance),
        ])
        transactions.append(tx)
    return transactions


def extract_chaoyang_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            transactions.extend(extract_chaoyang_rows(page.extract_text() or "", page_no))
    return transactions
