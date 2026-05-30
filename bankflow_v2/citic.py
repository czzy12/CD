import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中信银行个人"
ROW_RE = re.compile(
    r"^(?P<date>20\d{6})\s+RMB\s+(?P<amount>[\d,]+\.\d{2})\s+RMB\s+(?P<balance>[\d,]+\.\d{2})\s+(?P<summary>.*)$"
)
CENT = Decimal("0.01")


def _parse_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y%m%d")
    except ValueError:
        return None


def _resolve_direction(amount: Decimal, balance: Decimal, previous_balance: Decimal | None) -> tuple[Decimal, Decimal, list[str]]:
    if previous_balance is None:
        return amount, Decimal("0.00"), []

    income_expected = (previous_balance + amount).quantize(CENT)
    if income_expected == balance:
        return amount, Decimal("0.00"), []

    expense_expected = (previous_balance - amount).quantize(CENT)
    if expense_expected == balance:
        return Decimal("0.00"), amount, []

    return amount, Decimal("0.00"), [f"余额不连续: 上笔余额 {previous_balance} +/- 金额 {amount}, 当前余额 {balance}"]


def extract_citic(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            lines = [line.strip() for line in (page.extract_text() or "").splitlines() if line.strip()]
            for line_no, line in enumerate(lines, start=1):
                match = ROW_RE.match(line)
                if not match:
                    continue

                tx_time = _parse_date(match.group("date"))
                amount = money_to_decimal(match.group("amount"))
                balance = money_to_decimal(match.group("balance"))
                if tx_time is None or amount is None or balance is None:
                    continue

                income, expense, issues = _resolve_direction(amount, balance, previous_balance)
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_index,
                        row_no=line_no,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=[line],
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )
                previous_balance = balance

    return transactions
