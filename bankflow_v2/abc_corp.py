import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国农业银行"
START_RE = re.compile(r"^(\d{4}-\d{2}-(?:\d{2})?)(?:\s+(.*))?$")
TIME_RE = re.compile(r"^(?:(\d{2})\s+)?(\d{2}:\d{2}:\d{2})(?:\s+(.*))?$")
AMOUNT_RE = re.compile(r"^(\d[\d,]*\.\d{2})\s+(\d[\d,]*\.\d{2})(?:\s+(.*))?$")
DATE_PREFIX_RE = re.compile(r"20\d{2}-(?:\d{2}-)?$")
DAY_RE = re.compile(r"\d{2}")
MONTH_DAY_RE = re.compile(r"\d{2}-\d{2}")
MONEY_RE = re.compile(r"\d[\d,]*\.\d{2}")
CENT = Decimal("0.01")


@dataclass
class ParsedRow:
    tx_time: datetime
    amount: Decimal
    balance: Decimal
    raw_time: str
    raw_amount: str
    raw_text: str
    order_index: int
    same_time_order: int
    income: Decimal | None = None
    expense: Decimal | None = None


def _cell_text(value) -> str:
    return str(value or "").replace("\n", " ").strip()


def _is_record_start(line: str) -> bool:
    match = START_RE.match(line)
    if not match:
        return False
    date_text = match.group(1)
    return len(date_text) == 10 or date_text.endswith("-")


def _clean_line(line: str) -> str:
    return line.strip()


def _parse_blocks(pdf_path: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] | None = None
    skip_prefixes = ("账户明细", "账号:", "账号：", "户名:", "户名：", "币种:", "币种：", "交易时间", "第")

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for raw_line in (page.extract_text() or "").splitlines():
                line = _clean_line(raw_line)
                if not line or line.startswith(skip_prefixes):
                    continue

                if _is_record_start(line):
                    if current:
                        blocks.append(current)
                    current = [line]
                elif current is not None:
                    current.append(line)

    if current:
        blocks.append(current)
    return blocks


def _parse_datetime(block: list[str]) -> tuple[datetime | None, str]:
    start = START_RE.match(block[0])
    if not start:
        return None, ""

    date_prefix = start.group(1)
    date_text = date_prefix if len(date_prefix) == 10 else None
    time_text = None

    for line in block[1:]:
        match = TIME_RE.match(line)
        if not match:
            continue
        if date_text is None and match.group(1):
            date_text = f"{date_prefix}{match.group(1)}"
        time_text = match.group(2)
        break

    if date_text is None or time_text is None:
        return None, ""

    try:
        return datetime.strptime(f"{date_text} {time_text}", "%Y-%m-%d %H:%M:%S"), f"{date_text} {time_text}"
    except ValueError:
        return None, ""


def _parse_table_time(raw_time: str, accounting_date: str) -> datetime | None:
    digits = re.sub(r"\D", "", accounting_date)
    time_match = re.search(r"(\d{2}:\d{2}:\d{2})", raw_time)
    if len(digits) != 8 or not time_match:
        return None

    try:
        return datetime.strptime(f"{digits} {time_match.group(1)}", "%Y%m%d %H:%M:%S")
    except ValueError:
        return None


def _parse_amount_balance(block: list[str]) -> tuple[Decimal | None, Decimal | None, str]:
    for line in block[1:]:
        match = AMOUNT_RE.match(line)
        if not match:
            continue
        amount = money_to_decimal(match.group(1))
        balance = money_to_decimal(match.group(2))
        return amount, balance, line
    return None, None, ""


def _table_has_corp_header(row: list) -> bool:
    joined = "".join(_cell_text(cell) for cell in row)
    return all(marker in joined for marker in ("交易时间", "收入金额", "支出金额", "账户余额", "会计日期"))


