from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "泸州银行个人"
RAW_HEADERS = ["序号", "交易时间", "币种", "交易金额", "账户余额", "对方账号", "对方户名", "交易类型", "摘要", "交易渠道"]
ZERO = Decimal("0.00")


def _cell(row: list, index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).replace("\n", " ").strip()


def _money(text: str) -> Decimal | None:
    return money_to_decimal(text.replace(",", ""))


def _parse_time(text: str) -> datetime | None:
    try:
        return datetime.strptime(" ".join(text.split()), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def extract_luzhou(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not table:
                    continue
                for row in table[1:]:
                    if len(row) < len(RAW_HEADERS) or not _cell(row, 0).isdigit():
                        continue

                    tx_time = _parse_time(_cell(row, 1))
                    signed_amount = _money(_cell(row, 3))
                    balance = _money(_cell(row, 4))
                    if tx_time is None or signed_amount is None or balance is None:
                        continue

                    income = signed_amount if signed_amount > ZERO else ZERO
                    expense = abs(signed_amount) if signed_amount < ZERO else ZERO
                    raw_fields = [_cell(row, index) for index in range(len(RAW_HEADERS))]
                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_no,
                            row_no=int(raw_fields[0]),
                            raw_time=raw_fields[1],
                            raw_amount=raw_fields[3],
                            raw_balance=raw_fields[4],
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=RAW_HEADERS,
                        transaction_method=raw_fields[9],
                        field_sources={"transaction_method": "raw_headers[9]:交易渠道"} if raw_fields[9] else {},
                        field_confidence={"transaction_method": 1.0} if raw_fields[9] else {},
                    )
                    )

    # 清单按倒序展示；同一秒若有多笔交易，也按序号倒序排列。
    # 补微秒让统一汇总按真实余额链顺序排序。
    groups: dict[datetime, list[Transaction]] = defaultdict(list)
    for tx in transactions:
        groups[tx.transaction_time].append(tx)
    for group in groups.values():
        if len(group) <= 1:
            continue
        for microsecond, tx in enumerate(reversed(group)):
            tx.transaction_time = tx.transaction_time.replace(microsecond=microsecond)

    return transactions
