import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import choose_amount_and_balance, money_to_decimal


BANK_NAME = "招商银行"
LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s+CNY\s+"
    r"(?P<amount>[+-]?\d[\d,]*\.?\d{0,2})\s+"
    r"(?P<balance>\d[\d,]*\.?\d{0,2})(?:\s+"
    r"(?P<summary>\S+)(?:\s+(?P<counterparty>.*))?)?$"
)
RAW_HEADERS = ["交易日期", "币种", "交易金额", "余额", "交易摘要", "对手信息"]
COUNTERPARTY_ACCOUNT_RE = re.compile(r"[0-9*Xx-]+")


def _parse_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None


def _normalize_money(raw: str) -> str:
    """Keep normal amounts unchanged; add a decimal point only for obvious cents loss."""
    if "." in raw:
        return raw
    sign = ""
    text = raw
    if text.startswith(("+", "-")):
        sign = text[0]
        text = text[1:]
    clean = text.replace(",", "")
    if len(clean) > 2:
        return f"{sign}{clean[:-2]}.{clean[-2:]}"
    return raw


def _split_counterparty(raw: str) -> tuple[str, str]:
    parts = raw.rsplit(maxsplit=1)
    if len(parts) != 2 or not COUNTERPARTY_ACCOUNT_RE.fullmatch(parts[1]) or not any(char.isdigit() for char in parts[1]):
        return "", ""
    return parts[0].strip(), parts[1].strip()


def extract_cmb(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = LINE_RE.match(line)
                if not match:
                    continue

                tx_time = _parse_date(match.group("date"))
                if tx_time is None:
                    continue

                amount_raw = _normalize_money(match.group("amount"))
                balance_raw = _normalize_money(match.group("balance"))
                amount, balance, issues = choose_amount_and_balance(
                    amount_raw,
                    balance_raw,
                    previous_balance,
                )

                if amount is None:
                    amount = Decimal("0.00")
                if balance is None:
                    balance = money_to_decimal(balance_raw)

                summary = match.group("summary") or ""
                counterparty_raw = (match.group("counterparty") or "").strip()
                counterparty_name, counterparty_account = _split_counterparty(counterparty_raw)
                source_fields = {"counterparty_info_raw": counterparty_raw} if counterparty_raw else {}
                field_sources = (
                    {"counterparty_info_raw": "raw_headers[5]:对手信息"}
                    if counterparty_raw
                    else {}
                )
                if counterparty_name:
                    field_sources["counterparty_name"] = "raw_headers[5]:对手信息#末尾账号以前"
                if counterparty_account:
                    field_sources["counterparty_account"] = "raw_headers[5]:对手信息#末尾账号"

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if amount > 0 else Decimal("0.00"),
                        expense=-amount if amount < 0 else Decimal("0.00"),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_index,
                        row_no=line_no,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=[
                            match.group("date"),
                            "CNY",
                            match.group("amount"),
                            match.group("balance"),
                            summary,
                            counterparty_raw,
                        ],
                        raw_headers=RAW_HEADERS,
                        status="ok" if not issues else "review",
                        issues=issues,
                        summary=summary,
                        counterparty_name=counterparty_name,
                        counterparty_account=counterparty_account,
                        source_fields=source_fields,
                        field_sources=field_sources,
                        field_confidence={field_name: 1.0 for field_name in field_sources},
                    )
                )

                if balance is not None:
                    previous_balance = balance

    return transactions