def _parse_table_rows(pdf_path: str) -> list[ParsedRow]:
    parsed_rows: list[ParsedRow] = []
    order_index = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                if not any(_table_has_corp_header(row) for row in table):
                    continue
                for row in table:
                    if len(row) < 10 or _table_has_corp_header(row):
                        continue

                    raw_time = _cell_text(row[0])
                    tx_time = _parse_table_time(raw_time, _cell_text(row[9]))
                    income = money_to_decimal(_cell_text(row[1])) or Decimal("0.00")
                    expense = money_to_decimal(_cell_text(row[2])) or Decimal("0.00")
                    balance = money_to_decimal(_cell_text(row[3]))
                    if tx_time is None or balance is None or (income == 0 and expense == 0):
                        continue

                    order_index += 1
                    parsed_rows.append(
                        ParsedRow(
                            tx_time=tx_time,
                            amount=income if income else expense,
                            balance=balance,
                            raw_time=raw_time,
                            raw_amount=f"{_cell_text(row[1])}|{_cell_text(row[2])}",
                            raw_text=" | ".join(_cell_text(cell) for cell in row),
                            order_index=order_index,
                            same_time_order=order_index,
                            income=income,
                            expense=expense,
                        )
                    )

    return parsed_rows


def _parse_text_rows(pdf_path: str) -> list[ParsedRow]:
    parsed_rows: list[ParsedRow] = []

    for row_index, block in enumerate(_parse_blocks(pdf_path), start=1):
        tx_time, raw_time = _parse_datetime(block)
        amount, balance, raw_amount = _parse_amount_balance(block)
        raw_text = " | ".join(block)

        if tx_time is None or amount is None or balance is None:
            continue

        parsed_rows.append(
            ParsedRow(
                tx_time=tx_time,
                amount=amount,
                balance=balance,
                raw_time=raw_time,
                raw_amount=raw_amount,
                raw_text=raw_text,
                order_index=row_index,
                same_time_order=-row_index,
            )
        )

    return parsed_rows


def _body_words(page) -> list[dict]:
    return [
        word for word in page.extract_words(x_tolerance=1, y_tolerance=3, extra_attrs=["size"])
        if 7 <= float(word.get("size") or 0) <= 11
    ]


def _words_in_bounds(words: list[dict], left: float, right: float) -> list[dict]:
    return [word for word in words if left <= float(word["x0"]) < right]


def _joined_text(words: list[dict], left: float, right: float) -> str:
    column_words = _words_in_bounds(words, left, right)
    column_words.sort(key=lambda word: (round(float(word["top"]), 1), float(word["x0"])))
    return "".join(str(word["text"]) for word in column_words).strip()


def _first_money(text: str) -> Decimal | None:
    match = MONEY_RE.search(text)
    return money_to_decimal(match.group(0)) if match else None


