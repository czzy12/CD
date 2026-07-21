from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import choose_amount_and_balance


BANK_NAME = "中国建设银行"
DATE_COL = 2
AMOUNT_COL = 3
BALANCE_COL = 4
FILTERED_MARKERS = ("【筛选】", "不保证为连续交易")
RAW_HEADERS = ["序号", "摘要", "交易日期", "交易金额", "账户余额", "交易地点/附言", "对方账号与户名"]


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def parse_ccb_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).replace("\n", "").strip()
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime(int(text[:4]), int(text[4:6]), int(text[6:8]))
    except ValueError:
        return None


def _row_is_transaction(row: list) -> bool:
    if len(row) <= BALANCE_COL:
        return False
    return parse_ccb_date(row[DATE_COL]) is not None


def _is_filtered_statement(text: str) -> bool:
    return any(marker in text for marker in FILTERED_MARKERS)


def extract_ccb(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        first_page_text = pdf.pages[0].extract_text() if pdf.pages else ""
        balance_optional = _is_filtered_statement(first_page_text or "")
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if not row or not _row_is_transaction(row):
                        continue

                    tx_time = parse_ccb_date(row[DATE_COL])
                    amount, balance, issues = choose_amount_and_balance(
                        row[AMOUNT_COL],
                        row[BALANCE_COL],
                        None if balance_optional else previous_balance,
                    )

                    if amount is None:
                        amount = Decimal("0.00")

                    income = amount if amount > 0 else Decimal("0.00")
                    expense = -amount if amount < 0 else Decimal("0.00")

                    raw_fields = [_clean_cell(cell) for cell in row]
                    location_remark_raw = raw_fields[5] if len(raw_fields) > 5 else ""
                    counterparty_raw = raw_fields[6] if len(raw_fields) > 6 else ""
                    source_fields = {}
                    field_sources = {}
                    if location_remark_raw:
                        source_fields["transaction_location"] = location_remark_raw
                        field_sources["transaction_location"] = "raw_headers[5]:交易地点/附言"
                    if counterparty_raw:
                        source_fields["counterparty_account_name_raw"] = counterparty_raw
                        field_sources["counterparty_account_name_raw"] = "raw_headers[6]:对方账号与户名"

                    counterparty_name = ""
                    if counterparty_raw.count("/") == 1:
                        _account, name = counterparty_raw.split("/", 1)
                        counterparty_name = name.strip()
                        if counterparty_name:
                            field_sources["counterparty_name"] = "raw_headers[6]:对方账号与户名#斜杠后户名"

                    transaction = Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_index,
                        row_no=row_index,
                        raw_time=_clean_cell(row[DATE_COL]),
                        raw_amount=_clean_cell(row[AMOUNT_COL]),
                        raw_balance=_clean_cell(row[BALANCE_COL]),
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=RAW_HEADERS,
                        status="ok" if not issues else "review",
                        issues=issues,
                        counterparty_name=counterparty_name,
                        remark=location_remark_raw,
                        source_fields=source_fields,
                        field_sources={
                            **field_sources,
                            **({"remark": "raw_headers[5]:交易地点/附言"} if location_remark_raw else {}),
                        },
                        field_confidence={
                            field_name: 1.0
                            for field_name in (
                                list(field_sources) + (["remark"] if location_remark_raw else [])
                            )
                        },
                    )
                    if balance_optional:
                        transaction.balance_optional = True

                    transactions.append(transaction)

                    if balance is not None:
                        previous_balance = balance

    return transactions
