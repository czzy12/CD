import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国农业银行"
START_RE = re.compile(r"^(\d{4}-\d{2}-(?:\d{2})?)(?:\s+(.*))?$")
TIME_RE = re.compile(r"^(?:(\d{2})\s+)?(\d{2}:\d{2}:\d{2})(?:\s+(.*))?$")
AMOUNT_RE = re.compile(r"^(\d[\d,]*\.\d{2})\s+(\d[\d,]*\.\d{2})(?:\s+(.*))?$")


def _is_record_start(line: str) -> bool:
    match = START_RE.match(line)
    if not match:
        return False
    date_text = match.group(1)
    return len(date_text) == 10 or date_text.endswith("-")


def _clean_line(line: str) -> str:
    return line.strip()


def _parse_blocks(pdf_path: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    skip_prefixes = ("账户明细", "账号:", "币种:", "交易时间", "第")

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for raw_line in (page.extract_text() or "").splitlines():
                line = _clean_line(raw_line)
                if not line or line.startswith(skip_prefixes):
                    continue

                if _is_record_start(line):
                    if current:
                        blocks.append(current)
                    current = [line]
                elif current is not None:
                    current.append(line)

    if current:
        blocks.append(current)
    return blocks


def _parse_datetime(block: list[str]) -> tuple[datetime | None, str]:
    start = START_RE.match(block[0])
    if not start:
        return None, ""

    date_prefix = start.group(1)
    date_text = date_prefix if len(date_prefix) == 10 else None
    time_text = None

    for line in block[1:]:
        match = TIME_RE.match(line)
        if not match:
            continue
        if date_text is None and match.group(1):
            date_text = f"{date_prefix}{match.group(1)}"
        time_text = match.group(2)
        break

    if date_text is None or time_text is None:
        return None, ""

    try:
        return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S"), f"{date_text} {time_text}"
    except ValueError:
        return None, ""


def _parse_amount_balance(block: list[str]) -> tuple[Decimal | None, Decimal | None, str]:
    for line in block[1:]:
        match = AMOUNT_RE.match(line)
        if not match:
            continue
        amount = money_to_decimal(match.group(1))
        balance = money_to_decimal(match.group(2))
        return amount, balance, line
    return None, None, ""


def _direction(raw_text: str, amount: Decimal, balance: Decimal, previous_balance: Decimal | None) -> str | None:
    if previous_balance is not None:
        if (previous_balance + amount).quantize(Decimal("0.01")) == balance:
            return "income"
        if (previous_balance - amount).quantize(Decimal("0.01")) == balance:
            return "expense"

    if "转存" in raw_text:
        return "income"
    if any(keyword in raw_text for keyword in ("转取", "费用", "手续费", "公共缴费", "扣税")):
        return "expense"
    return None


def extract_abc_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    for row_index, block in enumerate(_parse_blocks(pdf_path), start=1):
        tx_time, raw_time = _parse_datetime(block)
        amount, balance, raw_amount = _parse_amount_balance(block)
        raw_text = " | ".join(block)
        issues: list[str] = []

        if tx_time is None:
            issues.append("交易时间无法解析")
        if amount is None:
            issues.append("金额无法解析")
        if balance is None:
            issues.append("余额无法解析")
        if issues:
            continue

        direction = _direction(raw_text, amount, balance, previous_balance)
        if direction == "income":
            income = amount
            expense = Decimal("0.00")
        elif direction == "expense":
            income = Decimal("0.00")
            expense = amount
        else:
            income = Decimal("0.00")
            expense = Decimal("0.00")
            issues.append("收支方向无法判定")

        transactions.append(
            Transaction(
                transaction_time=tx_time,
                income=income,
                expense=expense,
                balance=balance,
                bank=BANK_NAME,
                page_no=0,
                row_no=row_index,
                raw_time=raw_time,
                raw_amount=raw_amount,
                raw_balance=str(balance),
                status="ok" if not issues else "review",
                issues=issues,
            )
        )
        previous_balance = balance

    return transactions
