"""Versioned evidence JSON for downstream bank-flow verification."""

from __future__ import annotations

import json
import re
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from .models import Transaction, get_statement_metadata
from .summary import Summary, sort_transactions, summarize


SCHEMA_VERSION = "1.7"


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _date(value: date | datetime | None) -> str:
    return value.isoformat() if value is not None else ""


def _transaction_record(transaction: Transaction) -> dict[str, object]:
    return {
        "transaction_id": transaction.transaction_id,
        "source_file_id": transaction.source_file_id,
        "source_file": transaction.source_file,
        "evidence_locator": transaction.evidence_locator,
        "bank": transaction.bank,
        "transaction_time": transaction.transaction_time.isoformat(),
        "income": _decimal(transaction.income),
        "expense": _decimal(transaction.expense),
        "balance": _decimal(transaction.balance),
        "neutral": bool(getattr(transaction, "neutral", False)),
        "status": transaction.status,
        "issues": list(transaction.issues),
        "original": {
            "raw_time": transaction.raw_time,
            "raw_amount": transaction.raw_amount,
            "raw_balance": transaction.raw_balance,
            "raw_text": transaction.raw_text,
            "raw_headers": list(transaction.raw_headers),
            "raw_fields": list(transaction.raw_fields),
            "source_fields": dict(transaction.source_fields),
        },
        "standard_fields": {
            "counterparty_name": transaction.counterparty_name,
            "counterparty_account": transaction.counterparty_account,
            "counterparty_bank": transaction.counterparty_bank,
            "summary": transaction.summary,
            "remark": transaction.remark,
            "purpose": transaction.purpose,
            "transaction_type": transaction.transaction_type,
            "transaction_direction": transaction.transaction_direction,
            "transaction_method": transaction.transaction_method,
            "payment_method": transaction.payment_method,
            "product_description": transaction.product_description,
            "merchant_name": transaction.merchant_name,
            "merchant_category": transaction.merchant_category,
            "merchant_location": transaction.merchant_location,
            "field_sources": dict(transaction.field_sources),
            "field_confidence": dict(transaction.field_confidence),
        },
        "manual_review": dict(transaction.manual_review),
    }


def _summary_record(summary: Summary) -> dict[str, object]:
    return {
        "count": summary.count,
        "income_count": summary.income_count,
        "income_sum": _decimal(summary.income_sum),
        "expense_count": summary.expense_count,
        "expense_sum": _decimal(summary.expense_sum),
        "net": _decimal(summary.net),
        "opening_balance": _decimal(summary.opening_balance),
        "closing_balance": _decimal(summary.closing_balance),
    }


def _source_files(transactions: list[Transaction]) -> list[dict[str, object]]:
    sources: dict[tuple[str, str], int] = {}
    for transaction in transactions:
        key = (transaction.source_file_id, transaction.source_file)
        sources[key] = sources.get(key, 0) + 1
    return [
        {"source_file_id": source_id, "source_file": source_file, "transaction_count": count}
        for (source_id, source_file), count in sorted(sources.items())
    ]


def _transaction_ids(transactions: list[Transaction]) -> list[str]:
    return [transaction.transaction_id for transaction in transactions if transaction.transaction_id]


def _ratio(numerator: int | Decimal, denominator: int | Decimal) -> str | None:
    if denominator == 0:
        return None
    return f"{Decimal(numerator) / Decimal(denominator):.4f}"


def _coverage(
    required_fields: list[str],
    eligible_transactions: list[Transaction],
    covered_transactions: list[Transaction],
) -> dict[str, object]:
    return {
        "required_fields": required_fields,
        "eligible_transaction_count": len(eligible_transactions),
        "covered_transaction_count": len(covered_transactions),
        "transaction_coverage_rate": _ratio(
            len(covered_transactions), len(eligible_transactions)
        ),
    }


def _indicator(
    indicator_type: str,
    value: dict[str, object],
    parameters: dict[str, object],
    evidence_transactions: list[Transaction],
    field_coverage: dict[str, object],
) -> dict[str, object]:
    return {
        "indicator_type": indicator_type,
        "value": value,
        "parameters": parameters,
        "evidence_transaction_ids": _transaction_ids(evidence_transactions),
        "field_coverage": field_coverage,
    }


def _fact(
    fact_type: str, value: str | int, evidence_transactions: list[Transaction]
) -> dict[str, object]:
    return {
        "fact_type": fact_type,
        "value": value,
        "evidence_transaction_ids": _transaction_ids(evidence_transactions),
    }


def _facts(transactions: list[Transaction], summary: Summary) -> list[dict[str, object]]:
    ordered = sort_transactions(transactions)
    counted = [transaction for transaction in ordered if not getattr(transaction, "neutral", False)]
    facts = [
        _fact("transaction_count", summary.count, counted),
        _fact(
            "income_total",
            _decimal(summary.income_sum) or "0.00",
            [transaction for transaction in counted if transaction.income != Decimal("0.00")],
        ),
        _fact(
            "expense_total",
            _decimal(summary.expense_sum) or "0.00",
            [transaction for transaction in counted if transaction.expense != Decimal("0.00")],
        ),
        _fact("net_amount", _decimal(summary.net) or "0.00", counted),
    ]
    if ordered:
        facts.extend(
            [
                _fact("period_start", ordered[0].transaction_time.isoformat(), [ordered[0]]),
                _fact("period_end", ordered[-1].transaction_time.isoformat(), [ordered[-1]]),
            ]
        )
    if summary.opening_balance is not None and ordered:
        facts.append(_fact("opening_balance", _decimal(summary.opening_balance) or "0.00", [ordered[0]]))
    if summary.closing_balance is not None and ordered:
        facts.append(_fact("closing_balance", _decimal(summary.closing_balance) or "0.00", [ordered[-1]]))
    return facts


def _directional_transactions(
    transactions: list[Transaction], direction: str
) -> list[Transaction]:
    amount_field = "income" if direction == "income" else "expense"
    return [
        transaction
        for transaction in sort_transactions(transactions)
        if not getattr(transaction, "neutral", False)
        and getattr(transaction, amount_field) != Decimal("0.00")
    ]


def _month_key(value: date | datetime) -> tuple[int, int]:
    return value.year, value.month


def _month_text(value: tuple[int, int]) -> str:
    return f"{value[0]:04d}-{value[1]:02d}"


