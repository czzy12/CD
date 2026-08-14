from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "徽商银行对公"
RAW_HEADERS = [
    "交易时间",
    "收入金额",
    "支出金额",
    "账户余额",
    "对方账号",
    "对方户名",
    "对方开户行",
    "用途",
    "流水号",
    "附言",
    "摘要",
]

DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
MONEY_RE = re.compile(r"^-?\d[\d,]*\.\d{2}$")
ZERO = Decimal("0.00")


def _words(page) -> list[dict]:
    return page.extract_words(x_tolerance=1, y_tolerance=3, keep_blank_chars=False)


def _is_date_word(word: dict) -> bool:
    return 10 <= word["x0"] <= 65 and DATE_RE.match(word["text"] or "") is not None


def _is_time_word(word: dict) -> bool:
    return 15 <= word["x0"] <= 60 and TIME_RE.match(word["text"] or "") is not None


def _is_money_word(word: dict) -> bool:
    return MONEY_RE.match(word["text"] or "") is not None


def _money(text: str) -> Decimal:
    return money_to_decimal(text) or ZERO


def _block_text(words: list[dict]) -> str:
    return " | ".join(word["text"] for word in sorted(words, key=lambda item: (item["top"], item["x0"])))


def _balance_chain_score(transactions: list[Transaction]) -> int:
    score = 0
    for previous, current in zip(transactions, transactions[1:]):
        expected = (previous.balance + current.income - current.expense).quantize(Decimal("0.01"))
        if expected == current.balance.quantize(Decimal("0.01")):
            score += 1
    return score


def _restore_same_time_order(transactions: list[Transaction]) -> list[Transaction]:
    grouped: dict[datetime, list[Transaction]] = {}
    for tx in transactions:
        grouped.setdefault(tx.transaction_time, []).append(tx)

    for tx_time, items in grouped.items():
        if len(items) < 2:
            continue

        forward = sorted(items, key=lambda tx: (tx.page_no, tx.row_no))
        reverse = list(reversed(forward))
        ordered = reverse if _balance_chain_score(reverse) > _balance_chain_score(forward) else forward
        for index, tx in enumerate(ordered):
            tx.transaction_time = tx_time.replace(microsecond=index)

    return transactions


def _parse_block(date_word: dict, block_words: list[dict], page_no: int, row_no: int) -> Transaction | None:
    time_word = next((word for word in block_words if _is_time_word(word)), None)
    if time_word is None:
        return None

    income = ZERO
    expense = ZERO
    balance: Decimal | None = None
    raw_income = ""
    raw_expense = ""
    raw_balance = ""

    for word in block_words:
        if not _is_money_word(word):
            continue
        x0 = word["x0"]
        if 55 <= x0 < 98:
            income = _money(word["text"])
            raw_income = word["text"]
        elif 98 <= x0 < 140:
            expense = _money(word["text"])
            raw_expense = word["text"]
        elif 140 <= x0 < 190:
            balance = _money(word["text"])
            raw_balance = word["text"]

    if balance is None:
        return None

    raw_time = f"{date_word['text']} {time_word['text']}"
    return Transaction(
        transaction_time=datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S"),
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=raw_time,
        raw_amount=raw_income or raw_expense,
        raw_balance=raw_balance,
        raw_text=_block_text(block_words),
        raw_fields=[word["text"] for word in sorted(block_words, key=lambda item: (item["top"], item["x0"]))],
        raw_headers=RAW_HEADERS,
    )


def extract_huishang_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = _words(page)
            date_words = sorted((word for word in words if _is_date_word(word)), key=lambda item: item["top"])
            for index, date_word in enumerate(date_words):
                previous_top = date_words[index - 1]["top"] if index > 0 else 45
                next_top = date_words[index + 1]["top"] if index + 1 < len(date_words) else 800
                block_top = (previous_top + date_word["top"]) / 2
                block_bottom = (date_word["top"] + next_top) / 2
                block_words = [word for word in words if block_top <= word["top"] < block_bottom]
                tx = _parse_block(date_word, block_words, page_no, len(transactions) + 1)
                if tx is not None:
                    transactions.append(tx)
    return _restore_same_time_order(transactions)
