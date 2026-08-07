"""Export a human-reviewable, redacted mismatch dataset for Gate A."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    load_legacy_signature_entries,
)

from _profiles import PRESETS, classify_profile_name, resolve_profile


_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LONG_DIGIT_RE = re.compile(r"\d{6,}")
_ID_CARD_RE = re.compile(
    r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])"
    r"(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]\b"
)


def redact(value: str) -> str:
    text = str(value or "")
    text = _ID_CARD_RE.sub("***", text)
    text = _PHONE_RE.sub("***", text)
    text = _LONG_DIGIT_RE.sub("***", text)
    return text


def _rank(value: str) -> int:
    return {
        "none": 0,
        "weak": 1,
        "medium": 2,
        "strong": 3,
        "undetermined": -1,
    }.get(value, -2)


def mismatch_type(legacy: str, knowledge: str) -> str:
    if knowledge == "undetermined" and legacy != "undetermined":
        return "legacy_to_undetermined"
    if legacy == "undetermined" and knowledge != "undetermined":
        return "other_direction_change"
    if _rank(knowledge) > _rank(legacy):
        return "upgrade"
    if _rank(knowledge) < _rank(legacy):
        return "downgrade"
    return "other_direction_change"


def _inherited_from(
    runtime: KnowledgeRuntime,
    industry_id: str,
    concept_id: str,
) -> str:
    for node in runtime.taxonomy.parent_chain(industry_id)[1:]:
        if runtime.relations.approved(node.industry_id, concept_id) is not None:
            return node.industry_id
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_cache_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--canonical-dir", type=Path, default=Path("bankflow_v2/knowledge/canonical"))
    parser.add_argument(
        "--profile",
        choices=sorted(
            [
                "building_material",
                "construction_coal",
                "alcohol_retail",
                "furniture_decoration",
            ]
        ),
    )
    parser.add_argument("--profile-json", type=Path)
    parser.add_argument(
        "--per-entry-profile",
        action="store_true",
        help="按 legacy 业务上下文为每条签名使用对应行业画像",
    )
    args = parser.parse_args()

    profile = resolve_profile(
        args.profile,
        str(args.profile_json) if args.profile_json else None,
    )
    runtime = KnowledgeRuntime.load(args.canonical_dir)
    entries = load_legacy_signature_entries(args.legacy_cache_dir)
    rows: list[dict[str, object]] = []
    for index, entry in enumerate(entries, start=1):
        fields = entry["fields"]
        entry_profile = profile
        profile_name = ""
        if args.per_entry_profile:
            profile_name = classify_profile_name(
                entry["legacy_business_context"]
            )
            entry_profile = PRESETS.get(profile_name, profile)
        resolved = runtime.resolve_transaction_fields(fields, entry_profile)
        legacy = entry["legacy_semantic_judgement"]
        knowledge = resolved["final_relevance"]
        if legacy == knowledge:
            continue
        relations: list[dict[str, object]] = []
        for relation in resolved["relations"]:
            industry_id = str(relation.get("industry_id", ""))
            concept_id = str(relation.get("concept_id", ""))
            relations.append(
                {
                    "industry_id": industry_id,
                    "industry_name": (
                        runtime.taxonomy.node(industry_id).name
                        if runtime.taxonomy.node(industry_id)
                        else ""
                    ),
                    "concept_id": concept_id,
                    "relevance": relation.get("relevance", ""),
                    "relation_resolution_source": relation.get(
                        "relation_source",
                        "",
                    ),
                    "relation_ref": f"{industry_id}×{concept_id}",
                    "inherited": relation.get("relation_source") == "inherited",
                    "inherited_from_industry_id": (
                        _inherited_from(runtime, industry_id, concept_id)
                        if relation.get("relation_source") == "inherited"
                        else ""
                    ),
                    "knowledge_version": relation.get(
                        "knowledge_version",
                        "",
                    ),
                }
            )
        semantic = resolved["semantic"]
        concept_id = str(semantic.get("concept_id", ""))
        industry_ids = list(entry_profile.primary_industry_ids) + list(
            entry_profile.secondary_industry_ids
        )
        rows.append(
            {
                "mismatch_id": f"mm-{index:03d}",
                "signature_hash": entry["signature_hash"],
                "profile_name": profile_name or str(
                    getattr(entry_profile, "profile_name", "")
                ),
                "legacy_relevance": legacy,
                "knowledge_relevance": knowledge,
                "mismatch_type": mismatch_type(legacy, knowledge),
                "fields": {
                    str(name): redact(str(value))
                    for name, value in fields.items()
                },
                "knowledge": {
                    "concept_id": concept_id,
                    "concept_name": str(semantic.get("concept_name", "")),
                    "concept_resolution_source": str(
                        semantic.get("source", "")
                    ),
                    "industry_ids": industry_ids,
                    "industry_names": [
                        (
                            runtime.taxonomy.node(industry_id).name
                            if runtime.taxonomy.node(industry_id)
                            else ""
                        )
                        for industry_id in industry_ids
                    ],
                    "relations": relations,
                    "constraint_maximum": str(
                        resolved["constraints"].get(
                            "maximum_allowed_strength",
                            "",
                        )
                    ),
                    "directly_related_allowed": bool(
                        resolved["constraints"].get(
                            "directly_related_allowed",
                            False,
                        )
                    ),
                    "knowledge_version": runtime.version.knowledge_version,
                },
                "legacy": {
                    "relevance": legacy,
                    "reason": redact(entry["legacy_reason"]),
                    "used_fields": entry["legacy_used_fields"],
                    "business_context": {
                        str(name): redact(str(value))
                        for name, value in entry[
                            "legacy_business_context"
                        ].items()
                    },
                },
                "adjudication": {
                    "adjudicated_relevance": "",
                    "preferred_system": "",
                    "issue_type": "",
                    "action_required": "",
                    "reviewer_note": "",
                },
            }
        )

    counts: dict[str, int] = {}
    for row in rows:
        key = str(row["mismatch_type"])
        counts[key] = counts.get(key, 0) + 1
    output = {
        "export_version": "mismatch-review-v1",
        "profile": profile.to_dict(),
        "per_entry_profile": args.per_entry_profile,
        "total": len(rows),
        "mismatch_type_counts": counts,
        "rows": rows,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "mismatch_review.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# knowledge_v1 121 条 mismatch 人工审核数据",
        "",
        "- 导出时间：2026-08-07",
        f"- 总数：{len(rows)}",
    ]
    for key, count in sorted(counts.items()):
        lines.append(f"- {key}：{count}")
    lines.extend(
        [
            "",
            "审核规则：",
            "",
            "- mismatch 为逐签名比较，方向不限；",
            "- upgrade / downgrade / legacy_to_undetermined / other_direction_change；",
            "- 审核产物已脱敏（手机号/长数字/证件号掩码），不复制敏感原文；",
            "- 详细字段见同目录 mismatch_review.json。",
        ]
    )
    (args.output_dir / "mismatch_review.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )
    print("status=ok")
    print(f"total={len(rows)}")
    for key, count in sorted(counts.items()):
        print(f"{key}={count}")
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
