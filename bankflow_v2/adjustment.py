from dataclasses import dataclass, field
from decimal import Decimal
import random

from .models import Transaction
from .summary import CENT, ZERO, Summary, monthly_summaries, summarize


WAN = Decimal("10000")
WECHAT_MIN_MONTHLY_NET = Decimal("100.00")
WECHAT_MAX_MONTHLY_NET = Decimal("500.00")


@dataclass
class AdjustmentConfig:
    enabled: bool = False
    amount_wan: Decimal = ZERO
    start_month: str = ""
    end_month: str = ""
    balanced: bool = False
    label: str = ""
    randomized: bool = False


@dataclass
class AdjustmentRow:
    month: str
    original_count: int
    original_income_count: int
    original_income_sum: Decimal
    original_expense_count: int
    original_expense_sum: Decimal
    original_net: Decimal
    original_opening_balance: Decimal | None
    original_closing_balance: Decimal | None
    income_adjustment: Decimal = ZERO
    expense_adjustment: Decimal = ZERO
    adjusted_income_sum: Decimal = ZERO
    adjusted_expense_sum: Decimal = ZERO
    adjusted_net: Decimal = ZERO
    adjusted_opening_balance: Decimal | None = None
    adjusted_closing_balance: Decimal | None = None
    status: str = "正常"
    note: str = ""


@dataclass
class AdjustmentResult:
    rows: list[AdjustmentRow] = field(default_factory=list)
    parameters: list[tuple[str, str]] = field(default_factory=list)
    enabled: bool = False
    warnings: list[str] = field(default_factory=list)
    balanced: bool = False


def parse_amount_wan(text: str) -> Decimal:
    stripped = (text or "").replace(",", "").strip()
    if not stripped:
        return ZERO
    return Decimal(stripped)


def _month_in_range(month: str, start_month: str, end_month: str) -> bool:
    if start_month and month < start_month:
        return False
    if end_month and month > end_month:
        return False
    return True


def split_amount(total: Decimal, parts: int, randomized: bool = False, seed_text: str = "") -> list[Decimal]:
    if parts <= 0:
        return []
    if randomized:
        sign = Decimal("-1") if total < ZERO else Decimal("1")
        source = abs(total)
        rng = random.Random(seed_text or f"{total}:{parts}")
        weights = [Decimal(rng.randint(80, 120)) for _ in range(parts)]
        weight_sum = sum(weights, ZERO)
        amounts = [(source * weight / weight_sum).quantize(CENT) for weight in weights[:-1]]
        amounts.append((source - sum(amounts, ZERO)).quantize(CENT))
        return [(amount * sign).quantize(CENT) for amount in amounts]
    base = (total / Decimal(parts)).quantize(CENT)
    amounts = [base for _ in range(parts)]
    amounts[-1] = (total - sum(amounts[:-1], ZERO)).quantize(CENT)
    return amounts


def _is_wechat_transaction(tx: Transaction) -> bool:
    return getattr(tx, "flow_type", "") == "微信" or getattr(tx, "bank", "") == "微信流水"


def _copy_summary(summary: Summary) -> Summary:
    return Summary(
        count=summary.count,
        income_count=summary.income_count,
        income_sum=summary.income_sum,
        expense_count=summary.expense_count,
        expense_sum=summary.expense_sum,
        net=summary.net,
        opening_balance=summary.opening_balance,
        closing_balance=summary.closing_balance,
        issues=list(summary.issues),
    )


def _sum_summaries(summaries: list[Summary]) -> Summary:
    total = Summary()
    for summary in summaries:
        total.count += summary.count
        total.income_count += summary.income_count
        total.income_sum += summary.income_sum
        total.expense_count += summary.expense_count
        total.expense_sum += summary.expense_sum
    total.income_sum = total.income_sum.quantize(CENT)
    total.expense_sum = total.expense_sum.quantize(CENT)
    total.net = (total.income_sum - total.expense_sum).quantize(CENT)
    return total


