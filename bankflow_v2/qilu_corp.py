from datetime import datetime
from decimal import Decimal
from itertools import combinations

import pdfplumber

from .models import Transaction
from .number_parser import CENT, balance_candidates


BANK_NAME = "齐鲁银行对公"


def _clean_numeric(chars: list[dict]) -> str:
    return "".join(
        char["text"]
        for char in sorted(chars, key=lambda item: item["x0"])
        if char["text"].isdigit() or char["text"] in ",.-"
    )


def _baseline_texts(chars: list[dict], x0: float, x1: float, y0: float, ypad: float = 13) -> list[str]:
    selected = [
        char
        for char in chars
        if x0 <= char["x0"] < x1 and y0 - 1 <= char["top"] <= y0 + ypad
    ]
    groups: list[list] = []
    for char in sorted(selected, key=lambda item: item["top"]):
        for group in groups:
            if abs(group[0] - char["top"]) < 0.8:
                group[1].append(char)
                break
        else:
            groups.append([char["top"], [char]])

    ranked = sorted(
        (abs(top - (y0 + 3.3)), _clean_numeric(group_chars))
        for top, group_chars in groups
    )
    return [text for _, text in ranked if text]


def _column_raw(chars: list[dict], x0: float, x1: float, y0: float) -> str:
    return "|".join(_baseline_texts(chars, x0, x1, y0))


def _money_candidates(raw: str, signed: bool = False) -> list[Decimal]:
    values: list[Decimal] = []
    seen: set[Decimal] = set()
    for part in raw.split("|"):
        sign = -1 if signed and "-" in part[:3] else 1
        for value in balance_candidates(part.replace("-", "")):
            candidate = Decimal("0.00") if value == 0 else value * sign
            if candidate not in seen:
                values.append(candidate)
                seen.add(candidate)

    if Decimal("0.00") not in seen and ("0.00" in raw or not values):
        values.insert(0, Decimal("0.00"))
    return values[:24]


def _valid_date(text: str) -> datetime | None:
    try:
        value = datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None
    if datetime(2025, 1, 1) <= value <= datetime(2030, 12, 31):
        return value
    return None


def _date_from_raw(raw: str, previous: datetime | None) -> datetime | None:
    digits = "".join(char for char in raw if char.isdigit())[:16]
    options: list[datetime] = []
    for indexes in combinations(range(len(digits)), 8):
        value = _valid_date("".join(digits[index] for index in indexes))
        if value is not None:
            options.append(value)

    if not options:
        return previous
    if previous is not None:
        later = [value for value in options if value >= previous]
        if later:
            return min(later)
    return min(options)


def _option_cost(income_index: int, expense_index: int, balance_index: int, income: Decimal, expense: Decimal) -> Decimal:
    cost = Decimal(income_index + expense_index) / Decimal("1000")
    cost += Decimal(balance_index) / Decimal("10000")
    if income != 0 and expense != 0:
        cost += Decimal("5")
    return cost