def _next_month(value: tuple[int, int]) -> tuple[int, int]:
    year, month = value
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _calendar_months(
    start: date | datetime, end: date | datetime
) -> list[tuple[int, int]]:
    current = _month_key(start)
    end_month = _month_key(end)
    months: list[tuple[int, int]] = []
    while current <= end_month:
        months.append(current)
        current = _next_month(current)
    return months


def _time_proximity_indicator(
    transactions: list[Transaction], window_days: int
) -> dict[str, object]:
    ordered = sort_transactions(transactions)
    incomes = _directional_transactions(ordered, "income")
    expenses = _directional_transactions(ordered, "expense")
    expense_times = [transaction.transaction_time for transaction in expenses]
    matched_income_ids: set[int] = set()
    expense_match_counts = [0] * (len(expenses) + 1)
    pair_count = 0

    for income in incomes:
        start = bisect_left(expense_times, income.transaction_time)
        end = bisect_right(
            expense_times, income.transaction_time + timedelta(days=window_days)
        )
        if start == end:
            continue
        pair_count += end - start
        matched_income_ids.add(id(income))
        expense_match_counts[start] += 1
        expense_match_counts[end] -= 1

    matched_expense_ids: set[int] = set()
    active_matches = 0
    for index, expense in enumerate(expenses):
        active_matches += expense_match_counts[index]
        if active_matches:
            matched_expense_ids.add(id(expense))

    matched_ids = matched_income_ids | matched_expense_ids
    evidence = [transaction for transaction in ordered if id(transaction) in matched_ids]
    eligible = [
        transaction
        for transaction in ordered
        if transaction.income != Decimal("0.00")
        or transaction.expense != Decimal("0.00")
    ]
    covered = [transaction for transaction in eligible if transaction.transaction_id]
    available = bool(incomes and expenses)

    return _indicator(
        "fund_time_proximity",
        {
            "available": available,
            "reason": "" if available else "income_or_expense_transactions_unavailable",
            "time_proximity_pair_count": pair_count,
            "income_transaction_count_with_later_expense": len(matched_income_ids),
            "later_expense_transaction_count": len(matched_expense_ids),
        },
        {
            "window_days": window_days,
            "window_start_inclusive": True,
            "window_end_inclusive": True,
            "sequence": "income_then_expense",
            "interpretation": "仅表示时间窗口内先收入后支出共现，不表示支出资金来源于某笔收入。",
        },
        evidence,
        _coverage(
            ["transaction_time", "income", "expense", "transaction_id"],
            eligible,
            covered,
        ),
    )


def _income_continuity_indicator(
    transactions: list[Transaction],
) -> dict[str, object]:
    ordered = [
        transaction
        for transaction in sort_transactions(transactions)
        if not getattr(transaction, "neutral", False)
    ]
    income_transactions = [
        transaction
        for transaction in ordered
        if transaction.income != Decimal("0.00")
    ]
    covered = [transaction for transaction in ordered if transaction.transaction_id]

    if not ordered:
        return _indicator(
            "income_continuity",
            {
                "available": False,
                "reason": "no_transactions",
                "period_month_count": 0,
                "income_month_count": 0,
                "income_month_coverage_rate": None,
                "longest_consecutive_income_month_count": 0,
                "income_months": [],
                "months_without_income": [],
            },
            {
                "bucket": "calendar_month",
                "period_start_month_inclusive": True,
                "period_end_month_inclusive": True,
                "interpretation": "仅表示数据期内非零收入的月份分布，不表示工资稳定性、经营真实性或还款能力。",
            },
            [],
            _coverage(
                ["transaction_time", "income", "transaction_id"],
                ordered,
                covered,
            ),
        )

    months = _calendar_months(
        ordered[0].transaction_time, ordered[-1].transaction_time
    )
    income_month_set = {
        _month_key(transaction.transaction_time)
        for transaction in income_transactions
    }
    longest_run = 0
    current_run = 0
    for month in months:
        if month in income_month_set:
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0

    return _indicator(
        "income_continuity",
        {
            "available": True,
            "reason": "",
            "period_month_count": len(months),
            "income_month_count": len(income_month_set),
            "income_month_coverage_rate": _ratio(
                len(income_month_set), len(months)
            ),
            "longest_consecutive_income_month_count": longest_run,
            "income_months": [
                _month_text(month) for month in months if month in income_month_set
            ],
            "months_without_income": [
                _month_text(month) for month in months if month not in income_month_set
            ],
        },
        {
            "bucket": "calendar_month",
            "period_start_month_inclusive": True,
            "period_end_month_inclusive": True,
            "interpretation": "仅表示数据期内非零收入的月份分布，不表示工资稳定性、经营真实性或还款能力。",
        },
        income_transactions,
        _coverage(
            ["transaction_time", "income", "transaction_id"],
            ordered,
            covered,
        ),
    )


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal("2")


def _balance_observation_indicator(
    transactions: list[Transaction],
) -> dict[str, object]:
    ordered = sort_transactions(transactions)
    balance_transactions = [
        transaction for transaction in ordered if transaction.balance is not None
    ]
    covered = [
        transaction
        for transaction in ordered
        if transaction.balance is not None
        and transaction.source_file_id
        and transaction.transaction_id
    ]
    daily_snapshots: dict[tuple[str, date], Transaction] = {}
    for transaction in balance_transactions:
        if not transaction.source_file_id:
            continue
        daily_snapshots[
            (transaction.source_file_id, transaction.transaction_time.date())
        ] = transaction

    snapshots = sort_transactions(list(daily_snapshots.values()))
    balances = [
        transaction.balance
        for transaction in snapshots
        if transaction.balance is not None
    ]
    available = bool(balances)
    value: dict[str, object] = {
        "available": available,
        "reason": "" if available else "traceable_balance_snapshots_unavailable",
        "balance_transaction_count": len(balance_transactions),
        "daily_snapshot_count": len(snapshots),
        "source_file_count": len(
            {transaction.source_file_id for transaction in snapshots}
        ),
        "minimum_balance": None,
        "median_balance": None,
        "average_balance": None,
        "latest_snapshot_balance": None,
        "positive_balance_snapshot_count": 0,
        "positive_balance_snapshot_share": None,
    }
    if balances:
        positive_count = sum(balance > Decimal("0.00") for balance in balances)
        value.update(
            {
                "minimum_balance": _decimal(min(balances)),
                "median_balance": _decimal(_median(balances)),
                "average_balance": _decimal(
                    sum(balances, Decimal("0.00")) / Decimal(len(balances))
                ),
                "latest_snapshot_balance": _decimal(balances[-1]),
                "positive_balance_snapshot_count": positive_count,
                "positive_balance_snapshot_share": _ratio(
                    positive_count, len(balances)
                ),
            }
        )

    return _indicator(
        "balance_observation",
        value,
        {
            "group_by": ["source_file_id", "calendar_date"],
            "snapshot_selection": "last_transaction_with_balance",
            "aggregation_is_not": ["daily_average_balance", "merged_account_balance"],
            "interpretation": "仅描述逐来源文件的日末交易后余额快照，不表示资金充足或账户日均余额。",
        },
        snapshots,
        _coverage(
            [
                "transaction_time",
                "balance",
                "source_file_id",
                "transaction_id",
            ],
            ordered,
            covered,
        ),
    )


