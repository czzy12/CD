import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "湖北农商银行"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
TIME_RE = re.compile(r"(?<!\d)(\d{2}:\d{2}:\d{2})(?!\d)")
MONEY_RE = re.compile(r"[+-]?\d[\d,]*(?:\.\d{2})")


def _clean(value) -> str:
    return str(value or "").replace("\n", " ").strip()


def _money(value: str) -> Decimal | None:
    text = re.sub(r"[\u4e00-\u9fff]", "", _clean(value))
    matches = MONEY_RE.findall(text)
    if not matches:
        return None
    try:
        return Decimal(matches[-1].replace(",", "")).quantize(CENT)
    except InvalidOperation:
        return None


def _time(value: str) -> datetime | None:
    text = _clean(value)
    date_match = DATE_RE.search(text)
    time_matches = re.findall(r"\d{2}:\d{2}:\d{2}", text)
    if not date_match or not time_matches:
        return None
    for raw_time in reversed(time_matches):
        try:
            return datetime.strptime(f"{date_match.group(0)} {raw_time}", "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _account_meta(pdf_path: str) -> tuple[str, str]:
    with pdfplumber.open(pdf_path) as pdf:
        text = pdf.pages[0].extract_text() if pdf.pages else ""
    text = text or ""
    name_match = re.search(r"户\s*名\s*[:：]\s*([^\s]+)", text)
    account_match = re.search(r"卡号/账号\s*[:：]\s*([0-9]+)", text)
    return (name_match.group(1) if name_match else "", account_match.group(1) if account_match else "")


def extract_hubei_rural(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    account_name, account_no = _account_meta(pdf_path)
    headers = ["交易日期", "对方户名", "对方账号/卡号", "交易摘要", "发生额", "余额", "币种"]

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            # The diagonal verification watermark is encoded as oversized text
            # and otherwise gets interleaved into table cells by pdfplumber.
            clean_page = page.filter(
                lambda obj: not (
                    obj.get("object_type") == "char"
                    and float(obj.get("size") or 0) > 15
                )
            )
            for table in clean_page.extract_tables():
                for source_row_no, row in enumerate(table[1:], start=1):
                    if len(row) < 7:
                        continue
                    fields = [_clean(cell) for cell in row[:7]]
                    tx_time = _time(fields[0])
                    amount = _money(fields[4])
                    balance = _money(fields[5])
                    if tx_time is None or amount is None or balance is None:
                        continue
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=amount if amount > ZERO else ZERO,
                        expense=-amount if amount < ZERO else ZERO,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(rows) + 1,
                        raw_time=fields[0],
                        raw_amount=fields[4],
                        raw_balance=fields[5],
                        raw_text=" | ".join(fields),
                        raw_fields=fields,
                        raw_headers=headers,
                    )
                    tx.account_name = account_name
                    tx.account_no = account_no
                    tx.merge_key = "|".join([tx_time.isoformat(), str(amount), str(balance), fields[1], fields[2]])
                    rows.append(tx)
    return rows
