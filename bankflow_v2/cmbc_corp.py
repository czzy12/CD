import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国民生银行(对公)"
MONEY = r"[\d,]+\.\d{2}"
DATE_LINE_RE = re.compile(
    rf"^(?P<date>\d{{4}}/\d{{2}}/\d{{2}})\s+.*?\s+"
    rf"(?P<debit>{MONEY})\s+(?P<credit>{MONEY})\s+(?P<balance>{MONEY})\s+"
)
TIME_RE = re.compile(r"^(?P<time>\d{2}:\d{2}:\d{2})\b")


def _parse_time(raw_date: str, raw_time: str) -> datetime | None:
    try:
        return datetime.strptime(f"{raw_date} {raw_time}", "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


def extract_cmbc_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            lines = [line.strip() for line in (page.extract_text() or "").splitlines() if line.strip()]
            idx = 0
            while idx < len(lines):
                match = DATE_LINE_RE.match(lines[idx])
                if not match:
                    idx += 1
                    continue

                time_raw = "00:00:00"
                if idx + 1 < len(lines):
                    time_match = TIME_RE.match(lines[idx + 1])
                    if time_match:
                        time_raw = time_match.group("time")

                tx_time = _parse_time(match.group("date"), time_raw)
                if tx_time is None:
                    idx += 1
                    continue

                debit = money_to_decimal(match.group("debit")) or Decimal("0.00")
                credit = money_to_decimal(match.group("credit")) or Decimal("0.00")
                balance = money_to_decimal(match.group("balance"))
                issues = []
                if debit > 0 and credit > 0:
                    issues.append("借方和贷方同时有金额")
                if debit == 0 and credit == 0:
                    issues.append("借方和贷方均为零")
                if balance is None:
                    issues.append("余额无法解析")

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=credit,
                        expense=debit,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_index,
                        row_no=idx + 1,
                        raw_time=f"{match.group('date')} {time_raw}",
                        raw_amount=f"{match.group('debit')}|{match.group('credit')}",
                        raw_balance=match.group("balance"),
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )
                idx += 2 if idx + 1 < len(lines) and TIME_RE.match(lines[idx + 1]) else 1

    return transactions