def _amount_shape_indicator(
    transactions: list[Transaction],
) -> dict[str, object]:
    eligible = [
        transaction
        for transaction in sort_transactions(transactions)
        if not getattr(transaction, "neutral", False)
        and (
            transaction.income != Decimal("0.00")
            or transaction.expense != Decimal("0.00")
        )
    ]
    covered = [transaction for transaction in eligible if transaction.transaction_id]
    amounts = [
        abs(transaction.income) + abs(transaction.expense)
        for transaction in eligible
    ]
    units = (1, 100, 1000)
    rounding_units: dict[str, dict[str, object]] = {}
    for unit in units:
        count = sum(amount % Decimal(unit) == Decimal("0.00") for amount in amounts)
        rounding_units[str(unit)] = {
            "transaction_count": count,
            "transaction_share": _ratio(count, len(amounts)),
        }

    return _indicator(
        "amount_shape",
        {
            "available": bool(amounts),
            "reason": "" if amounts else "no_income_or_expense_transactions",
            "transaction_count": len(amounts),
            "rounding_units": rounding_units,
        },
        {
            "rounding_units_yuan": list(units),
            "amount_basis": "absolute_income_plus_absolute_expense_per_transaction",
            "units_are_cumulative": True,
            "interpretation": "仅表示金额能否被固定单位整除，不表示流水包装或异常。",
        },
        eligible,
        _coverage(
            ["income", "expense", "transaction_id"],
            eligible,
            covered,
        ),
    )


def _cashflow_scale_and_recent_change_indicator(
    transactions: list[Transaction],
) -> dict[str, object]:
    ordered = [
        transaction
        for transaction in sort_transactions(transactions)
        if not getattr(transaction, "neutral", False)
    ]
    eligible = [
        transaction
        for transaction in ordered
        if transaction.income != Decimal("0.00")
        or transaction.expense != Decimal("0.00")
    ]
    covered = [transaction for transaction in eligible if transaction.transaction_id]
    if not ordered:
        return _indicator(
            "cashflow_scale_and_recent_change",
            {
                "available": False,
                "reason": "no_transactions",
                "full_period": {
                    "month_count": 0,
                    "monthly_average_income": None,
                    "monthly_average_expense": None,
                },
                "recent_comparison": {
                    "available": False,
                    "reason": "insufficient_six_calendar_month_period",
                },
            },
            {
                "bucket": "calendar_month",
                "window_months": 3,
                "anchor": "last_transaction_calendar_month",
                "zero_transaction_months_included": True,
                "boundary_months_may_be_partial": True,
                "interpretation": "仅表示本次数据覆盖期内的收支规模和数值变化，不表示业务趋势或风险。",
            },
            [],
            _coverage(
                ["transaction_time", "income", "expense", "transaction_id"],
                eligible,
                covered,
            ),
        )

    months = _calendar_months(
        ordered[0].transaction_time, ordered[-1].transaction_time
    )
    monthly = {
        month: {"income": Decimal("0.00"), "expense": Decimal("0.00")}
        for month in months
    }
    for transaction in ordered:
        bucket = monthly[_month_key(transaction.transaction_time)]
        bucket["income"] += transaction.income
        bucket["expense"] += transaction.expense

    total_income = sum(
        (monthly[month]["income"] for month in months), Decimal("0.00")
    )
    total_expense = sum(
        (monthly[month]["expense"] for month in months), Decimal("0.00")
    )
    full_period = {
        "month_count": len(months),
        "period_start_month": _month_text(months[0]),
        "period_end_month": _month_text(months[-1]),
        "monthly_average_income": _decimal(
            total_income / Decimal(len(months))
        ),
        "monthly_average_expense": _decimal(
            total_expense / Decimal(len(months))
        ),
    }
    comparison: dict[str, object] = {
        "available": False,
        "reason": "insufficient_six_calendar_month_period",
    }
    if len(months) >= 6:
        previous_months = months[-6:-3]
        recent_months = months[-3:]
        previous_income = sum(
            (monthly[month]["income"] for month in previous_months),
            Decimal("0.00"),
        )
        recent_income = sum(
            (monthly[month]["income"] for month in recent_months),
            Decimal("0.00"),
        )
        previous_expense = sum(
            (monthly[month]["expense"] for month in previous_months),
            Decimal("0.00"),
        )
        recent_expense = sum(
            (monthly[month]["expense"] for month in recent_months),
            Decimal("0.00"),
        )
        comparison = {
            "available": True,
            "reason": "",
            "previous_window_start_month": _month_text(previous_months[0]),
            "previous_window_end_month": _month_text(previous_months[-1]),
            "recent_window_start_month": _month_text(recent_months[0]),
            "recent_window_end_month": _month_text(recent_months[-1]),
            "previous_window_income": _decimal(previous_income),
            "recent_window_income": _decimal(recent_income),
            "income_change": _decimal(recent_income - previous_income),
            "income_change_rate": _ratio(
                recent_income - previous_income, previous_income
            ),
            "previous_window_expense": _decimal(previous_expense),
            "recent_window_expense": _decimal(recent_expense),
            "expense_change": _decimal(recent_expense - previous_expense),
            "expense_change_rate": _ratio(
                recent_expense - previous_expense, previous_expense
            ),
        }

    return _indicator(
        "cashflow_scale_and_recent_change",
        {
            "available": True,
            "reason": "",
            "full_period": full_period,
            "recent_comparison": comparison,
        },
        {
            "bucket": "calendar_month",
            "window_months": 3,
            "anchor": "last_transaction_calendar_month",
            "zero_transaction_months_included": True,
            "boundary_months_may_be_partial": True,
            "interpretation": "仅表示本次数据覆盖期内的收支规模和数值变化，不表示业务趋势或风险。",
        },
        eligible,
        _coverage(
            ["transaction_time", "income", "expense", "transaction_id"],
            eligible,
            covered,
        ),
    )


