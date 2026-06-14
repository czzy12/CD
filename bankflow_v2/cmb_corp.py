import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import CENT, money_to_decimal


BANK_NAME = "招商银行对公"
MONEY = r"-?[\d,]+\.\d{2}"
ROW_RE = re.compile(
    rf"^(?P<date>20\d{{6}})(?P<business_type>\S+)\s+"
    rf"(?P<body>.*?)\s+(?P<amount>{MONEY})\s+"
    rf"(?P<balance>[\d,]+\.\d{{2}})(?P<counterparty>.*)$"
)


def _parse_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y%m%d")
    except ValueError:
        return None


def _append_continuation(transactions: list[Transaction], line: str) -> None:
    if not transactions:
        return
    tx = transactions[-1]
    tx.raw_text = f"{tx.raw_text}\n{line}" if tx.raw_text else line
    if tx.raw_fields:
        tx.raw_fields[-1] = f"{tx.raw_fields[-1]} {line}".strip()


def extract_cmb_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = ROW_RE.match(line)
                if not match:
                    if transactions and not line.startswith(("第", "特别提示", "If ", "若")):
                        _append_continuation(transactions, line)
                    continue

                tx_time = _parse_date(match.group("date"))
                if tx_time is None:
                    continue

                amount = money_to_decimal(match.group("amount"))
                balance = money_to_decimal(match.group("balance"))
                issues: list[str] = []
                if amount is None:
                    issues.append("金额无法解析")
                    amount = Decimal("0.00")
                if balance is None:
                    issues.append("余额无法解析")
                if previous_balance is not None and balance is not None:
                    expected = (previous_balance + amount).quantize(CENT)
                    if expected != balance:
                        issues.append(f"余额不连续: 期望 {expected}, 解析 {balance}")

                raw_fields = [
                    match.group("date"),
                    match.group("business_type"),
                    match.group("body").strip(),
                    match.group("amount"),
                    match.group("balance"),
                    match.group("counterparty").strip(),
                ]
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if amount > 0 else Decimal("0.00"),
                        expense=-amount if amount < 0 else Decimal("0.00"),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=line_no,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=raw_fields,
                        raw_headers=["日期", "业务类型", "票据号/摘要", "借方/贷方金额", "余额", "对手户名"],
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )
                if balance is not None:
                    previous_balance = balance

    return transactions
