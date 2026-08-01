import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "兴业银行"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_RE = re.compile(r"20\d{2}-\d{2}-\d{2}")
DATE_DIGITS_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
SIGNED_NUMBER_RE = re.compile(r"[+-]?\d+(?:\.\d+)?")
RAW_HEADERS = ["交易时间", "记账日期", "摘要", "支/收", "交易金额", "账户余额", "交易用途", "对方户名", "对方账户/对方银行"]
EIGHT_COLUMN_HEADERS = [
    "交易时间",
    "记账日",
    "支出金额",
    "收入金额",
    "账户余额",
    "摘要/用途",
    "对方户名",
    "对方账号",
]


def _cell(value: object) -> str:
    return str(value or "").replace("\n", "|").strip()


def _parse_date(*values: object) -> datetime | None:
    for value in values:
        text = _cell(value)
        match = DATE_RE.search(text)
        if match:
            try:
                return datetime.strptime(match.group(0), "%Y-%m-%d")
            except ValueError:
                pass

        digits = "".join(char for char in text if char.isdigit())
        for start in range(0, max(len(digits) - 7, 0)):
            match = DATE_DIGITS_RE.match(digits[start : start + 8])
            if not match:
                continue
            try:
                return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                continue
    return None


def _parse_amount(value: object) -> Decimal | None:
    text = _cell(value).replace(",", "")
    match = SIGNED_NUMBER_RE.search(text)
    if not match:
        return None
    raw = match.group(0)
    if "-" in text and not raw.startswith("-"):
        raw = f"-{raw}"
    elif "+" in text and not raw.startswith("+"):
        raw = f"+{raw}"
    try:
        return Decimal(raw).quantize(CENT)
    except InvalidOperation:
        return None


def _parse_watermarked_datetime(value: object) -> datetime | None:
    text = re.sub(r"[^0-9:\-\n ]", "", _cell(value))
    match = re.search(
        r"(20\d{2})-(\d{2})-(\d{2}).*?(\d{2}):(\d{2}):(\d{2})",
        text,
        re.DOTALL,
    )
    if not match:
        return _parse_date(value)
    try:
        return datetime(*(int(part) for part in match.groups()))
    except ValueError:
        return _parse_date(value)


def _parse_watermarked_money(value: object) -> Decimal | None:
    text = _cell(value).replace(",", "")
    matches = re.findall(r"\d+\.\d{2,}", text)
    if not matches:
        return None
    try:
        return Decimal(matches[-1]).quantize(CENT)
    except InvalidOperation:
        return None


def _repair_watermarked_amounts(
    rows: list[tuple[Transaction, Decimal]],
) -> None:
    for (transaction, balance), (_, older_balance) in zip(rows, rows[1:]):
        delta = (balance - older_balance).quantize(CENT)
        if delta == ZERO:
            continue
        amount = transaction.income if delta > ZERO else transaction.expense
        if (
            (delta > ZERO and transaction.expense > ZERO)
            or (delta < ZERO and transaction.income > ZERO)
        ):
            continue
        expected = abs(delta)
        if amount == expected:
            continue
        if f"{amount:.2f}".endswith(f"{expected:.2f}"):
            transaction.income = expected if delta > ZERO else ZERO
            transaction.expense = expected if delta < ZERO else ZERO


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw).quantize(CENT)
    except InvalidOperation:
        return None


def _balance_candidates(value: object) -> list[Decimal]:
    text = _cell(value).replace(",", "")
    candidates: list[Decimal] = []

    spaced = "".join(char if (char.isdigit() or char == ".") else " " for char in text)
    for match in re.finditer(r"\d+(?:\.\d{1,2})", spaced):
        value = _to_decimal(match.group(0))
        if value is not None:
            candidates.append(value)

    compact = "".join(char for char in text if char.isdigit() or char == ".")
    if "." in compact:
        dot_index = compact.rfind(".")
        integer_part = "".join(char for char in compact[:dot_index] if char.isdigit())
        fraction_part = "".join(char for char in compact[dot_index + 1 :] if char.isdigit())[:2]
        if fraction_part:
            for start in range(len(integer_part)):
                value = _to_decimal(f"{integer_part[start:]}.{fraction_part}")
                if value is not None:
                    candidates.append(value)

    unique: list[Decimal] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _choose_balance(candidates: list[Decimal], expected: Decimal | None) -> Decimal | None:
    if not candidates:
        return None
    if expected is not None:
        for candidate in candidates:
            if candidate == expected:
                return candidate
    return candidates[0]


def _has_confirmed_strong_watermark(text: str) -> bool:
    return (
        ("兴业银行交易明细" in text and "核验" in text)
        or (
            _has_fragmented_marker(text, "说明交易明细涉及您的个人隐私")
            and _has_fragmented_marker(text, "交易明细内容仅供个人参考")
        )
    )


def _has_fragmented_marker(text: str, marker: str) -> bool:
    position = text.find(marker[0])
    for char in marker[1:]:
        next_position = text.find(char, position + 1)
        if next_position < 0 or next_position - position > 40:
            return False
        position = next_position
    return True