def _reliable_counterparty(
    transaction: Transaction,
) -> tuple[str, str] | None:
    for field_name in ("counterparty_account", "counterparty_name"):
        value = str(getattr(transaction, field_name) or "").strip()
        if value and transaction.field_confidence.get(field_name) == 1.0:
            return field_name, value
    return None


def _counterparty_concentration_indicator(
    transactions: list[Transaction], direction: str
) -> dict[str, object]:
    eligible = _directional_transactions(transactions, direction)
    amount_field = "income" if direction == "income" else "expense"
    groups: dict[tuple[str, str], dict[str, object]] = {}
    covered: list[Transaction] = []

    for transaction in eligible:
        identity = _reliable_counterparty(transaction)
        if identity is None:
            continue
        covered.append(transaction)
        group = groups.setdefault(
            identity,
            {"transaction_count": 0, "amount": Decimal("0.00")},
        )
        group["transaction_count"] = int(group["transaction_count"]) + 1
        group["amount"] = Decimal(group["amount"]) + abs(
            getattr(transaction, amount_field)
        )

    eligible_amount = sum(
        (abs(getattr(transaction, amount_field)) for transaction in eligible),
        Decimal("0.00"),
    )
    covered_amount = sum(
        (abs(getattr(transaction, amount_field)) for transaction in covered),
        Decimal("0.00"),
    )
    available = bool(groups)
    value: dict[str, object] = {
        "available": available,
        "reason": (
            ""
            if available
            else (
                "reliable_counterparty_fields_unavailable"
                if eligible
                else f"no_{direction}_transactions"
            )
        ),
        "distinct_counterparty_count": len(groups),
        "top_counterparty": None,
    }

    if groups:
        identity, top = sorted(
            groups.items(),
            key=lambda item: (
                -Decimal(item[1]["amount"]),
                -int(item[1]["transaction_count"]),
                item[0][0],
                item[0][1],
            ),
        )[0]
        value["top_counterparty"] = {
            "identity_field": identity[0],
            "identity_value": identity[1],
            "transaction_count": top["transaction_count"],
            "amount": _decimal(Decimal(top["amount"])),
            "covered_amount_share": _ratio(Decimal(top["amount"]), covered_amount),
        }

    field_coverage = _coverage(
        ["counterparty_account_or_name", "field_confidence", amount_field],
        eligible,
        covered,
    )
    field_coverage.update(
        {
            "eligible_amount": _decimal(eligible_amount),
            "covered_amount": _decimal(covered_amount),
            "amount_coverage_rate": _ratio(covered_amount, eligible_amount),
        }
    )
    return _indicator(
        f"{direction}_counterparty_concentration",
        value,
        {
            "direction": direction,
            "identity_priority": ["counterparty_account", "counterparty_name"],
            "reliability_rule": "non_empty_and_field_confidence_equals_1.0",
            "amount_basis": f"absolute_{amount_field}",
            "concentration_measure": "top_counterparty_share_of_covered_amount",
        },
        covered,
        field_coverage,
    )


def _availability_and_evidence_indicator(
    transactions: list[Transaction],
) -> dict[str, object]:
    ordered = sort_transactions(transactions)
    incomes = _directional_transactions(ordered, "income")
    expenses = _directional_transactions(ordered, "expense")
    income_counterparties = [
        transaction for transaction in incomes if _reliable_counterparty(transaction)
    ]
    expense_counterparties = [
        transaction for transaction in expenses if _reliable_counterparty(transaction)
    ]
    fully_traceable = [
        transaction
        for transaction in ordered
        if transaction.transaction_id
        and transaction.source_file_id
        and transaction.evidence_locator
    ]
    linked = [transaction for transaction in ordered if transaction.transaction_id]

    return _indicator(
        "indicator_availability_and_evidence_coverage",
        {
            "availability": {
                "fund_time_proximity": bool(incomes and expenses),
                "income_counterparty_concentration": bool(income_counterparties),
                "expense_counterparty_concentration": bool(expense_counterparties),
                "income_continuity": bool(ordered),
                "balance_observation": any(
                    transaction.balance is not None
                    and transaction.source_file_id
                    for transaction in ordered
                ),
                "amount_shape": bool(incomes or expenses),
                "cashflow_scale_and_recent_change": bool(ordered),
            },
            "evidence_coverage": {
                "transaction_count": len(ordered),
                "transaction_id_covered_count": len(linked),
                "source_file_id_covered_count": sum(
                    bool(transaction.source_file_id) for transaction in ordered
                ),
                "evidence_locator_covered_count": sum(
                    bool(transaction.evidence_locator) for transaction in ordered
                ),
                "fully_traceable_transaction_count": len(fully_traceable),
                "fully_traceable_transaction_coverage_rate": _ratio(
                    len(fully_traceable), len(ordered)
                ),
            },
        },
        {
            "required_evidence_fields": [
                "transaction_id",
                "source_file_id",
                "evidence_locator",
            ],
            "availability_is_not_risk_assessment": True,
        },
        linked,
        _coverage(
            ["transaction_id", "source_file_id", "evidence_locator"],
            ordered,
            fully_traceable,
        ),
    )


def _indicators(transactions: list[Transaction]) -> list[dict[str, object]]:
    return [
        *[
            _time_proximity_indicator(transactions, window_days)
            for window_days in (1, 3, 7)
        ],
        _counterparty_concentration_indicator(transactions, "income"),
        _counterparty_concentration_indicator(transactions, "expense"),
        _income_continuity_indicator(transactions),
        _balance_observation_indicator(transactions),
        _amount_shape_indicator(transactions),
        _cashflow_scale_and_recent_change_indicator(transactions),
        _availability_and_evidence_indicator(transactions),
    ]


