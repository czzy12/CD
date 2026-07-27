import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList
from .number_parser import CENT, money_to_decimal


BANK_NAME = "招商银行对公"
MONEY = r"-?[\d,]+\.\d{2}"
ROW_RE = re.compile(
    rf"^(?P<date>20\d{{6}})(?P<business_type>\S+)\s+"
    rf"(?P<body>.*?)\s+(?P<amount>{MONEY})\s+"
    rf"(?P<balance>[\d,]+\.\d{{2}})(?P<counterparty>.*)$"
)
COORD_MONEY_RE = re.compile(r"^\d{1,3}(?:,\d{3})*\.\d{2}$|^\d+\.\d{2}$")
COORD_BALANCE_RE = re.compile(r"^(\d{1,3}(?:,\d{3})*\.\d{2}|\d+\.\d{2})")
COORD_DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
COORD_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")
COORD_HEADERS = ["交易日期", "借方(出账)", "贷方(入账)", "余额", "摘要", "收(付)方名称", "收(付)方账号", "交易类型"]
STATEMENT_HEADERS = ["日期", "业务类型", "票据号/摘要", "借方/贷方金额", "余额", "对手户名"]
BILL_NUMBER_RE = re.compile(r"^(?P<bill>\d{10,})(?:\s+(?P<summary>.*))?$")


def _statement_metadata(text: str) -> StatementMetadata:
    account_matches = re.findall(r"(?:账号|A/C\s*No\.)[：:\s]*([0-9][0-9\s-]{10,31})", text)
    name_matches = re.findall(r"(?:账户名称|Account\s*Name)[：:\s]*([^\n\r]+)", text)
    accounts = {re.sub(r"[\s-]+", "", value) for value in account_matches}
    names = {
        re.split(r"(?:上(?:一)?页余额|Last\s*Balance|业务类型|Business)", value)[0].strip()
        for value in name_matches
    }
    accounts = {value for value in accounts if value.isdigit() and 12 <= len(value) <= 32}
    names = {value for value in names if value}
    if len(accounts) != 1 or len(names) != 1:
        return StatementMetadata()
    return StatementMetadata(
        account_name=next(iter(names)),
        account_number=next(iter(accounts)),
        raw_fields=[f"账号: {next(iter(accounts))}", f"账户名称: {next(iter(names))}"],
        field_sources={
            "account_name": "page=1:document_header:账户名称",
            "account_number": "page=1:document_header:账号",
        },
        field_confidence={"account_name": 1.0, "account_number": 1.0},
    )


def _parse_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y%m%d")
    except ValueError:
        return None


def _summary_from_bill_or_description(raw: str) -> str:
    """Keep only the confirmed description portion of the combined text column."""
    text = raw.strip()
    match = BILL_NUMBER_RE.fullmatch(text)
    if match:
        return (match.group("summary") or "").strip()
    return text


def _append_continuation(transactions: list[Transaction], line: str) -> None:
    if not transactions:
        return
    tx = transactions[-1]
    tx.raw_text = f"{tx.raw_text}\n{line}" if tx.raw_text else line
    if tx.raw_fields:
        tx.raw_fields[-1] = f"{tx.raw_fields[-1]} {line}".strip()


def _coord_money(text: str) -> Decimal:
    return Decimal(text.replace(",", "")).quantize(CENT)


def _row_text(words: list[dict]) -> str:
    return " ".join(word.get("text", "") for word in words).strip()


