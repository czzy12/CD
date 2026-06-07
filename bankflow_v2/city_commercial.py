import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "小银行通用"
CENT = Decimal("0.01")
DATE_RE = re.compile(r"20\d{2}[-/]?\d{2}[-/]?\d{2}")
MONEY_RE = re.compile(r"[+-]?\d[\d,]*\.\d{1,2}")


def _cell(row: list[str], index: int | None) -> str:
    if index is None or index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).replace("\n", "|").strip()


def _norm(text: str) -> str:
    return str(text or "").replace("\n", "").replace("|", "").replace(" ", "").replace("　", "").strip()


def _parse_time(text: str) -> datetime | None:
    cleaned = _norm(text).replace("/", "-")
    for match in re.finditer(r"(20\d{2})-?(\d{2})-?(\d{2})(?:(\d{2}):?(\d{2}):?(\d{2}))?", cleaned):
        try:
            hour = int(match.group(4) or "0")
            minute = int(match.group(5) or "0")
            second = int(match.group(6) or "0")
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), hour, minute, second)
        except ValueError:
            try:
                return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue

    digits = "".join(char for char in cleaned if char.isdigit())
    for digit_match in re.finditer(r"(20\d{2})(\d{2})(\d{2})", digits):
        try:
            return datetime(int(digit_match.group(1)), int(digit_match.group(2)), int(digit_match.group(3)))
        except ValueError:
            continue
    return None


def _parse_money(text: str) -> Decimal | None:
    cleaned = _norm(text).replace("￥", "").replace("¥", "")
    if cleaned in {"", "-"}:
        return None
    double_negative = cleaned.startswith("--")
    if double_negative:
        cleaned = cleaned[2:]
    match = MONEY_RE.search(cleaned)
    if not match:
        return None
    raw = match.group(0).replace(",", "")
    if double_negative and raw.startswith("-"):
        raw = raw[1:]
    try:
        return Decimal(raw).quantize(CENT)
    except InvalidOperation:
        return None


def _find_col(headers: list[str], names: tuple[str, ...]) -> int | None:
    for name in names:
        for index, header in enumerate(headers):
            if name == header:
                return index
    for name in names:
        for index, header in enumerate(headers):
            if name in header:
                return index
    return None


def _table_mapping(table: list[list[str]]) -> tuple[int, dict[str, int | None]] | None:
    for row_index, row in enumerate(table[:12]):
        headers = [_norm(cell) for cell in row]
        date_col = _find_col(headers, ("交易日期", "记账日期", "交易日", "日期"))
        if date_col is None:
            continue

        income_col = _find_col(headers, ("收入", "贷方发生额", "贷方"))
        expense_col = _find_col(headers, ("支出", "借方发生额", "借方"))
        amount_col = _find_col(headers, ("收/支金额", "交易金额", "发生额", "收入/支出", "金额"))
        balance_col = _find_col(headers, ("账户余额", "实时余额", "余额"))
        if income_col == amount_col:
            income_col = None
        if expense_col == amount_col:
            expense_col = None

        if balance_col is None:
            money_cols = [index for index, header in enumerate(headers) if "金额" in header or "余额" in header]
            if len(money_cols) >= 2:
                amount_col = amount_col if amount_col is not None else money_cols[0]
                balance_col = money_cols[1]

        if (amount_col is not None or income_col is not None or expense_col is not None) and balance_col is not None:
            return row_index, {
                "date": date_col,
                "amount": amount_col,
                "income": income_col,
                "expense": expense_col,
                "balance": balance_col,
            }
    return None


def _make_tx(
    tx_time: datetime,
    income: Decimal,
    expense: Decimal,
    balance: Decimal,
    bank_name: str,
    page_no: int,
    row_no: int,
    raw_time: str,
    raw_amount: str,
    raw_balance: str,
    raw_fields: list[str],
) -> Transaction:
    tx = Transaction(
        transaction_time=tx_time,
        income=income.quantize(CENT),
        expense=expense.quantize(CENT),
        balance=balance.quantize(CENT),
        bank=bank_name,
        page_no=page_no,
        row_no=row_no,
        raw_time=tx_time.strftime("%Y-%m-%d %H:%M:%S"),
        raw_amount=raw_amount,
        raw_balance=raw_balance,
        raw_text=" ".join(field for field in raw_fields if field),
        raw_fields=raw_fields,
    )
    tx.merge_key = "|".join([raw_time, raw_amount, raw_balance, str(page_no), str(row_no)])
    return tx


