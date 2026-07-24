import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "邢台银行"
ZERO = Decimal("0.00")
ROW_RE = re.compile(
    r"^(?P<date>20\d{2}-\d{2}-\d{2})\s+(?P<direction>收入|支出)\s+"
    r"(?P<amount>\d[\d,]*\.\d{2})\s+(?P<balance>\d[\d,]*\.\d{2})\s+(?P<rest>.*)$"
)


def _parse_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return None


def _extract_xingtai_legacy(pdf_path: str) -> list[Transaction]:
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

                is_income = match.group("direction") == "收入"
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if is_income else ZERO,
                        expense=ZERO if is_income else amount,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=line_no,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=[line],
                        raw_headers=["交易时间", "收入/支出", "交易金额（元）", "余额（元）"],
                    )
                )

    return transactions


def extract_xingtai(pdf_path: str) -> list[Transaction]:
    headers = ["交易时间", "收入/支出", "交易金额（元）", "余额（元）", "对方账号", "对方账户名称", "交易户名", "交易账号", "交易渠道", "交易摘要"]
    excluded_headers = {"对方账号", "交易账号", "交易渠道"}
    kept_headers = [header for header in headers if header not in excluded_headers]
    transactions: list[Transaction] = []
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row_index, row in enumerate(table):
                    normalized = [str(cell or "").replace("\n", "").strip() for cell in row]
                    if normalized != headers:
                        continue
                    for values in table[row_index + 1:]:
                        fields = [str(value or "").replace("\n", " ").strip() for value in values]
                        if len(fields) < len(headers):
                            continue
                        tx_time = datetime.strptime(fields[0].replace(" ", ""), "%Y-%m-%d%H:%M:%S") if " " in fields[0] else _parse_date(fields[0])
                        amount = money_to_decimal(fields[2])
                        balance = money_to_decimal(fields[3])
                        if tx_time is None or amount is None or balance is None or fields[1] not in {"收入", "支出"}:
                            continue
                        sequence += 1
                        transactions.append(
                            Transaction(
                                transaction_time=tx_time,
                                income=amount if fields[1] == "收入" else ZERO,
                                expense=amount if fields[1] == "支出" else ZERO,
                                balance=balance,
                                bank=BANK_NAME,
                                page_no=page_no,
                                row_no=sequence,
                                raw_time=fields[0],
                                raw_amount=fields[2],
                                raw_balance=fields[3],
                                raw_text=" | ".join(fields[index] for index, header in enumerate(headers) if header not in excluded_headers),
                                raw_fields=[fields[index] for index, header in enumerate(headers) if header not in excluded_headers],
                                raw_headers=kept_headers,
                                source_fields={"transaction_account_name_raw": fields[6]} if fields[6] else {},
                                field_sources={"transaction_account_name_raw": "raw_headers[6]:交易户名"} if fields[6] else {},
                                field_confidence={"transaction_account_name_raw": 1.0} if fields[6] else {},
                            )
                        )
                    break
    return transactions
