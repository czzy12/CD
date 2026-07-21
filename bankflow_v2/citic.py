import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList
from .number_parser import money_to_decimal


BANK_NAME = "中信银行个人"
CORP_BANK_NAME = "中信银行对公"
ROW_RE = re.compile(
    r"^(?P<date>20\d{6})\s+RMB\s+(?P<amount>[\d,]+\.\d{2})\s+RMB\s+(?P<balance>[\d,]+\.\d{2})\s+(?P<details>.*)$"
)
CENT = Decimal("0.01")
CORP_HEADER_MARKERS = ("交易日期", "柜员交易号", "借方发生额", "贷方发生额", "余额")
PERSONAL_HEADERS = ["交易日期", "收入金额", "支出金额", "账户余额", "交易摘要", "对方账号", "对方户名"]
ACCOUNT_NAME_RE = re.compile(r"户名：\s*(?P<value>.*?)\s+证件类型：")
ACCOUNT_PERIOD_RE = re.compile(
    r"账号：\s*(?P<account>\S+)\s+时间段：\s*(?P<start>\d{8})-(?P<end>\d{8})\s+开立日期：\s*(?P<opened>\d{4}-?\d{2}-?\d{2})"
)
CURRENCY_RE = re.compile(r"币种：\s*(?P<value>\S+)")


def _parse_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y%m%d")
    except ValueError:
        return None


def _parse_corp_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _is_corp_table(table: list[list]) -> bool:
    if not table:
        return False
    header = "".join(_clean_cell(cell) for cell in table[0])
    return all(marker in header for marker in CORP_HEADER_MARKERS)


def _resolve_direction(amount: Decimal, balance: Decimal, previous_balance: Decimal | None) -> tuple[Decimal, Decimal, list[str]]:
    if previous_balance is None:
        return amount, Decimal("0.00"), []

    income_expected = (previous_balance + amount).quantize(CENT)
    if income_expected == balance:
        return amount, Decimal("0.00"), []

    expense_expected = (previous_balance - amount).quantize(CENT)
    if expense_expected == balance:
        return Decimal("0.00"), amount, []

    return amount, Decimal("0.00"), [f"余额不连续: 上笔余额 {previous_balance} +/- 金额 {amount}, 当前余额 {balance}"]


def _split_personal_details(raw: str) -> tuple[str, str, str]:
    parts = raw.rsplit(maxsplit=2)
    if len(parts) != 3:
        return "", "", ""
    return parts[0].strip(), parts[1].strip(), parts[2].strip()


def _personal_metadata(text: str) -> StatementMetadata:
    metadata = StatementMetadata()
    name_match = ACCOUNT_NAME_RE.search(text)
    if name_match:
        metadata.account_name = name_match.group("value").strip()
        metadata.field_sources["account_name"] = "document_header:户名"
        metadata.field_confidence["account_name"] = 1.0

    period_match = ACCOUNT_PERIOD_RE.search(text)
    if period_match:
        metadata.account_number = period_match.group("account")
        metadata.statement_period_start = datetime.strptime(period_match.group("start"), "%Y%m%d").date()
        metadata.statement_period_end = datetime.strptime(period_match.group("end"), "%Y%m%d").date()
        metadata.raw_fields["开户日期"] = period_match.group("opened")
        metadata.field_sources.update({
            "account_number": "document_header:账号",
            "statement_period_start": "document_header:时间段",
            "statement_period_end": "document_header:时间段",
            "开户日期": "document_header:开立日期",
        })
        metadata.field_confidence.update({
            "account_number": 1.0,
            "statement_period_start": 1.0,
            "statement_period_end": 1.0,
            "开户日期": 1.0,
        })

    currency_match = CURRENCY_RE.search(text)
    if currency_match:
        metadata.raw_fields["币种"] = currency_match.group("value")
        metadata.field_sources["币种"] = "document_header:币种"
        metadata.field_confidence["币种"] = 1.0
    return metadata


