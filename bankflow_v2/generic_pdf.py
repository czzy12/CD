import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction


BANK_NAME = "通用PDF识别"
CENT = Decimal("0.01")
DATE_ONLY_RE = re.compile(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}")
MONEY_RE = re.compile(r"\d[\d,]*\.\d{2}")
ROW_RE = re.compile(
    r"^(?:卡\s+\S+\s+)?"
    r"(?P<date>20\d{2}[/-]\d{1,2}[/-]\d{1,2})\s+"
    r"(?P<time>\d{1,2}:\d{2}:\d{2})\s+"
    r"(?P<summary>.*?)\s+"
    r"(?P<amount>[+-]?\d[\d,]*\.\d{2})\s+"
    r"(?P<balance>\d[\d,]*\.\d{2})\b"
)
DETAIL_QUERY_COLUMNS = {
    "date": (0, 70),
    "expense": (70, 135),
    "income": (135, 205),
    "balance": (205, 285),
    "summary": (285, 368),
    "account": (368, 464),
    "counterparty": (464, 595),
}
THREE_MONEY_ROW_RE = re.compile(
    r"^(?:鍗s+\S+\s+)?"
    r"(?P<date>20\d{2}[/-]\d{1,2}[/-]\d{1,2})\s+"
    r"(?P<time>\d{1,2}:\d{2}:\d{2})\s+"
    r"(?P<income>\d[\d,]*(?:\.\d{1,2})?)\s+"
    r"(?P<expense>\d[\d,]*(?:\.\d{1,2})?)\s+"
    r"(?P<balance>\d[\d,]*(?:\.\d{1,2})?)\b"
)


def _money(raw: str) -> Decimal:
    return Decimal(raw.replace(",", "")).quantize(CENT)


def _time(raw_date: str, raw_time: str) -> datetime | None:
    text = f"{raw_date.replace('/', '-')} {raw_time}"
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _date_only(raw_date: str) -> datetime | None:
    try:
        return datetime.strptime(raw_date.replace("/", "-"), "%Y-%m-%d")
    except ValueError:
        return None


def _is_body_word(word: dict) -> bool:
    size = float(word.get("size") or 0)
    return 7.5 <= size <= 10.5 and 0 <= float(word.get("x0") or 0) <= 595


def _column_text(words: list[dict], left: float, right: float) -> str:
    column_words = [
        word for word in words
        if left <= float(word.get("x0") or 0) < right and _is_body_word(word)
    ]
    column_words.sort(key=lambda word: (round(float(word["top"]), 1), float(word["x0"])))
    return "".join(str(word["text"]) for word in column_words).strip()


def _first_money(text: str) -> Decimal | None:
    match = MONEY_RE.search(text)
    return _money(match.group(0)) if match else None


def _has_detail_query_title(pdf) -> bool:
    for page in pdf.pages[:2]:
        if "明细账查询" in (page.extract_text() or ""):
            return True
    return False


def _extract_detail_query_page(page, page_index: int) -> list[Transaction]:
    words = page.extract_words(x_tolerance=2, y_tolerance=3, extra_attrs=["size"])
    date_words = [
        word for word in words
        if (
            _is_body_word(word)
            and 80 <= float(word["top"]) <= page.height - 40
            and 0 <= float(word["x0"]) <= 70
            and DATE_ONLY_RE.fullmatch(str(word["text"]))
        )
    ]
    date_words.sort(key=lambda word: float(word["top"]))

    transactions: list[Transaction] = []
    for row_index, date_word in enumerate(date_words, start=1):
        row_top = float(date_word["top"]) - 2
        if row_index < len(date_words):
            row_bottom = float(date_words[row_index]["top"]) - 2
        else:
            row_bottom = page.height - 40
        row_words = [
            word for word in words
            if row_top <= float(word["top"]) < row_bottom and _is_body_word(word)
        ]

        values = {
            name: _column_text(row_words, *bounds)
            for name, bounds in DETAIL_QUERY_COLUMNS.items()
        }
        tx_time = _date_only(values["date"])
        expense = _first_money(values["expense"]) or Decimal("0.00")
        income = _first_money(values["income"]) or Decimal("0.00")
        balance = _first_money(values["balance"])
        if tx_time is None or balance is None:
            continue

        raw_fields = [
            values["date"],
            values["expense"],
            values["income"],
            values["balance"],
            values["summary"],
            values["account"],
            values["counterparty"],
        ]
        tx = Transaction(
            transaction_time=tx_time,
            income=income,
            expense=expense,
            balance=balance,
            bank=BANK_NAME,
            page_no=page_index,
            row_no=row_index,
            raw_time=values["date"],
            raw_amount=f"{values['income']} / {values['expense']}",
            raw_balance=values["balance"],
            raw_text=" | ".join(raw_fields),
            raw_fields=raw_fields,
            raw_headers=["交易日期", "支出金额", "收入金额", "账户余额", "交易名称", "对方账号", "对方户名"],
        )
        transactions.append(tx)
    return transactions


def _extract_detail_query(pdf) -> list[Transaction]:
    if not _has_detail_query_title(pdf):
        return []

    transactions: list[Transaction] = []
    for page_index, page in enumerate(pdf.pages, start=1):
        transactions.extend(_extract_detail_query_page(page, page_index))
    return transactions


def extract_generic_pdf(pdf_path: str, bank_name: str = BANK_NAME) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                three_money_match = THREE_MONEY_ROW_RE.match(line)
                if three_money_match:
                    tx_time = _time(three_money_match.group("date"), three_money_match.group("time"))
                    if tx_time is None:
                        continue

                    income = _money(three_money_match.group("income"))
                    expense = _money(three_money_match.group("expense"))
                    balance = _money(three_money_match.group("balance"))
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=bank_name,
                        page_no=page_index,
                        row_no=line_no,
                        raw_time=f"{three_money_match.group('date')} {three_money_match.group('time')}",
                        raw_amount=f"{three_money_match.group('income')} / {three_money_match.group('expense')}",
                        raw_balance=three_money_match.group("balance"),
                        raw_text=line,
                        raw_fields=[line],
                    )
                    tx.balance_tolerance = Decimal("0.99")
                    transactions.append(tx)
                    continue

                match = ROW_RE.match(line)
                if not match:
                    continue

                tx_time = _time(match.group("date"), match.group("time"))
                if tx_time is None:
                    continue

                amount = _money(match.group("amount"))
                balance = _money(match.group("balance"))
                tx = Transaction(
                    transaction_time=tx_time,
                    income=amount if amount > 0 else Decimal("0.00"),
                    expense=-amount if amount < 0 else Decimal("0.00"),
                    balance=balance,
                    bank=bank_name,
                    page_no=page_index,
                    row_no=line_no,
                    raw_time=f"{match.group('date')} {match.group('time')}",
                    raw_amount=match.group("amount"),
                    raw_balance=match.group("balance"),
                    raw_text=line,
                    raw_fields=[line],
                )
                tx.balance_tolerance = Decimal("0.99")
                transactions.append(tx)
        if not transactions:
            transactions = _extract_detail_query(pdf)
    return transactions
