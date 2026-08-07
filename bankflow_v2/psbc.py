from datetime import datetime
from decimal import Decimal
import re

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList
from .number_parser import money_to_decimal


BANK_NAME = "中国邮政储蓄银行"
TIME_COL = 0
AMOUNT_COL = 5
BALANCE_COL = 6
CORP_HEADERS = [
    "序号",
    "交易时间",
    "记账日期",
    "支出金额",
    "收入金额",
    "余额",
    "对方账号",
    "对方户名",
    "对方行名",
    "用途",
    "附言",
    "摘要",
    "交易流水号",
    "全局路由号",
]
CORP_DATE_COL = 2
CORP_EXPENSE_COL = 3
CORP_INCOME_COL = 4
CORP_BALANCE_COL = 5


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", " ").strip()


def _parse_time(raw: str | None) -> datetime | None:
    text = _clean_cell(raw)
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _parse_corp_time(raw_time: str | None, raw_date: str | None) -> datetime | None:
    date_text = _clean_cell(raw_date)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
        return None

    time_text = _clean_cell(raw_time)
    match = re.search(r"\d{4}-\d{2}-\d{2}\s*(\d?)\s*([0-9]:\d{2}:\d{2})", time_text)
    if match:
        hour_prefix = match.group(1)
        time_part = match.group(2)
        if hour_prefix:
            time_part = f"{hour_prefix}{time_part}"
        if len(time_part.split(":", 1)[0]) == 1:
            time_part = f"0{time_part}"
        try:
            return datetime.strptime(f"{date_text} {time_part}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass

    return datetime.strptime(date_text, "%Y-%m-%d")


def _is_corp_header(row: list) -> bool:
    joined = "".join(_clean_cell(cell) for cell in row)
    return "交易时间" in joined and "支出金额" in joined and "收入金额" in joined and "全局路由号" in joined


def _is_corp_row(row: list) -> bool:
    return len(row) > CORP_BALANCE_COL and _clean_cell(row[0]).isdigit()


def _parse_corp_row(row: list, page_no: int, row_no: int) -> Transaction | None:
    if not _is_corp_row(row):
        return None

    tx_time = _parse_corp_time(row[1], row[CORP_DATE_COL])
    if tx_time is None:
        return None

    expense_raw = _clean_cell(row[CORP_EXPENSE_COL])
    income_raw = _clean_cell(row[CORP_INCOME_COL])
    balance_raw = _clean_cell(row[CORP_BALANCE_COL])
    expense = money_to_decimal(expense_raw) or Decimal("0.00")
    income = money_to_decimal(income_raw) or Decimal("0.00")
    balance = money_to_decimal(balance_raw)

    issues = []
    if income > 0 and expense > 0:
        issues.append("收入和支出同时有金额")
    if income == 0 and expense == 0:
        issues.append("收入和支出均为零")
    if balance is None:
        issues.append("余额无法解析")

    raw_text_parts = []
    for index in (7, 8, 9, 10, 11):
        if index < len(row):
            value = _clean_cell(row[index])
            if value:
                raw_text_parts.append(value)

    tx = Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_clean_cell(row[1]),
        raw_amount=f"{expense_raw}|{income_raw}",
        raw_balance=balance_raw,
        raw_text=" | ".join(raw_text_parts),
        raw_fields=[_clean_cell(cell) for cell in row],
        raw_headers=CORP_HEADERS,
        source_fields={
            field_name: _clean_cell(row[index])
            for field_name, index in (("posting_date", 2), ("transaction_reference", 12), ("global_routing_number", 13))
            if index < len(row) and _clean_cell(row[index])
        },
        field_sources={
            field_name: f"raw_headers[{index}]:{CORP_HEADERS[index]}"
            for field_name, index in (("posting_date", 2), ("transaction_reference", 12), ("global_routing_number", 13))
            if index < len(row) and _clean_cell(row[index])
        },
        field_confidence={
            field_name: 1.0
            for field_name, index in (("posting_date", 2), ("transaction_reference", 12), ("global_routing_number", 13))
            if index < len(row) and _clean_cell(row[index])
        },
        status="ok" if not issues else "review",
        issues=issues,
    )
    tx.merge_key = "|".join([_clean_cell(row[0]), tx.raw_time, expense_raw, income_raw, balance_raw, str(page_no), str(row_no)])
    return tx


