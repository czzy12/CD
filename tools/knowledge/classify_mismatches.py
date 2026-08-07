"""Recompute and bucket every legacy_v11 vs knowledge_v1 mismatch (no unexplained)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    MISMATCH_TYPES,
    compare_legacy_cache,
)

from _profiles import PRESETS, classify_profile_name, resolve_profile


def build_report(
    legacy_cache_dir: Path,
    *,
    canonical_dir: Path,
    cache_root: Path | None,
    profile: object,
) -> dict[str, object]:
    runtime = KnowledgeRuntime.load(canonical_dir, cache_root=cache_root)

    def profile_resolver(business_context):
        name = classify_profile_name(business_context)
        return PRESETS.get(name)

    report = compare_legacy_cache(
        legacy_cache_dir,
        runtime,
        profile,
        cache_root=cache_root,
        profile_resolver=profile_resolver,
    )
    rows = []
    for row in report["disagreements"]:
        rows.append(
            {
                "mismatch_id": str(row.get("signature_hash", "")),
                "legacy_relevance": str(row.get("legacy_semantic_judgement", "")),
                "knowledge_relevance": str(row.get("knowledge_relevance", "")),
                "mismatch_type": str(row.get("mismatch_type", "")),
                "reason": str(row.get("mismatch_reason", "")),
                "concept_id": str(row.get("concept_id", "")),
                "industry_id": str(row.get("industry_id", "")),
                "relation_source": str(row.get("relation_source", "")),
                "constraint_maximum": str(row.get("constraint_maximum", "")),
            }
        )
    classification = {
        str(name): int(report["mismatch_classification"].get(name, 0))
        for name in MISMATCH_TYPES
    }
    total = int(report["disagreement_count"])
    bucket_sum = sum(classification.values())
    unexplained = {
        name: count
        for name, count in classification.items()
        if name in {"other", "same_strength_different_state"} and count
    }
    output = {
        "legacy_cache_dir": str(legacy_cache_dir),
        "total_mismatch": total,
        "bucket_sum": bucket_sum,
        "bucket_sum_equals_total": total == bucket_sum,
        "classification": classification,
        "unexplained": unexplained,
        "rows": rows,
    }
    return output


def render_markdown(report: dict[str, object]) -> str:
    lines = [
        "# 96 mismatch 全量分类（无 unexplained 桶）",
        "",
        f"- 来源缓存：`{report['legacy_cache_dir']}`",
        f"- mismatch 总数：{report['total_mismatch']}",
        f"- 分类加总：{report['bucket_sum']}（相等：{report['bucket_sum_equals_total']}）",
        "",
        "## 分类分布",
        "",
    ]
    for name, count in sorted(report["classification"].items()):
        lines.append(f"- {name}：{count}")
    lines.extend(
        [
            "",
            "## 逐条明细（仅签名哈希与通用语义，不含原文）",
            "",
            "| mismatch_id | legacy | knowledge | 分类 | 概念 | 行业 | 关系来源 | 硬上限 | 原因 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in report["rows"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["mismatch_id"])[:24],
                    str(row["legacy_relevance"]),
                    str(row["knowledge_relevance"]),
                    str(row["mismatch_type"]),
                    str(row["concept_id"]),
                    str(row["industry_id"]),
                    str(row["relation_source"]),
                    str(row["constraint_maximum"]),
                    str(row["reason"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_cache_dir", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--markdown-path", type=Path)
    parser.add_argument(
        "--profile",
        choices=sorted(PRESETS),
        default="building_material",
        help="默认画像（per-entry 画像优先，此值仅作回退）",
    )
    parser.add_argument("--profile-json", type=Path)
    args = parser.parse_args()
    if not args.legacy_cache_dir.is_dir():
        print("status=not_started")
        print("reason=legacy_cache_dir_not_found")
        return 2
    profile = resolve_profile(
        args.profile,
        str(args.profile_json) if args.profile_json else None,
    )
    report = build_report(
        args.legacy_cache_dir,
        canonical_dir=args.canonical_dir,
        cache_root=args.cache_root,
        profile=profile,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.markdown_path:
        args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_path.write_text(
            render_markdown(report) + "\n",
            encoding="utf-8",
        )
    print("status=ok")
    print(f"total_mismatch={report['total_mismatch']}")
    print(f"bucket_sum={report['bucket_sum']}")
    print(f"bucket_sum_equals_total={report['bucket_sum_equals_total']}")
    print(f"unexplained={json.dumps(report['unexplained'], ensure_ascii=False)}")
    for name, count in sorted(report["classification"].items()):
        print(f"{name}={count}")
    print(f"output={args.output_json}")
    if not report["bucket_sum_equals_total"] or report["unexplained"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
