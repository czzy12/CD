import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import choose_amount_and_balance, money_to_decimal


BANK_NAME = "招商银行"
LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+CNY\s+"
    r"(?P<amount>[+-]?\d[\d,]*\.?\d{0,2})\s+"
    r"(?P<balance>\d[\d,]*\.?\d{0,2})\s+"
    r"(?P<type>\S+)(?:\s+.*)?$"
)


def _parse_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _normalize_money(raw: str) -> str:
    """Keep normal amounts unchanged; add a decimal point only for obvious cents loss."""
    if "." in raw:
        return raw
    sign = ""
    text = raw
    if text.startswith(("+", "-")):
        sign = text[0]
        text = text[1:]
    clean = text.replace(",", "")
    if len(clean) > 2:
        return f"{sign}{clean[:-2]}.{clean[-2:]}"
    return raw


def extract_cmb(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = LINE_RE.match(line)
                if not match:
                    continue

                tx_time = _parse_date(match.group("date"))
                if tx_time is None:
                    continue

                amount_raw = _normalize_money(match.group("amount"))
                balance_raw = _normalize_money(match.group("balance"))
                amount, balance, issues = choose_amount_and_balance(
                    amount_raw,
                    balance_raw,
                    previous_balance,
                )

                if amount is None:
                    amount = Decimal("0.00")
                if balance is None:
                    balance = money_to_decimal(balance_raw)

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if amount > 0 else Decimal("0.00"),
                        expense=-amount if amount < 0 else Decimal("0.00"),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_index,
                        row_no=line_no,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )

                if balance is not None:
                    previous_balance = balance

    return transactions