def _extract_coord_layout(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(x_tolerance=2, y_tolerance=3, keep_blank_chars=False)
            words = sorted(words, key=lambda word: (word["top"], word["x0"]))
            starts = [
                word
                for word in words
                if COORD_DATE_RE.match(word.get("text", "")) and word["x0"] < 80
            ]

            for index, start in enumerate(starts):
                y0 = start["top"] - 2
                y1 = starts[index + 1]["top"] - 2 if index + 1 < len(starts) else page.height - 25
                row_words = [word for word in words if y0 <= word["top"] < y1]
                time_text = next(
                    (
                        word["text"]
                        for word in row_words
                        if word["x0"] < 80 and COORD_TIME_RE.match(word.get("text", ""))
                    ),
                    "00:00:00",
                )
                debit = [
                    word["text"]
                    for word in row_words
                    if 85 <= word["x0"] <= 170 and COORD_MONEY_RE.match(word.get("text", ""))
                ]
                credit = [
                    word["text"]
                    for word in row_words
                    if 175 <= word["x0"] <= 255 and COORD_MONEY_RE.match(word.get("text", ""))
                ]
                balances = []
                for word in row_words:
                    if 260 <= word["x0"] <= 350:
                        match = COORD_BALANCE_RE.match(word.get("text", ""))
                        if match:
                            balances.append(match.group(1))

                raw_text = _row_text(row_words)
                raw_time = f"{start['text']} {time_text}"
                tx_time = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
                if len(debit) + len(credit) != 1 or not balances:
                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            bank=BANK_NAME,
                            page_no=page_no,
                            row_no=len(transactions) + 1,
                            raw_time=raw_time,
                            raw_text=raw_text,
                            raw_headers=COORD_HEADERS,
                            status="review",
                            issues=["借方/贷方/余额列无法唯一定位"],
                        )
                    )
                    continue

                if debit:
                    income = Decimal("0.00")
                    expense = _coord_money(debit[0])
                    raw_amount = f"借方:{debit[0]}"
                else:
                    income = _coord_money(credit[0])
                    expense = Decimal("0.00")
                    raw_amount = f"贷方:{credit[0]}"

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=_coord_money(balances[0]),
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(transactions) + 1,
                        raw_time=raw_time,
                        raw_amount=raw_amount,
                        raw_balance=balances[0],
                        raw_text=raw_text,
                        raw_headers=COORD_HEADERS,
                    )
                )

    for tx in transactions:
        tx.source_file = Path(pdf_path).name
    return transactions


def _extract_statement_of_account(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = ROW_RE.match(line)
                if not match:
                    if transactions and not line.startswith(("第", "特别提示", "If ", "若")):
                        _append_continuation(transactions, line)
                    continue

                tx_time = _parse_date(match.group("date"))
                if tx_time is None:
                    continue

                amount = money_to_decimal(match.group("amount"))
                balance = money_to_decimal(match.group("balance"))
                issues: list[str] = []
                if amount is None:
                    issues.append("金额无法解析")
                    amount = Decimal("0.00")
                if balance is None:
                    issues.append("余额无法解析")
                if previous_balance is not None and balance is not None:
                    expected = (previous_balance + amount).quantize(CENT)
                    if expected != balance:
                        issues.append(f"余额不连续: 期望 {expected}, 解析 {balance}")

                raw_fields = [
                    match.group("date"),
                    match.group("business_type"),
                    match.group("body").strip(),
                    match.group("amount"),
                    match.group("balance"),
                    match.group("counterparty").strip(),
                ]
                summary = _summary_from_bill_or_description(match.group("body"))
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=amount if amount > 0 else Decimal("0.00"),
                        expense=-amount if amount < 0 else Decimal("0.00"),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=line_no,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=raw_fields,
                        raw_headers=STATEMENT_HEADERS,
                        summary=summary,
                        field_sources={"summary": "raw_headers[2]:票据号/摘要"} if summary else {},
                        field_confidence={"summary": 1.0} if summary else {},
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )
                if balance is not None:
                    previous_balance = balance

    return transactions


def extract_cmb_corp(pdf_path: str) -> TransactionList:
    transactions = _extract_statement_of_account(pdf_path)
    if not transactions:
        transactions = _extract_coord_layout(pdf_path)
    with pdfplumber.open(pdf_path) as pdf:
        metadata = _statement_metadata(pdf.pages[0].extract_text() or "") if pdf.pages else StatementMetadata()
    return TransactionList(transactions, metadata=metadata)