def extract_citic(pdf_path: str) -> TransactionList:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None
    metadata = StatementMetadata()

    with pdfplumber.open(pdf_path) as pdf:
        header_text = "\n".join((page.extract_text() or "") for page in pdf.pages[:1])
        metadata = _personal_metadata(header_text)
        for page_index, page in enumerate(pdf.pages, start=1):
            lines = [line.strip() for line in (page.extract_text() or "").splitlines() if line.strip()]
            for line_no, line in enumerate(lines, start=1):
                match = ROW_RE.match(line)
                if not match:
                    continue

                tx_time = _parse_date(match.group("date"))
                amount = money_to_decimal(match.group("amount"))
                balance = money_to_decimal(match.group("balance"))
                if tx_time is None or amount is None or balance is None:
                    continue

                income, expense, issues = _resolve_direction(amount, balance, previous_balance)
                summary, counterparty_account, counterparty_name = _split_personal_details(match.group("details"))
                raw_fields = [
                    match.group("date"),
                    f"RMB {match.group('amount')}" if income else "",
                    f"RMB {match.group('amount')}" if expense else "",
                    f"RMB {match.group('balance')}",
                    summary,
                    counterparty_account,
                    counterparty_name,
                ]
                source_fields = {"currency_raw": "RMB"}
                if not summary and match.group("details").strip():
                    source_fields["transaction_details_raw"] = match.group("details").strip()
                field_sources = {"currency_raw": "raw_headers[1/2]:收入金额/支出金额"}
                if summary:
                    field_sources["summary"] = "raw_headers[4]:交易摘要"
                if counterparty_account:
                    field_sources["counterparty_account"] = "raw_headers[5]:对方账号"
                if counterparty_name:
                    field_sources["counterparty_name"] = "raw_headers[6]:对方户名"
                if "transaction_details_raw" in source_fields:
                    field_sources["transaction_details_raw"] = "raw_text:交易明细尾部"
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_index,
                        row_no=line_no,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=raw_fields,
                        raw_headers=PERSONAL_HEADERS,
                        status="ok" if not issues else "review",
                        issues=issues,
                        counterparty_account=counterparty_account,
                        counterparty_name=counterparty_name,
                        summary=summary,
                        source_fields=source_fields,
                        field_sources=field_sources,
                        field_confidence={field_name: 1.0 for field_name in field_sources},
                    )
                )
                previous_balance = balance

    return TransactionList(transactions, metadata)


def extract_citic_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not _is_corp_table(table):
                    continue

                for row_index, row in enumerate(table[1:], start=1):
                    if len(row) < 9:
                        continue

                    raw_date = _clean_cell(row[0])
                    tx_time = _parse_corp_date(raw_date)
                    if tx_time is None:
                        continue

                    debit = money_to_decimal(_clean_cell(row[6])) or Decimal("0.00")
                    credit = money_to_decimal(_clean_cell(row[7])) or Decimal("0.00")
                    balance = money_to_decimal(_clean_cell(row[8]))
                    issues = []
                    if debit > 0 and credit > 0:
                        issues.append("借方和贷方同时有金额")
                    if debit == 0 and credit == 0:
                        issues.append("借方和贷方均为零")
                    if balance is None:
                        issues.append("余额无法解析")

                    tx = Transaction(
                        transaction_time=tx_time,
                        income=credit,
                        expense=debit,
                        balance=balance,
                        bank=CORP_BANK_NAME,
                        page_no=page_index,
                        row_no=row_index,
                        raw_time=raw_date,
                        raw_amount=f"{_clean_cell(row[6])}|{_clean_cell(row[7])}",
                        raw_balance=_clean_cell(row[8]),
                        raw_text=" | ".join(_clean_cell(cell).replace("\n", " ") for cell in row),
                        raw_fields=[_clean_cell(cell) for cell in row],
                        raw_headers=[_clean_cell(cell) for cell in table[0]],
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                    tx.preserve_signed_columns = True
                    transactions.append(tx)

    return transactions
