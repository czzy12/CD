import json
from copy import copy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from .adjustment import AdjustmentConfig, split_amount
from .summary import Summary, monthly_summaries, summarize


CENT = Decimal("0.01")
WAN = Decimal("10000")
WECHAT_MIN_MONTHLY_NET = Decimal("100.00")
WECHAT_MAX_MONTHLY_NET = Decimal("500.00")
SALARY_KEYWORDS = ("工资", "薪资", "薪酬", "奖金", "奖", "代发工资")
SALARY_EXCLUDE_KEYWORDS = ("补助", "补贴", "补增资", "报销", "退款")


CORP_BANK_IDS = {
    "abc_corp",
    "boc_corp",
    "ccb_corp",
    "cmbc_corp",
    "hebei_corp_detail",
    "icbc_corp",
    "spdb_corp",
}

CORP_ACCOUNT_NAME_KEYWORDS = (
    "公司",
    "有限",
    "企业",
    "个体工商户",
    "经营部",
    "商行",
    "店",
    "厂",
    "合作社",
    "工作室",
    "事务所",
    "中心",
)


def to_wan(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float((value / WAN).quantize(CENT, rounding=ROUND_HALF_UP))


def flow_type(bank_id: str) -> str:
    if bank_id in CORP_BANK_IDS or bank_id.endswith("_corp"):
        return "对公"
    if bank_id == "wechat":
        return "微信"
    return "个人"


def looks_corporate_account_name(value: str) -> bool:
    text = (value or "").strip()
    return bool(text and any(keyword in text for keyword in CORP_ACCOUNT_NAME_KEYWORDS))


def result_flow_type(result) -> str:
    override = getattr(result, "_income_proof_flow_type_override", "")
    if override:
        return override
    detected = flow_type(getattr(result, "bank_id", ""))
    if detected == "个人" and looks_corporate_account_name(getattr(result, "account_name", "")):
        return "对公"
    return detected


def transaction_flow_type(tx, result=None) -> str:
    value = getattr(tx, "flow_type", "")
    if value in {"个人", "微信", "对公"}:
        return value
    return result_flow_type(result) if result is not None else "个人"


def split_results_by_flow(results: list, target_flow_type: str) -> list:
    split_results = []
    for result in results:
        transactions = [
            tx for tx in getattr(result, "transactions", []) or []
            if transaction_flow_type(tx, result) == target_flow_type
        ]
        if not transactions:
            continue
        cloned = copy(result)
        cloned.transactions = transactions
        cloned._income_proof_flow_type_override = target_flow_type
        split_results.append(cloned)
    return split_results


def normalize_bank_name(label: str, bank_id: str) -> str:
    if bank_id == "excel":
        return ""
    text = (label or bank_id or "").strip()
    if not text or set(text) == {"?"}:
        return ""
    for suffix in ("银行", "个人", "对公", "流水", "导入"):
        text = text.replace(suffix, "")
    text = text.strip()
    display_names = {
        "上海浦东发展": "浦发",
        "spdb": "浦发",
        "spdb_corp": "浦发",
        "中国邮政储蓄": "邮政",
        "邮储": "邮政",
        "psbc": "邮政",
    }
    text = display_names.get(text, text)
    if text.startswith("Excel"):
        return ""
    return text


def account_from_result(result) -> dict:
    account_no = getattr(result, "account_no", "")
    source_path = getattr(getattr(result, "path", None), "name", "")
    bank = normalize_bank_name(getattr(result, "bank_label", ""), getattr(result, "bank_id", ""))
    bank_confidence = int(getattr(result, "bank_confidence", 0) or 0)
    account_no_source = ""
    if account_no:
        suffix = Path(source_path).suffix.lower()
        account_no_source = "excel_auto" if suffix in {".xlsx", ".xlsm"} else "pdf_auto"
    return {
        "bank": bank,
        "bank_id": getattr(result, "bank_id", ""),
        "bank_label": getattr(result, "bank_label", ""),
        "bank_confidence": bank_confidence,
        "bank_reason": getattr(result, "bank_reason", ""),
        "bank_review_required": not bank or bank_confidence < 90,
        "area": "",
        "branch": "支行",
        "sub_branch": "",
        "account_no": account_no,
        "account_no_source": account_no_source,
        "account_no_review_required": bool(account_no),
        "flow_type": result_flow_type(result),
        "source_file": source_path,
    }


def unique_accounts(results: list) -> list[dict]:
    accounts: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for result in results:
        account = account_from_result(result)
        account_no = account.get("account_no", "")
        if not account_no:
            accounts.append(account)
            continue
        key = (account.get("flow_type", ""), account_no)
        if key in seen:
            continue
        seen.add(key)
        accounts.append(account)
    return accounts


def result_latest_time(result) -> datetime:
    transactions = getattr(result, "transactions", []) or []
    if not transactions:
        return datetime.min
    return max(tx.transaction_time for tx in transactions)


def balance_group_key(result) -> tuple[str, str]:
    account_no = getattr(result, "account_no", "") or ""
    if account_no:
        return (result_flow_type(result), account_no)
    source_path = getattr(getattr(result, "path", None), "name", "")
    return (result_flow_type(result), source_path)


def latest_balance_wan(results: Iterable) -> float | None:
    latest_by_account: dict[tuple[str, str], tuple[datetime, Decimal]] = {}
    for result in results:
        summary = getattr(result, "summary", None)
        closing = getattr(summary, "closing_balance", None)
        if closing is None:
            continue
        key = balance_group_key(result)
        latest_time = result_latest_time(result)
        previous = latest_by_account.get(key)
        if previous is None or latest_time >= previous[0]:
            latest_by_account[key] = (latest_time, closing)
    if not latest_by_account:
        return None
    total = sum((closing for _latest_time, closing in latest_by_account.values()), Decimal("0"))
    return to_wan(total)


def copy_summary(summary: Summary) -> Summary:
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


def sum_summaries(summaries: Iterable[Summary]) -> Summary:
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


def split_by_weights(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    if not weights:
        return []
    if total <= Decimal("0.00"):
        return [Decimal("0.00") for _weight in weights]
    weight_sum = sum(weights, Decimal("0.00"))
    if weight_sum <= Decimal("0.00"):
        weights = [Decimal("1") for _weight in weights]
        weight_sum = sum(weights, Decimal("0.00"))
    amounts = [(total * weight / weight_sum).quantize(CENT) for weight in weights[:-1]]
    amounts.append((total - sum(amounts, Decimal("0.00"))).quantize(CENT))
    return amounts


def expense_capacity(index: int, incomes: list[Decimal], reserves: list[Decimal], expenses: list[Decimal]) -> Decimal:
    running_income = Decimal("0.00")
    running_expense = Decimal("0.00")
    capacity: Decimal | None = None
    for month_index, (income, expense) in enumerate(zip(incomes, expenses)):
        running_income += income
        running_expense += expense
        if month_index >= index:
            available = (running_income - reserves[month_index] - running_expense).quantize(CENT)
            capacity = available if capacity is None else min(capacity, available)
    return max(capacity or Decimal("0.00"), Decimal("0.00"))


def balance_wechat_summaries(month_pairs: list[tuple[str, Summary]]) -> dict[str, Summary]:
    balanced = {month: copy_summary(summary) for month, summary in month_pairs}
    if not balanced:
        return balanced
    months = list(balanced)
    incomes = [balanced[month].income_sum for month in months]
    raw_expenses = [balanced[month].expense_sum for month in months]
    total_income = sum(incomes, Decimal("0.00")).quantize(CENT)
    if total_income <= Decimal("0.00"):
        for summary in balanced.values():
            summary.expense_sum = Decimal("0.00")
            summary.net = Decimal("0.00")
        return balanced

    rng_seed = "|".join(
        [
            "wechat_default_expense",
            ",".join(months),
            ",".join(str(income) for income in incomes),
            ",".join(str(expense) for expense in raw_expenses),
        ]
    )
    import random

    rng = random.Random(rng_seed)
    reserves: list[Decimal] = []
    running_income = Decimal("0.00")
    for income in incomes:
        running_income += income
        reserve = Decimal(rng.randint(int(WECHAT_MIN_MONTHLY_NET), int(WECHAT_MAX_MONTHLY_NET))).quantize(CENT)
        reserves.append(min(reserve, running_income).quantize(CENT))

    target_total_expense = max(total_income - reserves[-1], Decimal("0.00")).quantize(CENT)
    expenses = split_by_weights(target_total_expense, raw_expenses)

    running_income = Decimal("0.00")
    running_expense = Decimal("0.00")
    for index, income in enumerate(incomes):
        running_income += income
        running_expense += expenses[index]
        limit = (running_income - reserves[index]).quantize(CENT)
        if running_expense > limit:
            reduction = min(expenses[index], (running_expense - limit).quantize(CENT))
            expenses[index] = (expenses[index] - reduction).quantize(CENT)
            running_expense = (running_expense - reduction).quantize(CENT)

    remaining = (target_total_expense - sum(expenses, Decimal("0.00"))).quantize(CENT)
    for index in range(len(expenses) - 1, -1, -1):
        if remaining <= Decimal("0.00"):
            break
        addition = min(expense_capacity(index, incomes, reserves, expenses), remaining).quantize(CENT)
        expenses[index] = (expenses[index] + addition).quantize(CENT)
        remaining = (remaining - addition).quantize(CENT)

    for month, expense in zip(months, expenses):
        summary = balanced[month]
        summary.expense_sum = max(expense, Decimal("0.00")).quantize(CENT)
        summary.net = (summary.income_sum - summary.expense_sum).quantize(CENT)
    return balanced


def combined_month_summaries(results: list, selected_months: set[str]) -> list[tuple[str, Summary]]:
    normal_summaries: dict[str, list[Summary]] = {}
    wechat_transactions = []
    for result in results:
        normal_transactions = [
            tx for tx in getattr(result, "transactions", []) or []
            if transaction_flow_type(tx, result) != "微信"
        ]
        for month, summary in monthly_summaries(normal_transactions):
            normal_summaries.setdefault(month, []).append(summary)
        wechat_transactions.extend(
            tx for tx in getattr(result, "transactions", []) or []
            if transaction_flow_type(tx, result) == "微信"
        )

    normal_by_month = {
        month: sum_summaries(summaries)
        for month, summaries in normal_summaries.items()
        if month in selected_months
    }
    wechat_pairs = [(month, summary) for month, summary in monthly_summaries(wechat_transactions) if month in selected_months]
    wechat_by_month = balance_wechat_summaries(wechat_pairs)
    rows = []
    for month in sorted(selected_months):
        normal = normal_by_month.get(month, Summary())
        wechat = wechat_by_month.get(month, Summary())
        rows.append((
            month,
            Summary(
                count=normal.count + wechat.count,
                income_count=normal.income_count + wechat.income_count,
                income_sum=(normal.income_sum + wechat.income_sum).quantize(CENT),
                expense_count=normal.expense_count + wechat.expense_count,
                expense_sum=(normal.expense_sum + wechat.expense_sum).quantize(CENT),
                net=(normal.net + wechat.net).quantize(CENT),
            ),
        ))
    return rows


def flow_month_pairs(results: list, target_flow_type: str | None = None) -> list[tuple[str, Summary]]:
    if target_flow_type == "对公":
        target_results = split_results_by_flow(results, "对公")
    elif target_flow_type == "个人":
        target_results = split_results_by_flow(results, "个人") + split_results_by_flow(results, "微信")
    else:
        target_results = list(results)
    transactions = [tx for result in target_results for tx in getattr(result, "transactions", [])]
    month_pairs = monthly_summaries(transactions)[-6:]
    months = {month for month, _summary in month_pairs}
    return combined_month_summaries(target_results, months)


def add_adjustment(summary: Summary, income_adjustment: Decimal, expense_adjustment: Decimal) -> Summary:
    adjusted = copy_summary(summary)
    adjusted.income_sum = (adjusted.income_sum + income_adjustment).quantize(CENT)
    adjusted.expense_sum = (adjusted.expense_sum + expense_adjustment).quantize(CENT)
    adjusted.net = (adjusted.income_sum - adjusted.expense_sum).quantize(CENT)
    return adjusted


def enabled_adjustment_configs(configs: list[AdjustmentConfig] | None) -> list[AdjustmentConfig]:
    return [config for config in (configs or []) if config.enabled and config.amount_wan != Decimal("0")]


def allocate_adjustments_by_flow(results: list, configs: list[AdjustmentConfig] | None) -> dict[str, dict[str, tuple[Decimal, Decimal]]]:
    active_configs = enabled_adjustment_configs(configs)
    allocations = {"个人": {}, "对公": {}}
    if not active_configs:
        return allocations

    summaries_by_flow = {
        "个人": dict(flow_month_pairs(results, "个人")),
        "对公": dict(flow_month_pairs(results, "对公")),
    }
    months = sorted(set(summaries_by_flow["个人"]) | set(summaries_by_flow["对公"]))
    if not months:
        return allocations

    for config in active_configs:
        target_months = [
            month for month in months
            if (not config.start_month or month >= config.start_month)
            and (not config.end_month or month <= config.end_month)
        ]
        total = (config.amount_wan * WAN).quantize(CENT)
        seed_text = "|".join([config.label, str(total), config.start_month, config.end_month, str(config.balanced), ",".join(target_months)])
        for month, amount in zip(target_months, split_amount(total, len(target_months), config.randomized, seed_text)):
            flow_shares = []
            for flow_name in ("个人", "对公"):
                summary = summaries_by_flow[flow_name].get(month)
                if not summary:
                    base = Decimal("0")
                else:
                    base = summary.income_sum if summary.income_sum > Decimal("0") else summary.expense_sum
                flow_shares.append((flow_name, base))
            total_base = sum((base for _flow_name, base in flow_shares), Decimal("0"))
            if total_base == Decimal("0"):
                flow_shares = [(flow_name, Decimal("1") if month in summaries_by_flow[flow_name] else Decimal("0")) for flow_name in ("个人", "对公")]
                total_base = sum((base for _flow_name, base in flow_shares), Decimal("0"))
            if total_base == Decimal("0"):
                continue

            remaining = amount
            active_flows = [(flow_name, base) for flow_name, base in flow_shares if base != Decimal("0")]
            for index, (flow_name, base) in enumerate(active_flows):
                flow_amount = remaining if index == len(active_flows) - 1 else (amount * base / total_base).quantize(CENT)
                remaining -= flow_amount
                income_adjustment, expense_adjustment = allocations[flow_name].get(month, (Decimal("0"), Decimal("0")))
                income_adjustment += flow_amount
                if config.balanced:
                    expense_adjustment += flow_amount
                allocations[flow_name][month] = (income_adjustment.quantize(CENT), expense_adjustment.quantize(CENT))
    return allocations


def apply_flow_adjustments(month_pairs: list[tuple[str, Summary]], allocations: dict[str, tuple[Decimal, Decimal]] | None) -> list[tuple[str, Summary]]:
    if not allocations:
        return month_pairs
    return [
        (month, add_adjustment(summary, *allocations.get(month, (Decimal("0"), Decimal("0")))))
        for month, summary in month_pairs
    ]


def salary_match_text(tx) -> str:
    raw_fields = " | ".join(str(field) for field in getattr(tx, "raw_fields", []) or [])
    return f"{getattr(tx, 'raw_text', '')} | {raw_fields} | {getattr(tx, 'raw_amount', '')}".strip()


def is_salary_transaction(tx) -> bool:
    if tx.income <= Decimal("0.00"):
        return False
    text = salary_match_text(tx)
    if any(keyword in text for keyword in SALARY_EXCLUDE_KEYWORDS):
        return False
    return any(keyword in text for keyword in SALARY_KEYWORDS)


def salary_flow_block(results: list, adjustment_configs: list[AdjustmentConfig] | None = None) -> dict:
    all_transactions = [tx for result in results for tx in getattr(result, "transactions", [])]
    salary_transactions = [tx for tx in all_transactions if is_salary_transaction(tx)]
    all_months = dict(monthly_summaries(all_transactions))
    salary_months = dict(monthly_summaries(salary_transactions))
    selected_months = sorted(salary_months or all_months)[-6:]
    allocations = allocate_adjustments_by_flow(results, adjustment_configs).get("个人", {})

    total_salary = Summary()
    total_expense = Summary()
    rows = []
    for month in selected_months:
        salary_summary = salary_months.get(month, Summary())
        all_summary = all_months.get(month, Summary())
        income_adjustment, expense_adjustment = allocations.get(month, (Decimal("0"), Decimal("0")))
        total_salary.income_count += salary_summary.income_count
        total_salary.income_sum += salary_summary.income_sum + income_adjustment
        total_expense.expense_count += all_summary.expense_count
        total_expense.expense_sum += all_summary.expense_sum + expense_adjustment
        rows.append(
            {
                "month": month.replace("-", "."),
                "income_count": int(salary_summary.income_count),
                "income_amount_wan": to_wan(salary_summary.income_sum + income_adjustment) or 0,
                "expense_count": int(all_summary.expense_count),
                "expense_amount_wan": to_wan(all_summary.expense_sum + expense_adjustment) or 0,
            }
        )

    total_salary.income_sum = total_salary.income_sum.quantize(CENT)
    total_expense.expense_sum = total_expense.expense_sum.quantize(CENT)
    month_count = Decimal("6")
    return {
        "accounts": unique_accounts(results)[:5],
        "latest_balance_wan": latest_balance_wan(results),
        "salary_keywords": list(SALARY_KEYWORDS),
        "salary_transaction_count": int(total_salary.income_count),
        "summary": {
            "income_count_total": int(total_salary.income_count),
            "income_amount_total_wan": to_wan(total_salary.income_sum) or 0,
            "expense_count_total": int(total_expense.expense_count),
            "expense_amount_total_wan": to_wan(total_expense.expense_sum) or 0,
            "income_monthly_avg_wan": to_wan(total_salary.income_sum / month_count) or 0,
            "expense_monthly_avg_wan": to_wan(total_expense.expense_sum / month_count) or 0,
        },
        "months": rows,
    }


def flow_block(
    results: list,
    target_flow_type: str | None = None,
    adjustment_allocations: dict[str, dict[str, tuple[Decimal, Decimal]]] | None = None,
) -> dict:
    if target_flow_type == "对公":
        results = split_results_by_flow(results, "对公")
    elif target_flow_type == "个人":
        results = split_results_by_flow(results, "个人") + split_results_by_flow(results, "微信")
    month_pairs = flow_month_pairs(results)
    if target_flow_type in ("个人", "对公") and adjustment_allocations:
        month_pairs = apply_flow_adjustments(month_pairs, adjustment_allocations.get(target_flow_type))
    total = Summary()
    for _month, summary in month_pairs:
        total.count += summary.count
        total.income_count += summary.income_count
        total.income_sum += summary.income_sum
        total.expense_count += summary.expense_count
        total.expense_sum += summary.expense_sum
    total.income_sum = total.income_sum.quantize(CENT)
    total.expense_sum = total.expense_sum.quantize(CENT)

    return {
        "accounts": unique_accounts(results)[:5],
        "latest_balance_wan": latest_balance_wan(results),
        "summary": {
            "income_count_total": int(total.income_count),
            "income_amount_total_wan": to_wan(total.income_sum) or 0,
            "expense_count_total": int(total.expense_count),
            "expense_amount_total_wan": to_wan(total.expense_sum) or 0,
            "income_monthly_avg_wan": to_wan(total.income_sum / Decimal("6")) or 0,
            "expense_monthly_avg_wan": to_wan(total.expense_sum / Decimal("6")) or 0,
        },
        "months": [
            {
                "month": month.replace("-", "."),
                "income_count": int(summary.income_count),
                "income_amount_wan": to_wan(summary.income_sum) or 0,
                "expense_count": int(summary.expense_count),
                "expense_amount_wan": to_wan(summary.expense_sum) or 0,
            }
            for month, summary in month_pairs
        ],
    }


def build_income_proof_input(
    results: list,
    template_path: str = "",
    output_path: str = "",
    adjustment_configs: list[AdjustmentConfig] | None = None,
) -> dict:
    personal_results = split_results_by_flow(results, "个人") + split_results_by_flow(results, "微信")
    corporate_results = split_results_by_flow(results, "对公")
    adjustment_allocations = allocate_adjustments_by_flow(results, adjustment_configs)

    return {
        "schema_version": "1.0",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_path": template_path or "D:\\report workflow\\data\\流水佐证自雇.docx",
        "output_path": output_path or "D:\\report workflow\\data\\生成结果_流水佐证自雇.docx",
        "customer": {
            "name": "",
            "city": "",
            "system_monthly_income_wan": 0,
            "report_date": datetime.now().strftime("%Y年%m月%d日"),
        },
        "business": {
            "company_name": "",
            "role": "法人",
            "share_ratio": 1.0,
            "share_ratio_text": "100%",
            "established_date": "",
            "address": "",
            "main_business": "",
            "profit_rate": 0.05,
            "profit_rate_text": "5%",
        },
        "flow_policy": {
            "use_corporate_flow": False,
        },
        "personal_flow": flow_block(results, "个人", adjustment_allocations) if personal_results else empty_flow(),
        "corporate_flow": flow_block(results, "对公", adjustment_allocations) if corporate_results else empty_flow(),
        "notes": {
            "supplement": "",
            "export_note": "客户、单位、占股、地区等字段需人工补充或由后续系统/API填入；未识别到的账号需人工补充；对公流水必须人工确认后才启用。",
        },
    }


def empty_flow() -> dict:
    return {
        "accounts": [],
        "latest_balance_wan": None,
        "summary": {
            "income_count_total": 0,
            "income_amount_total_wan": 0,
            "expense_count_total": 0,
            "expense_amount_total_wan": 0,
            "income_monthly_avg_wan": 0,
            "expense_monthly_avg_wan": 0,
        },
        "months": [],
    }


def write_income_proof_input(
    path: Path,
    results: list,
    template_path: str = "",
    output_path: str = "",
    adjustment_configs: list[AdjustmentConfig] | None = None,
) -> None:
    data = build_income_proof_input(results, template_path=template_path, output_path=output_path, adjustment_configs=adjustment_configs)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def build_salary_income_proof_input(
    results: list,
    template_path: str = "",
    output_path: str = "",
    adjustment_configs: list[AdjustmentConfig] | None = None,
) -> dict:
    personal_results = split_results_by_flow(results, "个人") + split_results_by_flow(results, "微信")
    adjustment_allocations = allocate_adjustments_by_flow(results, adjustment_configs)
    return {
        "schema_version": "1.0",
        "proof_type": "salary",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_path": template_path or "D:\\report workflow\\data\\流水佐证工资.docx",
        "output_path": output_path or "D:\\report workflow\\data\\生成结果_流水佐证工资.docx",
        "customer": {
            "name": "",
            "city": "",
            "system_monthly_income_wan": 0,
            "report_date": datetime.now().strftime("%Y年%m月%d日"),
        },
        "flow_policy": {
            "use_corporate_flow": False,
        },
        "salary_flow": salary_flow_block(personal_results, adjustment_configs) if personal_results else empty_flow(),
        "personal_flow": flow_block(personal_results, "个人", adjustment_allocations) if personal_results else empty_flow(),
        "corporate_flow": empty_flow(),
        "notes": {
            "supplement": "",
            "export_note": "工资类佐证：流入仅统计摘要/原始字段命中工资、薪资、薪酬、奖金、奖、代发工资的入账，并排除补助、补贴、补增资、报销、退款；流出统计个人账户全量支出。",
        },
    }


def write_salary_income_proof_input(
    path: Path,
    results: list,
    template_path: str = "",
    output_path: str = "",
    adjustment_configs: list[AdjustmentConfig] | None = None,
) -> None:
    data = build_salary_income_proof_input(results, template_path=template_path, output_path=output_path, adjustment_configs=adjustment_configs)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
