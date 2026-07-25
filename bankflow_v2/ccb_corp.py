import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList
from .number_parser import money_to_decimal


BANK_NAME = "中国建设银行"
TIME_COL = 1
DEBIT_COL = 2
CREDIT_COL = 3
BALANCE_COL = 4
SERIAL_COL = 12
METADATA_RE = re.compile(
    r"账号[:：]\s*(?P<account>[0-9A-Za-z-]+)\s+账户名称[:：]\s*(?P<name>.+?)\s+日期[:：]\s*"
    r"(?P<start>\d{8})\s*-\s*(?P<end>\d{8})",
    re.S,
)


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _split_cell(value) -> list[str]:
    return [part.strip() for part in str(value or "").splitlines()]


def _parse_time(raw: str | None) -> datetime | None:
    text = _clean_cell(raw)
    if len(text) == 16 and text[8] != " ":
        text = f"{text[:8]} {text[8:]}"
    try:
        return datetime.strptime(text, "%Y%m%d %H:%M:%S")
    except ValueError:
        return None


def _parse_date(raw: str | None) -> datetime | None:
    text = _clean_cell(raw)
    try:
        return datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None


def _parse_money(raw: str | None) -> Decimal:
    return money_to_decimal(_clean_cell(raw)) or Decimal("0.00")


def _classify_amounts(debit: Decimal, credit: Decimal) -> tuple[Decimal, Decimal]:
    """Keep signed debit/credit reversals in their economic direction."""
    income = credit if credit > 0 else -debit if debit < 0 else Decimal("0.00")
    expense = debit if debit > 0 else -credit if credit < 0 else Decimal("0.00")
    return income, expense


def _cell_at(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def _is_deposit_detail_table(table: list[list]) -> bool:
    if len(table) < 3:
        return False
    header = "".join(_clean_cell(cell) for row in table[:2] for cell in row)
    return (
        "账号" not in header
        and "交易时间" not in header
        and "日期" in header
        and "发生额" in header
        and "借方" in header
        and "贷方" in header
        and "余额" in header
    )


def _extract_deposit_detail_rows(table: list[list], page_index: int) -> list[Transaction]:
    transactions: list[Transaction] = []
    for row_index, row in enumerate(table, start=1):
        if len(row) < 9:
            continue
        dates = _split_cell(row[0])
        if not dates or not any(_parse_date(date) for date in dates):
            continue

        debits = _split_cell(row[5])
        credits = _split_cell(row[6])
        balances = _split_cell(row[8])
        vouchers = _split_cell(row[1]) if len(row) > 1 else []
        summaries = _split_cell(row[3]) if len(row) > 3 else []
        counterparties = _split_cell(row[4]) if len(row) > 4 else []
        serials = _split_cell(row[9]) if len(row) > 9 else []

        for index, date_text in enumerate(dates):
            tx_time = _parse_date(date_text)
            if tx_time is None:
                continue

            debit = _parse_money(_cell_at(debits, index))
            credit = _parse_money(_cell_at(credits, index))
            balance = money_to_decimal(_cell_at(balances, index))
            income, expense = _classify_amounts(debit, credit)
            issues = []

            if debit > 0 and credit > 0:
                issues.append("借方和贷方同时有金额")
            if debit == 0 and credit == 0:
                issues.append("借方和贷方均为零")

            raw_summary = _cell_at(summaries, index)
            raw_counterparty = _cell_at(counterparties, index)
            tx = Transaction(
                transaction_time=tx_time,
                income=income,
                expense=expense,
                balance=balance,
                bank=BANK_NAME,
                page_no=page_index,
                row_no=row_index * 1000 + index,
                raw_time=date_text,
                raw_amount=f"{_cell_at(debits, index)}|{_cell_at(credits, index)}",
                raw_balance=_cell_at(balances, index),
                raw_text=" | ".join(part for part in (raw_summary, raw_counterparty) if part),
                raw_fields=[
                    date_text,
                    _cell_at(vouchers, index),
                    raw_summary,
                    raw_counterparty,
                    _cell_at(debits, index),
                    _cell_at(credits, index),
                    _cell_at(balances, index),
                    _cell_at(serials, index),
                ],
                raw_headers=["日期", "凭证种类", "摘要", "对方户名", "借方", "贷方", "余额", "交易流水号"],
                status="ok" if not issues else "review",
                issues=issues,
            )
            tx.preserve_signed_columns = True
            tx.merge_key = "|".join([date_text, _cell_at(debits, index), _cell_at(credits, index), _cell_at(balances, index), str(page_index), str(index)])
            transactions.append(tx)

    return transactions


def _transaction_key(row: list) -> str:
    serial = _clean_cell(row[SERIAL_COL]) if len(row) > SERIAL_COL else ""
    if serial:
        return serial
    return "|".join(
        _clean_cell(row[index])
        for index in (TIME_COL, DEBIT_COL, CREDIT_COL, BALANCE_COL)
        if len(row) > index
    )


def _statement_metadata(pdf_path: str) -> StatementMetadata:
    metadata = StatementMetadata()
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return metadata
        match = METADATA_RE.search(pdf.pages[0].extract_text() or "")
    if not match:
        return metadata
    metadata.account_name = match.group("name").strip()
    metadata.account_number = match.group("account")
    metadata.statement_period_start = datetime.strptime(match.group("start"), "%Y%m%d").date()
    metadata.statement_period_end = datetime.strptime(match.group("end"), "%Y%m%d").date()
    metadata.field_sources = {
        "account_name": "document_header:账户名称",
        "account_number": "document_header:账号",
        "statement_period_start": "document_header:日期",
        "statement_period_end": "document_header:日期",
    }
    metadata.field_confidence = {field_name: 1.0 for field_name in metadata.field_sources}
    return metadata


def extract_ccb_corp(pdf_path: str) -> TransactionList:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if _is_deposit_detail_table(table):
                    transactions.extend(_extract_deposit_detail_rows(table, page_index))
                    continue

                for row_index, row in enumerate(table, start=1):
                    if len(row) <= BALANCE_COL:
                        continue

                    tx_time = _parse_time(row[TIME_COL])
                    if tx_time is None:
                        continue

                    debit = _parse_money(row[DEBIT_COL])
                    credit = _parse_money(row[CREDIT_COL])
                    balance = money_to_decimal(_clean_cell(row[BALANCE_COL]))
                    income, expense = _classify_amounts(debit, credit)
                    issues = []

                    if debit > 0 and credit > 0:
                        issues.append("借方和贷方同时有金额")
                    if debit == 0 and credit == 0:
                        issues.append("借方和贷方均为零")

                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=_clean_cell(row[TIME_COL]),
                            raw_amount=f"{_clean_cell(row[DEBIT_COL])}|{_clean_cell(row[CREDIT_COL])}",
                            raw_balance=_clean_cell(row[BALANCE_COL]),
                            status="ok" if not issues else "review",
                            issues=issues,
                        )
                    )

                    transactions[-1].merge_key = _transaction_key(row)

    return TransactionList(transactions, _statement_metadata(pdf_path))


def merge_transactions(transactions: list[Transaction]) -> list[Transaction]:
    merged: list[Transaction] = []
    seen: set[str] = set()

    for tx in sorted(transactions, key=lambda item: (item.transaction_time, getattr(item, "merge_key", ""))):
        key = getattr(tx, "merge_key", "")
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        merged.append(tx)

    return merged
