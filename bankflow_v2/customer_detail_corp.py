import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import CENT, money_to_decimal


BANK_NAME = "对公客户账户明细"
RAW_HEADERS = ["交易日期", "交易发生金额", "账户余额", "对方账号", "对方户名", "摘要", "备注"]
FALLBACK_RAW_HEADERS = ["交易日期", "交易发生金额", "账户余额", "对方账号", "未拆分交易文本"]
ROW_RE = re.compile(
    r"(?P<date>20\d{6})\s+"
    r"(?P<amount>[+-][\d,]+\.\d{2})\s+"
    r"(?P<balance>[\d,]+\.\d{2})\s+"
    r"(?P<body>.+)$"
)


def _date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(raw, "%Y%m%d")
    except ValueError:
        return None


def _split_body(body: str) -> tuple[str, str]:
    text = body.strip()
    match = re.match(r"(?P<account>[0-9A-Za-z]+(?:等\d+户)?)(?P<rest>.*)", text)
    if not match:
        return "", text
    return match.group("account"), match.group("rest").strip()


def _append_continuation(transactions: list[Transaction], line: str) -> None:
    if not transactions:
        return
    tx = transactions[-1]
    tx.raw_text = f"{tx.raw_text}\n{line}" if tx.raw_text else line
    if tx.raw_fields:
        tx.raw_fields[-1] = f"{tx.raw_fields[-1]} {line}".strip()
        tx.source_fields["unparsed_transaction_text"] = tx.raw_fields[-1]


def _column_text(words: list[dict], left: float, right: float, top: float, bottom: float) -> str:
    selected = [
        word
        for word in words
        if left <= float(word["x0"]) < right and top <= float(word["top"]) < bottom
    ]
    return " ".join(word["text"] for word in sorted(selected, key=lambda word: (float(word["top"]), float(word["x0"])))).strip()


def _coordinate_rows(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            if not hasattr(page, "extract_words"):
                continue
            words = page.extract_words(x_tolerance=1, y_tolerance=3)
            anchors = [
                word
                for word in words
                if re.fullmatch(r"20\d{6}", word.get("text", ""))
                and 40 <= float(word["x0"]) <= 80
                and float(word["top"]) > 160
            ]
            anchors.sort(key=lambda word: float(word["top"]))
            for row_index, anchor in enumerate(anchors, start=1):
                # Some wrapped columns begin a few points above the date/amount anchor.
                top = float(anchor["top"]) - 6
                bottom = float(anchors[row_index]["top"]) - 6 if row_index < len(anchors) else page.height - 35
                raw_date = anchor["text"]
                raw_amount = _column_text(words, 80, 140, top, bottom)
                raw_balance = _column_text(words, 140, 195, top, bottom)
                raw_account = _column_text(words, 200, 285, top, bottom)
                counterparty_name = _column_text(words, 285, 360, top, bottom)
                summary = _column_text(words, 360, 407, top, bottom)
                remark = _column_text(words, 407, 570, top, bottom)
                tx_time = _date(raw_date)
                amount = money_to_decimal(raw_amount)
                balance = money_to_decimal(raw_balance)
                if tx_time is None or amount is None or balance is None:
                    continue
                income = amount if amount > 0 else Decimal("0.00")
                expense = -amount if amount < 0 else Decimal("0.00")
                raw_fields = [raw_date, raw_amount, raw_balance, raw_account, counterparty_name, summary, remark]
                source_fields = {"counterparty_account_raw": raw_account} if raw_account else {}
                field_sources = {"counterparty_account_raw": "raw_headers[3]:对方账号"} if raw_account else {}
                field_confidence = {"counterparty_account_raw": 1.0} if raw_account else {}
                tx = Transaction(
                        transaction_time=tx_time,
                        income=income.quantize(CENT),
                        expense=expense.quantize(CENT),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(transactions) + 1,
                        raw_time=raw_date,
                        raw_amount=raw_amount,
                        raw_balance=raw_balance,
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=RAW_HEADERS,
                        counterparty_name=counterparty_name,
                        summary=summary,
                        remark=remark,
                        source_fields=source_fields,
                        field_sources=field_sources,
                        field_confidence=field_confidence,
                    )
                tx.counterparty_account = ""
                tx.field_sources.pop("counterparty_account", None)
                tx.field_confidence.pop("counterparty_account", None)
                transactions.append(tx)
    return transactions


def extract_customer_detail_corp(pdf_path: str) -> list[Transaction]:
    coordinate_transactions = _coordinate_rows(pdf_path)
    if coordinate_transactions:
        return coordinate_transactions
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                match = ROW_RE.search(line)
                if not match:
                    if transactions and line and not line.startswith(("对公客户账户明细", "打印日期", "打印时间", "账 号", "客户名称", "起始日期", "交易日期", "借方合计", "贷方合计")):
                        _append_continuation(transactions, line)
                    continue

                tx_time = _date(match.group("date"))
                amount = money_to_decimal(match.group("amount"))
                balance = money_to_decimal(match.group("balance"))
                issues: list[str] = []
                if tx_time is None:
                    issues.append("日期无法解析")
                    continue
                if amount is None:
                    issues.append("金额无法解析")
                    amount = Decimal("0.00")
                if balance is None:
                    issues.append("余额无法解析")

                account, rest = _split_body(match.group("body"))
                income = amount if amount > 0 else Decimal("0.00")
                expense = -amount if amount < 0 else Decimal("0.00")
                raw_fields = [
                    match.group("date"),
                    match.group("amount"),
                    match.group("balance"),
                    account,
                    rest,
                ]
                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=income.quantize(CENT),
                        expense=expense.quantize(CENT),
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=len(transactions) + 1,
                        raw_time=match.group("date"),
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=line,
                        raw_fields=raw_fields,
                        raw_headers=FALLBACK_RAW_HEADERS,
                        source_fields={"unparsed_transaction_text": rest} if rest else {},
                        field_sources={"unparsed_transaction_text": "raw_headers[4]:未拆分交易文本"} if rest else {},
                        field_confidence={"unparsed_transaction_text": 1.0} if rest else {},
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )

    return transactions