def extract_cib(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    eight_column_rows: list[tuple[Transaction, Decimal]] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        sample_text = "\n".join((page.extract_text() or "") for page in pdf.pages[:2])
        strong_watermark = _has_confirmed_strong_watermark(sample_text)
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 6:
                        continue
                    if len(row) == 8:
                        tx_time = _parse_watermarked_datetime(row[0])
                        expense = _parse_watermarked_money(row[2])
                        income = _parse_watermarked_money(row[3])
                        balance = _parse_watermarked_money(row[4])
                        if (
                            tx_time is None
                            or balance is None
                            or (expense is None and income is None)
                        ):
                            continue
                        expense = expense or ZERO
                        income = income or ZERO
                        if expense > ZERO and income > ZERO:
                            continue

                        row_no = len(rows) + 1
                        fields = [_cell(cell) for cell in row]
                        direction = "支出" if expense > ZERO else "收入"
                        counterparty_account_raw = fields[7]
                        tx = Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=None if strong_watermark else balance,
                            bank=BANK_NAME,
                            page_no=page_no,
                            row_no=row_no,
                            raw_time=_cell(row[0]),
                            raw_amount=(
                                f"支出:{_cell(row[2])}|收入:{_cell(row[3])}"
                            ),
                            raw_balance=_cell(row[4]),
                            raw_text=" ".join(field for field in fields if field),
                            raw_fields=fields,
                            raw_headers=EIGHT_COLUMN_HEADERS,
                            counterparty_name=fields[6],
                            summary=fields[5],
                            purpose=fields[5],
                            transaction_direction=direction,
                            source_fields=(
                                {"counterparty_account_raw": counterparty_account_raw}
                                if counterparty_account_raw
                                else {}
                            ),
                            field_sources={
                                "counterparty_name": "raw_headers[6]:对方户名",
                                "summary": "raw_headers[5]:摘要/用途",
                                "purpose": "raw_headers[5]:摘要/用途",
                                "transaction_direction": (
                                    "raw_headers[2]:支出金额"
                                    if expense > ZERO
                                    else "raw_headers[3]:收入金额"
                                ),
                                **(
                                    {"counterparty_account_raw": "raw_headers[7]:对方账号"}
                                    if counterparty_account_raw
                                    else {}
                                ),
                            },
                            field_confidence={
                                "counterparty_name": 1.0,
                                "summary": 1.0,
                                "purpose": 1.0,
                                "transaction_direction": 1.0,
                                **(
                                    {"counterparty_account_raw": 1.0}
                                    if counterparty_account_raw
                                    else {}
                                ),
                            },
                        )
                        if strong_watermark:
                            tx.balance_optional = True
                            tx.raw_balance = f"参考余额:{tx.raw_balance}"
                        tx.merge_key = "|".join(
                            [str(row_no), tx.raw_time, tx.raw_amount, tx.raw_balance]
                        )
                        rows.append(tx)
                        eight_column_rows.append((tx, balance))
                        continue

                    tx_time = _parse_date(row[1], row[0])
                    amount = _parse_amount(row[4])
                    balance_candidates = _balance_candidates(row[5])
                    if tx_time is None or amount is None or not balance_candidates:
                        continue

                    expected = None
                    if previous_balance is not None:
                        expected = (previous_balance + amount).quantize(CENT)
                    balance = _choose_balance(balance_candidates, expected)
                    if balance is None:
                        continue
                    previous_balance = balance

                    row_no = len(rows) + 1
                    fields = [_cell(cell) for cell in row]
                    counterparty_account_bank_raw = fields[8] if len(fields) > 8 else ""
                    source_fields = (
                        {"counterparty_account_bank_raw": counterparty_account_bank_raw}
                        if counterparty_account_bank_raw
                        else {}
                    )
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=amount if amount >= ZERO else ZERO,
                        expense=-amount if amount < ZERO else ZERO,
                        balance=None if strong_watermark else balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=row_no,
                        raw_time=tx_time.strftime("%Y-%m-%d"),
                        raw_amount=_cell(row[4]),
                        raw_balance=_cell(row[5]),
                        raw_text=" ".join(field for field in fields if field),
                        raw_fields=fields,
                        raw_headers=RAW_HEADERS,
                        transaction_direction=fields[3],
                        source_fields=source_fields,
                        field_sources={
                            **({"transaction_direction": "raw_headers[3]:支/收"} if fields[3] else {}),
                            **(
                                {"counterparty_account_bank_raw": "raw_headers[8]:对方账户/对方银行"}
                                if counterparty_account_bank_raw
                                else {}
                            ),
                        },
                        field_confidence={
                            field_name: 1.0
                            for field_name in (
                                (["transaction_direction"] if fields[3] else [])
                                + (["counterparty_account_bank_raw"] if counterparty_account_bank_raw else [])
                            )
                        },
                    )
                    if strong_watermark:
                        tx.balance_optional = True
                        tx.raw_balance = f"参考余额:{tx.raw_balance}"
                    tx.merge_key = "|".join([str(row_no), tx.raw_time, tx.raw_amount, tx.raw_balance])
                    rows.append(tx)

    _repair_watermarked_amounts(eight_column_rows)
    return rows
