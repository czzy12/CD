"""Audit every real-case AI semantic input without loading credentials or calling AI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.ai_business_observation import (
    build_ai_input_audit,
    build_fixed_ai_sample_manifest,
)
from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.case_context import (
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)
from bankflow_v2.pipeline import extract_transactions


def _sources(case_dir: Path) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for text_path in sorted(case_dir.glob("*.txt")):
        role = (
            SOURCE_ROLE_RISK_INVESTIGATION_REPORT
            if "调查报告" in text_path.name
            else SOURCE_ROLE_SYSTEM_CUSTOMER_DATA
        )
        sources.append(
            {
                "source_ref": text_path.name,
                "source_role": role,
                "text": text_path.read_text(encoding="utf-8"),
            }
        )
    return sources


def _markdown(case_name: str, audit: dict[str, object]) -> str:
    lines = [
        f"# {case_name} AI经营语义纯本地输入审计",
        "",
        "- 本报告未读取 API Key，未调用任何模型。",
        f"- 原交易：{audit['transaction_count']}笔",
        f"- 确定性精确命中：{audit['deterministic_exact_match_count']}笔",
        f"- v9口径候选：{audit['legacy_ai_candidate_count']}笔",
        f"- v9口径唯一语义：{audit['legacy_unique_semantic_signature_count']}种",
        (
            "- 确定性边界后送模候选："
            f"{audit['model_candidate_count_after_deterministic_boundaries']}笔"
        ),
        (
            "- 确定性边界后唯一语义："
            f"{audit['model_unique_semantic_signature_count_after_deterministic_boundaries']}种"
        ),
        (
            "- 本地直接归为非经营："
            f"{audit['deterministic_non_business_transaction_count']}笔"
        ),
        "",
        "## 无语义字段分类",
        "",
    ]
    category_counts = audit.get(
        "field_filter_category_counts_by_unique_signature",
        {},
    )
    if isinstance(category_counts, dict):
        for category, count in sorted(category_counts.items()):
            lines.append(f"- {category}：{count}种唯一语义")
    lines.extend(["", "## 最高允许强度", ""])
    strength_counts = audit.get("maximum_allowed_strength_counts", {})
    if isinstance(strength_counts, dict):
        for strength, count in sorted(strength_counts.items()):
            lines.append(f"- {strength}：{count}种")
    lines.extend(["", "## direct硬边界", ""])
    allowed_counts = audit.get("directly_related_allowed_counts", {})
    if isinstance(allowed_counts, dict):
        for state, count in sorted(allowed_counts.items()):
            lines.append(f"- {state}：{count}种")
    lines.extend(
        [
            "",
            "## 通用性边界",
            "",
            "- 经营判断只使用统一标准字段；银行名、原始表头和PDF列位置不参与业务分类。",
            "- 原始字段、字段来源、来源文件、交易ID和页行证据仍保留在本地审计明细。",
            "- `product_description` 是当前项目的统一商品字段名；`goods_description` 不是现行模型字段。",
            "- `transaction_type`、`transaction_method`、`payment_method`可追溯，但不单独构成行业证据。",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("--markdown-path", type=Path)
    parser.add_argument("--manifest-path", type=Path)
    args = parser.parse_args()
    if not args.case_dir.is_dir():
        print("status=not_started")
        print("reason=case_directory_not_found")
        return 2

    context = build_case_context(args.case_dir.name, _sources(args.case_dir))
    transactions = []
    for pdf_path in sorted(args.case_dir.glob("*.pdf")):
        detection = detect_bank_type(str(pdf_path))
        if not detection.bank_id:
            print(f"ignored_unrecognized_pdf={pdf_path.name}")
            continue
        print(f"parsing={pdf_path.name}")
        transactions.extend(
            extract_transactions(str(pdf_path), detection.bank_id)
        )

    audit = build_ai_input_audit(
        transactions,
        context,
        allow_business_names=True,
    )
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.markdown_path:
        args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_path.write_text(
            _markdown(args.case_dir.name, audit) + "\n",
            encoding="utf-8",
        )
    if args.manifest_path:
        manifest = build_fixed_ai_sample_manifest(
            transactions,
            context,
            allow_business_names=True,
        )
        args.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print("status=ok")
    print(f"legacy_unique_semantics={audit['legacy_unique_semantic_signature_count']}")
    print(
        "model_unique_semantics_after_boundaries="
        f"{audit['model_unique_semantic_signature_count_after_deterministic_boundaries']}"
    )
    print(f"audit={args.audit_json}")
    if args.manifest_path:
        print(f"manifest={args.manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
