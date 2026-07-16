import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "邢台银行"
ZERO = Decimal("0.00")
ROW_RE = re.compile(
    r"^(?P<date>20\d{2}-\d{2}-\d{2})\s+(?P<direction>收入|支出)\s+"
    r"(?P<amount>\d[\d,]*\.\d{2})\s+(?P<balance>\d[\d,]*\.\d{2})\s+(?P<rest>.*)$"
)


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def extract_xingtai(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = ROW_RE.match(line)
                if not match:
                    continue
                tx_time = _parse_date(match.group("date"))
                amount = money_to_decimal(match.group("amount"))
                balance = money_to_decimal(match.group("balance"))
                if tx_time is None or amount is None or balance is None:
                    continue

                is_income = match.group("direction") == "收入"
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if is_income else ZERO,
                        expense=ZERO if is_income else amount,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=line_no,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=[line],
                        raw_headers=["交易时间", "收入/支出", "交易金额（元）", "余额（元）"],
                    )
                )

    return transactions
