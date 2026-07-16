import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import resolve_amount_balance_sequence


BANK_NAME = "中国工商银行"
DATE_COL = 0
AMOUNT_COL = 8
BALANCE_COL = 9


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def parse_icbc_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).replace("\n", " ")
    text = re.sub(r"[^\d\-/:.\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()

    patterns = [
        r"(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})",
        r"(\d{4})-(\d{2})-(\d{2})(\d{2}):(\d{2}):(\d{2})",
        r"(\d{2})(\d{2})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        parts = [int(p) for p in match.groups()]
        try:
            if len(parts) == 6:
                return datetime(*parts)
            if len(parts) == 7:
                year = parts[0] * 100 + parts[1]
                return datetime(year, *parts[2:])
        except ValueError:
            continue
    return None


def _row_is_transaction(row: list) -> bool:
    if len(row) <= BALANCE_COL:
        return False
    return parse_icbc_time(row[DATE_COL]) is not None


def _row_is_non_current_account(row: list) -> bool:
    account_type_text = "".join(_clean_cell(cell) for cell in row[1:4])
    return "活期" not in account_type_text and ("定期" in account_type_text or "通知存款" in account_type_text)


def _row_is_foreign_currency(row: list) -> bool:
    currency_text = "".join(_clean_cell(cell) for cell in row[4:6])
    return any(name in currency_text for name in ("美元", "港币", "欧元", "日元", "英镑"))


def extract_icbc(pdf_path: str) -> list[Transaction]:
    rows: list[tuple[int, int, list, datetime]] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if not row or not _row_is_transaction(row):
                        continue
                    if _row_is_non_current_account(row):
                        continue
                    if _row_is_foreign_currency(row):
                        continue

                    tx_time = parse_icbc_time(row[DATE_COL])
                    if tx_time is not None:
                        rows.append((page_index, row_index, row, tx_time))

    resolved = resolve_amount_balance_sequence([(row[AMOUNT_COL], row[BALANCE_COL]) for _, _, row, _ in rows])
    transactions: list[Transaction] = []

    for (page_index, row_index, row, tx_time), (amount, balance, issues) in zip(rows, resolved):
        if amount is None:
            amount = Decimal("0.00")

        income = amount if amount > 0 else Decimal("0.00")
        expense = -amount if amount < 0 else Decimal("0.00")
        status = "ok" if not issues else "review"

        tx = Transaction(
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
            status=status,
            issues=issues,
        )
        transactions.append(tx)

    return transactions
