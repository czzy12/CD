import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "兴业银行"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
DATE_DIGITS_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
SIGNED_NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")


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


def extract_cib(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
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
