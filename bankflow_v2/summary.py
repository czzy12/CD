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


def sort_transactions(transactions: list[Transaction]) -> list[Transaction]:
    return sorted(transactions, key=lambda tx: (tx.transaction_time, tx.page_no, tx.row_no))


def summarize(transactions: list[Transaction], source: str = "") -> Summary:
    ordered = sort_transactions(transactions)
    summary = Summary()

    for tx in ordered:
        if getattr(tx, "neutral", False):
            continue
        summary.count += 1
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
            if expected != tx.balance.quantize(CENT):
                issues.append(
                    Issue(
                        "需复核",
                        where,
                        time_text,
                        f"余额不连续: 上笔余额 {money(previous.balance)} + 收入 {money(tx.income)} - 支出 {money(tx.expense)} = {money(expected)}, 当前余额 {money(tx.balance)}",
                        tx.raw_amount,
                        tx.raw_balance,
                    )
                )

        previous = tx

    return issues