def extract_psbc(pdf_path: str) -> TransactionList:
    transactions: list[Transaction] = []
    diagnostics = {
        "source_row_count": 0,
        "parsed_transaction_count": 0,
        "skipped_row_count": 0,
        "unparsed_row_count": 0,
        "ignored_non_transaction_row_count": 0,
        "review_row_count": 0,
        "unsupported_row_count": 0,
    }
    metadata = StatementMetadata()

    with pdfplumber.open(pdf_path) as pdf:
        if pdf.pages:
            first_text = pdf.pages[0].extract_text() or ""
            owner_match = re.search(r"户名[:：]\s*([^\s，,]+)", first_text)
            if owner_match:
                metadata.account_name = owner_match.group(1).strip()
                metadata.field_sources["account_name"] = "document_header:户名"
                metadata.field_confidence["account_name"] = 1.0
            account_match = re.search(r"账号[:：]\s*([0-9A-Za-z*]+)", first_text)
            if account_match:
                account_raw = account_match.group(1).strip()
                if "*" not in account_raw:
                    metadata.account_number = account_raw
                    metadata.field_sources["account_number"] = "document_header:账号"
                    metadata.field_confidence["account_number"] = 1.0
                else:
                    metadata.raw_fields["masked_account_number"] = account_raw
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                table_has_corp_header = any(_is_corp_header(row) for row in table)
                header_row: list[str] = []
                if not table_has_corp_header:
                    for row in table[:5]:
                        header_text = "|".join(_clean_cell(cell) for cell in row)
                        if "交易时间" in header_text and ("余额" in header_text or "金额" in header_text):
                            header_row = [_clean_cell(cell) for cell in row]
                            break
                for row_index, row in enumerate(table, start=1):
                    if table_has_corp_header or _is_corp_row(row):
                        diagnostics["source_row_count"] += 1
                        tx = _parse_corp_row(row, page_index, row_index)
                        if tx is not None:
                            transactions.append(tx)
                            diagnostics["parsed_transaction_count"] += 1
                            if tx.status == "review":
                                diagnostics["review_row_count"] += 1
                        else:
                            diagnostics["skipped_row_count"] += 1
                            diagnostics["unparsed_row_count"] += 1
                        continue

                    if len(row) <= BALANCE_COL:
                        diagnostics["ignored_non_transaction_row_count"] += 1
                        continue
                    if header_row and [_clean_cell(cell) for cell in row] == header_row:
                        diagnostics["ignored_non_transaction_row_count"] += 1
                        continue
                    diagnostics["source_row_count"] += 1
                    tx_time = _parse_time(row[TIME_COL])
                    if tx_time is None:
                        diagnostics["skipped_row_count"] += 1
                        diagnostics["unparsed_row_count"] += 1
                        continue

                    amount = money_to_decimal(_clean_cell(row[AMOUNT_COL]))
                    balance = money_to_decimal(_clean_cell(row[BALANCE_COL]))
                    issues = []
                    if amount is None:
                        issues.append("金额无法解析")
                        amount = Decimal("0.00")
                    if balance is None:
                        issues.append("余额无法解析")

                    raw_fields = [_clean_cell(cell) for cell in row]
                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=amount if amount > 0 else Decimal("0.00"),
                            expense=-amount if amount < 0 else Decimal("0.00"),
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=_clean_cell(row[TIME_COL]),
                            raw_amount=_clean_cell(row[AMOUNT_COL]),
                            raw_balance=_clean_cell(row[BALANCE_COL]),
                            raw_text=" | ".join(raw_fields),
                            raw_fields=raw_fields,
                            raw_headers=header_row,
                            status="ok" if not issues else "review",
                            issues=issues,
                        )
                    )
                    diagnostics["parsed_transaction_count"] += 1
                    if transactions[-1].status == "review":
                        diagnostics["review_row_count"] += 1

    diagnostics["parsed_transaction_count"] = len(transactions)
    return TransactionList(transactions, metadata=metadata, diagnostics=diagnostics)
