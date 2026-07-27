import re
from datetime import datetime
from decimal import Decimal
from typing import Any

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList
from .number_parser import money_to_decimal


BANK_NAME = "微信流水"
RAW_HEADERS = ["交易单号", "交易时间", "交易类型", "收/支/其他", "交易方式", "金额(元)", "交易对方", "商户单号"]
TIME_RE = re.compile(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{1,2}(?::\d{1,2})?")
WECHAT_OWNER_RE = re.compile(r"兹证明\s*[：:]\s*([^\s（(，,：:]{1,50})\s*[（(]")
WECHAT_IDENTITY_NUMBER_RE = re.compile(r"(?:居民身份证|身份证(?:号码|号)?)\s*[：:]\s*(\d{17}[\dXx]|\d{15})")
WECHAT_ACCOUNT_ID_RE = re.compile(r"微信号\s*[：:]\s*([A-Za-z][A-Za-z0-9_.@-]{4,63})")
AMOUNT_RE = re.compile(r"[￥¥]?\s*[+-]?\d[\d,]*\.\d{2}")


def _clean(value: Any) -> str:
    return str(value or "").replace("\n", " ").strip()


def _norm(value: Any) -> str:
    return _clean(value).replace(" ", "").replace("　", "")


def _parse_time(value: Any) -> datetime | None:
    text = _clean(value).replace("/", "-")
    match = TIME_RE.search(text)
    if not match:
        return None
    raw = match.group(0)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    return None


def _parse_amount(value: Any) -> Decimal | None:
    text = _clean(value).replace("￥", "").replace("¥", "").replace(" ", "")
    match = AMOUNT_RE.search(text)
    if not match:
        return None
    return money_to_decimal(match.group(0).replace("￥", "").replace("¥", "").replace(" ", ""))


def _direction(value: Any) -> str | None:
    text = _norm(value)
    if "其他" in text:
        return "neutral"
    if any(word in text for word in ("收入", "收款", "转入", "退款", "+")):
        return "income"
    if any(word in text for word in ("支出", "付款", "转出", "提现", "-")):
        return "expense"
    return None


def _find_col(headers: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        for index, header in enumerate(headers):
            if header == name:
                return index
    for name in names:
        for index, header in enumerate(headers):
            if name in header:
                return index
    return None


def _unique_matches(pattern: re.Pattern[str], text: str) -> set[str]:
    return {value.strip() for value in pattern.findall(text or "") if value.strip()}


def _wechat_identity_metadata(first_page_text: str) -> StatementMetadata:
    """Extract only explicit first-page WeChat proof identity labels."""
    owners = _unique_matches(WECHAT_OWNER_RE, first_page_text)
    identity_numbers = _unique_matches(WECHAT_IDENTITY_NUMBER_RE, first_page_text)
    payment_account_ids = _unique_matches(WECHAT_ACCOUNT_ID_RE, first_page_text)
    if not (len(owners) == len(identity_numbers) == len(payment_account_ids) == 1):
        return StatementMetadata()

    owner = next(iter(owners))
    identity_number = next(iter(identity_numbers)).upper()
    payment_account_id = next(iter(payment_account_ids))
    source = "page=1:wechat_proof_header"
    return StatementMetadata(
        account_name=owner,
        raw_fields={
            "payment_account_type": "wechat_account",
            "identity_owner_name": owner,
            "identity_number": identity_number,
            "payment_account_id": payment_account_id,
        },
        field_sources={
            "account_name": source,
            "identity_owner_name": source,
            "identity_number": source,
            "payment_account_id": source,
        },
        field_confidence={
            "account_name": 1.0,
            "identity_owner_name": 1.0,
            "identity_number": 1.0,
            "payment_account_id": 1.0,
        },
    )


def extract_wechat_identity_metadata(pdf_path: str) -> StatementMetadata:
    """Read page one only; do not parse transaction pages for identity discovery."""
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return StatementMetadata()
        return _wechat_identity_metadata(pdf.pages[0].extract_text() or "")


def _parse_table(table: list[list[Any]], page_no: int) -> list[Transaction]:
    transactions: list[Transaction] = []
    header_index = None
    raw_headers = RAW_HEADERS
    cols: dict[str, int | None] = {}

    for row_index, row in enumerate(table[:20]):
        headers = [_norm(cell) for cell in row]
        time_col = _find_col(headers, ("交易时间", "时间"))
        amount_col = _find_col(headers, ("金额(元)", "金额", "交易金额"))
        direction_col = _find_col(headers, ("收/支", "收支", "收入/支出", "交易方向"))
        if time_col is not None and amount_col is not None:
            header_index = row_index
            raw_headers = [_clean(cell) for cell in row]
            cols = {"time": time_col, "amount": amount_col, "direction": direction_col}
            break

    if header_index is None:
        cols = {"time": 1, "amount": 5, "direction": 3}
        header_index = -1

    for row_no, row in enumerate(table[header_index + 1 :], start=header_index + 2):
        tx_time = _parse_time(row[cols["time"]]) if cols["time"] is not None and cols["time"] < len(row) else None
        if tx_time is None:
            continue

        raw_amount = _clean(row[cols["amount"]]) if cols["amount"] is not None and cols["amount"] < len(row) else ""
        amount = _parse_amount(raw_amount)
        row_text = " ".join(_clean(cell) for cell in row)
        raw_direction = _clean(row[cols["direction"]]) if cols["direction"] is not None and cols["direction"] < len(row) else row_text
        direction = _direction(f"{raw_direction} {row_text}")
        issues: list[str] = []

        if amount is None:
            amount = Decimal("0.00")
            issues.append("金额无法解析")
        if direction == "income":
            income = amount
            expense = Decimal("0.00")
        elif direction == "expense":
            income = Decimal("0.00")
            expense = amount
        elif direction == "neutral":
            income = Decimal("0.00")
            expense = Decimal("0.00")
        else:
            income = Decimal("0.00")
            expense = Decimal("0.00")
            issues.append("收支方向无法解析")

        tx = Transaction(
            transaction_time=tx_time,
            income=income,
            expense=expense,
            balance=None,
            bank=BANK_NAME,
            page_no=page_no,
            row_no=row_no,
            raw_time=_clean(row[cols["time"]]),
            raw_amount=raw_amount,
            raw_balance="",
            raw_text=row_text,
            raw_fields=[_clean(cell) for cell in row],
            raw_headers=raw_headers,
            status="ok" if not issues else "review",
            issues=issues,
        )
        tx.balance_optional = True
        tx.neutral = direction == "neutral"
        transactions.append(tx)

    return transactions


def _parse_text_line(line: str, page_no: int, row_no: int) -> Transaction | None:
    tx_time = _parse_time(line)
    if tx_time is None:
        return None

    amount = _parse_amount(line)
    direction = _direction(line)
    if amount is None or direction is None:
        return None

    if direction == "income":
        income = amount
        expense = Decimal("0.00")
    elif direction == "expense":
        income = Decimal("0.00")
        expense = amount
    else:
        income = Decimal("0.00")
        expense = Decimal("0.00")

    tx = Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=None,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=tx_time.strftime("%Y-%m-%d %H:%M:%S"),
        raw_amount=_clean(line),
        raw_balance="",
        raw_text=_clean(line),
    )
    tx.balance_optional = True
    tx.neutral = direction == "neutral"
    return tx


def extract_wechat(pdf_path: str) -> TransactionList:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        metadata = (
            _wechat_identity_metadata(pdf.pages[0].extract_text() or "")
            if pdf.pages
            else StatementMetadata()
        )
        for page_no, page in enumerate(pdf.pages, start=1):
            before = len(transactions)
            for table in page.extract_tables():
                transactions.extend(_parse_table(table, page_no))

            if len(transactions) > before:
                continue

            for row_no, line in enumerate((page.extract_text() or "").splitlines(), start=1):
                tx = _parse_text_line(line, page_no, row_no)
                if tx is not None:
                    transactions.append(tx)

    return TransactionList(transactions, metadata=metadata)
