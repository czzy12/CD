import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "徽商银行个人"
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
MONEY_RE = re.compile(r"^-?\d[\d,]*\.\d{2}$")
HEADERS = ["记账日期", "交易金额", "账户余额"]


def extract_huishang(pdf_path: str) -> list[Transaction]:
    printed_rows: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=1, y_tolerance=2, keep_blank_chars=False)
            date_words = sorted(
                (word for word in words if float(word["x0"]) < 70 and DATE_RE.fullmatch(word["text"] or "")),
                key=lambda word: float(word["top"]),
            )
            for index, date_word in enumerate(date_words):
                top = float(date_word["top"])
                bottom = float(date_words[index + 1]["top"]) if index + 1 < len(date_words) else top + 45
                row_words = [word for word in words if top - 1 <= float(word["top"]) < bottom]
                amount_word = next(
                    (word for word in row_words if 125 <= float(word["x0"]) < 190 and MONEY_RE.fullmatch(word["text"] or "")),
                    None,
                )
                balance_word = next(
                    (word for word in row_words if 190 <= float(word["x0"]) < 260 and MONEY_RE.fullmatch(word["text"] or "")),
                    None,
                )
                if amount_word is None or balance_word is None:
                    continue
                amount = money_to_decimal(amount_word["text"])
                balance = money_to_decimal(balance_word["text"])
                if amount is None or balance is None:
                    continue
                fields = [date_word["text"], amount_word["text"], balance_word["text"]]
                printed_rows.append(Transaction(
                    transaction_time=datetime.strptime(date_word["text"], "%Y-%m-%d"),
                    income=amount if amount > 0 else Decimal("0.00"),
                    expense=-amount if amount < 0 else Decimal("0.00"),
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=len(printed_rows) + 1,
                    raw_time=date_word["text"],
                    raw_amount=amount_word["text"],
                    raw_balance=balance_word["text"],
                    raw_text=" | ".join(fields),
                    raw_fields=fields,
                    raw_headers=HEADERS,
                ))

    rows = list(reversed(printed_rows))
    for row_no, tx in enumerate(rows, start=1):
        tx.page_no = 1
        tx.row_no = row_no
    return rows