def _resolve_rows(raw_rows: list[tuple[str, str, str]]) -> list[tuple[Decimal, Decimal, Decimal, list[str]]]:
    beams: list[tuple[Decimal, Decimal | None, list[tuple[Decimal, Decimal, Decimal]]]] = [
        (Decimal("0.00"), None, [])
    ]

    for income_raw, expense_raw, balance_raw in raw_rows:
        incomes = _money_candidates(income_raw, signed=True)
        expenses = _money_candidates(expense_raw, signed=True)
        balances = _money_candidates(balance_raw, signed=False)
        next_beams: list[tuple[Decimal, Decimal | None, list[tuple[Decimal, Decimal, Decimal]]]] = []

        for cost, previous_balance, path in beams:
            options: list[tuple[Decimal, Decimal, Decimal, Decimal]] = []
            if previous_balance is None:
                for income_index, income in enumerate(incomes[:3]):
                    for expense_index, expense in enumerate(expenses[:3]):
                        for balance_index, balance in enumerate(balances[:3]):
                            options.append((
                                _option_cost(income_index, expense_index, balance_index, income, expense),
                                income,
                                expense,
                                balance,
                            ))
            else:
                for income_index, income in enumerate(incomes):
                    for expense_index, expense in enumerate(expenses):
                        expected = (previous_balance + income - expense).quantize(CENT)
                        for balance_index, balance in enumerate(balances[:40]):
                            if balance == expected:
                                options.append((
                                    _option_cost(income_index, expense_index, balance_index, income, expense),
                                    income,
                                    expense,
                                    balance,
                                ))

                if not options:
                    for income_index, income in enumerate(incomes[:8]):
                        for expense_index, expense in enumerate(expenses[:8]):
                            expected = (previous_balance + income - expense).quantize(CENT)
                            for balance_index, balance in enumerate(balances[:12]):
                                gap = abs(expected - balance)
                                options.append((
                                    Decimal("1000") + min(gap, Decimal("1000")) + _option_cost(income_index, expense_index, balance_index, income, expense),
                                    income,
                                    expense,
                                    balance,
                                ))

            for option_cost, income, expense, balance in sorted(options, key=lambda item: item[0])[:30]:
                next_beams.append((cost + option_cost, balance, path + [(income, expense, balance)]))

        beams = sorted(next_beams, key=lambda item: item[0])[:120]

    best_path = min(beams, key=lambda item: item[0])[2] if beams else []
    resolved: list[tuple[Decimal, Decimal, Decimal, list[str]]] = []
    previous_balance: Decimal | None = None
    for income, expense, balance in best_path:
        issues: list[str] = []
        if previous_balance is not None:
            expected = (previous_balance + income - expense).quantize(CENT)
            if expected != balance:
                issues.append(f"余额不连续: 期望 {expected}, 解析 {balance}")
        resolved.append((income, expense, balance, issues))
        previous_balance = balance
    return resolved


def extract_qilu_corp(pdf_path: str) -> list[Transaction]:
    raw_rows: list[tuple[str, str, str]] = []
    row_meta: list[tuple[int, int, datetime | None, str, str, str]] = []
    previous_date: datetime | None = None
    row_no = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            chars = page.chars
            for table in [table for table in page.find_tables() if table.bbox[1] > 160]:
                for row in table.rows:
                    y0 = row.bbox[1]
                    income_raw = _column_raw(chars, 180, 260, y0)
                    expense_raw = _column_raw(chars, 270, 335, y0)
                    balance_raw = _column_raw(chars, 350, 410, y0)
                    date_raw = _column_raw(chars, 45, 105, y0)
                    if not (income_raw or expense_raw or balance_raw):
                        continue

                    tx_date = _date_from_raw(date_raw, previous_date)
                    if tx_date is not None:
                        previous_date = tx_date

                    row_no += 1
                    raw_rows.append((income_raw, expense_raw, balance_raw))
                    row_meta.append((page_no, row_no, tx_date, income_raw, expense_raw, balance_raw))

    resolved = _resolve_rows(raw_rows)
    transactions: list[Transaction] = []
    for (page_no, row_no, tx_date, income_raw, expense_raw, balance_raw), (income, expense, balance, issues) in zip(row_meta, resolved):
        if tx_date is None:
            continue
        tx = Transaction(
            transaction_time=tx_date,
            income=income.quantize(CENT),
            expense=expense.quantize(CENT),
            balance=balance.quantize(CENT),
            bank=BANK_NAME,
            page_no=page_no,
            row_no=row_no,
            raw_time=tx_date.strftime("%Y-%m-%d"),
            raw_amount=f"收入:{income_raw} 支出:{expense_raw}",
            raw_balance=balance_raw,
            raw_text=f"{income_raw} {expense_raw} {balance_raw}",
            raw_fields=[income_raw, expense_raw, balance_raw],
            raw_headers=["收入", "支出", "账户余额"],
            issues=issues,
        )
        tx.preserve_signed_columns = True
        tx.merge_key = "|".join([tx.raw_time, income_raw, expense_raw, balance_raw, str(page_no), str(row_no)])
        transactions.append(tx)

    return transactions
