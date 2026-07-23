import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "中国民生银行个人"
ZERO = Decimal("0.00")
CENT = Decimal("0.01")
RAW_HEADERS = ["交易时间", "摘要", "交易金额", "账户余额", "现转标志", "交易渠道", "交易机构", "对方户名/账号", "对方行名"]
COLUMNS = {
    "date": (92, 134),
    "time": (134, 166),
    "summary": (166, 342),
    "amount": (330, 390),
    "balance": (390, 447),
    "transfer_flag": (447, 470),
    "channel": (470, 532),
    "institution": (532, 565),
    "counterparty": (565, 695),
    "counterparty_bank": (695, 900),
}


def _column_text(words: list[dict], column: str, top: float, bottom: float) -> str:
    left, right = COLUMNS[column]
    return "".join(
        str(word["text"])
        for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"])))
        if left <= float(word["x0"]) < right and top <= float(word["top"]) < bottom
    )


def _parse_time(raw_date: str, raw_time: str) -> datetime | None:
    date_match = re.search(r"\d{4}/\d{2}/\d{2}", raw_date)
    time_match = re.search(r"\d{2}:\d{2}:\d{2}", raw_time)
    if not date_match or not time_match:
        return None
    try:
        return datetime.strptime(f"{date_match.group()} {time_match.group()}", "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


def _parse_decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", "")).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _meaningful_name(value: str) -> str:
    value = value.strip()
    if re.search(r"[\u4e00-\u9fff]", value) or re.fullmatch(r"[A-Za-z][A-Za-z .'-]+", value):
        return value
    return ""


def _counterparty_name(value: str) -> str:
    return _meaningful_name(value.split("/", 1)[0])


def _row_tops(words: list[dict]) -> list[float]:
    return sorted(
        float(word["top"])
        for word in words
        if re.fullmatch(r"20\d{2}/\d{2}/\d{2}", str(word.get("text", "")))
        and 92 <= float(word["x0"]) <= 100
        and float(word["top"]) > 90
    )


def extract_cmbc(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        first_page_text = pdf.pages[0].extract_text() if pdf.pages else ""
        if "个人账户对账单" not in (first_page_text or ""):
            return transactions

        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=1, y_tolerance=3)
            tops = _row_tops(words)
            for index, top in enumerate(tops):
                bottom = tops[index + 1] if index + 1 < len(tops) else float(page.height)
                raw_date = _column_text(words, "date", top, bottom)
                raw_time = _column_text(words, "time", top, bottom)
                tx_time = _parse_time(raw_date, raw_time)
                amount = _parse_decimal(_column_text(words, "amount", top, bottom))
                balance = _parse_decimal(_column_text(words, "balance", top, bottom))
                if tx_time is None or amount is None or balance is None:
                    continue

                summary = _column_text(words, "summary", top, bottom)
                transfer_flag = _column_text(words, "transfer_flag", top, bottom)
                channel = _column_text(words, "channel", top, bottom)
                institution = _column_text(words, "institution", top, bottom)
                counterparty_raw = _column_text(words, "counterparty", top, bottom)
                counterparty_bank = _column_text(words, "counterparty_bank", top, bottom)
                raw_fields = [
                    f"{raw_date} {raw_time}", summary, str(amount), str(balance), transfer_flag,
                    channel, institution, counterparty_raw, counterparty_bank,
                ]
                source_fields = {
                    field_name: value
                    for field_name, value in (
                        ("transaction_channel", channel),
                        ("transaction_institution", institution),
                        ("counterparty_name_account_raw", counterparty_raw),
                        ("counterparty_bank_raw", counterparty_bank),
                    )
                    if value
                }
                source_indices = {
                    "transaction_channel": 5,
                    "transaction_institution": 6,
                    "counterparty_name_account_raw": 7,
                    "counterparty_bank_raw": 8,
                }
                field_sources = {
                    field_name: f"raw_headers[{source_indices[field_name]}]:{RAW_HEADERS[source_indices[field_name]]}"
                    for field_name in source_fields
                }
                counterparty_name = _counterparty_name(counterparty_raw)
                if summary:
                    field_sources["summary"] = "raw_headers[1]:摘要"
                if counterparty_name:
                    field_sources["counterparty_name"] = "raw_headers[7]:对方户名/账号#斜杠前文字部分"

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if amount > ZERO else ZERO,
                        expense=-amount if amount < ZERO else ZERO,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(transactions) + 1,
                        raw_time=f"{raw_date} {raw_time}",
                        raw_amount=str(amount),
                        raw_balance=str(balance),
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=RAW_HEADERS,
                        summary=summary,
                        counterparty_name=counterparty_name,
                        source_fields=source_fields,
                        field_sources=field_sources,
                        field_confidence={field_name: 1.0 for field_name in field_sources},
                    )
                )
    return transactions