def _split_by_weights(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    if not weights:
        return []
    if total <= ZERO:
        return [ZERO for _weight in weights]
    weight_sum = sum(weights, ZERO)
    if weight_sum <= ZERO:
        weights = [Decimal("1") for _weight in weights]
        weight_sum = sum(weights, ZERO)
    amounts = [(total * weight / weight_sum).quantize(CENT) for weight in weights[:-1]]
    amounts.append((total - sum(amounts, ZERO)).quantize(CENT))
    return amounts


def _expense_capacity(index: int, incomes: list[Decimal], reserves: list[Decimal], expenses: list[Decimal]) -> Decimal:
    running_income = ZERO
    running_expense = ZERO
    capacity: Decimal | None = None
    for month_index, (income, expense) in enumerate(zip(incomes, expenses)):
        running_income += income
        running_expense += expense
        if month_index >= index:
            available = (running_income - reserves[month_index] - running_expense).quantize(CENT)
            capacity = available if capacity is None else min(capacity, available)
    return max(capacity or ZERO, ZERO)


def _balance_wechat_month_pairs(month_pairs: list[tuple[str, Summary]]) -> list[tuple[str, Summary]]:
    balanced = [(month, _copy_summary(summary)) for month, summary in month_pairs]
    if not balanced:
        return balanced

    months = [month for month, _summary in balanced]
    by_month = dict(balanced)
    incomes = [by_month[month].income_sum for month in months]
    raw_expenses = [by_month[month].expense_sum for month in months]
    total_income = sum(incomes, ZERO).quantize(CENT)
    if total_income <= ZERO:
        for _month, summary in balanced:
            summary.expense_sum = ZERO
            summary.net = ZERO
        return balanced

    rng_seed = "|".join(
        [
            "wechat_default_expense",
            ",".join(months),
            ",".join(str(income) for income in incomes),
            ",".join(str(expense) for expense in raw_expenses),
        ]
    )
    rng = random.Random(rng_seed)
    reserves: list[Decimal] = []
    running_income = ZERO
    for income in incomes:
        running_income += income
        reserve = Decimal(rng.randint(int(WECHAT_MIN_MONTHLY_NET), int(WECHAT_MAX_MONTHLY_NET))).quantize(CENT)
        reserves.append(min(reserve, running_income).quantize(CENT))

    target_total_expense = max(total_income - reserves[-1], ZERO).quantize(CENT)
    expenses = _split_by_weights(target_total_expense, raw_expenses)

    running_income = ZERO
    running_expense = ZERO
    for index, income in enumerate(incomes):
        running_income += income
        running_expense += expenses[index]
        limit = (running_income - reserves[index]).quantize(CENT)
        if running_expense > limit:
            reduction = min(expenses[index], (running_expense - limit).quantize(CENT))
            expenses[index] = (expenses[index] - reduction).quantize(CENT)
            running_expense = (running_expense - reduction).quantize(CENT)

    remaining = (target_total_expense - sum(expenses, ZERO)).quantize(CENT)
    for index in range(len(expenses) - 1, -1, -1):
        if remaining <= ZERO:
            break
        addition = min(_expense_capacity(index, incomes, reserves, expenses), remaining).quantize(CENT)
        expenses[index] = (expenses[index] + addition).quantize(CENT)
        remaining = (remaining - addition).quantize(CENT)

    for month, expense in zip(months, expenses):
        summary = by_month[month]
        summary.expense_sum = max(expense, ZERO).quantize(CENT)
        summary.net = (summary.income_sum - summary.expense_sum).quantize(CENT)
    return balanced


def apply_adjustments(transactions: list[Transaction], configs: list[AdjustmentConfig]) -> AdjustmentResult:
    enabled_configs = [config for config in configs if config.enabled]
    active_configs = [config for config in enabled_configs if config.amount_wan != ZERO]
    warnings = [f"{config.label}已启用，但调整金额为空或为 0" for config in enabled_configs if config.amount_wan == ZERO]
    balanced = any(config.balanced for config in enabled_configs)
    rows: list[AdjustmentRow] = []
    wechat_income_mode = (
        bool(active_configs)
        and not balanced
        and bool(transactions)
        and all(_is_wechat_transaction(tx) for tx in transactions)
    )
    raw_month_pairs = monthly_summaries(transactions)
    raw_summary_by_month = dict(raw_month_pairs)
    month_pairs = _balance_wechat_month_pairs(raw_month_pairs) if wechat_income_mode else raw_month_pairs
    months = [month for month, _ in month_pairs]
    summary_by_month = dict(month_pairs)
    allocations: dict[str, tuple[Decimal, Decimal, list[str]]] = {
        month: (ZERO, ZERO, []) for month in months
    }

    parameters: list[tuple[str, str]] = [("是否启用调整", "是" if enabled_configs else "否")]
    for warning in warnings:
        parameters.append(("提示", warning))
    for config in active_configs:
        target_months = [month for month in months if _month_in_range(month, config.start_month, config.end_month)]
        total = (config.amount_wan * WAN).quantize(CENT)
        seed_text = "|".join([config.label, str(total), config.start_month, config.end_month, str(config.balanced), ",".join(target_months)])
        split = split_amount(total, len(target_months), config.randomized, seed_text)
        monthly_amount = (total / Decimal(len(target_months))).quantize(CENT) if target_months else ZERO
        distribution_note = "随机分配" if config.randomized else "平均分配"
        parameters.extend(
            [
                ("调整类型", config.label),
                ("调整金额", f"{total:.2f}"),
                ("分配方式", distribution_note),
                ("调整月份", f"{config.start_month} 至 {config.end_month}"),
                ("参与月份数", str(len(target_months))),
                ("月均收入调整", f"{monthly_amount:.2f}" if split else "0.00"),
                ("月均支出平衡", f"{monthly_amount:.2f}" if config.balanced and split else "0.00"),
            ]
        )
        for month, amount in zip(target_months, split):
            income_adjustment, expense_adjustment, notes = allocations[month]
            income_adjustment += amount
            if config.balanced:
                expense_adjustment += amount
                notes.append(f"收支平衡调整（{distribution_note}）")
            else:
                notes.append(f"收入调整（{distribution_note}）")
            allocations[month] = (income_adjustment.quantize(CENT), expense_adjustment.quantize(CENT), notes)

    wechat_adjusted_by_month: dict[str, Summary] = {}
    if wechat_income_mode:
        adjusted_month_pairs = []
        for month, summary in month_pairs:
            income_adjustment, expense_adjustment, _notes = allocations[month]
            adjusted_summary = _copy_summary(raw_summary_by_month[month])
            adjusted_summary.income_sum = (adjusted_summary.income_sum + income_adjustment).quantize(CENT)
            adjusted_summary.expense_sum = (adjusted_summary.expense_sum + expense_adjustment).quantize(CENT)
            adjusted_summary.net = (adjusted_summary.income_sum - adjusted_summary.expense_sum).quantize(CENT)
            adjusted_month_pairs.append((month, adjusted_summary))
        wechat_adjusted_by_month = dict(_balance_wechat_month_pairs(adjusted_month_pairs))

    previous_adjusted_closing: Decimal | None = None
    for month in months:
        summary = summary_by_month[month]
        income_adjustment, expense_adjustment, notes = allocations[month]
        adjusted_income = (summary.income_sum + income_adjustment).quantize(CENT)
        adjusted_expense = (summary.expense_sum + expense_adjustment).quantize(CENT)
        if wechat_income_mode:
            adjusted_summary = wechat_adjusted_by_month[month]
            adjusted_income = adjusted_summary.income_sum
            adjusted_expense = adjusted_summary.expense_sum
        adjusted_net = (adjusted_income - adjusted_expense).quantize(CENT)

        if previous_adjusted_closing is None:
            adjusted_opening = summary.opening_balance if summary.opening_balance is not None else ZERO
        else:
            adjusted_opening = previous_adjusted_closing
        adjusted_closing = (adjusted_opening + adjusted_income - adjusted_expense).quantize(CENT)
        status = "正常" if adjusted_closing >= ZERO else "需复核"
        if income_adjustment == ZERO and expense_adjustment == ZERO:
            note = ""
        else:
            note = "；".join(dict.fromkeys(notes))

        rows.append(
            AdjustmentRow(
                month=month,
                original_count=summary.count,
                original_income_count=summary.income_count,
                original_income_sum=summary.income_sum,
                original_expense_count=summary.expense_count,
                original_expense_sum=summary.expense_sum,
                original_net=summary.net,
                original_opening_balance=summary.opening_balance,
                original_closing_balance=summary.closing_balance,
                income_adjustment=income_adjustment,
                expense_adjustment=expense_adjustment,
                adjusted_income_sum=adjusted_income,
                adjusted_expense_sum=adjusted_expense,
                adjusted_net=adjusted_net,
                adjusted_opening_balance=adjusted_opening,
                adjusted_closing_balance=adjusted_closing,
                status=status,
                note=note,
            )
        )
        previous_adjusted_closing = adjusted_closing

    if rows:
        original_total = _sum_summaries(list(summary_by_month.values())) if wechat_income_mode else summarize(transactions, "调整前总计")
        income_adjustment = sum((row.income_adjustment for row in rows), ZERO).quantize(CENT)
        expense_adjustment = sum((row.expense_adjustment for row in rows), ZERO).quantize(CENT)
        if wechat_income_mode:
            adjusted_income = sum((row.adjusted_income_sum for row in rows), ZERO).quantize(CENT)
            adjusted_expense = sum((row.adjusted_expense_sum for row in rows), ZERO).quantize(CENT)
        else:
            adjusted_income = (original_total.income_sum + income_adjustment).quantize(CENT)
            adjusted_expense = (original_total.expense_sum + expense_adjustment).quantize(CENT)
        adjusted_opening = rows[0].adjusted_opening_balance
        adjusted_closing = rows[-1].adjusted_closing_balance
        rows.append(
            AdjustmentRow(
                month="总计",
                original_count=original_total.count,
                original_income_count=original_total.income_count,
                original_income_sum=original_total.income_sum,
                original_expense_count=original_total.expense_count,
                original_expense_sum=original_total.expense_sum,
                original_net=original_total.net,
                original_opening_balance=original_total.opening_balance,
                original_closing_balance=original_total.closing_balance,
                income_adjustment=income_adjustment,
                expense_adjustment=expense_adjustment,
                adjusted_income_sum=adjusted_income,
                adjusted_expense_sum=adjusted_expense,
                adjusted_net=(adjusted_income - adjusted_expense).quantize(CENT),
                adjusted_opening_balance=adjusted_opening,
                adjusted_closing_balance=adjusted_closing,
                status="需复核" if any(row.status == "需复核" for row in rows) else "正常",
                note="汇总",
            )
        )

    return AdjustmentResult(rows=rows, parameters=parameters, enabled=bool(enabled_configs), warnings=warnings, balanced=balanced)
