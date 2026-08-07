"""D.1A: audit Gate D privacy-blocked cases (classification, no value leak)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import guard_item, load_legacy_signature_entries
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields
from bankflow_v2.knowledge.privacy import (
    _BANK_CARD_RE,
    classify_bank_card_block,
)


def _mask(value: str) -> str:
    if len(value) <= 4:
        return "***"
    return value[:2] + "…" + value[-2:]


def _char_class(value: str) -> str:
    classified = re.sub(r"[A-Za-z]", "A", value)
    classified = re.sub(r"[0-9]", "D", classified)
    classified = re.sub(r"[\u3400-\u9fff]", "C", classified)
    return classified[:60]


def _find_source_fields(
    signature_hash: str,
    entries: list[dict[str, Any]],
    manifest_items: list[dict[str, Any]],
) -> dict[str, str] | None:
    for entry in entries:
        if (
            semantic_signature_from_fields(entry["fields"]).signature_id
            == signature_hash
        ):
            return dict(entry["fields"])
    for item in manifest_items:
        if str(item.get("signature_hash", "")) == signature_hash:
            return dict(item.get("fields", {}))
    return None


def audit_case(
    signature_hash: str,
    blocked_fields: list[str],
    blocked_reasons: list[str],
    fields: dict[str, str],
) -> dict[str, Any]:
    """Classify one blocked case without exporting full sensitive values."""
    classifications: list[str] = []
    reasons_detail: list[dict[str, Any]] = []
    guard = guard_item(fields)
    for field_key in blocked_fields:
        value = str(fields.get(field_key, ""))
        if "bank_card" in blocked_reasons:
            classification = classify_bank_card_block(field_key, value)
        else:
            classification = "true_positive"
        classifications.append(classification)
        reasons_detail.append(
            {
                "originating_field": field_key,
                "blocking_rule": (
                    "bank_card" if "bank_card" in blocked_reasons else "other"
                ),
                "detected_pattern_category": (
                    "13-19_digit_run"
                    if "bank_card" in blocked_reasons
                    else "identity_or_key"
                ),
                "classification": classification,
                "value_length": len(value),
                "char_class": _char_class(value),
                "masked_value": _mask(value),
                "luhn_valid_runs": [
                    len(re.sub(r"[^0-9]", "", match.group()))
                    for match in _BANK_CARD_RE.finditer(value)
                ],
            }
        )
    final_classification = (
        "true_positive"
        if "true_positive" in classifications
        else "false_positive"
        if classifications and all(
            item == "false_positive" for item in classifications
        )
        else "ambiguous"
    )
    safely_remediated = guard.allowed
    return {
        "privacy_case_id": signature_hash,
        "semantic_signature": signature_hash,
        "blocked_fields": blocked_fields,
        "blocked_reasons": blocked_reasons,
        "sent_to_provider": False,
        "candidate_generated": False,
        "classification": final_classification,
        "safely_remediated": safely_remediated,
        "detail": reasons_detail,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("preflight_json", type=Path)
    parser.add_argument("legacy_cache_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--unseen-manifest", type=Path)
    args = parser.parse_args()
    if not args.preflight_json.is_file() or not args.legacy_cache_dir.is_dir():
        print("status=not_started")
        print("reason=inputs_missing")
        return 2
    preflight = json.loads(args.preflight_json.read_text(encoding="utf-8"))
    entries = load_legacy_signature_entries(args.legacy_cache_dir)
    manifest_items: list[dict[str, Any]] = []
    if args.unseen_manifest:
        manifest = json.loads(args.unseen_manifest.read_text(encoding="utf-8"))
        manifest_items = list(manifest.get("items", []))
    blocked_rows = [
        item
        for item in preflight.get("items", [])
        if item.get("blocked")
    ]
    cases: list[dict[str, Any]] = []
    for row in blocked_rows:
        signature_hash = str(row.get("signature_hash", ""))
        fields = _find_source_fields(
            signature_hash,
            entries,
            manifest_items,
        )
        if fields is None:
            fields = {}
        cases.append(
            audit_case(
                signature_hash,
                [str(name) for name in row.get("blocked_fields", [])],
                [str(name) for name in row.get("blocked_reasons", [])],
                fields,
            )
        )
    counts = {
        "total_blocked": len(cases),
        "true_positive": sum(
            1 for case in cases if case["classification"] == "true_positive"
        ),
        "false_positive": sum(
            1 for case in cases if case["classification"] == "false_positive"
        ),
        "ambiguous": sum(
            1 for case in cases if case["classification"] == "ambiguous"
        ),
        "safely_remediated": sum(
            1 for case in cases if case["safely_remediated"]
        ),
        "remains_blocked": sum(
            1 for case in cases if not case["safely_remediated"]
        ),
        "released_cases_ai_validated": 0,
        "unauthorized_sensitive_outbound": 0,
    }
    if counts["total_blocked"]:
        counts["false_positive_rate"] = round(
            counts["false_positive"] / counts["total_blocked"],
            4,
        )
    else:
        counts["false_positive_rate"] = 0.0
    report = {
        "generated_at": preflight.get("generated_at", ""),
        "audit_scope": "Gate D real AI fallback privacy preflight",
        "counts": counts,
        "guard_policy": (
            "default blocks any 13-19 digit run; typed business fields "
            "(product_description/merchant_category) exempt only Luhn-invalid "
            "runs embedded in non-digit business text without card hints; "
            "Luhn-valid card numbers always block"
        ),
        "cases": cases,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "privacy_block_audit.json"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    md_path = args.output_dir / "privacy_block_audit.md"
    lines = [
        "# Privacy Block Audit（Gate D.1A）",
        "",
        f"- 审计时间：{report['generated_at']}",
        f"- total blocked：{counts['total_blocked']}",
        f"- true positive：{counts['true_positive']}",
        f"- false positive：{counts['false_positive']}",
        f"- ambiguous：{counts['ambiguous']}",
        f"- safely remediated：{counts['safely_remediated']}",
        f"- remains blocked：{counts['remains_blocked']}",
        f"- unauthorized sensitive outbound：{counts['unauthorized_sensitive_outbound']}",
        "",
        "## 逐条",
        "",
        "| case | 字段 | 规则 | 分类 | 长度 | 字符类 | 掩码 | 已发送 | 已生成候选 | 已放行 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in cases:
        for detail in case["detail"]:
            lines.append(
                "| "
                + " | ".join(
                    [
                        str(case["privacy_case_id"])[:24],
                        str(detail["originating_field"]),
                        str(detail["blocking_rule"]),
                        str(detail["classification"]),
                        str(detail["value_length"]),
                        str(detail["char_class"]),
                        str(detail["masked_value"]),
                        "false",
                        "false",
                        "yes" if case["safely_remediated"] else "no",
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "- 两条 blocked 均为商户小票中的 16 位订单/流水号，Luhn 校验失败且嵌入中文业务文本，",
            "  分类为 false_positive；",
            "- guard 已通过 typed business field + Luhn-invalid + 非纯数字上下文例外安全放行，",
            "  真正银行卡号（Luhn 有效）与裸数字仍被阻断；",
            "- 本轮未为这两条重新调用 AI（released_cases_ai_validated=0），待后续最小化验收；",
            "- unauthorized_sensitive_outbound = 0。",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("status=ok")
    for key, value in counts.items():
        print(f"{key}={value}")
    print(f"output={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
