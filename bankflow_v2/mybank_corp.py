import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

from .models import Transaction


BANK_NAME = "浙江网商银行对公"
CENT = Decimal("0.01")
HEADERS = [
    "序号",
    "账务流水号",
    "提交时间",
    "交易时间",
    "交易名称",
    "借方金额（收）",
    "贷方金额（支）",
    "余额",
    "对方户名",
    "对方账号",
    "对方机构",
    "备注",
]


def _money(text: Any) -> Decimal | None:
    value = str(text or "").replace(",", "").strip()
    if not re.fullmatch(r"\d+\.\d{2}", value):
        return None
    try:
        return Decimal(value).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _column_text(words: list[dict[str, Any]], x0: float, x1: float) -> str:
    selected = [word for word in words if x0 <= word["x0"] < x1]
    return " ".join(word["text"] for word in sorted(selected, key=lambda word: (word["top"], word["x0"]))).strip()


def _first_money(words: list[dict[str, Any]], x0: float, x1: float) -> Decimal:
    for word in sorted((word for word in words if x0 <= word["x0"] < x1), key=lambda word: (word["top"], word["x0"])):
        value = _money(word["text"])
        if value is not None:
            return value
    return Decimal("0.00")


def _parse_time(block: list[dict[str, Any]]) -> datetime | None:
    transaction_text = _column_text(block, 190, 245)
    submit_text = _column_text(block, 130, 185)
    date_text = transaction_text if re.search(r"20\d{2}-\d{2}-\d{2}", transaction_text) else submit_text
    date_match = re.search(r"(20\d{2}-\d{2}-\d{2})", date_text)
    time_match = re.search(r"(\d{2}:\d{2}:\d{2})", f"{transaction_text} {submit_text}")
    if not date_match or not time_match:
        return None
    try:
        return datetime.strptime(f"{date_match.group(1)} {time_match.group(1)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def extract_mybank_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
            sequence_words = sorted(
                (
                    word
                    for word in words
                    if 35 <= word["x0"] <= 50
                    and word["text"].isdigit()
                    and 0 < int(word["text"]) < 1000
                    and word["top"] > 50
                ),
                key=lambda word: word["top"],
            )

            for index, sequence_word in enumerate(sequence_words):
                sequence = int(sequence_word["text"])
                block_top = sequence_word["top"] - 18
                block_bottom = sequence_words[index + 1]["top"] - 3 if index + 1 < len(sequence_words) else 10000
                block = [word for word in words if block_top <= word["top"] < block_bottom]

                tx_time = _parse_time(block)
                balance = _first_money(block, 455, 520)
                if tx_time is None or balance == Decimal("0.00"):
                    continue

                income = _first_money(block, 300, 382)
                expense = _first_money(block, 382, 455)
                raw_fields = [
                    str(sequence),
                    _column_text(block, 70, 128),
                    _column_text(block, 130, 185),
                    _column_text(block, 190, 245),
                    _column_text(block, 250, 300),
                    f"{income:.2f}" if income else "",
                    f"{expense:.2f}" if expense else "",
                    f"{balance:.2f}",
                    _column_text(block, 515, 575),
                    _column_text(block, 575, 635),
                    _column_text(block, 635, 690),
                    _column_text(block, 690, 780),
                ]

                tx = Transaction(
                    # The PDF is printed newest-first. For multiple rows with
                    # the same second, the larger sequence number is earlier.
                    transaction_time=tx_time.replace(microsecond=max(0, 999999 - sequence)),
                    income=income,
                    expense=expense,
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=sequence,
                    raw_time=tx_time.strftime("%Y-%m-%d %H:%M:%S"),
                    raw_amount=f"借方:{raw_fields[5]} 贷方:{raw_fields[6]}",
                    raw_balance=raw_fields[7],
                    raw_text=" | ".join(raw_fields),
                    raw_fields=raw_fields,
                    raw_headers=HEADERS,
                )
                tx.preserve_signed_columns = True
                transactions.append(tx)

    return transactions
