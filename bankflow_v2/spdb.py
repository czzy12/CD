from datetime import datetime
from decimal import Decimal
import re

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList
from .number_parser import choose_amount_and_balance, money_to_decimal


SPDB_NAME = "上海浦东发展银行"
SPDB_CORP_NAME = "上海浦东发展银行对公"
PERSONAL_HEADERS = ["交易日期", "交易时间", "交易账号", "交易名称", "交易金额", "账户余额", "对手姓名", "对手账号", "交易摘要"]
CORP_HEADERS = ["交易日期", "交易流水号", "借方", "贷方", "账户余额", "对手机构", "对手名称", "摘要代码", "备注"]
PERSONAL_METADATA_RE = re.compile(
    r"户名:\s*(?P<name>.*?)\s+账号:\s*(?P<account>\S+)\s+起止日期:\s*(?P<start>\d{8})-(?P<end>\d{8})"
)


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_personal_time(raw_date: str | None, raw_time: str | None) -> datetime | None:
    date_text = re.sub(r"\D", "", _clean_cell(raw_date))
    time_text = re.sub(r"\D", "", _clean_cell(raw_time)) or "000000"
    if len(date_text) != 8 or len(time_text) != 6:
        return None
    try:
        return datetime(
            int(date_text[:4]),
            int(date_text[4:6]),
            int(date_text[6:8]),
            int(time_text[:2]),
            int(time_text[2:4]),
            int(time_text[4:6]),
        )
    except ValueError:
        return None


def _parse_corp_time(raw_date: str | None) -> datetime | None:
    text = _clean_cell(raw_date)
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def extract_spdb(pdf_path: str) -> TransactionList:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None
    metadata = StatementMetadata()

    with pdfplumber.open(pdf_path) as pdf:
        if pdf.pages:
            match = PERSONAL_METADATA_RE.search(pdf.pages[0].extract_text() or "")
            if match:
                metadata.account_name = match.group("name").strip()
                metadata.account_number = match.group("account")
                metadata.statement_period_start = datetime.strptime(match.group("start"), "%Y%m%d").date()
                metadata.statement_period_end = datetime.strptime(match.group("end"), "%Y%m%d").date()
                metadata.field_sources = {
                    "account_name": "document_header:户名",
                    "account_number": "document_header:账号",
                    "statement_period_start": "document_header:起止日期",
                    "statement_period_end": "document_header:起止日期",
                }
                metadata.field_confidence = {field_name: 1.0 for field_name in metadata.field_sources}
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if not row or len(row) < 6:
                        continue
                    tx_time = _parse_personal_time(row[0], row[1])
                    if tx_time is None:
                        continue

                    amount, balance, issues = choose_amount_and_balance(row[4], row[5], previous_balance)
                    if amount is None:
                        amount = Decimal("0.00")

                    income = amount if amount > 0 else Decimal("0.00")
                    expense = -amount if amount < 0 else Decimal("0.00")
                    raw_fields = [_clean_cell(cell) for cell in row]
                    transaction = Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=SPDB_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=f"{_clean_cell(row[0])} {_clean_cell(row[1])}".strip(),
                            raw_amount=_clean_cell(row[4]),
                            raw_balance=_clean_cell(row[5]),
                            raw_text=" | ".join(raw_fields),
                            raw_fields=raw_fields,
                            raw_headers=PERSONAL_HEADERS,
                            status="ok" if not issues else "review",
                            issues=issues,
                            counterparty_name=raw_fields[6] if len(raw_fields) > 6 else "",
                            field_sources=(
                                {"counterparty_name": "raw_headers[6]:对手姓名"}
                                if len(raw_fields) > 6 and raw_fields[6]
                                else {}
                            ),
                            field_confidence=(
                                {"counterparty_name": 1.0}
                                if len(raw_fields) > 6 and raw_fields[6]
                                else {}
                            ),
                    )
                    transaction.counterparty_account = ""
                    transaction.summary = ""
                    for field_name in ("counterparty_account", "summary"):
                        transaction.field_sources.pop(field_name, None)
                        transaction.field_confidence.pop(field_name, None)
                    transactions.append(transaction)
                    if balance is not None:
                        previous_balance = balance

    return TransactionList(transactions, metadata)


def extract_spdb_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table, start=1):
                    if not row or len(row) < 5:
                        continue
                    tx_time = _parse_corp_time(row[0])
                    if tx_time is None:
                        continue

                    debit = money_to_decimal(_clean_cell(row[2]))
                    credit = money_to_decimal(_clean_cell(row[3]))
                    balance = money_to_decimal(_clean_cell(row[4]))
                    issues: list[str] = []

                    if debit is not None and credit is not None:
                        issues.append("借方和贷方同时存在")
                    if debit is None and credit is None:
                        issues.append("借方/贷方金额无法解析")
                    if balance is None:
                        issues.append("余额无法解析")

                    income = credit or Decimal("0.00")
                    expense = debit or Decimal("0.00")
                    raw_amount = _clean_cell(row[3] if credit is not None else row[2])

                    raw_fields = [_clean_cell(cell) for cell in row]
                    abstract_code = raw_fields[7] if len(raw_fields) > 7 else ""
                    transaction_reference = raw_fields[1] if len(raw_fields) > 1 else ""
                    source_fields = {}
                    field_sources = {}
                    if abstract_code:
                        source_fields["abstract_code"] = abstract_code
                        field_sources["abstract_code"] = "raw_headers[7]:摘要代码"
                    if transaction_reference:
                        source_fields["transaction_reference"] = transaction_reference
                        field_sources["transaction_reference"] = "raw_headers[1]:交易流水号"
                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=SPDB_CORP_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=_clean_cell(row[0]),
                            raw_amount=raw_amount,
                            raw_balance=_clean_cell(row[4]),
                            raw_text=" | ".join(raw_fields),
                            raw_fields=raw_fields,
                            raw_headers=CORP_HEADERS,
                            status="ok" if not issues else "review",
                            issues=issues,
                            counterparty_bank=raw_fields[5] if len(raw_fields) > 5 else "",
                            transaction_type=abstract_code,
                            source_fields=source_fields,
                            field_sources={
                                **field_sources,
                                **(
                                    {"counterparty_bank": "raw_headers[5]:对手机构"}
                                    if len(raw_fields) > 5 and raw_fields[5]
                                    else {}
                                ),
                                **({"transaction_type": "raw_headers[7]:摘要代码"} if abstract_code else {}),
                            },
                            field_confidence={
                                field_name: 1.0
                                for field_name in (
                                    list(field_sources)
                                    + (["counterparty_bank"] if len(raw_fields) > 5 and raw_fields[5] else [])
                                    + (["transaction_type"] if abstract_code else [])
                                )
                            },
                        )
                    )

    return transactions
