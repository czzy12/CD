import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import CENT, money_to_decimal


BANK_NAME = "对公客户账户明细"
RAW_HEADERS = ["交易日期", "交易发生金额", "账户余额", "对方账号", "未拆分交易文本"]
ROW_RE = re.compile(
    r"(?P<date>20\d{6})\s+"
    r"(?P<amount>[+-][\d,]+\.\d{2})\s+"
    r"(?P<balance>[\d,]+\.\d{2})\s+"
    r"(?P<body>.+)$"
)


def _date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y%m%d")
    except ValueError:
        return None


def _split_body(body: str) -> tuple[str, str]:
    text = body.strip()
    match = re.match(r"(?P<account>[0-9A-Za-z]+(?:等\d+户)?)(?P<rest>.*)", text)
    if not match:
        return "", text
    return match.group("account"), match.group("rest").strip()


def _append_continuation(transactions: list[Transaction], line: str) -> None:
    if not transactions:
        return
    tx = transactions[-1]
    tx.raw_text = f"{tx.raw_text}\n{line}" if tx.raw_text else line
    if tx.raw_fields:
        tx.raw_fields[-1] = f"{tx.raw_fields[-1]} {line}".strip()
        tx.source_fields["unparsed_transaction_text"] = tx.raw_fields[-1]


def extract_customer_detail_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = ROW_RE.search(line)
                if not match:
                    if transactions and line and not line.startswith(("对公客户账户明细", "打印日期", "打印时间", "账 号", "客户名称", "起始日期", "交易日期", "借方合计", "贷方合计")):
                        _append_continuation(transactions, line)
                    continue

                tx_time = _date(match.group("date"))
                amount = money_to_decimal(match.group("amount"))
                balance = money_to_decimal(match.group("balance"))
                issues: list[str] = []
                if tx_time is None:
                    issues.append("日期无法解析")
                    continue
                if amount is None:
                    issues.append("金额无法解析")
                    amount = Decimal("0.00")
                if balance is None:
                    issues.append("余额无法解析")

                account, rest = _split_body(match.group("body"))
                income = amount if amount > 0 else Decimal("0.00")
                expense = -amount if amount < 0 else Decimal("0.00")
                raw_fields = [
                    match.group("date"),
                    match.group("amount"),
                    match.group("balance"),
                    account,
                    rest,
                ]
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=income.quantize(CENT),
                        expense=expense.quantize(CENT),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(transactions) + 1,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=raw_fields,
                        raw_headers=RAW_HEADERS,
                        source_fields={"unparsed_transaction_text": rest} if rest else {},
                        field_sources={"unparsed_transaction_text": "raw_headers[4]:未拆分交易文本"} if rest else {},
                        field_confidence={"unparsed_transaction_text": 1.0} if rest else {},
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )

    return transactions
