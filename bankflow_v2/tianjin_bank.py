import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "天津银行个人"
ZERO = Decimal("0.00")
CENT = Decimal("0.01")
RAW_HEADERS = ["序号", "交易日期", "交易金额", "余额", "交易摘要", "附言"]
COLUMNS = {
    "seq": (40, 80),
    "date": (90, 170),
    "amount": (180, 260),
    "balance": (280, 340),
    "summary": (360, 450),
    "postscript": (450, 570),
}


def _compact(text: object) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _column_text(chars: list[dict], column: str, top: float, bottom: float, allowed: str | None = None) -> str:
    x0, x1 = COLUMNS[column]
    column_chars = [
        char
        for char in chars
        if x0 <= float(char["x0"]) <= x1 and top <= float(char["top"]) < bottom
    ]
    text = "".join(
        char["text"]
        for char in sorted(column_chars, key=lambda item: (float(item["top"]), float(item["x0"])))
    )
    if allowed is not None:
        text = "".join(char for char in text if char in allowed)
    return " ".join(text.split())


def _parse_decimal(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "")).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _parse_date(text: str, sequence: int) -> datetime | None:
    digits = "".join(char for char in text if char.isdigit())
    if len(digits) != 8:
        return None
    try:
        parsed = datetime.strptime(digits, "%Y%m%d")
    except ValueError:
        return None
    return parsed.replace(microsecond=sequence)


def _sequence_tops(words: list[dict]) -> list[tuple[int, float]]:
    rows: list[tuple[int, float]] = []
    for word in words:
        text = word.get("text", "")
        if (
            re.fullmatch(r"\d+", text)
            and COLUMNS["seq"][0] <= float(word["x0"]) <= COLUMNS["seq"][1]
            and float(word["top"]) > 115
        ):
            rows.append((int(text), float(word["top"])))
    return sorted(rows, key=lambda item: item[0])


def _is_target_statement(first_page_text: str) -> bool:
    compact = _compact(first_page_text)
    return (
        "天津银行个人账户交易明细清单" in compact
        and "户名" in compact
        and "账号" in compact
        and "序号交易日期交易金额余额交易摘要附言" in compact
    )


def _account_name(first_page_text: str) -> str:
    match = re.search(r"户名[:：]\s*([^\s]+)", first_page_text)
    return match.group(1) if match else ""


def _clean_note(text: str, account_name: str) -> str:
    if account_name:
        text = text.replace(account_name, "")
    return " ".join(text.split())


def extract_tianjin_bank(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        first_page_text = pdf.pages[0].extract_text() if pdf.pages else ""
        if not pdf.pages or not _is_target_statement(first_page_text or ""):
            return transactions
        account_name = _account_name(first_page_text or "")

        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words()
            sequence_tops = _sequence_tops(words)
            chars = page.chars

            for index, (sequence, top) in enumerate(sequence_tops):
                next_top = sequence_tops[index + 1][1] if index + 1 < len(sequence_tops) else 690
                band_top = top - 4
                band_bottom = next_top - 2
                raw_date = _column_text(chars, "date", band_top, band_bottom, allowed="0123456789")
                raw_amount = _column_text(chars, "amount", band_top, band_bottom, allowed="+-0123456789,.")
                raw_balance = _column_text(chars, "balance", band_top, band_bottom, allowed="0123456789,.")
                summary = _clean_note(_column_text(chars, "summary", band_top, band_bottom), account_name)
                postscript = _clean_note(_column_text(chars, "postscript", band_top, band_bottom), account_name)

                tx_time = _parse_date(raw_date, sequence)
                amount = _parse_decimal(raw_amount)
                balance = _parse_decimal(raw_balance)
                if tx_time is None or amount is None or balance is None:
                    continue

                raw_fields = [
                    str(sequence),
                    raw_date,
                    raw_amount,
                    raw_balance,
                    summary,
                    postscript,
                ]
                transaction = Transaction(
                    transaction_time=tx_time,
                    income=amount if amount > ZERO else ZERO,
                    expense=-amount if amount < ZERO else ZERO,
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=sequence,
                    raw_time=f"{raw_date} 00:00:00",
                    raw_amount=raw_amount,
                    raw_balance=raw_balance,
                    raw_text=" | ".join(raw_fields),
                    raw_fields=raw_fields,
                    raw_headers=RAW_HEADERS,
                )
                transaction.merge_key = "|".join([str(sequence), raw_date, raw_amount, raw_balance])
                transactions.append(transaction)

    return transactions
