import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "平安银行"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_RE = re.compile(r"(20\d{2})-?(\d{2})-?(\d{2})")
PAGE_RE = re.compile(r"(\d+)\s*/\s*31")
RAW_HEADERS = ["序号", "交易日期", "交易金额", "余额", "交易地点", "摘要", "备注", "交易对手信息"]


def _cell(value: object) -> str:
    return str(value or "").replace("\n", "|").strip()


def _parse_decimal(value: object) -> Decimal | None:
    text = _cell(value).replace(",", "")
    sign = "-" if "-" in text else "+" if "+" in text else ""
    body = "".join(char for char in text if char.isdigit() or char == ".")
    if not body:
        return None
    if body.count(".") > 1:
        first_dot = body.find(".")
        body = body[: first_dot + 1] + body[first_dot + 1 :].replace(".", "")
    try:
        return Decimal(f"{sign}{body}").quantize(CENT)
    except InvalidOperation:
        return None


def _parse_int(value: object) -> int | None:
    digits = "".join(char for char in _cell(value) if char.isdigit())
    return int(digits) if digits else None


def _parse_date(value: object) -> datetime | None:
    text = "".join(char for char in _cell(value) if char.isdigit() or char == "-")
    match = DATE_RE.search(text)
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _statement_page(page_text: str, fallback: int) -> int:
    matches = PAGE_RE.findall(page_text or "")
    if not matches:
        return fallback
    return int(matches[-1])


def extract_pingan(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for local_page_no, page in enumerate(pdf.pages, start=1):
            page_no = _statement_page(page.extract_text() or "", local_page_no)
            for table in page.extract_tables():
                for row in table[1:]:
                    if len(row) < 4:
                        continue
                    sequence = _parse_int(row[0])
                    tx_time = _parse_date(row[1])
                    amount = _parse_decimal(row[2])
                    balance = _parse_decimal(row[3])
                    if sequence is None or tx_time is None or amount is None or balance is None:
                        continue

                    fields = [_cell(cell) for cell in row]
                    source_fields = {
                        field_name: fields[index]
                        for field_name, index in (("transaction_location", 4), ("counterparty_info_raw", 7))
                        if index < len(fields) and fields[index]
                    }
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=amount if amount >= ZERO else ZERO,
                        expense=-amount if amount < ZERO else ZERO,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=sequence,
                        raw_time=tx_time.strftime("%Y-%m-%d"),
                        raw_amount=_cell(row[2]),
                        raw_balance=_cell(row[3]),
                        raw_text=" ".join(field for field in fields if field),
                        raw_fields=fields,
                        raw_headers=RAW_HEADERS,
                        source_fields=source_fields,
                        field_sources={
                            field_name: f"raw_headers[{index}]:{RAW_HEADERS[index]}"
                            for field_name, index in (("transaction_location", 4), ("counterparty_info_raw", 7))
                            if field_name in source_fields
                        },
                        field_confidence={field_name: 1.0 for field_name in source_fields},
                    )
                    tx.merge_key = "|".join([str(sequence), tx.raw_time, tx.raw_amount, tx.raw_balance])
                    rows.append(tx)

    return rows
