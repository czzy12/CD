import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from .summary import Summary, monthly_summaries, summarize


CENT = Decimal("0.01")
WAN = Decimal("10000")


CORP_BANK_IDS = {
    "abc_corp",
    "boc_corp",
    "ccb_corp",
    "cmbc_corp",
    "icbc_corp",
    "spdb_corp",
}


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


def normalize_bank_name(label: str, bank_id: str) -> str:
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
    if text == "Excel":
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
        "flow_type": flow_type(getattr(result, "bank_id", "")),
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
        return (flow_type(getattr(result, "bank_id", "")), account_no)
    source_path = getattr(getattr(result, "path", None), "name", "")
    return (flow_type(getattr(result, "bank_id", "")), source_path)


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


def balance_wechat_summaries(month_pairs: list[tuple[str, Summary]]) -> dict[str, Summary]:
    balanced = {month: copy_summary(summary) for month, summary in month_pairs}
    if not balanced:
        return balanced
    months = list(balanced)
    rng_seed = "|".join(
        [
            "wechat_default_expense",
            ",".join(months),
            ",".join(str(balanced[month].income_sum) for month in months),
            ",".join(str(balanced[month].expense_sum) for month in months),
        ]
    )
    import random

    rng = random.Random(rng_seed)
    for index, month in enumerate(months):
        summary = balanced[month]
        if summary.income_sum <= Decimal("0"):
            target_net = Decimal("0.00")
        elif index == 0 or index == len(months) - 1:
            target_net = min(Decimal("0.01"), summary.income_sum).quantize(CENT)
        else:
            random_net = (Decimal(rng.randint(2, 100)) / Decimal("100")).quantize(CENT)
            target_net = min(random_net, summary.income_sum).quantize(CENT)
        summary.expense_sum = max(summary.income_sum - target_net, Decimal("0.00")).quantize(CENT)
        summary.net = (summary.income_sum - summary.expense_sum).quantize(CENT)
    return balanced


def combined_month_summaries(results: list, selected_months: set[str]) -> list[tuple[str, Summary]]:
    normal_transactions = []
    wechat_transactions = []
    for result in results:
        target = wechat_transactions if flow_type(getattr(result, "bank_id", "")) == "微信" else normal_transactions
        target.extend(getattr(result, "transactions", []) or [])

    normal_by_month = {month: summary for month, summary in monthly_summaries(normal_transactions) if month in selected_months}
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


def flow_block(results: list) -> dict:
    transactions = [tx for result in results for tx in getattr(result, "transactions", [])]
    month_pairs = monthly_summaries(transactions)
    month_pairs = month_pairs[-6:]
    # Rebuild the transaction slice by month so totals match the exported rows.
    months = {month for month, _summary in month_pairs}
    month_pairs = combined_month_summaries(results, months)
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


def build_income_proof_input(results: list, template_path: str = "", output_path: str = "") -> dict:
    personal_results = [
        result for result in results if flow_type(getattr(result, "bank_id", "")) != "对公"
    ]
    corporate_results = [
        result for result in results if flow_type(getattr(result, "bank_id", "")) == "对公"
    ]

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
        "personal_flow": flow_block(personal_results) if personal_results else empty_flow(),
        "corporate_flow": flow_block(corporate_results) if corporate_results else empty_flow(),
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


def write_income_proof_input(path: Path, results: list, template_path: str = "", output_path: str = "") -> None:
    data = build_income_proof_input(results, template_path=template_path, output_path=output_path)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
