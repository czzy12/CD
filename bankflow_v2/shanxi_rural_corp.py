from datetime import datetime
from decimal import Decimal

import pdfplumber

from .ccb_corp import _amount_columns
from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "山西阳城农村商业银行对公"
HEADERS = ["交易时间", "分账号", "收入金额", "支出金额", "账户余额", "对方账户", "对方户名", "对方行名", "交易机构", "交易渠道", "摘要", "用途", "附言"]


def _cell(row: list, index: int) -> str:
    return str(row[index] or "").replace("\n", "").strip() if index < len(row) else ""


def _balance_chain_score(items: list[Transaction]) -> int:
    score = 0
    for previous, current in zip(items, items[1:]):
        expected = (previous.balance + current.income - current.expense).quantize(Decimal("0.01"))
        if expected == current.balance.quantize(Decimal("0.01")):
            score += 1
    return score


def _normalize_order_and_duplicates(transactions: list[Transaction]) -> list[Transaction]:
    groups: dict[datetime, list[Transaction]] = {}
    for tx in transactions:
        groups.setdefault(tx.transaction_time, []).append(tx)

    for tx_time, items in groups.items():
        if len(items) < 2:
            continue
        forward = sorted(items, key=lambda tx: (tx.page_no, tx.row_no))
        reverse = list(reversed(forward))
        ordered = reverse if _balance_chain_score(reverse) > _balance_chain_score(forward) else forward
        for offset, tx in enumerate(ordered):
            tx.transaction_time = tx_time.replace(microsecond=offset)

    ordered = sorted(transactions, key=lambda tx: tx.transaction_time)
    result: list[Transaction] = []
    previous_balance = None
    for tx in ordered:
        if (
            previous_balance is not None
            and tx.balance == previous_balance
            and (tx.income != 0 or tx.expense != 0)
        ):
            continue
        result.append(tx)
        previous_balance = tx.balance
    return result


def extract_shanxi_rural_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 5:
                        continue
                    try:
                        tx_time = datetime.strptime(_cell(row, 0), "%Y-%m-%d%H:%M:%S")
                    except ValueError:
                        continue
                    income, expense, issues = _amount_columns(_cell(row, 3), _cell(row, 2))
                    balance = money_to_decimal(_cell(row, 4))
                    raw_fields = [_cell(row, i) for i in range(len(row))]
                    transactions.append(Transaction(
                        transaction_time=tx_time, income=income, expense=expense, balance=balance,
                        bank=BANK_NAME, page_no=page_no, row_no=len(transactions) + 1,
                        raw_time=raw_fields[0], raw_amount=f"{raw_fields[2]}|{raw_fields[3]}",
                        raw_balance=raw_fields[4], raw_text=" | ".join(raw_fields[5:]),
                        raw_fields=raw_fields, raw_headers=HEADERS,
                        status="ok" if not issues else "review", issues=issues,
                    ))
    return _normalize_order_and_duplicates(transactions)
