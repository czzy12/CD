import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .icbc_corp import _restore_same_time_order
from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "德州银行对公"
HEADERS = ["交易时间", "交易渠道", "收入", "支出", "账户余额", "币种", "对方账号", "对方户名", "摘要备注"]
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
MONEY_RE = re.compile(r"^-?\d[\d,]*\.\d{2}$")
ZERO = Decimal("0.00")


def _cell(row: list, index: int) -> str:
    return str(row[index] or "").replace("\n", " ").strip() if index < len(row) else ""


def _restore_amounts_from_balance(rows: list[Transaction]) -> None:
    ordered = sorted(rows, key=lambda tx: (tx.transaction_time, tx.page_no, tx.row_no))
    previous: Transaction | None = None
    for tx in ordered:
        if previous is not None:
            delta = (tx.balance - previous.balance).quantize(Decimal("0.01"))
            if tx.expense < ZERO:
                tx.income = ZERO
                tx.expense = -delta
            elif tx.income < ZERO:
                tx.income = delta
                tx.expense = ZERO
            else:
                tx.income = delta if delta > 0 else ZERO
                tx.expense = -delta if delta < 0 else ZERO
        previous = tx


def extract_dezhou_corp(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=1, y_tolerance=2)
            time_words = [
                word for word in words
                if 45 <= float(word["x0"]) < 90 and TIME_RE.fullmatch(word["text"] or "")
            ]
            for time_word in time_words:
                top = float(time_word["top"])
                date_word = next(
                    (
                        word for word in words
                        if 45 <= float(word["x0"]) < 100
                        and top - 12 <= float(word["top"]) < top
                        and DATE_RE.fullmatch(word["text"] or "")
                    ),
                    None,
                )
                money_words = [
                    word for word in words
                    if top - 1 <= float(word["top"]) <= top + 1
                    and MONEY_RE.fullmatch(word["text"] or "")
                ]
                if date_word is None:
                    continue
                income_word = next((word for word in money_words if 170 <= float(word["x1"]) <= 174), None)
                expense_word = next((word for word in money_words if 215 <= float(word["x1"]) <= 219), None)
                balance_word = next((word for word in money_words if 283 <= float(word["x1"]) <= 287), None)
                if balance_word is None:
                    continue
                raw_time = f"{date_word['text']} {time_word['text']}"
                income_text = income_word["text"] if income_word else ""
                expense_text = expense_word["text"] if expense_word else ""
                income = money_to_decimal(income_text) or ZERO
                expense = money_to_decimal(expense_text) or ZERO
                balance = money_to_decimal(balance_word["text"])
                fields = [date_word["text"], time_word["text"], income_text, expense_text, balance_word["text"]]
                tx = Transaction(
                    transaction_time=datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S"),
                    income=income,
                    expense=expense,
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=len(rows) + 1,
                    raw_time=raw_time,
                    raw_amount=f"{income_text}|{expense_text}",
                    raw_balance=balance_word["text"],
                    raw_text=" | ".join(fields),
                    raw_fields=fields,
                    raw_headers=HEADERS[:5],
                )
                tx.preserve_signed_columns = True
                rows.append(tx)
    rows = _restore_same_time_order(rows)
    _restore_amounts_from_balance(rows)
    return rows
