from datetime import datetime
from decimal import Decimal
import re

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国银行对公"
OPENING_MARKER = "承前页余额"
DATE_RE = re.compile(r"\d{6}|\d{8}")
ONLINE_HEADER_MARKER = "交易类型业务类型"
ONLINE_TRANSACTION_RE = re.compile(
    r"(?P<date>20\d{6})(?P<time>\d{2}:\d{2}:\d{2})\s+CNY\s+"
    r"(?P<amount>-?[\d,]+\.\d{2})(?P<balance>[\d,]+\.\d{2})\s+20\d{6}"
)


def _parse_money(raw: str | None) -> Decimal:
    return money_to_decimal((raw or "").strip()) or Decimal("0.00")


def _parse_date(raw: str | None) -> datetime | None:
    match = DATE_RE.search(raw or "")
    if not match:
        return None

    text = match.group()
    if len(text) == 6:
        text = f"20{text}"

    try:
        return datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None


def _opening_balance(text: str) -> Decimal | None:
    index = text.find(OPENING_MARKER)
    if index < 0:
        return None

    match = re.search(r"[\d,]+\.\d{2}", text[index : index + 80])
    if not match:
        return None
    return money_to_decimal(match.group())


def _split_pipe_row(line: str) -> list[str]:
    return [part.strip() for part in line.split("|")]


def _parse_transaction_line(line: str, page_no: int, row_no: int) -> Transaction | None:
    parts = _split_pipe_row(line)
    if len(parts) < 11:
        return None

    serial = parts[1]
    if not serial.isdigit():
        return None

    tx_time = _parse_date(parts[2])
    if tx_time is None:
        return None

    debit_raw = parts[7] if len(parts) > 7 else ""
    credit_raw = parts[8] if len(parts) > 8 else ""
    balance_raw = parts[9] if len(parts) > 9 else ""
    debit = _parse_money(debit_raw)
    credit = _parse_money(credit_raw)
    balance = money_to_decimal(balance_raw)

    issues: list[str] = []
    if debit > 0 and credit > 0:
        issues.append("借方和贷方同时有金额")
    if debit == 0 and credit == 0:
        issues.append("借方和贷方均为零")
    if balance is None:
        issues.append("余额无法解析")

    raw_text_parts = []
    for index in (4, 6, 10, 11):
        if index < len(parts) and parts[index]:
            raw_text_parts.append(parts[index])

    tx = Transaction(
        transaction_time=tx_time,
        income=credit,
        expense=debit,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=parts[2],
        raw_amount=f"{debit_raw}|{credit_raw}",
        raw_balance=balance_raw,
        raw_text=" | ".join(raw_text_parts),
        raw_fields=parts[1:-1] if parts and parts[-1] == "" else parts[1:],
        raw_headers=[
            "序号",
            "记账日",
            "起息日",
            "交易类型",
            "凭证",
            "凭证号码/业务编号/用途/摘要",
            "借方发生额",
            "贷方发生额",
            "余额",
            "机构/柜员/流水",
            "备注",
        ],
        status="ok" if not issues else "review",
        issues=issues,
    )
    tx.merge_key = "|".join([parts[1], parts[2], debit_raw, credit_raw, balance_raw, str(page_no), str(row_no)])
    return tx


def _parse_online_transaction(
    match: re.Match[str],
    raw_lines: list[str],
    page_no: int,
    row_no: int,
) -> Transaction | None:
    try:
        tx_time = datetime.strptime(
            f"{match.group('date')} {match.group('time')}",
            "%Y%m%d %H:%M:%S",
        )
    except ValueError:
        return None

    amount_raw = match.group("amount")
    balance_raw = match.group("balance")
    amount = _parse_money(amount_raw)
    balance = money_to_decimal(balance_raw)
    issues: list[str] = []
    if balance is None:
        issues.append("余额无法解析")

    tx = Transaction(
        transaction_time=tx_time,
        income=amount if amount > 0 else Decimal("0.00"),
        expense=-amount if amount < 0 else Decimal("0.00"),
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=f"{match.group('date')} {match.group('time')}",
        raw_amount=amount_raw,
        raw_balance=balance_raw,
        raw_text=" ".join(raw_lines),
        raw_fields=raw_lines,
        raw_headers=["原始文本行"],
        status="ok" if not issues else "review",
        issues=issues,
    )
    tx.merge_key = "|".join(
        [
            tx.raw_time,
            tx.raw_amount,
            tx.raw_balance,
            str(page_no),
            str(row_no),
        ]
    )
    return tx


def _restore_online_duplicate_order(transactions: list[Transaction]) -> None:
    same_time: dict[datetime, list[Transaction]] = {}
    for tx in transactions:
        same_time.setdefault(tx.transaction_time, []).append(tx)

    for items in same_time.values():
        if len(items) < 2:
            continue
        for index, tx in enumerate(items):
            tx.transaction_time = tx.transaction_time.replace(microsecond=index)


def _extract_online_statement(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            pending_lines: list[str] = []
            reading_rows = page_no > 1
            for line in (page.extract_text() or "").splitlines():
                if ONLINE_HEADER_MARKER in line:
                    reading_rows = True
                    pending_lines.clear()
                    continue
                if not reading_rows:
                    continue

                pending_lines.append(line.strip())
                match = ONLINE_TRANSACTION_RE.search(line)
                if match is None:
                    continue

                tx = _parse_online_transaction(match, pending_lines, page_no, len(transactions) + 1)
                if tx is not None:
                    transactions.append(tx)
                pending_lines = []

    _restore_online_duplicate_order(transactions)
    return transactions


def extract_boc_corp(pdf_path: str) -> list[Transaction]:
    with pdfplumber.open(pdf_path) as pdf:
        first_page_text = pdf.pages[0].extract_text() if pdf.pages else ""
    if ONLINE_HEADER_MARKER in (first_page_text or ""):
        return _extract_online_statement(pdf_path)

    transactions: list[Transaction] = []
    first_opening: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if first_opening is None:
                first_opening = _opening_balance(text)

            for row_no, line in enumerate(text.splitlines(), start=1):
                if not line.startswith("|"):
                    continue
                tx = _parse_transaction_line(line, page_no, row_no)
                if tx is None:
                    continue
                transactions.append(tx)

    if transactions and first_opening is not None:
        transactions[0].opening_balance = first_opening

    return transactions