def _normalize_full_account(value: object) -> str | None:
    normalized = re.sub(r"[\s-]+", "", str(value or ""))
    if not normalized.isdigit() or not 12 <= len(normalized) <= 32:
        return None
    return normalized


def _confirmed_owned_accounts(
    verification_context: dict[str, object] | None,
) -> dict[str, dict[str, object]]:
    if not verification_context:
        return {}

    confirmed: dict[str, dict[str, str]] = {}
    accounts = verification_context.get("confirmed_owned_accounts", [])
    if not isinstance(accounts, list):
        return confirmed

    for account in accounts:
        if not isinstance(account, dict):
            continue
        if account.get("verification_status") != "confirmed":
            continue
        account_ref = str(account.get("account_ref", "")).strip()
        ownership_evidence_ref = str(account.get("ownership_evidence_ref", "")).strip()
        normalized = _normalize_full_account(account.get("account_number"))
        if not account_ref or not ownership_evidence_ref or normalized is None:
            continue
        confirmed.setdefault(
            normalized,
            {
                "account_ref": account_ref,
                "ownership_evidence_ref": ownership_evidence_ref,
                "source_file_ids": [
                    str(source_file_id).strip()
                    for source_file_id in account.get("source_file_ids", [])
                    if str(source_file_id).strip()
                ]
                if isinstance(account.get("source_file_ids", []), list)
                else [],
            },
        )
    return confirmed


def _own_account_transfer_observation(
    transactions: list[Transaction],
    verification_context: dict[str, object] | None,
) -> dict[str, object]:
    eligible = [
        transaction
        for transaction in sort_transactions(transactions)
        if not getattr(transaction, "neutral", False)
        and (
            transaction.income != Decimal("0.00")
            or transaction.expense != Decimal("0.00")
        )
    ]
    covered = [
        transaction
        for transaction in eligible
        if transaction.transaction_id
        and transaction.field_confidence.get("counterparty_account") == 1.0
        and _normalize_full_account(transaction.counterparty_account) is not None
    ]
    confirmed_accounts = _confirmed_owned_accounts(verification_context)
    candidates: list[dict[str, object]] = []
    matched_transactions: list[Transaction] = []

    for transaction in covered:
        account = confirmed_accounts.get(
            _normalize_full_account(transaction.counterparty_account) or ""
        )
        if account is None:
            continue
        income = transaction.income != Decimal("0.00")
        candidates.append(
            {
                "transaction_id": transaction.transaction_id,
                "confirmed_account_ref": account["account_ref"],
                "ownership_evidence_ref": account["ownership_evidence_ref"],
                "direction": (
                    "income_from_confirmed_owned_account"
                    if income
                    else "expense_to_confirmed_owned_account"
                ),
                "transaction_time": transaction.transaction_time.isoformat(),
                "amount": _decimal(
                    transaction.income if income else transaction.expense
                ),
            }
        )
        matched_transactions.append(transaction)

    available = bool(confirmed_accounts) and bool(covered)
    value: dict[str, object] = {
        "available": available,
        "matched_transaction_count": len(matched_transactions),
        "matched_income": _decimal(
            sum(
                (transaction.income for transaction in matched_transactions),
                Decimal("0.00"),
            )
        ),
        "matched_expense": _decimal(
            sum(
                (transaction.expense for transaction in matched_transactions),
                Decimal("0.00"),
            )
        ),
        "candidates": candidates,
    }

    if not confirmed_accounts:
        value["reason"] = "confirmed_owned_accounts_unavailable"
    elif not covered:
        value["reason"] = "reliable_counterparty_accounts_unavailable"

    return {
        "observation_type": "confirmed_own_account_transfer_candidates",
        "value": value,
        "parameters": {
            "matching_rule": "normalized_full_account_exact_match",
            "account_normalization": "remove_whitespace_and_hyphens",
            "full_account_digit_length": {"minimum": 12, "maximum": 32},
            "required_counterparty_account_confidence": 1.0,
            "excludes_neutral_transactions": True,
            "interpretation": (
                "仅表示交易对手账号与外部已确认本人账户集合精确匹配；"
                "不表示资金来源、资金闭环或账户实际控制关系。"
            ),
        },
        "evidence_transaction_ids": _transaction_ids(matched_transactions),
        "field_coverage": _coverage(
            [
                "counterparty_account",
                "field_confidence.counterparty_account",
                "transaction_id",
            ],
            eligible,
            covered,
        ),
    }


def _masked_case_account_observation(verification_context: dict[str, object] | None) -> dict[str, object]:
    accounts = verification_context.get("masked_case_accounts", []) if verification_context else []
    included = [account for account in accounts if isinstance(account, dict)] if isinstance(accounts, list) else []
    return {
        "observation_type": "masked_case_account_included_with_warning",
        "value": {"available": bool(included), "accounts": included},
        "parameters": {
            "account_rule": "same_case_masked_header_account",
            "excluded_from": ["confirmed_own_account_transfer_candidates", "confirmed_own_account_transfer_pair_candidates"],
            "interpretation": "掩码账号仅作为同案分析来源候选，不能用于完整账号精确匹配、唯一双边配对或账户归属结论。",
        },
        "evidence_transaction_ids": [],
        "field_coverage": {"eligible_transaction_count": 0, "covered_transaction_count": 0, "transaction_coverage_rate": None},
    }


_WECHAT_CARD_TAIL_RE = re.compile(r"(?:储蓄卡|信用卡|银行卡)\s*[（(]\s*(\d{4})\s*[）)]")
_IDENTITY_NUMBER_RE = re.compile(r"(?:\d{15}|\d{17}[\dXx])$")


def _wechat_card_tail(transaction: Transaction) -> str | None:
    if transaction.field_confidence.get("transaction_method") != 1.0:
        return None
    match = _WECHAT_CARD_TAIL_RE.search(transaction.transaction_method)
    return match.group(1) if match else None


def _normalized_merchant_parts(value: str) -> set[str]:
    parts = re.split(r"[·•|/\\\\]", value or "")
    return {
        re.sub(r"[\s\-_.()（）]+", "", part).casefold()
        for part in parts
        if len(re.sub(r"[\s\-_.()（）]+", "", part)) >= 2
    }


def _wechat_merchant_matches_bank_text(merchant: str, bank_text: str) -> bool:
    bank_normalized = re.sub(r"[\s\-_.()（）]+", "", bank_text or "").casefold()
    return any(part in bank_normalized for part in _normalized_merchant_parts(merchant))


