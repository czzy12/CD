import json
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from .summary import monthly_summaries, summarize


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


def latest_balance_wan(results: Iterable) -> float | None:
    total = Decimal("0")
    found = False
    for result in results:
        summary = getattr(result, "summary", None)
        closing = getattr(summary, "closing_balance", None)
        if closing is not None:
            total += closing
            found = True
    return to_wan(total) if found else None


def flow_block(results: list) -> dict:
    transactions = [tx for result in results for tx in getattr(result, "transactions", [])]
    month_pairs = monthly_summaries(transactions)
    month_pairs = month_pairs[-6:]
    # Rebuild the transaction slice by month so totals match the exported rows.
    months = {month for month, _summary in month_pairs}
    selected_transactions = [
        tx for tx in transactions if tx.transaction_time.strftime("%Y-%m") in months
    ]
    total = summarize(selected_transactions, "收入佐证导出")

    return {
        "accounts": [account_from_result(result) for result in results[:5]],
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
