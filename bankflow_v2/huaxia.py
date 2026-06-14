import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "华夏银行"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_RE = re.compile(r"^(20\d{2}-\d{2}-\d{2})\s+(?P<body>.+)$")
MONEY_RE = re.compile(r"[+-]?\d[\d,]*\.\d{2}")


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


def extract_huaxia(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line in (page.extract_text() or "").splitlines():
                line = line.strip()
                match = DATE_RE.match(line)
                if not match:
                    continue

                body = match.group("body")
                money_matches = MONEY_RE.findall(body)
                if len(money_matches) < 2:
                    continue

                amount = _parse_money(money_matches[0])
                balance = _parse_money(money_matches[1])
                if amount is None or balance is None:
                    continue

                tx_time = datetime.strptime(match.group(1), "%Y-%m-%d")
                description = body[: body.find(money_matches[0])].strip()
                row_no = len(rows) + 1
                tx = Transaction(
                    transaction_time=tx_time,
                    income=amount if amount >= ZERO else ZERO,
                    expense=-amount if amount < ZERO else ZERO,
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=row_no,
                    raw_time=match.group(1),
                    raw_amount=money_matches[0],
                    raw_balance=money_matches[1],
                    raw_text=line,
                    raw_fields=[match.group(1), description, money_matches[0], money_matches[1], line],
                )
                tx.merge_key = "|".join([match.group(1), money_matches[0], money_matches[1], str(page_no), str(row_no)])
                rows.append(tx)

    return _normalize_reverse_printed(rows)