def _bank_transaction_text(transaction: Transaction) -> str:
    return " ".join(
        value
        for value in (
            transaction.summary,
            transaction.remark,
            transaction.counterparty_name,
            transaction.raw_text,
        )
        if value
    )


def _wechat_payment_bank_debit_observation(
    transactions: list[Transaction],
    verification_context: dict[str, object] | None,
) -> dict[str, object]:
    """Link a confirmed bank debit to a WeChat expense without treating it as a transfer."""
    confirmed_accounts = _confirmed_owned_accounts(verification_context)
    confirmed_wechat_sources: dict[str, dict[str, str]] = {}
    ambiguous_wechat_source_ids: set[str] = set()
    payment_sources = verification_context.get("confirmed_owned_payment_sources", []) if verification_context else []
    if isinstance(payment_sources, list):
        for source in payment_sources:
            if not isinstance(source, dict) or source.get("verification_status") != "confirmed":
                continue
            if source.get("payment_account_type") != "wechat_account":
                continue
            source_file_id = str(source.get("source_file_id", "")).strip()
            account_ref = str(source.get("account_ref", "")).strip()
            evidence_ref = str(source.get("ownership_evidence_ref", "")).strip()
            owner_name = str(source.get("identity_owner_name", "")).strip()
            identity_number = str(source.get("identity_number", "")).strip()
            payment_account_id = str(source.get("payment_account_id", "")).strip()
            if (
                source_file_id
                and account_ref
                and evidence_ref
                and owner_name
                and _IDENTITY_NUMBER_RE.fullmatch(identity_number)
                and payment_account_id
            ):
                current = confirmed_wechat_sources.get(source_file_id)
                candidate = {"account_ref": account_ref, "ownership_evidence_ref": evidence_ref}
                if current is not None and current != candidate:
                    ambiguous_wechat_source_ids.add(source_file_id)
                else:
                    confirmed_wechat_sources[source_file_id] = candidate
    for source_file_id in ambiguous_wechat_source_ids:
        confirmed_wechat_sources.pop(source_file_id, None)
    accounts_by_tail: dict[str, list[dict[str, object]]] = {}
    source_accounts: dict[str, dict[str, object]] = {}
    ambiguous_source_ids: set[str] = set()
    for account_number, account in confirmed_accounts.items():
        accounts_by_tail.setdefault(account_number[-4:], []).append(account)
        for source_file_id in account["source_file_ids"]:
            current = source_accounts.get(source_file_id)
            if current is not None and current["account_ref"] != account["account_ref"]:
                ambiguous_source_ids.add(source_file_id)
            else:
                source_accounts[source_file_id] = account
    for source_file_id in ambiguous_source_ids:
        source_accounts.pop(source_file_id, None)

    wallet_candidates: list[tuple[Transaction, dict[str, object]]] = []
    for transaction in sort_transactions(transactions):
        tail = _wechat_card_tail(transaction)
        if (
            transaction.bank != "微信流水"
            or getattr(transaction, "neutral", False)
            or transaction.income != Decimal("0.00")
            or transaction.expense == Decimal("0.00")
            or not transaction.transaction_id
            or not tail
            or transaction.source_file_id not in confirmed_wechat_sources
            or transaction.field_confidence.get("counterparty_name") != 1.0
            or not transaction.counterparty_name.strip()
        ):
            continue
        accounts = accounts_by_tail.get(tail, [])
        if len(accounts) == 1:
            wallet_candidates.append((transaction, accounts[0]))

    edges: list[dict[str, object]] = []
    for wallet_transaction, funding_account in wallet_candidates:
        for bank_transaction in sort_transactions(transactions):
            if (
                bank_transaction.bank == "微信流水"
                or getattr(bank_transaction, "neutral", False)
                or bank_transaction.income != Decimal("0.00")
                or bank_transaction.expense != wallet_transaction.expense
                or bank_transaction.transaction_time.date() != wallet_transaction.transaction_time.date()
                or source_accounts.get(bank_transaction.source_file_id, {}).get("account_ref")
                != funding_account["account_ref"]
            ):
                continue
            bank_text = _bank_transaction_text(bank_transaction)
            if (
                "财付通" not in bank_text
                or "微信支付" not in bank_text
                or not _wechat_merchant_matches_bank_text(wallet_transaction.counterparty_name, bank_text)
            ):
                continue
            edges.append(
                {
                    "wallet_transaction": wallet_transaction,
                    "bank_transaction": bank_transaction,
                    "funding_account": funding_account,
                }
            )

    by_wallet: dict[str, list[dict[str, object]]] = {}
    by_bank: dict[str, list[dict[str, object]]] = {}
    for edge in edges:
        by_wallet.setdefault(edge["wallet_transaction"].transaction_id, []).append(edge)
        by_bank.setdefault(edge["bank_transaction"].transaction_id, []).append(edge)

    paired: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    paired_wallet_ids: set[str] = set()
    for edge in edges:
        wallet_transaction = edge["wallet_transaction"]
        bank_transaction = edge["bank_transaction"]
        evidence = {
            "wallet_transaction_id": wallet_transaction.transaction_id,
            "bank_transaction_id": bank_transaction.transaction_id,
            "wechat_account_ref": confirmed_wechat_sources[wallet_transaction.source_file_id]["account_ref"],
            "wechat_ownership_evidence_ref": confirmed_wechat_sources[wallet_transaction.source_file_id][
                "ownership_evidence_ref"
            ],
            "funding_account_ref": edge["funding_account"]["account_ref"],
            "calendar_date": wallet_transaction.transaction_time.date().isoformat(),
            "amount": _decimal(wallet_transaction.expense),
        }
        if len(by_wallet[wallet_transaction.transaction_id]) == 1 and len(by_bank[bank_transaction.transaction_id]) == 1:
            if wallet_transaction.transaction_id not in paired_wallet_ids:
                paired_wallet_ids.add(wallet_transaction.transaction_id)
                paired.append(evidence)
        else:
            ambiguous.append(
                {
                    **evidence,
                    "candidate_bank_transaction_ids": sorted(
                        item["bank_transaction"].transaction_id
                        for item in by_wallet[wallet_transaction.transaction_id]
                    ),
                }
            )

    available = bool(confirmed_accounts) and bool(confirmed_wechat_sources) and bool(wallet_candidates)
    value: dict[str, object] = {
        "available": available,
        "paired": paired,
        "ambiguous_candidates": ambiguous,
    }
    if not confirmed_accounts:
        value["reason"] = "confirmed_owned_accounts_unavailable"
    elif not confirmed_wechat_sources:
        value["reason"] = "confirmed_owned_wechat_sources_unavailable"
    elif not wallet_candidates:
        value["reason"] = "reliable_wechat_card_tail_or_merchant_unavailable"

    evidence_transactions = [
        transaction
        for edge in edges
        for transaction in (edge["wallet_transaction"], edge["bank_transaction"])
    ]
    return {
        "observation_type": "wechat_payment_bank_debit_link_candidates",
        "value": value,
        "parameters": {
            "matching_rule": "unique_card_tail_same_day_exact_amount_literal_wechat_channel_unique_merchant_component",
            "wallet_fields": ["transaction_method", "counterparty_name"],
            "wallet_source_rule": (
                "confirmed_owned_payment_sources:wechat_account source_file_id exact match; "
                "identity_owner_name + identity_number + payment_account_id all required"
            ),
            "bank_marker": "财付通 + 微信支付",
            "account_rule": "wallet_card_tail_matches_exactly_one_confirmed_full_bank_account",
            "amount_rule": "exact_same_currency_amount",
            "date_rule": "same_calendar_date",
            "interpretation": "仅表示微信消费与已确认银行账户扣款的可复核关联候选；不表示本人账户互转、资金来源、资金闭环或账户实际控制关系。",
        },
        "evidence_transaction_ids": _transaction_ids(evidence_transactions),
        "field_coverage": _coverage(
            ["transaction_method", "counterparty_name", "transaction_id"],
            [transaction for transaction in transactions if transaction.bank == "微信流水"],
            [transaction for transaction, _ in wallet_candidates],
        ),
    }


