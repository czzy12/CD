from __future__ import annotations

import re
from datetime import datetime, timedelta
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国银行公户版式2"
ZERO = Decimal("0.00")
HEADERS = [
    "交易日期",
    "支出(借)",
    "收入(贷)",
    "余额",
    "交易对手账号",
    "交易对手名称",
    "交易对手行名",
    "摘要",
    "附言",
]


def _clean(value: object) -> str:
    return str(value or "").replace("\n", " ").strip()


def _parse_time(value: object) -> datetime | None:
    try:
        return datetime.strptime(_clean(value), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_account_meta(text: str) -> tuple[str, str]:
    number_match = re.search(r"账户\s*[:：]\s*(\d{15,30})", text)
    name_match = re.search(r"账户名称\s*[:：]\s*([^\n]+)", text)
    return (
        name_match.group(1).strip() if name_match else "",
        number_match.group(1) if number_match else "",
    )


def _restore_printed_order(transactions: list[Transaction]) -> None:
    for previous, current in zip(transactions, transactions[1:]):
        if previous.transaction_time.date() != current.transaction_time.date():
            continue
        if current.transaction_time > previous.transaction_time:
            continue
        if "结息" in previous.raw_text:
            previous.transaction_time = current.transaction_time - timedelta(microseconds=1)
        else:
            current.transaction_time = previous.transaction_time + timedelta(microseconds=1)


def extract_boc_corp_v2(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    account_name = ""
    account_no = ""

    with pdfplumber.open(pdf_path) as pdf:
        if pdf.pages:
            account_name, account_no = _parse_account_meta(pdf.pages[0].extract_text() or "")

        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_no, row in enumerate(table, start=1):
                    if not row or len(row) < 4:
                        continue
                    tx_time = _parse_time(row[0])
                    if tx_time is None:
                        continue

                    raw_expense = _clean(row[1])
                    raw_income = _clean(row[2])
                    raw_balance = _clean(row[3])
                    expense = money_to_decimal(raw_expense) or ZERO
                    income = money_to_decimal(raw_income) or ZERO
                    balance = money_to_decimal(raw_balance)
                    issues: list[str] = []
                    if expense != ZERO and income != ZERO:
                        issues.append("支出和收入同时存在")
                    if expense == ZERO and income == ZERO:
                        issues.append("支出和收入均为空")
                    if balance is None:
                        issues.append("余额无法解析")

                    fields = [_clean(cell) for cell in row[: len(HEADERS)]]
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=row_no,
                        raw_time=fields[0],
                        raw_amount=f"{raw_income}|{raw_expense}",
                        raw_balance=raw_balance,
                        raw_text=" | ".join(fields[4:]),
                        raw_fields=fields,
                        raw_headers=HEADERS,
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                    tx.preserve_signed_columns = True
                    tx.account_name = account_name
                    tx.account_no = account_no
                    transactions.append(tx)

    _restore_printed_order(transactions)
    return transactions
