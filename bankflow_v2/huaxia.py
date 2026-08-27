import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "华夏银行"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_RE = re.compile(r"^(20\d{2}-\d{2}-\d{2})\s+(?P<body>.+)$")
MONEY_RE = re.compile(r"[+-]?\d[\d,]*\.\d{2}")


def _parse_money(text: str) -> Decimal | None:
    try:
        return Decimal(str(text).replace(",", "")).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _normalize_reverse_printed(rows: list[Transaction]) -> list[Transaction]:
    if len(rows) < 2:
        return rows

    reverse_printed = rows[0].transaction_time.date() > rows[-1].transaction_time.date()
    rows = sorted(rows, key=lambda tx: (tx.transaction_time.date(), -tx.row_no if reverse_printed else tx.row_no))
    for index, tx in enumerate(rows, start=1):
        tx.transaction_time = tx.transaction_time + timedelta(seconds=index)
        tx.raw_time = tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S")
    return rows


def _table_time(value: str) -> datetime | None:
    match = re.search(r"(20\d{2}-\d{2}-\d{2}).*?(\d{2}:\d{2}:\d{2})", value or "")
    if not match:
        return None
    try:
        return datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _extract_table_rows(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    headers = ["记账日期", "摘要", "收入金额", "支出金额", "余额", "交易机构", "对方姓名", "对方卡/账号", "对方开户行", "附言"]
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not table or [str(cell or "").replace("\n", "").strip() for cell in table[0]][:10] != headers:
                    continue
                for source_row_no, row in enumerate(table[1:], start=1):
                    fields = [str(cell or "").replace("\n", " ").strip() for cell in row]
                    if len(fields) < 5:
                        continue
                    tx_time = _table_time(fields[0])
                    income = _parse_money(fields[2]) or ZERO
                    expense = _parse_money(fields[3]) or ZERO
                    balance = _parse_money(fields[4])
                    if tx_time is None or balance is None or (income == ZERO and expense == ZERO):
                        continue
                    row_no = len(rows) + 1
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=row_no,
                        raw_time=fields[0],
                        raw_amount=f"{fields[2]}|{fields[3]}",
                        raw_balance=fields[4],
                        raw_text=" | ".join(fields[:10]),
                        raw_fields=fields[:10],
                        raw_headers=headers,
                    )
                    tx.merge_key = "|".join([tx_time.isoformat(), fields[2], fields[3], fields[4], fields[1]])
                    rows.append(tx)
    return _normalize_reverse_printed(rows)


def extract_huaxia(pdf_path: str) -> list[Transaction]:
    table_rows = _extract_table_rows(pdf_path)
    if table_rows:
        return table_rows

    rows: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line in (page.extract_text() or "").splitlines():
                line = line.strip()
                match = DATE_RE.match(line)
                if not match:
                    continue

                body = match.group("body")
                money_matches = MONEY_RE.findall(body)
                if len(money_matches) < 2:
                    continue

                amount = _parse_money(money_matches[0])
                balance = _parse_money(money_matches[1])
                if amount is None or balance is None:
                    continue

                tx_time = datetime.strptime(match.group(1), "%Y-%m-%d")
                description = body[: body.find(money_matches[0])].strip()
                row_no = len(rows) + 1
                tx = Transaction(
                    transaction_time=tx_time,
                    income=amount if amount >= ZERO else ZERO,
                    expense=-amount if amount < ZERO else ZERO,
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=row_no,
                    raw_time=match.group(1),
                    raw_amount=money_matches[0],
                    raw_balance=money_matches[1],
                    raw_text=line,
                    raw_fields=[match.group(1), description, money_matches[0], money_matches[1], line],
                )
                tx.merge_key = "|".join([match.group(1), money_matches[0], money_matches[1], str(page_no), str(row_no)])
                rows.append(tx)

    return _normalize_reverse_printed(rows)
