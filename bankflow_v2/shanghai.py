import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .coordinate_rows import extract_coordinate_rows
from .models import Transaction
from .number_parser import money_to_decimal


PERSONAL_BANK_NAME = "上海银行个人"
CORP_BANK_NAME = "上海银行对公"
ZERO = Decimal("0.00")


PERSONAL_LINE_RE = re.compile(
    r"^(?P<date>\d{8})\s+"
    r"(?P<description>.+?)\s+"
    r"CNY\s+"
    r"(?P<amount>[+-]?\d[\d,]*\.\d{2})\s+"
    r"(?P<balance>[+-]?\d[\d,]*\.\d{2})"
    r"(?P<rest>.*)$"
)


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_datetime(raw: str | None) -> datetime | None:
    text = _clean_cell(raw).replace("/", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d%H:%M:%S", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _money(raw: str | None) -> Decimal | None:
    text = _clean_cell(raw)
    if not text or text == "--":
        return None
    return money_to_decimal(text)


def _header_index(row: list) -> dict[str, int]:
    return {_clean_cell(cell): idx for idx, cell in enumerate(row or [])}


def _cell(row: list, index: dict[str, int], name: str) -> str:
    idx = index.get(name)
    if idx is None or idx >= len(row):
        return ""
    return _clean_cell(row[idx])


def _looks_like_account_statement_header(row: list) -> bool:
    text = "".join(_clean_cell(cell) for cell in row or [])
    return (
        "序号" in text
        and "交易时间" in text
        and "借方金额" in text
        and "贷方金额" in text
        and "余额" in text
    )


def _looks_like_account_query_header(row: list) -> bool:
    text = "".join(_clean_cell(cell) for cell in row or [])
    return (
        "交易流水号" in text
        and "交易时间" in text
        and "交易方向" in text
        and "借方发生额" in text
        and "贷方发生额" in text
        and "余额" in text
    )


def _parse_debit_credit_row(
    row: list,
    index: dict[str, int],
    page_no: int,
    row_no: int,
    *,
    debit_name: str,
    credit_name: str,
    time_name: str,
    sequence_name: str,
    reverse_same_second: bool = False,
) -> Transaction | None:
    sequence = _cell(row, index, sequence_name)
    if sequence_name == "序号" and not sequence.isdigit():
        return None
    if sequence_name == "交易流水号" and not sequence:
        return None

    tx_time = _parse_datetime(_cell(row, index, time_name))
    if tx_time is None:
        return None
    if reverse_same_second:
        tx_time = tx_time.replace(microsecond=max(0, 999999 - row_no))

    debit = _money(_cell(row, index, debit_name))
    credit = _money(_cell(row, index, credit_name))
    balance = _money(_cell(row, index, "余额"))
    issues: list[str] = []

    if debit is None:
        debit = ZERO
    if credit is None:
        credit = ZERO
    if debit and credit:
        issues.append("借贷金额同时存在")
    if not debit and not credit:
        issues.append("借贷金额均为空")
    if balance is None:
        issues.append("余额无法解析")

    raw_amount = _cell(row, index, credit_name) if credit else _cell(row, index, debit_name)
    raw_fields = [_clean_cell(cell) for cell in row]
    source_fields = {
        field_name: _cell(row, index, header)
        for field_name, header in (
            ("posting_date", "记账日期"),
            ("transaction_reference", "交易流水号"),
            ("transaction_voucher_id", "交易凭证号"),
        )
        if _cell(row, index, header)
    }
    source_headers = {
        "posting_date": "记账日期",
        "transaction_reference": "交易流水号",
        "transaction_voucher_id": "交易凭证号",
    }
    return Transaction(
        transaction_time=tx_time,
        income=credit,
        expense=debit,
        balance=balance,
        bank=CORP_BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_cell(row, index, time_name),
        raw_amount=raw_amount,
        raw_balance=_cell(row, index, "余额"),
        raw_text=" | ".join(raw_fields),
        raw_fields=raw_fields,
        raw_headers=[name for name, _idx in sorted(index.items(), key=lambda item: item[1])],
        source_fields=source_fields,
        field_sources={
            field_name: f"raw_headers[{index[source_headers[field_name]]}]:{source_headers[field_name]}"
            for field_name in source_fields
        },
        field_confidence={field_name: 1.0 for field_name in source_fields},
        status="ok" if not issues else "review",
        issues=issues,
    )


def extract_shanghai_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    print_index = 0
    statement_index: dict[str, int] | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                index: dict[str, int] | None = statement_index
                format_id = "statement" if statement_index is not None else ""
                for row_index, row in enumerate(table, start=1):
                    if not row:
                        continue
                    if _looks_like_account_statement_header(row):
                        index = _header_index(row)
                        statement_index = index
                        format_id = "statement"
                        continue
                    if _looks_like_account_query_header(row):
                        index = _header_index(row)
                        format_id = "query"
                        continue
                    if index is None:
                        continue
                    print_index += 1
                    if format_id == "statement":
                        tx = _parse_debit_credit_row(
                            row,
                            index,
                            page_index,
                            row_index,
                            debit_name="借方金额",
                            credit_name="贷方金额",
                            time_name="交易时间",
                            sequence_name="序号",
                        )
                    else:
                        tx = _parse_debit_credit_row(
                            row,
                            index,
                            page_index,
                            print_index,
                            debit_name="借方发生额",
                            credit_name="贷方发生额",
                            time_name="交易时间",
                            sequence_name="交易流水号",
                            reverse_same_second=True,
                        )
                    if tx is not None:
                        transactions.append(tx)

    return transactions


def extract_shanghai(pdf_path: str) -> list[Transaction]:
    """Parse the confirmed personal layout with its printed column coordinates."""
    headers = ["记账日期", "交易摘要", "币种", "交易金额", "期末金额", "交易网点", "对方户名", "交易渠道"]
    kept_headers = [header for header in headers if header != "交易网点"]
    transactions: list[Transaction] = []
    print_index = 0
    column_positions: dict[str, float] = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for row in extract_coordinate_rows(page, headers, lambda value: _parse_datetime(value) is not None, column_positions):
                tx_time = _parse_datetime(row["记账日期"])
                amount = money_to_decimal(row["交易金额"])
                balance = money_to_decimal(row["期末金额"])
                if tx_time is None or amount is None:
                    continue
                print_index += 1
                issues = ["余额无法解析"] if balance is None else []
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if amount >= 0 else ZERO,
                        expense=-amount if amount < 0 else ZERO,
                        balance=balance,
                        bank=PERSONAL_BANK_NAME,
                        page_no=0,
                        row_no=-print_index,
                        raw_time=row["记账日期"],
                        raw_amount=row["交易金额"],
                        raw_balance=row["期末金额"],
                        raw_text=" | ".join(row[header] for header in kept_headers if row[header]),
                        raw_fields=[row[header] for header in kept_headers],
                        raw_headers=kept_headers,
                        source_fields={"transaction_channel_raw": row["交易渠道"]} if row["交易渠道"] else {},
                        field_sources={"transaction_channel_raw": "raw_headers[6]:交易渠道"} if row["交易渠道"] else {},
                        field_confidence={"transaction_channel_raw": 1.0} if row["交易渠道"] else {},
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )
    return transactions


def _extract_shanghai_legacy(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    print_index = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for line in text.splitlines():
                match = PERSONAL_LINE_RE.match(line.strip())
                if not match:
                    continue

                tx_time = _parse_datetime(match.group("date"))
                amount = money_to_decimal(match.group("amount"))
                balance = money_to_decimal(match.group("balance"))
                if tx_time is None or amount is None:
                    continue

                print_index += 1
                income = amount if amount >= 0 else ZERO
                expense = -amount if amount < 0 else ZERO
                issues: list[str] = []
                if balance is None:
                    issues.append("余额无法解析")

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=PERSONAL_BANK_NAME,
                        page_no=0,
                        row_no=-print_index,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line.strip(),
                        raw_fields=[
                            match.group("date"),
                            match.group("description").strip(),
                            "CNY",
                            match.group("amount"),
                            match.group("balance"),
                            match.group("rest").strip(),
                        ],
                        raw_headers=["记账日期", "交易摘要", "币种", "交易金额", "期末金额", "其余字段"],
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )

    return transactions
