"""Field-level spot check for real statements.

Parses every PDF in a case directory, samples a small deterministic set of
transactions per source (personal bank / corporate bank / WeChat / Alipay /
Excel), and renders the mapped standard fields next to the original fields
for human verification. A mechanical "traceable" check flags values that
cannot be found in the original raw text/fields.

No credentials are loaded and no model is called.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.pipeline import extract_transactions


UNIFIED_FIELDS = (
    "counterparty_name",
    "summary",
    "remark",
    "purpose",
    "product_description",
    "merchant_name",
    "merchant_category",
    "transaction_method",
)


def _normalize(value: str) -> str:
    return re.sub(r"[\s\u3000]+", "", str(value or ""))


def _sample_indices(total: int, size: int) -> list[int]:
    if total <= 0:
        return []
    if total <= size:
        return list(range(total))
    if size <= 1:
        return [0]
    return sorted(
        {
            round(i * (total - 1) / (size - 1))
            for i in range(size)
        }
    )


def _direction_amount(transaction) -> tuple[str, str]:
    income = str(getattr(transaction, "income", "") or "0.00")
    expense = str(getattr(transaction, "expense", "") or "0.00")
    if income not in {"", "0", "0.0", "0.00", "None"}:
        return "收入", income
    if expense not in {"", "0", "0.0", "0.00", "None"}:
        return "支出", expense
    return "中性", "0.00"


def _traceable(value: str, raw_text: str, raw_fields: list[str]) -> bool:
    normalized = _normalize(value)
    if not normalized:
        return True
    if normalized in _normalize(raw_text):
        return True
    return any(normalized in _normalize(field) for field in raw_fields)


def _spot_check(case_dir: Path, sample_size: int) -> dict[str, object]:
    sources: dict[str, dict[str, object]] = {}
    for pdf_path in sorted(case_dir.glob("*.pdf")):
        detection = detect_bank_type(str(pdf_path))
        if not detection.bank_id:
            print(f"ignored_unrecognized_pdf={pdf_path.name}")
            continue
        print(f"parsing={pdf_path.name}")
        transactions = extract_transactions(str(pdf_path), detection.bank_id)
        bank = detection.bank_id
        if bank == "ccb":
            bank = "中国建设银行"
        elif bank == "abc":
            bank = "中国农业银行"
        elif bank == "boc":
            bank = "中国银行"
        elif bank == "icbc":
            bank = "中国工商银行"
        elif bank == "cib":
            bank = "兴业银行"
        elif bank == "wechat":
            bank = "微信流水"
        elif bank == "alipay":
            bank = "支付宝交易流水"
        rows = []
        for index in _sample_indices(len(transactions), sample_size):
            transaction = transactions[index]
            direction, amount = _direction_amount(transaction)
            raw_fields = list(getattr(transaction, "raw_fields", []) or [])
            raw_text = str(getattr(transaction, "raw_text", "") or "")
            standard_fields = {}
            field_sources = dict(getattr(transaction, "field_sources", {}) or {})
            field_confidence = dict(
                getattr(transaction, "field_confidence", {}) or {}
            )
            for field in UNIFIED_FIELDS:
                value = str(getattr(transaction, field, "") or "").strip()
                if not value:
                    continue
                standard_fields[field] = {
                    "value": value,
                    "confidence": float(field_confidence.get(field, 0.0)),
                    "source": str(field_sources.get(field, "")),
                    "traceable": _traceable(value, raw_text, raw_fields),
                }
            rows.append({
                "transaction_id": str(transaction.transaction_id),
                "page_no": int(getattr(transaction, "page_no", 0) or 0),
                "row_no": int(getattr(transaction, "row_no", 0) or 0),
                "transaction_time": str(transaction.transaction_time or ""),
                "direction": direction,
                "amount": amount,
                "raw_text": raw_text,
                "raw_fields": raw_fields,
                "standard_fields": standard_fields,
            })
        sources[pdf_path.name] = {
            "bank": bank,
            "parsed_transactions": len(transactions),
            "sampled": rows,
        }
    return {"case_dir": str(case_dir), "sources": sources}


def _render_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# 流水文字字段级抽查（人工核对）",
        "",
        f"- 案件目录：`{payload['case_dir']}`",
        "- 范围：个人银行 / 对公 / 微信 / 支付宝等真实来源各抽一批交易。",
        "- 目的：人工核对统一标准字段（对手、摘要、备注、用途、商品等）与原始字段是否对应。",
        "- 机械检查：每个非空标准字段值须能在原始 raw_text/raw_fields 中溯源；未溯源项标为“待人工核对”。",
        "- 本报告不加载 Key、不调用模型。",
        "",
    ]
    total_fields = 0
    untraceable = 0
    for source_name, source in sorted(payload["sources"].items()):
        sampled = source["sampled"]
        lines.extend([
            f"## {source_name}（{source['bank']}，共 {source['parsed_transactions']} 笔，抽查 {len(sampled)} 笔）",
            "",
            "| # | 日期 | 方向 | 金额 | 页/行 | 原始字段 | 标准字段 | 字段来源 | 溯源 |",
            "| --- | --- | --- | ---: | --- | --- | --- | --- | --- |",
        ])
        for number, row in enumerate(sampled, start=1):
            raw_text = row["raw_text"] or "（无 raw_text）"
            raw_fields = "；".join(
                f"raw_fields[{index}]={value}"
                for index, value in enumerate(row["raw_fields"])
            ) or "（无 raw_fields）"
            standard = "；".join(
                f"{field}={item['value']}"
                for field, item in sorted(row["standard_fields"].items())
            ) or "（无统一字段）"
            sources = "；".join(
                f"{field}←{item['source'] or '?'}"
                for field, item in sorted(row["standard_fields"].items())
            ) or "—"
            traceable_flags = [
                item["traceable"]
                for item in row["standard_fields"].values()
            ]
            for item in row["standard_fields"].values():
                total_fields += 1
                if not item["traceable"]:
                    untraceable += 1
            trace = "是" if all(traceable_flags) else f"待核对（{sum(not f for f in traceable_flags)}）"
            date = str(row["transaction_time"])[:19]
            lines.append(
                f"| {number} | {date} | {row['direction']} | {row['amount']} "
                f"| p{row['page_no']}r{row['row_no']} "
                f"| {raw_text}；{raw_fields} "
                f"| {standard} | {sources} | {trace} |"
            )
        lines.append("")
    lines.extend([
        "## 汇总",
        "",
        f"- 抽查非空标准字段：{total_fields}",
        f"- 未溯源（待人工核对）：{untraceable}",
        "",
        "未溯源不代表解析错误，只表示需要人工回到原件核对；标准字段为空表示该来源未映射或未提取。",
    ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("output_md", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--sample-size", type=int, default=10)
    args = parser.parse_args()
    if not args.case_dir.is_dir():
        print("status=not_started")
        print("reason=case_directory_not_found")
        return 2
    payload = _spot_check(args.case_dir, args.sample_size)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(
        _render_markdown(payload) + "\n",
        encoding="utf-8",
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"report={args.output_md}")
    print(f"detail={args.output_json}")
    print("status=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