def _alipay_payment_bank_debit_observation() -> dict[str, object]:
    return {
        "observation_type": "alipay_payment_bank_debit_link_pending_field_confirmation",
        "value": {"available": False, "reason": "alipay_payment_bank_debit_link_fields_pending_confirmation"},
        "parameters": {
            "interpretation": "支付宝支付扣款银行流水关联尚待原件字段确认；当前不进行自动匹配。",
        },
        "evidence_transaction_ids": [],
        "field_coverage": {"eligible_transaction_count": 0, "covered_transaction_count": 0, "transaction_coverage_rate": None},
    }


def _cross_account_pair_observation(
    transactions: list[Transaction],
    verification_context: dict[str, object] | None,
) -> dict[str, object]:
    confirmed_accounts = _confirmed_owned_accounts(verification_context)
    source_accounts: dict[str, dict[str, object]] = {}
    ambiguous_source_ids: set[str] = set()
    for account in confirmed_accounts.values():
        for source_file_id in account["source_file_ids"]:
            existing = source_accounts.get(source_file_id)
            if existing is not None and existing["account_ref"] != account["account_ref"]:
                ambiguous_source_ids.add(source_file_id)
                continue
            source_accounts[source_file_id] = account
    for source_file_id in ambiguous_source_ids:
        source_accounts.pop(source_file_id, None)

    eligible: list[tuple[Transaction, str]] = []
    for transaction in sort_transactions(transactions):
        if getattr(transaction, "neutral", False) or not transaction.transaction_id:
            continue
        if transaction.income != Decimal("0.00") and transaction.expense == Decimal("0.00"):
            direction = "income"
        elif transaction.expense != Decimal("0.00") and transaction.income == Decimal("0.00"):
            direction = "expense"
        else:
            continue
        eligible.append((transaction, direction))

    candidates: list[dict[str, object]] = []
    for transaction, direction in eligible:
        source_account = source_accounts.get(transaction.source_file_id)
        counterparty_account = confirmed_accounts.get(
            _normalize_full_account(transaction.counterparty_account) or ""
        )
        if (
            source_account is None
            or counterparty_account is None
            or source_account["account_ref"] == counterparty_account["account_ref"]
            or transaction.field_confidence.get("counterparty_account") != 1.0
        ):
            continue
        candidates.append(
            {
                "transaction": transaction,
                "source_account_ref": source_account["account_ref"],
                "counterparty_account_ref": counterparty_account["account_ref"],
                "direction": direction,
                "amount": transaction.income if direction == "income" else transaction.expense,
            }
        )

    paired: list[dict[str, object]] = []
    single_sided: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    paired_ids: set[str] = set()
    reciprocal_by_transaction_id: dict[str, list[dict[str, object]]] = {}
    for candidate in candidates:
        transaction = candidate["transaction"]
        reciprocal_by_transaction_id[transaction.transaction_id] = [
            other
            for other in candidates
            if other["source_account_ref"] == candidate["counterparty_account_ref"]
            and other["counterparty_account_ref"] == candidate["source_account_ref"]
            and other["direction"] != candidate["direction"]
            and other["amount"] == candidate["amount"]
            and other["transaction"].transaction_time.date()
            == transaction.transaction_time.date()
        ]
    for candidate in candidates:
        transaction = candidate["transaction"]
        reciprocal = reciprocal_by_transaction_id[transaction.transaction_id]
        evidence = {
            "transaction_id": transaction.transaction_id,
            "source_account_ref": candidate["source_account_ref"],
            "counterparty_account_ref": candidate["counterparty_account_ref"],
            "direction": candidate["direction"],
            "transaction_time": transaction.transaction_time.isoformat(),
            "amount": _decimal(candidate["amount"]),
        }
        if len(reciprocal) == 0:
            single_sided.append(evidence)
        elif (
            len(reciprocal) > 1
            or len(reciprocal_by_transaction_id[reciprocal[0]["transaction"].transaction_id])
            > 1
        ):
            ambiguous.append(
                {
                    **evidence,
                    "candidate_transaction_ids": sorted(
                        other["transaction"].transaction_id for other in reciprocal
                    ),
                }
            )
        else:
            other_transaction = reciprocal[0]["transaction"]
            pair_key = tuple(sorted((transaction.transaction_id, other_transaction.transaction_id)))
            if transaction.transaction_id in paired_ids or other_transaction.transaction_id in paired_ids:
                continue
            paired_ids.update(pair_key)
            paired.append(
                {
                    "transaction_ids": list(pair_key),
                    "calendar_date": transaction.transaction_time.date().isoformat(),
                    "amount": _decimal(candidate["amount"]),
                    "account_refs": sorted(
                        [candidate["source_account_ref"], candidate["counterparty_account_ref"]]
                    ),
                }
            )

    available = bool(confirmed_accounts) and bool(source_accounts) and bool(eligible)
    value: dict[str, object] = {
        "available": available,
        "paired": paired,
        "single_sided_candidates": single_sided,
        "ambiguous_candidates": ambiguous,
    }
    if not confirmed_accounts:
        value["reason"] = "confirmed_owned_accounts_unavailable"
    elif not source_accounts:
        value["reason"] = "confirmed_account_source_files_unavailable"
    elif not eligible:
        value["reason"] = "eligible_transactions_unavailable"

    evidence_transactions = [candidate["transaction"] for candidate in candidates]
    return {
        "observation_type": "confirmed_own_account_transfer_pair_candidates",
        "value": value,
        "parameters": {
            "matching_rule": "mutual_normalized_full_account_exact_match",
            "source_account_rule": "confirmed_account_source_file_exact_match",
            "date_rule": "same_calendar_date",
            "amount_rule": "exact_same_currency_amount",
            "direction_rule": "opposite_income_expense",
            "required_counterparty_account_confidence": 1.0,
            "excludes_neutral_transactions": True,
            "interpretation": (
                "仅表示已确认账户之间同日、同额、方向相反的双边交易候选；"
                "不表示资金来源、资金闭环或账户实际控制关系。"
            ),
        },
        "evidence_transaction_ids": _transaction_ids(evidence_transactions),
        "field_coverage": _coverage(
            [
                "transaction_id",
                "source_file_id",
                "counterparty_account",
                "field_confidence.counterparty_account",
            ],
            [transaction for transaction, _ in eligible],
            evidence_transactions,
        ),
    }