def _extract_table_rows(pdf_path: str, bank_name: str) -> list[Transaction]:
    rows: list[Transaction] = []
    sequence = 0
    last_cols: dict[str, int | None] | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                mapping = _table_mapping(table)
                if mapping:
                    start_row = mapping[0] + 1
                    cols = mapping[1]
                    last_cols = cols
                else:
                    start_row = 0
                    cols = last_cols

                for row in table[start_row:]:
                    fields = [_cell(row, index) for index in range(len(row))]
                    if cols is None:
                        continue
                    tx_time = _parse_time(_cell(row, cols["date"]))
                    balance = _parse_money(_cell(row, cols["balance"]))
                    if tx_time is None or balance is None:
                        continue

                    raw_income = _cell(row, cols["income"])
                    raw_expense = _cell(row, cols["expense"])
                    income = _parse_money(raw_income)
                    expense = _parse_money(raw_expense)
                    if income is not None or expense is not None:
                        income = income if income is not None and income > 0 else Decimal("0.00")
                        expense = expense if expense is not None and expense > 0 else Decimal("0.00")
                        raw_amount = f"收入:{raw_income} 支出:{raw_expense}"
                    else:
                        raw_amount = _cell(row, cols["amount"])
                        amount = _parse_money(raw_amount)
                        if amount is None:
                            continue
                        income = amount if amount >= 0 else Decimal("0.00")
                        expense = -amount if amount < 0 else Decimal("0.00")

                    sequence += 1
                    rows.append(
                        _make_tx(
                            tx_time,
                            income,
                            expense,
                            balance,
                            bank_name,
                            page_no,
                            sequence,
                            _cell(row, cols["date"]),
                            raw_amount,
                            _cell(row, cols["balance"]),
                            fields,
                        )
                    )
    return _normalize_partial_times(rows)


def _extract_text_rows(pdf_path: str, bank_name: str) -> list[Transaction]:
    rows: list[Transaction] = []
    sequence = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = raw_line.strip()
                tx_time = _parse_time(line)
                if tx_time is None:
                    continue

                money_text = (
                    line.replace("|", "")
                    .replace("\n", "")
                    .replace("CNY", " ")
                    .replace("人民币", " ")
                    .replace("¥", "")
                    .replace("￥", "")
                )
                money_matches = MONEY_RE.findall(money_text)
                if len(money_matches) < 2:
                    continue
                amount = _parse_money(money_matches[0])
                balance = _parse_money(money_matches[1])
                if amount is None or balance is None:
                    continue

                sequence += 1
                rows.append(
                    _make_tx(
                        tx_time,
                        amount if amount >= 0 else Decimal("0.00"),
                        -amount if amount < 0 else Decimal("0.00"),
                        balance,
                        bank_name,
                        page_no,
                        sequence,
                        tx_time.strftime("%Y-%m-%d"),
                        money_matches[0],
                        money_matches[1],
                        [line],
                    )
                )
    return _normalize_partial_times(rows)


def _normalize_partial_times(rows: list[Transaction]) -> list[Transaction]:
    rows = _dedupe_rows(rows)
    if len(rows) < 2:
        return rows

    first = rows[0].transaction_time.date()
    last = rows[-1].transaction_time.date()
    reverse_printed = first > last
    rows = sorted(rows, key=lambda tx: (tx.transaction_time.date(), -tx.row_no if reverse_printed else tx.row_no))
    for index, tx in enumerate(rows):
        if tx.transaction_time.time() != datetime.min.time():
            continue
        offset = index + 1
        tx.transaction_time = tx.transaction_time + timedelta(seconds=offset)
        tx.raw_time = tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S")
    return rows


def _dedupe_rows(rows: list[Transaction]) -> list[Transaction]:
    seen: set[tuple] = set()
    unique: list[Transaction] = []
    for tx in rows:
        leading_digits = "".join(char for char in (tx.raw_fields[0] if tx.raw_fields else "") if char.isdigit())
        if len(leading_digits) >= 5:
            key = (leading_digits, tx.transaction_time.date(), tx.income, tx.expense, tx.balance)
            if key in seen:
                continue
            seen.add(key)
        unique.append(tx)
    return unique


def extract_city_commercial(pdf_path: str, bank_name: str = BANK_NAME) -> list[Transaction]:
    table_rows = _extract_table_rows(pdf_path, bank_name)
    if table_rows:
        return table_rows
    return _extract_text_rows(pdf_path, bank_name)


def extract_jiujiang(pdf_path: str) -> list[Transaction]:
    return extract_city_commercial(pdf_path, "九江银行")


def extract_foshan_rural(pdf_path: str) -> list[Transaction]:
    return extract_city_commercial(pdf_path, "佛山农村商业银行")


def extract_lanzhou(pdf_path: str) -> list[Transaction]:
    return extract_city_commercial(pdf_path, "兰州银行")


def extract_ningbo(pdf_path: str) -> list[Transaction]:
    return extract_city_commercial(pdf_path, "宁波银行")


def extract_nanjing_corp(pdf_path: str) -> list[Transaction]:
    return extract_city_commercial(pdf_path, "南京银行对公")
