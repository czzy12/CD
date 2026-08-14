import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "兴业银行个人"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
DATE_DIGITS_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
SIGNED_NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
MONEY_RE = re.compile(r"^[+-]?\d[\d,]*\.\d{2}$")
TIME_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})")


def _cell(value: object) -> str:
    return str(value or "").replace("\n", "|").strip()


def _parse_date(*values: object) -> datetime | None:
    for value in values:
        text = _cell(value)
        match = DATE_RE.search(text)
        if match:
            try:
                return datetime.strptime(match.group(0), "%Y-%m-%d")
            except ValueError:
                pass

        digits = "".join(char for char in text if char.isdigit())
        for start in range(0, max(len(digits) - 7, 0)):
            match = DATE_DIGITS_RE.match(digits[start : start + 8])
            if not match:
                continue
            try:
                return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
    return None


def _parse_amount(value: object) -> Decimal | None:
    text = _cell(value).replace(",", "")
    match = SIGNED_NUMBER_RE.search(text)
    if not match:
        return None
    raw = match.group(0)
    if "-" in text and not raw.startswith("-"):
        raw = f"-{raw}"
    elif "+" in text and not raw.startswith("+"):
        raw = f"+{raw}"
    try:
        return Decimal(raw).quantize(CENT)
    except InvalidOperation:
        return None


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw).quantize(CENT)
    except InvalidOperation:
        return None


def _balance_candidates(value: object) -> list[Decimal]:
    text = _cell(value).replace(",", "")
    candidates: list[Decimal] = []

    spaced = "".join(char if (char.isdigit() or char == ".") else " " for char in text)
    for match in re.finditer(r"\d+(?:\.\d{1,2})", spaced):
        value = _to_decimal(match.group(0))
        if value is not None:
            candidates.append(value)

    compact = "".join(char for char in text if char.isdigit() or char == ".")
    if "." in compact:
        dot_index = compact.rfind(".")
        integer_part = "".join(char for char in compact[:dot_index] if char.isdigit())
        fraction_part = "".join(char for char in compact[dot_index + 1 :] if char.isdigit())[:2]
        if fraction_part:
            for start in range(len(integer_part)):
                value = _to_decimal(f"{integer_part[start:]}.{fraction_part}")
                if value is not None:
                    candidates.append(value)

    unique: list[Decimal] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _choose_balance(candidates: list[Decimal], expected: Decimal | None) -> Decimal | None:
    if not candidates:
        return None
    if expected is not None:
        for candidate in candidates:
            if candidate == expected:
                return candidate
    return candidates[0]


def _has_split_amount_columns(page) -> bool:
    for table in page.extract_tables():
        if not table or len(table[0]) != 8:
            continue
        header = "".join(_cell(cell) for cell in table[0])
        if "支出" in header and "收入" in header and "账户余额" in header and "交易金额" not in header:
            return True
    return False


def _date_for_time(words: list[dict], time_word: dict) -> datetime | None:
    time_top = float(time_word["top"])
    parts = [
        word["text"]
        for word in sorted(words, key=lambda word: float(word["x0"]))
        if 45 <= float(word["x0"]) < 140
        and time_top - 16 <= float(word["top"]) <= time_top - 4
        and ("20" in word["text"] or "-" in word["text"])
    ]
    return _parse_date("".join(parts))


def _column_amount(words: list[dict], left: float, right: float) -> Decimal | None:
    for word in sorted(words, key=lambda word: (float(word["top"]), float(word["x0"]))):
        if left <= float(word["x0"]) < right and MONEY_RE.fullmatch(word["text"]):
            return _parse_amount(word["text"])
    return None