def _parse_coordinate_rows(pdf_path: str) -> list[ParsedRow]:
    parsed_rows: list[ParsedRow] = []
    order_index = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = _body_words(page)
            date_words = [
                word for word in words
                if (
                    80 <= float(word["top"]) <= page.height - 30
                    and 10 <= float(word["x0"]) <= 75
                    and DATE_PREFIX_RE.fullmatch(str(word["text"]))
                )
            ]
            date_words.sort(key=lambda word: float(word["top"]))

            for date_index, date_word in enumerate(date_words):
                row_top = float(date_word["top"]) - 1
                row_bottom = float(date_words[date_index + 1]["top"]) - 1 if date_index + 1 < len(date_words) else page.height - 20
                row_words = [
                    word for word in words
                    if row_top <= float(word["top"]) < row_bottom
                ]
                date_prefix = str(date_word["text"])
                if re.fullmatch(r"20\d{2}-\d{2}-", date_prefix):
                    date_tail_words = [
                        word for word in _words_in_bounds(row_words, 25, 60)
                        if DAY_RE.fullmatch(str(word["text"]))
                    ]
                else:
                    date_tail_words = [
                        word for word in _words_in_bounds(row_words, 20, 70)
                        if MONTH_DAY_RE.fullmatch(str(word["text"]))
                    ]
                time_words = [
                    word for word in _words_in_bounds(row_words, 15, 75)
                    if re.fullmatch(r"\d{2}:\d{2}:\d{2}", str(word["text"]))
                ]
                if not date_tail_words or not time_words:
                    continue

                raw_date = f"{date_prefix}{date_tail_words[0]['text']}"
                raw_time = str(time_words[0]["text"])
                try:
                    tx_time = datetime.strptime(f"{raw_date} {raw_time}", "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    continue

                income_text = _joined_text(row_words, 72, 128)
                expense_text = _joined_text(row_words, 128, 184)
                balance_text = _joined_text(row_words, 184, 240)
                income = _first_money(income_text) or Decimal("0.00")
                expense = _first_money(expense_text) or Decimal("0.00")
                balance = _first_money(balance_text)
                if balance is None or (income == Decimal("0.00") and expense == Decimal("0.00")):
                    continue

                order_index += 1
                raw_text = " | ".join(
                    [
                        raw_date,
                        raw_time,
                        income_text,
                        expense_text,
                        balance_text,
                        _joined_text(row_words, 240, 296),
                        _joined_text(row_words, 296, 352),
                        _joined_text(row_words, 416, 520),
                    ]
                )
                parsed_rows.append(
                    ParsedRow(
                        tx_time=tx_time,
                        amount=income if income else expense,
                        balance=balance,
                        raw_time=f"{raw_date} {raw_time}",
                        raw_amount=f"{income_text}|{expense_text}",
                        raw_text=raw_text,
                        order_index=order_index,
                        same_time_order=order_index,
                        income=income,
                        expense=expense,
                    )
                )

    return parsed_rows


def _direction(raw_text: str, amount: Decimal, balance: Decimal, previous_balance: Decimal | None) -> str | None:
    if previous_balance is not None:
        if (previous_balance + amount).quantize(CENT) == balance:
            return "income"
        if (previous_balance - amount).quantize(CENT) == balance:
            return "expense"

    if "转存" in raw_text or "柜台存现" in raw_text:
        return "income"
    if any(keyword in raw_text for keyword in ("转取", "费用", "手续费", "公共缴费", "扣税")):
        return "expense"
    return None


def _matches_previous(row: ParsedRow, previous_balance: Decimal | None) -> bool:
    if previous_balance is None:
        return False
    if row.income is not None and row.expense is not None:
        expected = (previous_balance + row.income - row.expense).quantize(CENT)
        return expected == row.balance
    return (
        (previous_balance + row.amount).quantize(CENT) == row.balance
        or (previous_balance - row.amount).quantize(CENT) == row.balance
    )


def _order_same_time_group(rows: list[ParsedRow], previous_balance: Decimal | None) -> list[ParsedRow]:
    remaining = sorted(rows, key=lambda row: row.same_time_order)
    ordered: list[ParsedRow] = []
    current_balance = previous_balance

    while remaining:
        match_index = None
        for index, row in enumerate(remaining):
            if _matches_previous(row, current_balance):
                match_index = index
                break
        if match_index is None:
            ordered.extend(remaining)
            break

        row = remaining.pop(match_index)
        ordered.append(row)
        current_balance = row.balance

    return ordered


def _order_rows(parsed_rows: list[ParsedRow]) -> list[ParsedRow]:
    ordered: list[ParsedRow] = []
    previous_balance: Decimal | None = None
    index = 0
    rows = sorted(parsed_rows, key=lambda row: row.tx_time)

    while index < len(rows):
        tx_time = rows[index].tx_time
        group: list[ParsedRow] = []
        while index < len(rows) and rows[index].tx_time == tx_time:
            group.append(rows[index])
            index += 1
        ordered_group = _order_same_time_group(group, previous_balance)
        ordered.extend(ordered_group)
        if ordered_group:
            previous_balance = ordered_group[-1].balance

    return ordered


def extract_abc_corp(pdf_path: str) -> list[Transaction]:
    parsed_rows = _parse_table_rows(pdf_path)
    if not parsed_rows:
        parsed_rows = _parse_text_rows(pdf_path)
    if not parsed_rows:
        parsed_rows = _parse_coordinate_rows(pdf_path)

    ordered_rows = _order_rows(parsed_rows)
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    for row_index, row in enumerate(ordered_rows, start=1):
        issues: list[str] = []
        if row.income is not None and row.expense is not None:
            income = row.income
            expense = row.expense
        else:
            direction = _direction(row.raw_text, row.amount, row.balance, previous_balance)
            if direction == "income":
                income = row.amount
                expense = Decimal("0.00")
            elif direction == "expense":
                income = Decimal("0.00")
                expense = row.amount
            else:
                income = Decimal("0.00")
                expense = Decimal("0.00")
                issues.append("收支方向无法判定")

        transactions.append(
            Transaction(
                transaction_time=row.tx_time,
                income=income,
                expense=expense,
                balance=row.balance,
                bank=BANK_NAME,
                page_no=0,
                row_no=row_index,
                raw_time=row.raw_time,
                raw_amount=row.raw_amount,
                raw_balance=str(row.balance),
                raw_text=row.raw_text,
                status="ok" if not issues else "review",
                issues=issues,
            )
        )
        previous_balance = row.balance

    return transactions
