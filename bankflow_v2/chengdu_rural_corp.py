from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import pdfplumber

from .models import Transaction


BANK_NAME = "成都农村商业银行对公"
CENT = Decimal("0.01")
RAW_HEADERS = ["序号", "子序号", "交易日期", "摘要", "币种", "借方金额", "贷方金额", "余额"]


def _parts(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines()]


def _money(value: str) -> Decimal | None:
    text = value.replace(",", "").strip()
    if not text:
        return None
    try:
        return Decimal(text).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value.strip(), "%Y%m%d")
    except ValueError:
        return None


def _is_detail_table(table: list[list[Any]]) -> bool:
    if len(table) < 2 or len(table[0]) < 8:
        return False
    header = "".join(str(cell or "").replace("\n", "") for cell in table[0])
    return (
        "交易日期" in header
        and "借方金额" in header
        and "贷方金额" in header
        and "余额" in header
        and "对方户名" in header
    )


def extract_chengdu_rural_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        for actual_page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not _is_detail_table(table):
                    continue
                cols = [_parts(cell) for cell in table[1]]
                row_count = max(len(cols[index]) for index in range(min(8, len(cols))))
                for index in range(row_count):
                    try:
                        raw_seq = cols[0][index]
                        raw_sub = cols[1][index]
                        raw_date = cols[2][index]
                        raw_summary = cols[3][index]
                        raw_currency = cols[4][index]
                        raw_debit = cols[5][index]
                        raw_credit = cols[6][index]
                        raw_balance = cols[7][index]
                    except IndexError:
                        continue

                    tx_date = _date(raw_date)
                    debit = _money(raw_debit)
                    credit = _money(raw_credit)
                    balance = _money(raw_balance)
                    if tx_date is None or debit is None or credit is None or balance is None:
                        continue

                    sequence += 1
                    raw_fields = [
                        raw_seq,
                        raw_sub,
                        raw_date,
                        raw_summary,
                        raw_currency,
                        raw_debit,
                        raw_credit,
                        raw_balance,
                        f"原页:{actual_page_no}",
                    ]
                    tx = Transaction(
                        transaction_time=tx_date,
                        income=credit,
                        expense=debit,
                        balance=balance,
                        bank=BANK_NAME,
                        # This statement is printed newest-first. Sort partial-date
                        # rows by reverse print sequence to restore the balance chain.
                        page_no=0,
                        row_no=-sequence,
                        raw_time=raw_date,
                        raw_amount=f"借方:{raw_debit} 贷方:{raw_credit}",
                        raw_balance=raw_balance,
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=RAW_HEADERS + ["原页"],
                    )
                    tx.preserve_signed_columns = True
                    transactions.append(tx)

    return transactions
