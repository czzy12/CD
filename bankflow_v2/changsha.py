import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "长沙银行"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
LINE_RE = re.compile(
    r"^(?P<date>20\d{2}-\d{2}-\d{2})\s+"
    r"(?P<amount>[+-]\d[\d,]*\.\d{2})\s+"
    r"(?P<balance>\d[\d,]*\.\d{2})(?:\s+(?P<tail>.*))?$"
)


def _money(value: str) -> Decimal:
    try:
        return Decimal(value.replace(",", "")).quantize(CENT)
    except InvalidOperation:
        return ZERO


def _account_meta(pdf_path: str) -> tuple[str, str]:
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() if pdf.pages else ""
    text = text or ""
    name_match = re.search(r"账户名称\s*[:：]\s*([^\s]+)", text)
    account_match = re.search(r"客户账号\s*[:：]\s*([0-9]+)", text)
    return (name_match.group(1) if name_match else "", account_match.group(1) if account_match else "")


def extract_changsha(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    account_name, account_no = _account_meta(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = LINE_RE.match(line)
                if not match:
                    continue
                amount = _money(match.group("amount"))
                balance = _money(match.group("balance"))
                tx_time = datetime.strptime(match.group("date"), "%Y-%m-%d")
                tx = Transaction(
                    transaction_time=tx_time,
                    income=amount if amount > ZERO else ZERO,
                    expense=-amount if amount < ZERO else ZERO,
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=len(rows) + 1,
                    raw_time=match.group("date"),
                    raw_amount=match.group("amount"),
                    raw_balance=match.group("balance"),
                    raw_text=line,
                    raw_fields=[match.group("date"), match.group("amount"), match.group("balance"), match.group("tail") or ""],
                    raw_headers=["交易日期", "交易金额", "账户余额", "对方信息/摘要"],
                )
                tx.account_name = account_name
                tx.account_no = account_no
                tx.merge_key = "|".join([match.group("date"), match.group("amount"), match.group("balance"), match.group("tail") or ""])
                rows.append(tx)
    return rows
