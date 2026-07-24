import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .coordinate_rows import extract_coordinate_rows
from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "盛京银行"
ZERO = Decimal("0.00")
ROW_RE = re.compile(
    r"^(?P<date>20\d{6})\s+人民币\s+(?P<amount>[+-]?\d[\d,]*\.\d{2})\s+"
    r"(?P<balance>\d[\d,]*\.\d{2})\s+(?P<summary>.*)$"
)


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None


def _extract_shengjing_legacy(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = ROW_RE.match(line)
                if not match:
                    continue
                tx_time = _parse_date(match.group("date"))
                amount = money_to_decimal(match.group("amount"))
                balance = money_to_decimal(match.group("balance"))
                if tx_time is None or amount is None or balance is None:
                    continue

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if amount >= ZERO else ZERO,
                        expense=-amount if amount < ZERO else ZERO,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=line_no,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=[line],
                    )
                )

    return transactions


def extract_shengjing(pdf_path: str) -> list[Transaction]:
    headers = ["记账日期", "货币", "交易金额", "账户余额", "交易摘要", "对手信息", "附言"]
    kept_headers = [header for header in headers if header != "货币"]
    transactions: list[Transaction] = []
    sequence = 0
    column_positions: dict[str, float] = {}

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for row in extract_coordinate_rows(page, headers, lambda value: _parse_date(value) is not None, column_positions):
                tx_time = _parse_date(row["记账日期"])
                amount = money_to_decimal(row["交易金额"])
                balance = money_to_decimal(row["账户余额"])
                if tx_time is None or amount is None or balance is None:
                    continue
                sequence += 1
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if amount >= ZERO else ZERO,
                        expense=-amount if amount < ZERO else ZERO,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=sequence,
                        raw_time=row["记账日期"],
                        raw_amount=row["交易金额"],
                        raw_balance=row["账户余额"],
                        raw_text=" | ".join(row[header] for header in kept_headers if row[header]),
                        raw_fields=[row[header] for header in kept_headers],
                        raw_headers=kept_headers,
                        source_fields={"counterparty_info_raw": row["对手信息"]} if row["对手信息"] else {},
                        field_sources={"counterparty_info_raw": "raw_headers[4]:对手信息"} if row["对手信息"] else {},
                        field_confidence={"counterparty_info_raw": 1.0} if row["对手信息"] else {},
                    )
                )
    return transactions
