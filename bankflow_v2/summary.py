from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .models import Transaction


CENT = Decimal("0.01")
ZERO = Decimal("0.00")


@dataclass
class Issue:
    level: str
    source: str
    time: str
    message: str
    raw_amount: str = ""
    raw_balance: str = ""


@dataclass
class Summary:
    count: int = 0
    income_count: int = 0
    income_sum: Decimal = ZERO
    expense_count: int = 0
    expense_sum: Decimal = ZERO
    net: Decimal = ZERO
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    issues: list[Issue] = field(default_factory=list)


def money(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value.quantize(CENT):,.2f}"


def _has_explicit_time(tx: Transaction) -> bool:
    raw_time = getattr(tx, "raw_time", "") or ""
    if any(char == ":" for char in raw_time):
        return True
    digits = "".join(char for char in raw_time if char.isdigit())
    return len(digits) >= 14


def sort_transactions(transactions: list[Transaction]) -> list[Transaction]:
    date_has_partial_time: dict[object, bool] = defaultdict(bool)
    for tx in transactions:
        date_key = tx.transaction_time.date()
        if not _has_explicit_time(tx):
            date_has_partial_time[date_key] = True

    def sort_key(tx: Transaction):
        date_key = tx.transaction_time.date()
        if date_has_partial_time[date_key]:
            return (date_key, tx.page_no, tx.row_no)
        return (date_key, tx.transaction_time.time(), tx.page_no, tx.row_no)

    return sorted(transactions, key=sort_key)


def needs_total_balance_check(transactions: list[Transaction]) -> bool:
    if not transactions:
        return False
    if all(getattr(tx, "bank", "") == "微信流水" for tx in transactions):
        return False
    if all(getattr(tx, "balance_optional", False) for tx in transactions):
        return False
    return True


def summarize(transactions: list[Transaction], source: str = "") -> Summary:
    ordered = sort_transactions(transactions)
    summary = Summary()

    for tx in ordered:
        if getattr(tx, "neutral", False):
            continue
        summary.count += 1
        if getattr(tx, "preserve_signed_columns", False):
            if tx.income != ZERO:
                summary.income_count += 1
                summary.income_sum += tx.income
            if tx.expense != ZERO:
                summary.expense_count += 1
                summary.expense_sum += tx.expense
        else:
            if tx.amount >= ZERO:
                summary.income_count += 1
                summary.income_sum += tx.income
            if tx.expense > ZERO:
                summary.expense_count += 1
                summary.expense_sum += tx.expense

    summary.income_sum = summary.income_sum.quantize(CENT)
    summary.expense_sum = summary.expense_sum.quantize(CENT)
    summary.net = (summary.income_sum - summary.expense_sum).quantize(CENT)

    if ordered and ordered[0].balance is not None:
        first = ordered[0]
        summary.opening_balance = (first.balance - first.income + first.expense).quantize(CENT)
    if ordered and ordered[-1].balance is not None:
        summary.closing_balance = ordered[-1].balance.quantize(CENT)

    summary.issues = collect_issues(ordered, source)
    if (
        needs_total_balance_check(ordered)
        and summary.opening_balance is not None
        and summary.closing_balance is not None
    ):
        balance_change = (summary.closing_balance - summary.opening_balance).quantize(CENT)
        if summary.net != balance_change:
            summary.issues.append(
                Issue(
                    "需复核",
                    source,
                    "",
                    (
                        f"收支余额不闭合: 收入 {money(summary.income_sum)} - 支出 {money(summary.expense_sum)} "
                        f"= 净额 {money(summary.net)}, 期末余额 {money(summary.closing_balance)} "
                        f"- 期初余额 {money(summary.opening_balance)} = 余额变动 {money(balance_change)}"
                    ),
                )
            )
    return summary


def monthly_summaries(transactions: list[Transaction]) -> list[tuple[str, Summary]]:
    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for tx in transactions:
        grouped[tx.transaction_time.strftime("%Y-%m")].append(tx)
    return [(month, summarize(items, month)) for month, items in sorted(grouped.items())]


def collect_issues(transactions: list[Transaction], source: str = "") -> list[Issue]:
    issues: list[Issue] = []
    previous: Transaction | None = None

    for tx in sort_transactions(transactions):
        where = source or Path(getattr(tx, "source_file", "")).name
        time_text = tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S")

        if tx.status != "ok" or tx.issues:
            for message in tx.issues or ["解析状态需复核"]:
                issues.append(Issue("需复核", where, time_text, message, tx.raw_amount, tx.raw_balance))

        if tx.balance is None and not getattr(tx, "balance_optional", False):
            issues.append(Issue("需复核", where, time_text, "余额缺失", tx.raw_amount, tx.raw_balance))

        if previous is not None and previous.balance is not None and tx.balance is not None:
            expected = (previous.balance + tx.income - tx.expense).quantize(CENT)
            actual = tx.balance.quantize(CENT)
            if expected != actual:
                tolerance = getattr(tx, "balance_tolerance", ZERO) or ZERO
                level = "低风险" if abs(expected - actual) <= tolerance else "需复核"
                issues.append(
                    Issue(
                        level,
                        where,
                        time_text,
                        f"余额不连续: 上笔余额 {money(previous.balance)} + 收入 {money(tx.income)} - 支出 {money(tx.expense)} = {money(expected)}, 当前余额 {money(tx.balance)}",
                        tx.raw_amount,
                        tx.raw_balance,
                    )
                )

        previous = tx

    return issues