def _review_items(transactions: list[Transaction], summary: Summary) -> list[dict[str, object]]:
    review_items: list[dict[str, object]] = []
    transaction_issue_messages = {message for transaction in transactions for message in transaction.issues}

    for transaction in transactions:
        reasons = list(transaction.issues) + list(transaction.manual_review.values())
        if transaction.status != "ok":
            reasons.append(f"解析状态：{transaction.status}")
        if not transaction.transaction_id:
            reasons.append("缺少交易 ID")
        if not transaction.source_file_id:
            reasons.append("缺少来源文件 ID")
        if reasons:
            review_items.append(
                {
                    "scope": "transaction",
                    "transaction_id": transaction.transaction_id,
                    "source_file_id": transaction.source_file_id,
                    "evidence_locator": transaction.evidence_locator,
                    "evidence_transaction_ids": _transaction_ids([transaction]),
                    "reasons": reasons,
                }
            )

    ordered = sort_transactions(transactions)
    for issue in summary.issues:
        if issue.message in transaction_issue_messages:
            continue
        evidence = [
            transaction
            for transaction in ordered
            if transaction.transaction_time.strftime("%Y-%m-%d %H:%M:%S") == issue.time
            and transaction.raw_amount == issue.raw_amount
            and transaction.raw_balance == issue.raw_balance
        ]
        if not evidence and not issue.time:
            evidence = [transaction for transaction in ordered if not getattr(transaction, "neutral", False)]
        review_items.append(
            {
                "scope": "summary",
                "evidence_transaction_ids": _transaction_ids(evidence),
                "reasons": [issue.message],
            }
        )
    return review_items


def build_bankflow_result(
    transactions: list[Transaction],
    metadata: object | None = None,
    verification_context: dict[str, object] | None = None,
) -> dict[str, object]:
    """Build a verification result without applying adjustment or analysis logic."""
    original_transactions = list(transactions)
    statement_metadata = metadata or get_statement_metadata(transactions)
    summary = summarize(original_transactions)
    review_items = _review_items(original_transactions, summary)

    return {
        "schema_version": SCHEMA_VERSION,
        "module": "bankflow",
        "analysis_source": "original_transactions",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_files": _source_files(original_transactions),
        "statement_metadata": {
            "account_name": statement_metadata.account_name,
            "account_number": statement_metadata.account_number,
            "statement_period_start": _date(statement_metadata.statement_period_start),
            "statement_period_end": _date(statement_metadata.statement_period_end),
            "generated_at": _date(statement_metadata.generated_at),
            "source_part_label": statement_metadata.source_part_label,
            "page_total": statement_metadata.page_total,
        },
        "result": {
            "summary": _summary_record(summary),
            "original_transactions": [_transaction_record(transaction) for transaction in original_transactions],
            "facts": _facts(original_transactions, summary),
            "indicators": _indicators(original_transactions),
            "observations": [
                _own_account_transfer_observation(
                    original_transactions,
                    verification_context,
                ),
                _cross_account_pair_observation(
                    original_transactions,
                    verification_context,
                ),
                _masked_case_account_observation(verification_context),
                _wechat_payment_bank_debit_observation(
                    original_transactions,
                    verification_context,
                ),
                _alipay_payment_bank_debit_observation(),
            ],
        },
        "manual_review": {"required": bool(review_items), "items": review_items},
        "warnings": [],
        "notes": [
            "仅包含原始标准交易、确定性事实、确定性指标和待人工核实事项；未应用流水调整或风险定性。",
            "资金时间邻近指标仅表示先收入后支出的时间共现，不表示支出资金来源于某笔收入。",
            "收入连续性、余额快照、金额形态和近期变化均为中性数值观察，不表示工资稳定、资金充足、流水包装或业务趋势。",
            "本人账户转账候选仅基于外部已确认账户集合与可靠完整对手账号精确匹配，不表示资金来源、资金闭环或账户实际控制关系。",
            "跨账户双边候选仅基于已确认账户来源文件、可靠完整对手账号、同日同额和相反方向匹配，不表示资金来源、资金闭环或账户实际控制关系。",
            "微信支付扣款关联候选仅在唯一银行卡尾号、已确认银行账户、同日同额、文字渠道和唯一商户内容同时满足时输出；不表示本人账户互转。",
        ],
    }


def write_bankflow_json(result: dict[str, object], output_path: str | Path) -> Path:
    """Write a UTF-8 evidence JSON file and return its path."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
