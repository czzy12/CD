import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国民生银行(对公)"
MONEY = r"[\d,]+\.\d{2}"
DATE_LINE_RE = re.compile(
    rf"^(?P<date>\d{{4}}/\d{{2}}/\d{{2}})\s+(?P<prefix>.*?)\s+"
    rf"(?P<debit>{MONEY})\s+(?P<credit>{MONEY})\s+(?P<balance>{MONEY})\s+"
    rf"(?P<rest>.*)$"
)
TIME_RE = re.compile(r"^(?P<time>\d{2}:\d{2}:\d{2})(?:\s+(?P<rest>.*))?$")
RAW_HEADERS = ["交易时间", "摘要", "凭证类型", "凭证号码", "借方发生额", "贷方发生额", "账户余额", "流水号", "对方户名/账号", "对方行名"]
VOUCHER_NUMBER_RE = re.compile(r"\d+")


def _parse_time(raw_date: str, raw_time: str) -> datetime | None:
    try:
        return datetime.strptime(f"{raw_date} {raw_time}", "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


def _split_prefix(raw: str) -> tuple[str, str, str]:
    parts = raw.split()
    if len(parts) >= 3 and parts[-2].endswith("凭证") and VOUCHER_NUMBER_RE.fullmatch(parts[-1]):
        return " ".join(parts[:-2]), parts[-2], parts[-1]
    return raw.strip(), "", ""


def _split_suffix(date_rest: str, time_rest: str) -> tuple[str, str, str]:
    date_parts = date_rest.split()
    time_parts = time_rest.split()
    reference_parts: list[str] = []
    if date_parts and VOUCHER_NUMBER_RE.fullmatch(date_parts[0]):
        reference_parts.append(date_parts.pop(0))
    if time_parts and VOUCHER_NUMBER_RE.fullmatch(time_parts[0]):
        reference_parts.append(time_parts.pop(0))

    counterparty_raw = date_parts.pop(0) if date_parts else ""
    counterparty_bank = " ".join(date_parts + time_parts)
    return "".join(reference_parts), counterparty_raw, counterparty_bank


def extract_cmbc_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            lines = [line.strip() for line in (page.extract_text() or "").splitlines() if line.strip()]
            idx = 0
            while idx < len(lines):
                match = DATE_LINE_RE.match(lines[idx])
                if not match:
                    idx += 1
                    continue

                time_raw = "00:00:00"
                time_line = ""
                time_rest = ""
                if idx + 1 < len(lines):
                    time_match = TIME_RE.match(lines[idx + 1])
                    if time_match:
                        time_raw = time_match.group("time")
                        time_line = lines[idx + 1]
                        time_rest = time_match.group("rest") or ""

                tx_time = _parse_time(match.group("date"), time_raw)
                if tx_time is None:
                    idx += 1
                    continue

                debit = money_to_decimal(match.group("debit")) or Decimal("0.00")
                credit = money_to_decimal(match.group("credit")) or Decimal("0.00")
                balance = money_to_decimal(match.group("balance"))
                issues = []
                if debit > 0 and credit > 0:
                    issues.append("借方和贷方同时有金额")
                if debit == 0 and credit == 0:
                    issues.append("借方和贷方均为零")
                if balance is None:
                    issues.append("余额无法解析")

                summary, voucher_type, voucher_number = _split_prefix(match.group("prefix"))
                transaction_reference, counterparty_raw, counterparty_bank = _split_suffix(
                    match.group("rest"),
                    time_rest,
                )
                counterparty_name = ""
                counterparty_account = ""
                if counterparty_raw.count("/") == 1:
                    counterparty_name, counterparty_account = (part.strip() for part in counterparty_raw.split("/", 1))

                raw_fields = [
                    f"{match.group('date')} {time_raw}",
                    summary,
                    voucher_type,
                    voucher_number,
                    match.group("debit"),
                    match.group("credit"),
                    match.group("balance"),
                    transaction_reference,
                    counterparty_raw,
                    counterparty_bank,
                ]
                source_fields = {
                    field_name: value
                    for field_name, value in (
                        ("voucher_type", voucher_type),
                        ("voucher_number", voucher_number),
                        ("transaction_reference", transaction_reference),
                        ("counterparty_name_account_raw", counterparty_raw),
                    )
                    if value
                }
                source_indices = {
                    "voucher_type": 2,
                    "voucher_number": 3,
                    "transaction_reference": 7,
                    "counterparty_name_account_raw": 8,
                }
                field_sources = {
                    field_name: f"raw_headers[{source_indices[field_name]}]:{RAW_HEADERS[source_indices[field_name]]}"
                    for field_name in source_fields
                }
                if counterparty_name:
                    field_sources["counterparty_name"] = "raw_headers[8]:对方户名/账号#斜杠前户名"
                if counterparty_account:
                    field_sources["counterparty_account"] = "raw_headers[8]:对方户名/账号#斜杠后账号"

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=credit,
                        expense=debit,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_index,
                        row_no=idx + 1,
                        raw_time=f"{match.group('date')} {time_raw}",
                        raw_amount=f"{match.group('debit')}|{match.group('credit')}",
                        raw_balance=match.group("balance"),
                        raw_text=" | ".join(part for part in (lines[idx], time_line) if part),
                        raw_fields=raw_fields,
                        raw_headers=RAW_HEADERS,
                        status="ok" if not issues else "review",
                        issues=issues,
                        counterparty_name=counterparty_name,
                        counterparty_account=counterparty_account,
                        source_fields=source_fields,
                        field_sources=field_sources,
                        field_confidence={field_name: 1.0 for field_name in field_sources},
                    )
                )
                idx += 2 if idx + 1 < len(lines) and TIME_RE.match(lines[idx + 1]) else 1

    return transactions
