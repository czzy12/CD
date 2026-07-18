import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import CENT, money_to_decimal


BANK_NAME = "富滇银行"
ZERO = Decimal("0.00")
HEADERS = [
    "序号SerialNumber",
    "交易日期TradingDate",
    "货币Currency",
    "交易金额TradingAmount",
    "账户余额AccountBalance",
    "对方账号CounterpartyAccount",
    "对方户名CounterpartyName",
    "摘要描述TradingDescription",
    "备注Remark",
]


def _compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _cell_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _is_target_table(table: list[list[object]]) -> bool:
    if not table or len(table[0]) < len(HEADERS):
        return False
    return [_compact(value) for value in table[0][: len(HEADERS)]] == HEADERS


def _parse_time(raw: str) -> datetime | None:
    try:
        return datetime.strptime(_compact(raw), "%Y-%m-%d%H:%M:%S")
    except ValueError:
        return None


def extract_fudian(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return transactions
        first_page = _compact(pdf.pages[0].extract_text() or "")
        if "富滇银行交易流水" not in first_page or "FudianBankTransactionDetails" not in first_page:
            return transactions

        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not table:
                    continue
                start_index = 1 if _is_target_table(table) else 0
                for row in table[start_index:]:
                    if len(row) < len(HEADERS):
                        continue
                    raw_fields = [_cell_text(value) for value in row[: len(HEADERS)]]
                    try:
                        sequence = int(_compact(raw_fields[0]))
                    except ValueError:
                        continue

                    tx_time = _parse_time(raw_fields[1])
                    amount = money_to_decimal(_compact(raw_fields[3]))
                    balance = money_to_decimal(_compact(raw_fields[4]))
                    if tx_time is None or amount is None or balance is None:
                        continue

                    transaction = Transaction(
                        transaction_time=tx_time,
                        income=amount.quantize(CENT) if amount > ZERO else ZERO,
                        expense=(-amount).quantize(CENT) if amount < ZERO else ZERO,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=sequence,
                        raw_time=raw_fields[1],
                        raw_amount=raw_fields[3],
                        raw_balance=raw_fields[4],
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=HEADERS,
                    )
                    transaction.merge_key = "|".join(
                        [raw_fields[0], raw_fields[1], raw_fields[3], raw_fields[4]]
                    )
                    transactions.append(transaction)
    return transactions
