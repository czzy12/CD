import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import choose_amount_and_balance


BANK_NAME = "中国农业银行"
LINE_RE = re.compile(
    r"^(?P<date>\d{8})(?:\s+(?P<time>\d{6}))?\s+"
    r"(?P<type>\S+)\s+"
    r"(?P<amount>[+-]?\d[\d,]*\.\d{2})\s+"
    r"(?P<balance>\d[\d,]*\.\d{2})(?:\s+(?P<counterparty>.*))?$"
)


def parse_abc_time(raw_date: str, raw_time: str | None = None) -> datetime | None:
    if not raw_date or len(raw_date) != 8 or not raw_date.isdigit():
        return None

    raw_time = raw_time or "000000"
    if len(raw_time) != 6 or not raw_time.isdigit():
        return None

    try:
        return datetime(
            int(raw_date[:4]),
            int(raw_date[4:6]),
            int(raw_date[6:8]),
            int(raw_time[:2]),
            int(raw_time[2:4]),
            int(raw_time[4:6]),
        )
    except ValueError:
        return None


def extract_abc(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for line_no, line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = line.strip()
                match = LINE_RE.match(line)
                if not match:
                    continue

                tx_time = parse_abc_time(match.group("date"), match.group("time"))
                if tx_time is None:
                    continue

                amount, balance, issues = choose_amount_and_balance(
                    match.group("amount"),
                    match.group("balance"),
                    previous_balance,
                )

                if amount is None:
                    amount = Decimal("0.00")

                income = amount if amount > 0 else Decimal("0.00")
                expense = -amount if amount < 0 else Decimal("0.00")
                raw_time = match.group("date")
                if match.group("time"):
                    raw_time = f"{raw_time} {match.group('time')}"

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_index,
                        row_no=line_no,
                        raw_time=raw_time,
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )

                if balance is not None:
                    previous_balance = balance

    return transactions
