import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .models import Transaction
from .number_parser import extract_signed_amount, money_to_decimal


BANK_NAME = "Excel导入"
CENT = Decimal("0.01")


def _norm(value: Any) -> str:
    return str(value or "").replace("\n", "").replace(" ", "").replace("　", "").strip()


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, time):
        return value.strftime("%H:%M:%S")
    return str(value).strip()


def _find_col(headers: list[str], names: tuple[str, ...], exclude: set[int] | None = None) -> int | None:
    exclude = exclude or set()
    for name in names:
        for index, header in enumerate(headers):
            if index not in exclude and header == name:
                return index
    for name in names:
        for index, header in enumerate(headers):
            if index not in exclude and name in header:
                return index
    return None


def _parse_date_part(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _cell_text(value).replace("/", "-").replace("年", "-").replace("月", "-").replace("日", "")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _parse_time_part(value: Any) -> time:
    if isinstance(value, datetime):
        return value.time().replace(microsecond=0)
    if isinstance(value, time):
        return value.replace(microsecond=0)
    text = _cell_text(value).replace("：", ":")
    match = re.search(r"(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?", text)
    if not match:
        return time(0, 0, 0)
    try:
        return time(int(match.group(1)), int(match.group(2)), int(match.group(3) or "0"))
    except ValueError:
        return time(0, 0, 0)


def _parse_datetime(date_value: Any, time_value: Any | None = None) -> datetime | None:
    if isinstance(date_value, datetime) and time_value in (None, ""):
        return date_value.replace(microsecond=0)

    if time_value not in (None, ""):
        parsed_date = _parse_date_part(date_value)
        if parsed_date is None:
            return None
        return datetime.combine(parsed_date, _parse_time_part(time_value))

    text = _cell_text(date_value).replace("：", ":").replace("/", "-")
    text = text.replace("年", "-").replace("月", "-").replace("日", " ")
    match = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?", text)
    if not match:
        return None
    try:
        parsed_date = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        parsed_time = time(int(match.group(4) or "0"), int(match.group(5) or "0"), int(match.group(6) or "0"))
        return datetime.combine(parsed_date, parsed_time)
    except ValueError:
        return None


def _parse_money(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value.quantize(CENT)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return Decimal(str(value)).quantize(CENT)
        except InvalidOperation:
            return None
    text = _cell_text(value)
    if not text:
        return None
    cleaned = (
        text.replace("￥", "")
        .replace("元", "")
        .replace("，", ",")
        .replace("。", ".")
        .replace("．", ".")
        .replace(" ", "")
    )
    direct = money_to_decimal(cleaned)
    if direct is not None:
        return direct
    signed = extract_signed_amount(cleaned)
    if signed is not None:
        return signed
    try:
        return Decimal(re.sub(r"[^0-9.\-]", "", cleaned)).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _direction(text: str) -> str | None:
    compact = _norm(text)
    if any(word in compact for word in ("收入", "贷", "转入", "入账", "收")):
        return "income"
    if any(word in compact for word in ("支出", "借", "转出", "出账", "付")):
        return "expense"
    return None


def _resolve_missing_directions(transactions: list[Transaction]) -> None:
    previous: Transaction | None = None
    for tx in sorted(transactions, key=lambda item: (item.transaction_time, item.row_no)):
        if previous is not None and previous.balance is not None and tx.balance is not None:
            amount = _parse_money(tx.raw_amount)
            if amount is not None and tx.income == 0 and tx.expense == 0:
                if (previous.balance + amount).quantize(CENT) == tx.balance.quantize(CENT):
                    tx.income = amount
                    tx.issues = [issue for issue in tx.issues if issue != "收支方向无法解析"]
                elif (previous.balance - amount).quantize(CENT) == tx.balance.quantize(CENT):
                    tx.expense = amount
                    tx.issues = [issue for issue in tx.issues if issue != "收支方向无法解析"]
                if not tx.issues:
                    tx.status = "ok"
        previous = tx


def _header_mapping(rows: list[tuple[Any, ...]]) -> tuple[int, list[str], dict[str, int]] | None:
    for row_index, row in enumerate(rows[:30]):
        headers = [_norm(cell) for cell in row]
        time_col = _find_col(headers, ("交易时间", "交易日期时间", "日期时间"))
        date_col = time_col if time_col is not None else _find_col(headers, ("交易日期", "记账日期", "日期"))
        separate_time_col = None if time_col is not None else _find_col(headers, ("时间", "交易时刻"))
        amount_col = _find_col(headers, ("交易金额", "发生额", "本次金额", "交易额", "金额"))
        income_col = _find_col(headers, ("收入金额", "收入", "贷方发生额", "贷方", "贷"))
        expense_col = _find_col(headers, ("支出金额", "支出", "借方发生额", "借方", "借"))
        direction_col = _find_col(headers, ("收入/支出", "收入支出", "收支", "借贷标志", "借贷方向", "方向"))

        exclude = {col for col in (amount_col, income_col, expense_col) if col is not None}
        balance_col = _find_col(headers, ("账户余额", "本次余额", "交易余额", "余额", "金额"), exclude)

        if date_col is not None and (amount_col is not None or income_col is not None or expense_col is not None):
            return row_index, headers, {
                "date": date_col,
                "time": separate_time_col,
                "amount": amount_col,
                "income": income_col,
                "expense": expense_col,
                "direction": direction_col,
                "balance": balance_col,
            }
    return None


def _extract_sheet(rows: list[tuple[Any, ...]], sheet_index: int) -> list[Transaction]:
    mapping = _header_mapping(rows)
    if mapping is None:
        return []

    header_row, headers, cols = mapping
    transactions: list[Transaction] = []
    for excel_row_index, row in enumerate(rows[header_row + 1 :], start=header_row + 2):
        tx_time = _parse_datetime(row[cols["date"]] if cols["date"] is not None and cols["date"] < len(row) else None,
                                  row[cols["time"]] if cols["time"] is not None and cols["time"] < len(row) else None)
        if tx_time is None:
            continue

        raw_amount = _cell_text(row[cols["amount"]]) if cols["amount"] is not None and cols["amount"] < len(row) else ""
        raw_balance = _cell_text(row[cols["balance"]]) if cols["balance"] is not None and cols["balance"] < len(row) else ""
        amount = _parse_money(raw_amount)
        balance = _parse_money(raw_balance)
        issues: list[str] = []

        income = _parse_money(row[cols["income"]]) if cols["income"] is not None and cols["income"] < len(row) else None
        expense = _parse_money(row[cols["expense"]]) if cols["expense"] is not None and cols["expense"] < len(row) else None
        if income is not None or expense is not None:
            income = income or Decimal("0.00")
            expense = expense or Decimal("0.00")
            raw_amount = raw_amount or _cell_text(income if income > 0 else expense)
        elif amount is not None:
            raw_direction = _cell_text(row[cols["direction"]]) if cols["direction"] is not None and cols["direction"] < len(row) else ""
            direction = _direction(raw_direction)
            if direction == "income":
                income = amount
                expense = Decimal("0.00")
            elif direction == "expense":
                income = Decimal("0.00")
                expense = amount
            elif amount < 0:
                income = Decimal("0.00")
                expense = abs(amount)
            else:
                income = Decimal("0.00")
                expense = Decimal("0.00")
                issues.append("收支方向无法解析")
        else:
            income = Decimal("0.00")
            expense = Decimal("0.00")
            issues.append("交易金额无法解析")

        if balance is None and cols["balance"] is not None:
            issues.append("余额无法解析")

        transactions.append(
            Transaction(
                transaction_time=tx_time,
                income=income,
                expense=expense,
                balance=balance,
                bank=BANK_NAME,
                page_no=sheet_index,
                row_no=excel_row_index,
                raw_time=_cell_text(row[cols["date"]]),
                raw_amount=raw_amount,
                raw_balance=raw_balance,
                raw_text=" | ".join(_cell_text(cell) for cell in row),
                raw_fields=[_cell_text(cell) for cell in row],
                raw_headers=headers,
                status="ok" if not issues else "review",
                issues=issues,
            )
        )

    _resolve_missing_directions(transactions)
    return transactions


def extract_excel_transactions(path: str) -> list[Transaction]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    best: list[Transaction] = []
    for sheet_index, worksheet in enumerate(workbook.worksheets, start=1):
        rows = list(worksheet.iter_rows(values_only=True))
        transactions = _extract_sheet(rows, sheet_index)
        if len(transactions) > len(best):
            best = transactions
    return best