def _extract_split_amount_columns(pdf) -> list[Transaction]:
    """Extract the 8-column electronic receipt with separate expense and income columns."""
    rows: list[Transaction] = []
    for page_no, page in enumerate(pdf.pages, start=1):
        words = page.extract_words(x_tolerance=1, y_tolerance=2)
        time_words = [
            word
            for word in words
            if 45 <= float(word["x0"]) < 140 and TIME_RE.match(word["text"])
        ]
        time_words.sort(key=lambda word: float(word["top"]))

        for index, time_word in enumerate(time_words):
            tx_time = _date_for_time(words, time_word)
            if tx_time is None:
                continue
            time_text = TIME_RE.match(time_word["text"]).group(1)
            time_top = float(time_word["top"])
            row_bottom = (
                float(time_words[index + 1]["top"]) - 20
                if index + 1 < len(time_words)
                else page.height
            )
            row_words = [
                word
                for word in words
                if time_top - 24 <= float(word["top"]) < row_bottom
            ]
            # The electronic watermark can be merged into a number as a stray
            # minus sign.  Direction comes from the dedicated column, so keep
            # the column value unsigned.
            expense = abs(_column_amount(row_words, 200, 270) or ZERO)
            income = abs(_column_amount(row_words, 270, 350) or ZERO)
            balance = _column_amount(row_words, 350, 415)
            if balance is None or (income == ZERO and expense == ZERO):
                continue

            row_no = len(rows) + 1
            transaction_time = tx_time.replace(
                hour=int(time_text[:2]),
                minute=int(time_text[3:5]),
                second=int(time_text[6:]),
                # Multiple transactions can share the same printed second.
                # PDF order is newest to oldest, so preserve the balance order
                # with a reverse sequence number for the sort layer.
                microsecond=999_999 - row_no,
            )
            fields = [
                tx_time.strftime("%Y-%m-%d"),
                time_text,
                str(expense),
                str(income),
                str(balance),
            ]
            tx = Transaction(
                transaction_time=transaction_time,
                income=income,
                expense=expense,
                balance=balance,
                bank=BANK_NAME,
                page_no=page_no,
                row_no=row_no,
                raw_time=f"{tx_time:%Y-%m-%d} {time_text}",
                raw_amount=f"收入 {income} / 支出 {expense}",
                raw_balance=str(balance),
                raw_text=" | ".join(fields),
                raw_fields=fields,
                raw_headers=["交易日期", "交易时间", "支出", "收入", "账户余额"],
            )
            tx.merge_key = "|".join([str(page_no), str(row_no), tx.raw_time, tx.raw_amount, tx.raw_balance])
            rows.append(tx)

    # Pages are ordered from newest to oldest.  The electronic watermark can
    # insert digits into the printed amount, while the balance column remains
    # intact; use the adjacent balances as the authoritative transaction value.
    for newer, older in zip(rows, rows[1:]):
        delta = (newer.balance - older.balance).quantize(CENT)
        newer.income = delta if delta > ZERO else ZERO
        newer.expense = -delta if delta < ZERO else ZERO
        newer.raw_amount = f"收入 {newer.income} / 支出 {newer.expense}"
        newer.merge_key = "|".join(
            [str(newer.page_no), str(newer.row_no), newer.raw_time, newer.raw_amount, newer.raw_balance]
        )
    return rows


def extract_cib(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        if _has_split_amount_columns(pdf.pages[0]):
            return _extract_split_amount_columns(pdf)

        sample_text = "\n".join((page.extract_text() or "") for page in pdf.pages[:2])
        strong_watermark = "兴业银行交易明细" in sample_text and "核验" in sample_text
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table[1:]:
                    if len(row) < 6:
                        continue
                    tx_time = _parse_date(row[1], row[0])
                    amount = _parse_amount(row[4])
                    balance_candidates = _balance_candidates(row[5])
                    if tx_time is None or amount is None or not balance_candidates:
                        continue

                    expected = None
                    if previous_balance is not None:
                        expected = (previous_balance + amount).quantize(CENT)
                    balance = _choose_balance(balance_candidates, expected)
                    if balance is None:
                        continue
                    previous_balance = balance

                    row_no = len(rows) + 1
                    fields = [_cell(cell) for cell in row]
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=amount if amount >= ZERO else ZERO,
                        expense=-amount if amount < ZERO else ZERO,
                        balance=None if strong_watermark else balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=row_no,
                        raw_time=tx_time.strftime("%Y-%m-%d"),
                        raw_amount=_cell(row[4]),
                        raw_balance=_cell(row[5]),
                        raw_text=" ".join(field for field in fields if field),
                        raw_fields=fields,
                    )
                    if strong_watermark:
                        tx.balance_optional = True
                        tx.raw_balance = f"参考余额:{tx.raw_balance}"
                    tx.merge_key = "|".join([str(row_no), tx.raw_time, tx.raw_amount, tx.raw_balance])
                    rows.append(tx)

    return rows
