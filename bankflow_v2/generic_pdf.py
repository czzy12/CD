import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction


BANK_NAME = "通用PDF识别"
CENT = Decimal("0.01")
ROW_RE = re.compile(
    r"^(?:卡\s+\S+\s+)?"
    r"(?P<date>20\d{2}[/-]\d{1,2}[/-]\d{1,2})\s+"
    r"(?P<time>\d{1,2}:\d{2}:\d{2})\s+"
    r"(?P<summary>.*?)\s+"
    r"(?P<amount>[+-]?\d[\d,]*\.\d{2})\s+"
    r"(?P<balance>\d[\d,]*\.\d{2})\b"
)


def _money(raw: str) -> Decimal:
    return Decimal(raw.replace(",", "")).quantize(CENT)


def _time(raw_date: str, raw_time: str) -> datetime | None:
    text = f"{raw_date.replace('/', '-')} {raw_time}"
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def extract_generic_pdf(pdf_path: str, bank_name: str = BANK_NAME) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = ROW_RE.match(line)
                if not match:
                    continue

                tx_time = _time(match.group("date"), match.group("time"))
                if tx_time is None:
                    continue

                amount = _money(match.group("amount"))
                balance = _money(match.group("balance"))
                transactions.append(
                    Transaction(
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
                    )
                )
    return transactions
