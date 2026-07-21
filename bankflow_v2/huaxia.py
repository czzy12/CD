import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "华夏银行"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
RAW_HEADERS = ["记账日期", "摘要", "交易金额", "余额", "交易机构", "对方姓名", "对方卡/账号", "对方开户行", "附言"]
COLUMN_LEFTS = (35.0, 75.0, 125.0, 180.0, 218.0, 265.0, 340.0, 415.0, 480.0)


def _parse_money(text: str) -> Decimal | None:
    try:
        return Decimal(str(text).replace(",", "")).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _normalize_reverse_printed(rows: list[Transaction]) -> list[Transaction]:
    if len(rows) < 2:
        return rows

    reverse_printed = rows[0].transaction_time.date() > rows[-1].transaction_time.date()
    rows = sorted(rows, key=lambda tx: (tx.transaction_time.date(), -tx.row_no if reverse_printed else tx.row_no))
    for index, tx in enumerate(rows, start=1):
        tx.transaction_time = tx.transaction_time + timedelta(seconds=index)
        tx.raw_time = tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S")
    return rows


def _column_index(x0: float) -> int | None:
    for index in range(len(COLUMN_LEFTS) - 1, -1, -1):
        if x0 >= COLUMN_LEFTS[index]:
            return index
    return None


def _join_words(words: list[dict]) -> str:
    lines: dict[float, list[dict]] = {}
    for word in words:
        lines.setdefault(round(float(word["top"]), 1), []).append(word)
    return "\n".join(
        " ".join(str(word["text"]) for word in sorted(lines[top], key=lambda item: float(item["x0"])))
        for top in sorted(lines)
    ).strip()


def _extract_page_rows(page) -> list[list[str]]:
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    anchors = sorted(
        (word for word in words if 35.0 <= float(word["x0"]) < 75.0 and DATE_RE.fullmatch(str(word["text"]))),
        key=lambda word: float(word["top"]),
    )
    rows: list[list[str]] = []
    for index, anchor in enumerate(anchors):
        top = float(anchor["top"])
        previous_gap = top - float(anchors[index - 1]["top"]) if index else None
        next_gap = float(anchors[index + 1]["top"]) - top if index + 1 < len(anchors) else None
        start = top - ((previous_gap if previous_gap is not None else next_gap or 24.0) / 2)
        end = top + ((next_gap if next_gap is not None else previous_gap or 24.0) / 2)
        columns: list[list[dict]] = [[] for _ in RAW_HEADERS]
        for word in words:
            word_top = float(word["top"])
            if not (start <= word_top < end):
                continue
            column = _column_index(float(word["x0"]))
            if column is not None:
                columns[column].append(word)
        rows.append([_join_words(column_words) for column_words in columns])
    return rows


def extract_huaxia(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for raw_fields in _extract_page_rows(page):
                if len(raw_fields) != len(RAW_HEADERS):
                    continue
                amount = _parse_money(raw_fields[2])
                balance = _parse_money(raw_fields[3])
                if amount is None or balance is None:
                    continue
                try:
                    tx_time = datetime.strptime(raw_fields[0], "%Y-%m-%d")
                except ValueError:
                    continue

                row_no = len(rows) + 1
                transaction_institution = raw_fields[4]
                source_fields = (
                    {"transaction_institution": transaction_institution}
                    if transaction_institution
                    else {}
                )
                tx = Transaction(
                    transaction_time=tx_time,
                    income=amount if amount >= ZERO else ZERO,
                    expense=-amount if amount < ZERO else ZERO,
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=row_no,
                    raw_time=raw_fields[0],
                    raw_amount=raw_fields[2],
                    raw_balance=raw_fields[3],
                    raw_text=" | ".join(raw_fields),
                    raw_fields=raw_fields,
                    raw_headers=RAW_HEADERS,
                    source_fields=source_fields,
                    field_sources=(
                        {"transaction_institution": "raw_headers[4]:交易机构"}
                        if transaction_institution
                        else {}
                    ),
                    field_confidence=(
                        {"transaction_institution": 1.0}
                        if transaction_institution
                        else {}
                    ),
                )
                tx.counterparty_bank = ""
                tx.field_sources.pop("counterparty_bank", None)
                tx.field_confidence.pop("counterparty_bank", None)
                tx.merge_key = "|".join([raw_fields[0], raw_fields[2], raw_fields[3], str(page_no), str(row_no)])
                rows.append(tx)

    return _normalize_reverse_printed(rows)
