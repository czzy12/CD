import re
from datetime import datetime, timedelta
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import CENT, money_to_decimal


BANK_NAME = "华夏银行对公"
ZERO = Decimal("0.00")
HEADERS = [
    "序号",
    "交易日期",
    "交易时间",
    "支出金额",
    "收入金额",
    "余额",
    "对方账号",
    "对方户名",
    "对方行名",
    "核心流水号",
    "交易描述",
    "摘要",
    "凭证号码",
    "明细标注",
    "记账日期",
]


def _clean(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _is_target_table(table: list[list[object]]) -> bool:
    if not table or len(table[0]) < len(HEADERS):
        return False
    return [_clean(value) for value in table[0][: len(HEADERS)]] == HEADERS


def _parse_time(raw_date: str, raw_time: str, sequence: int) -> datetime | None:
    try:
        value = datetime.strptime(f"{_clean(raw_date)} {_clean(raw_time)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return value - timedelta(microseconds=sequence)


def extract_huaxia_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not _is_target_table(table):
                    continue
                for row in table[1:]:
                    cells = list(row) + [""] * (len(HEADERS) - len(row))
                    raw_fields = [_clean(value) for value in cells[: len(HEADERS)]]
                    try:
                        sequence = int(raw_fields[0])
                    except ValueError:
                        continue

                    tx_time = _parse_time(raw_fields[1], raw_fields[2], sequence)
                    expense = money_to_decimal(raw_fields[3]) if raw_fields[3] else ZERO
                    income = money_to_decimal(raw_fields[4]) if raw_fields[4] else ZERO
                    balance = money_to_decimal(raw_fields[5])
                    if tx_time is None or expense is None or income is None or balance is None:
                        continue

                    raw_amount = raw_fields[4] if income != ZERO else f"-{raw_fields[3]}"
                    source_fields = {
                        field_name: raw_fields[index]
                        for field_name, index in (
                            ("core_transaction_id", 9),
                            ("transaction_description", 10),
                            ("voucher_number", 12),
                            ("detail_marker", 13),
                            ("posting_date", 14),
                        )
                        if raw_fields[index]
                    }
                    source_labels = {
                        "core_transaction_id": 9,
                        "transaction_description": 10,
                        "voucher_number": 12,
                        "detail_marker": 13,
                        "posting_date": 14,
                    }
                    transaction = Transaction(
                        transaction_time=tx_time,
                        income=income.quantize(CENT),
                        expense=expense.quantize(CENT),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=sequence,
                        raw_time=f"{raw_fields[1]} {raw_fields[2]}",
                        raw_amount=raw_amount,
                        raw_balance=raw_fields[5],
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=HEADERS,
                        source_fields=source_fields,
                        field_sources={
                            field_name: f"raw_headers[{source_labels[field_name]}]:{HEADERS[source_labels[field_name]]}"
                            for field_name in source_fields
                        },
                        field_confidence={field_name: 1.0 for field_name in source_fields},
                    )
                    transaction.preserve_signed_columns = True
                    transaction.merge_key = "|".join(
                        [raw_fields[0], raw_fields[1], raw_fields[2], raw_fields[3], raw_fields[4], raw_fields[5]]
                    )
                    transactions.append(transaction)
    return transactions
