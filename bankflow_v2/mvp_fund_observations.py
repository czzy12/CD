"""Deterministic fund, balance, interest and counterparty observations."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from .models import Transaction
from .summary import sort_transactions


LARGE_TRANSACTION_THRESHOLD = Decimal("10000.00")
LARGE_INFLOW_THRESHOLD = Decimal("30000.00")
COMPONENT_MINIMUM = Decimal("1000.00")
COMPONENT_RATIO = Decimal("0.05")
NEAR_TOTAL_MIN = Decimal("0.90")
NEAR_TOTAL_MAX = Decimal("1.10")
LARGE_PORTION_MIN = Decimal("0.80")
LOW_RETAINED_INCREMENT_MAX = Decimal("0.20")
WINDOW_DAYS = (1, 3, 7)

TEXT_FIELDS = (
    "counterparty_name",
    "counterparty_account",
    "summary",
    "remark",
    "purpose",
    "transaction_type",
    "product_description",
    "merchant_name",
    "merchant_category",
)

PURPOSE_TERMS: dict[str, tuple[str, ...]] = {
    "salary": ("工资", "薪资"),
    "reimbursement": ("报销",),
    "tax": ("税费", "税款", "缴税"),
    "engineering": ("工程款",),
    "material": ("材料款",),
    "purchase": ("采购",),
    "goods_payment": ("货款",),
    "merchant_receipt": ("商户收款",),
    "repayment": ("还款",),
    "interest": ("结息", "利息"),
}


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def _ratio(numerator: Decimal, denominator: Decimal) -> str | None:
    return f"{numerator / denominator:.4f}" if denominator else None


def _evidence_ids(transactions: list[Transaction]) -> list[str]:
    return [
        transaction.transaction_id
        for transaction in transactions
        if transaction.transaction_id
    ]


def _base_observation(
    observation_type: str,
    value: dict[str, object],
    parameters: dict[str, object],
    evidence: list[Transaction],
    eligible: list[Transaction],
    covered: list[Transaction],
) -> dict[str, object]:
    return {
        "observation_type": observation_type,
        "value": value,
        "parameters": parameters,
        "evidence_transaction_ids": list(dict.fromkeys(_evidence_ids(evidence))),
        "field_coverage": {
            "eligible_transaction_count": len(eligible),
            "covered_transaction_count": len(covered),
        },
    }


def _reliable_text_fields(transaction: Transaction) -> dict[str, str]:
    return {
        field_name: str(getattr(transaction, field_name) or "").strip()
        for field_name in TEXT_FIELDS
        if str(getattr(transaction, field_name) or "").strip()
        and transaction.field_confidence.get(field_name) == 1.0
    }


def _transaction_context(transaction: Transaction) -> dict[str, object]:
    return {
        "transaction_id": transaction.transaction_id,
        "source_file_id": transaction.source_file_id,
        "source_file": transaction.source_file,
        "evidence_locator": transaction.evidence_locator,
        "transaction_time": transaction.transaction_time.isoformat(),
        "income": _decimal(transaction.income),
        "expense": _decimal(transaction.expense),
        "balance": _decimal(transaction.balance),
        "reliable_standard_fields": _reliable_text_fields(transaction),
    }


def _large_transactions(transactions: list[Transaction]) -> dict[str, object]:
    eligible = [
        transaction
        for transaction in sort_transactions(transactions)
        if not getattr(transaction, "neutral", False)
        and (transaction.income > 0 or transaction.expense > 0)
    ]
    covered = [
        transaction
        for transaction in eligible
        if max(transaction.income, transaction.expense)
        >= LARGE_TRANSACTION_THRESHOLD
    ]
    return _base_observation(
        "large_transaction_candidates",
        {
            "available": bool(covered),
            "reason": "" if covered else "no_transactions_meet_large_threshold",
            "candidate_only": True,
            "candidates": [_transaction_context(transaction) for transaction in covered],
        },
        {
            "threshold_inclusive": _decimal(LARGE_TRANSACTION_THRESHOLD),
            "interpretation": "仅表示单笔金额达到展示阈值，不表示异常或资金用途。",
        },
        covered,
        eligible,
        eligible,
    )


def _source_groups(
    transactions: list[Transaction],
) -> dict[str, list[Transaction]]:
    groups: dict[str, list[Transaction]] = defaultdict(list)
    for transaction in sort_transactions(transactions):
        groups[transaction.source_file_id or "source_file_id_unavailable"].append(
            transaction
        )
    return groups


def _day_end_balance(
    source_transactions: list[Transaction],
    target_date: date,
) -> tuple[Decimal | None, Transaction | None]:
    candidates = [
        transaction
        for transaction in source_transactions
        if transaction.transaction_time.date() == target_date
        and transaction.balance is not None
    ]
    if not candidates:
        return None, None
    selected = candidates[-1]
    return selected.balance, selected


def _large_inflow_paths(transactions: list[Transaction]) -> dict[str, object]:
    groups = _source_groups(transactions)
    inflows = [
        transaction
        for transaction in sort_transactions(transactions)
        if not getattr(transaction, "neutral", False)
        and transaction.income >= LARGE_INFLOW_THRESHOLD
    ]
    candidates: list[dict[str, object]] = []
    evidence: list[Transaction] = []
    balance_covered: list[Transaction] = []

    for inflow in inflows:
        source_rows = groups[inflow.source_file_id or "source_file_id_unavailable"]
        pre_balance = (
            inflow.balance - inflow.income + inflow.expense
            if inflow.balance is not None
            else None
        )
        windows: list[dict[str, object]] = []
        evidence.append(inflow)
        if inflow.balance is not None:
            balance_covered.append(inflow)
        component_threshold = max(
            COMPONENT_MINIMUM,
            inflow.income * COMPONENT_RATIO,
        )
        for days in WINDOW_DAYS:
            end_time = inflow.transaction_time + timedelta(days=days)
            expenses = [
                transaction
                for transaction in source_rows
                if inflow.transaction_time < transaction.transaction_time <= end_time
                and transaction.expense > 0
                and not getattr(transaction, "neutral", False)
            ]
            components = [
                transaction
                for transaction in expenses
                if transaction.expense >= component_threshold
            ]
            cumulative = sum(
                (transaction.expense for transaction in components),
                Decimal("0.00"),
            )
            outflow_ratio = cumulative / inflow.income
            end_balance, balance_tx = _day_end_balance(
                source_rows,
                (inflow.transaction_time + timedelta(days=days)).date(),
            )
            retained_increment_ratio = (
                (end_balance - pre_balance) / inflow.income
                if end_balance is not None and pre_balance is not None
                else None
            )
            if balance_tx is not None:
                evidence.append(balance_tx)
            evidence.extend(components)
            windows.append(
                {
                    "window_days": days,
                    "component_expense_threshold": _decimal(component_threshold),
                    "included_component_expense_count": len(components),
                    "included_component_transaction_ids": _evidence_ids(components),
                    "cumulative_expense": _decimal(cumulative),
                    "cumulative_expense_ratio": f"{outflow_ratio:.4f}",
                    "exact_total_outflow": cumulative == inflow.income,
                    "near_total_outflow": (
                        NEAR_TOTAL_MIN <= outflow_ratio <= NEAR_TOTAL_MAX
                    ),
                    "large_portion_outflow": outflow_ratio >= LARGE_PORTION_MIN,
                    "end_of_day_balance": _decimal(end_balance),
                    "end_of_day_balance_transaction_id": (
                        balance_tx.transaction_id if balance_tx else ""
                    ),
                    "retained_balance_increment_ratio": (
                        f"{retained_increment_ratio:.4f}"
                        if retained_increment_ratio is not None
                        else None
                    ),
                    "low_retained_balance_increment": (
                        outflow_ratio >= LARGE_PORTION_MIN
                        and retained_increment_ratio is not None
                        and retained_increment_ratio
                        <= LOW_RETAINED_INCREMENT_MAX
                    ),
                }
            )
        candidates.append(
            {
                "inflow_transaction": _transaction_context(inflow),
                "pre_inflow_balance": _decimal(pre_balance),
                "windows": windows,
            }
        )

    return _base_observation(
        "large_inflow_balance_paths",
        {
            "available": bool(candidates),
            "reason": "" if candidates else "no_income_meets_path_threshold",
            "candidate_only": True,
            "candidates": candidates,
        },
        {
            "large_inflow_threshold_inclusive": _decimal(LARGE_INFLOW_THRESHOLD),
            "windows_days": list(WINDOW_DAYS),
            "included_component_minimum": _decimal(COMPONENT_MINIMUM),
            "included_component_ratio_of_inflow": f"{COMPONENT_RATIO:.2f}",
            "near_total_ratio_inclusive": [
                f"{NEAR_TOTAL_MIN:.2f}",
                f"{NEAR_TOTAL_MAX:.2f}",
            ],
            "large_portion_ratio_inclusive": f"{LARGE_PORTION_MIN:.2f}",
            "low_retained_increment_ratio_inclusive": f"{LOW_RETAINED_INCREMENT_MAX:.2f}",
            "same_source_file_only": True,
            "fund_source_attribution": False,
            "interpretation": "只展示同一来源内大额入账后的支出与余额路径，不认定支出使用了该笔收入。",
        },
        evidence,
        inflows,
        balance_covered,
    )


def _interest_match(transaction: Transaction) -> bool:
    return any(
        term in re.sub(r"\s+", "", value)
        for value in _reliable_text_fields(transaction).values()
        for term in PURPOSE_TERMS["interest"]
    )


def _balance_and_interest(transactions: list[Transaction]) -> dict[str, object]:
    groups = _source_groups(transactions)
    source_values: list[dict[str, object]] = []
    evidence: list[Transaction] = []
    covered: list[Transaction] = []

    for source_file_id, rows in sorted(groups.items()):
        day_end: dict[date, Transaction] = {}
        for transaction in rows:
            if transaction.balance is not None:
                day_end[transaction.transaction_time.date()] = transaction
        balances = [transaction.balance for transaction in day_end.values()]
        balance_stats = None
        if balances:
            balance_stats = {
                "day_count": len(balances),
                "minimum": _decimal(min(balances)),
                "median": _decimal(Decimal(str(median(balances)))),
                "average": _decimal(
                    sum(balances, Decimal("0.00")) / Decimal(len(balances))
                ),
                "closing": _decimal(list(day_end.values())[-1].balance),
            }
            covered.extend(day_end.values())
            evidence.extend(day_end.values())

        interest_rows = [transaction for transaction in rows if _interest_match(transaction)]
        evidence.extend(interest_rows)
        quarter_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        for transaction in interest_rows:
            quarter = (transaction.transaction_time.month - 1) // 3 + 1
            key = f"{transaction.transaction_time.year:04d}-Q{quarter}"
            quarter_totals[key] += transaction.income - transaction.expense
        quarterly_interest: list[dict[str, object]] = []
        previous: Decimal | None = None
        for quarter, amount in sorted(quarter_totals.items()):
            quarterly_interest.append(
                {
                    "quarter": quarter,
                    "net_interest": _decimal(amount),
                    "change_from_previous": (
                        _decimal(amount - previous) if previous is not None else None
                    ),
                }
            )
            previous = amount

        source_values.append(
            {
                "source_file_id": source_file_id,
                "source_file": rows[0].source_file if rows else "",
                "bank": rows[0].bank if rows else "",
                "balance_available": bool(balances),
                "balance_unavailable_reason": (
                    "" if balances else "reliable_balance_unavailable"
                ),
                "balance_statistics": balance_stats,
                "interest_records": [
                    _transaction_context(transaction) for transaction in interest_rows
                ],
                "quarterly_interest": quarterly_interest,
            }
        )

    return _base_observation(
        "end_of_day_balance_and_interest",
        {
            "available": bool(source_values),
            "reason": "" if source_values else "source_transactions_unavailable",
            "sources": source_values,
        },
        {
            "day_end_rule": "last_transaction_with_balance_on_each_calendar_date_per_source",
            "interest_terms": list(PURPOSE_TERMS["interest"]),
            "interpretation": "日末余额不是日均余额；结息金额只按可靠文字命中逐笔及按季度汇总。",
        },
        evidence,
        sort_transactions(transactions),
        covered,
    )


def is_identifiable_counterparty_name(value: str) -> bool:
    """Return whether a reliable name is usable as a counterparty identity."""
    compact = re.sub(r"\s+", "", value).strip("()（）[]【】")
    prefixed_name = re.fullmatch(
        r"([A-Za-z0-9-]+)([\u4e00-\u9fff]{2,8})",
        compact,
    )
    prefixed_short_name = False
    if prefixed_name:
        chinese_suffix = prefixed_name.group(2)
        recognizable_entity_suffix = re.search(
            r"公司|商行|经营部|门市部|商店|超市|酒店|医院|银行|"
            r"中心|工厂|厂|店$",
            chinese_suffix,
        )
        prefixed_short_name = bool(
            "账户" in chinese_suffix
            or (
                len(chinese_suffix) <= 4
                and recognizable_entity_suffix is None
            )
        )
    return bool(
        compact
        and compact not in {"空", "无", "未知", "-", "其他"}
        and "*" not in compact
        and "（空）" not in value
        and not prefixed_short_name
        and re.search(r"[\u4e00-\u9fffA-Za-z]", compact)
    )


def _counterparty_identity(transaction: Transaction) -> tuple[str, str] | None:
    name = transaction.counterparty_name.strip()
    if (
        name
        and transaction.field_confidence.get("counterparty_name") == 1.0
        and is_identifiable_counterparty_name(name)
    ):
        return "counterparty_name", re.sub(r"\s+", "", name)
    account = re.sub(r"[\s-]+", "", transaction.counterparty_account)
    if (
        account.isdigit()
        and 12 <= len(account) <= 32
        and transaction.field_confidence.get("counterparty_account") == 1.0
    ):
        return "counterparty_account", account
    return None


def _top_counterparties(transactions: list[Transaction]) -> dict[str, object]:
    eligible = [
        transaction
        for transaction in sort_transactions(transactions)
        if not getattr(transaction, "neutral", False)
        and (transaction.income > 0 or transaction.expense > 0)
    ]
    direction_values: dict[str, object] = {}
    evidence: list[Transaction] = []
    covered: list[Transaction] = []
    for direction, amount_field in (("income", "income"), ("expense", "expense")):
        directional = [
            transaction
            for transaction in eligible
            if getattr(transaction, amount_field) > 0
        ]
        directional_amount = sum(
            (getattr(transaction, amount_field) for transaction in directional),
            Decimal("0.00"),
        )
        groups: dict[tuple[str, str], dict[str, object]] = {}
        direction_covered: list[Transaction] = []
        for transaction in directional:
            amount = getattr(transaction, amount_field)
            identity = _counterparty_identity(transaction)
            if identity is None:
                continue
            covered.append(transaction)
            direction_covered.append(transaction)
            group = groups.setdefault(
                identity,
                {
                    "amount": Decimal("0.00"),
                    "count": 0,
                    "months": set(),
                    "transactions": [],
                },
            )
            group["amount"] += amount
            group["count"] += 1
            group["months"].add(transaction.transaction_time.strftime("%Y-%m"))
            group["transactions"].append(transaction)
        covered_amount = sum(
            (
                getattr(transaction, amount_field)
                for transaction in direction_covered
            ),
            Decimal("0.00"),
        )
        ranked = sorted(
            groups.items(),
            key=lambda item: (
                -item[1]["amount"],
                -item[1]["count"],
                item[0][1],
            ),
        )[:5]
        direction_values[direction] = []
        for identity, group in ranked:
            evidence.extend(group["transactions"])
            direction_values[direction].append(
                {
                    "identity_field": identity[0],
                    "identity_value": identity[1],
                    "transaction_count": group["count"],
                    "amount": _decimal(group["amount"]),
                    "covered_amount_share": _ratio(
                        group["amount"],
                        covered_amount,
                    ),
                    "direction_amount_share": _ratio(
                        group["amount"],
                        directional_amount,
                    ),
                    "months": sorted(group["months"]),
                    "evidence_transaction_ids": _evidence_ids(group["transactions"]),
                }
            )
        direction_values[f"{direction}_summary"] = {
            "available": bool(groups),
            "reason": (
                ""
                if groups
                else (
                    f"no_{direction}_transactions"
                    if not directional
                    else "identifiable_counterparty_unavailable"
                )
            ),
            "eligible_transaction_count": len(directional),
            "covered_transaction_count": len(direction_covered),
            "eligible_amount": _decimal(directional_amount),
            "covered_amount": _decimal(covered_amount),
            "amount_coverage_rate": _ratio(
                covered_amount,
                directional_amount,
            ),
            "distinct_identifiable_counterparty_count": len(groups),
        }

    return _base_observation(
        "top_counterparties",
        {
            "available": bool(direction_values["income"] or direction_values["expense"]),
            "reason": (
                ""
                if direction_values["income"] or direction_values["expense"]
                else "identifiable_counterparty_unavailable"
            ),
            **direction_values,
        },
        {
            "top_n": 5,
            "identity_priority": ["counterparty_name", "counterparty_account"],
            "masked_or_placeholder_names_excluded": True,
            "interpretation": "排名只表示可靠可识别对手的金额汇总，不表示对手关系或实际控制。",
        },
        evidence,
        eligible,
        covered,
    )


def _cross_source_occurrences(transactions: list[Transaction]) -> dict[str, object]:
    groups: dict[str, dict[str, object]] = {}
    eligible = [
        transaction
        for transaction in sort_transactions(transactions)
        if not getattr(transaction, "neutral", False)
        and (transaction.income > 0 or transaction.expense > 0)
    ]
    covered: list[Transaction] = []
    for transaction in eligible:
        name = transaction.counterparty_name.strip()
        if (
            transaction.field_confidence.get("counterparty_name") != 1.0
            or not is_identifiable_counterparty_name(name)
        ):
            continue
        normalized = re.sub(r"\s+", "", name).casefold()
        covered.append(transaction)
        group = groups.setdefault(
            normalized,
            {
                "display_name": re.sub(r"\s+", "", name),
                "sources": defaultdict(
                    lambda: {
                        "source_file": "",
                        "income": Decimal("0.00"),
                        "expense": Decimal("0.00"),
                        "count": 0,
                        "transactions": [],
                    }
                ),
            },
        )
        source = group["sources"][
            transaction.source_file_id or "source_file_id_unavailable"
        ]
        source["source_file"] = transaction.source_file
        source["income"] += transaction.income
        source["expense"] += transaction.expense
        source["count"] += 1
        source["transactions"].append(transaction)

    counterparties: list[dict[str, object]] = []
    evidence: list[Transaction] = []
    for group in groups.values():
        if len(group["sources"]) < 2:
            continue
        source_rows: list[dict[str, object]] = []
        for source_file_id, source in sorted(group["sources"].items()):
            evidence.extend(source["transactions"])
            source_rows.append(
                {
                    "source_file_id": source_file_id,
                    "source_file": source["source_file"],
                    "transaction_count": source["count"],
                    "income": _decimal(source["income"]),
                    "expense": _decimal(source["expense"]),
                    "evidence_transaction_ids": _evidence_ids(source["transactions"]),
                }
            )
        counterparties.append(
            {
                "counterparty_name": group["display_name"],
                "source_count": len(source_rows),
                "sources": source_rows,
            }
        )
    counterparties.sort(key=lambda item: (-item["source_count"], item["counterparty_name"]))

    return _base_observation(
        "cross_source_counterparty_occurrences",
        {
            "available": bool(counterparties),
            "reason": (
                "" if counterparties else "no_identifiable_name_across_multiple_sources"
            ),
            "counterparties": counterparties,
        },
        {
            "match_rule": "reliable_counterparty_name_after_whitespace_normalization_exact_match",
            "minimum_source_count": 2,
            "relationship_inference": False,
            "interpretation": "仅表示同一可识别名称在多个来源出现，不表示主体关系、账户归属或资金闭环。",
        },
        evidence,
        eligible,
        covered,
    )


def _explicit_purposes(transactions: list[Transaction]) -> dict[str, object]:
    candidates: list[dict[str, object]] = []
    evidence: list[Transaction] = []
    eligible = sort_transactions(transactions)
    covered: list[Transaction] = []
    for transaction in eligible:
        fields = _reliable_text_fields(transaction)
        compact_fields = {
            name: re.sub(r"\s+", "", value) for name, value in fields.items()
        }
        for category, terms in PURPOSE_TERMS.items():
            field_matches = {
                field_name: [term for term in terms if term in value]
                for field_name, value in compact_fields.items()
            }
            field_matches = {
                field_name: matches
                for field_name, matches in field_matches.items()
                if matches
            }
            if not field_matches:
                continue
            candidates.append(
                {
                    "transaction_id": transaction.transaction_id,
                    "category": category,
                    "matched_fields": field_matches,
                    "transaction_context": _transaction_context(transaction),
                }
            )
            evidence.append(transaction)
            covered.append(transaction)
            break

    return _base_observation(
        "explicit_purpose_candidates",
        {
            "available": bool(candidates),
            "reason": "" if candidates else "no_explicit_purpose_hits",
            "candidate_only": True,
            "candidates": candidates,
        },
        {
            "category_terms": {
                category: list(terms) for category, terms in PURPOSE_TERMS.items()
            },
            "interpretation": "明确用途词命中只按可靠字段报告，不判断劳动、经营或债务关系真实性。",
        },
        evidence,
        eligible,
        covered,
    )


def build_fund_observations(
    transactions: list[Transaction],
) -> list[dict[str, object]]:
    """Build deterministic fund observations from the existing transactions."""
    return [
        _large_transactions(transactions),
        _large_inflow_paths(transactions),
        _balance_and_interest(transactions),
        _top_counterparties(transactions),
        _cross_source_occurrences(transactions),
        _explicit_purposes(transactions),
    ]
