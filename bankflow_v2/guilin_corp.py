import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


PERSONAL_BANK_NAME = "桂林银行个人"
CORP_BANK_NAME = "桂林银行对公"
CENT = Decimal("0.01")
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
MONEY_RE = re.compile(r"^[+-]?\d[\d,]*\.\d{2}$")
RAW_HEADERS = ["交易日期", "对方账号", "对方户名", "收入", "支出", "余额", "原页"]
TABLE_HEADERS = ["交易日期", "对方账号", "对方户名", "收入（元）", "支出（元）", "账户余额（元）", "备注"]


def _money(value: str) -> Decimal | None:
    try:
        return Decimal(value.replace(",", "")).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_table_transactions(pdf_path: str, bank_name: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        for actual_page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                headers: list[str] | None = None
                for row in table:
                    fields = [_cell(cell) for cell in row]
                    if fields[:7] == TABLE_HEADERS:
                        headers = fields[:7]
                        continue
                    if len(fields) < 7 or not DATE_RE.match(fields[0]):
                        continue

                    income = _money(fields[3])
                    expense = _money(fields[4])
                    balance = _money(fields[5])
                    if income is None or expense is None or balance is None:
                        continue

                    sequence += 1
                    tx = Transaction(
                        transaction_time=datetime.strptime(fields[0], "%Y-%m-%d"),
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=bank_name,
                        # The statement is printed newest-first. Reverse print
                        # sequence within each date restores the balance chain.
                        page_no=0,
                        row_no=-sequence,
                        raw_time=fields[0],
                        raw_amount=f"收入:{fields[3]} 支出:{fields[4]}",
                        raw_balance=fields[5],
                        raw_text=" | ".join(fields[:7]),
                        raw_fields=fields[:7],
                        raw_headers=headers or TABLE_HEADERS,
                    )
                    tx.preserve_signed_columns = True
                    tx.merge_key = "|".join(fields[:6] + [str(actual_page_no)])
                    transactions.append(tx)

    return transactions


def extract_guilin(pdf_path: str) -> list[Transaction]:
    return _parse_table_transactions(pdf_path, PERSONAL_BANK_NAME)


def _word_lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for word in sorted(words, key=lambda item: (item["top"], item["x0"])):
        if not lines or abs(lines[-1][0]["top"] - word["top"]) > 3:
            lines.append([word])
        else:
            lines[-1].append(word)
    return lines


def extract_guilin_corp(pdf_path: str) -> list[Transaction]:
    table_transactions = _parse_table_transactions(pdf_path, CORP_BANK_NAME)
    if table_transactions:
        return table_transactions

    transactions: list[Transaction] = []
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        for actual_page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(
                keep_blank_chars=False,
                use_text_flow=False,
                x_tolerance=2,
                y_tolerance=3,
            )
            for line_words in _word_lines(words):
                texts = [str(word["text"]).strip() for word in line_words if str(word["text"]).strip()]
                if len(texts) < 5 or not DATE_RE.match(texts[0]):
                    continue

                money_indexes = [index for index, text in enumerate(texts) if MONEY_RE.match(text)]
                if len(money_indexes) < 3:
                    continue

                income_text, expense_text, balance_text = [texts[index] for index in money_indexes[-3:]]
                income = _money(income_text)
                expense = _money(expense_text)
                balance = _money(balance_text)
                if income is None or expense is None or balance is None:
                    continue

                tx_time = datetime.strptime(texts[0], "%Y-%m-%d")
                account = texts[1]
                first_money_index = money_indexes[-3]
                counterparty = "".join(texts[2:first_money_index])
                sequence += 1
                raw_fields = [
                    texts[0],
                    account,
                    counterparty,
                    income_text,
                    expense_text,
                    balance_text,
                    str(actual_page_no),
                ]
                tx = Transaction(
                    transaction_time=tx_time,
                    income=income,
                    expense=expense,
                    balance=balance,
                    bank=CORP_BANK_NAME,
                    # The statement is printed newest-first. Reverse print
                    # sequence within each date restores the balance chain.
                    page_no=0,
                    row_no=-sequence,
                    raw_time=texts[0],
                    raw_amount=f"收入:{income_text} 支出:{expense_text}",
                    raw_balance=balance_text,
                    raw_text=" | ".join(raw_fields),
                    raw_fields=raw_fields,
                    raw_headers=RAW_HEADERS,
                )
                tx.preserve_signed_columns = True
                tx.merge_key = "|".join([texts[0], account, counterparty, income_text, expense_text, balance_text])
                transactions.append(tx)

    return transactions
