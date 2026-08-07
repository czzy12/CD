"""legacy_v11 vs knowledge_v1 shadow comparison (offline, no provider calls)."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .models import AIUsageStats, IndustryProfile
from .resolver import KnowledgeRuntime


_STRENGTH_RANK = {
    "none": 0,
    "weak": 1,
    "medium": 2,
    "strong": 3,
}


def load_legacy_signature_entries(
    legacy_cache_dir: str | Path,
) -> list[dict[str, Any]]:
    """Load business_relevance signature cache entries (no customer identity)."""
    root = Path(legacy_cache_dir)
    entries: list[dict[str, Any]] = []
    signatures_root = root / "signatures"
    if not signatures_root.is_dir():
        return entries
    for namespace in sorted(signatures_root.iterdir()):
        if not namespace.is_dir():
            continue
        for path in sorted(namespace.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, Mapping):
                continue
            if data.get("task_type") != "business_relevance":
                continue
            if data.get("prompt_version") != "business-relevance-mvp-v11":
                continue
            input_data = data.get("input")
            if not isinstance(input_data, Mapping):
                continue
            fields = input_data.get("fields")
            if not isinstance(fields, Mapping):
                continue
            legacy_business_context = input_data.get("business_context", {})
            if not isinstance(legacy_business_context, Mapping):
                legacy_business_context = {}
            response_item = data.get("response_item")
            if not isinstance(response_item, Mapping):
                response_item = {}
            entries.append(
                {
                    "cache_path": str(path),
                    "signature_id": str(data.get("semantic_signature", ""))[:24],
                    "signature_hash": path.stem,
                    "model": str(data.get("model", "")),
                    "prompt_version": str(data.get("prompt_version", "")),
                    "fields": {
                        str(name): str(value)
                        for name, value in fields.items()
                        if str(value).strip()
                    },
                    "legacy_semantic_judgement": str(
                        response_item.get("semantic_judgement", "")
                    ),
                    "legacy_reason": str(response_item.get("reason", "")),
                    "legacy_used_fields": [
                        str(item)
                        for item in response_item.get("used_fields", [])
                    ],
                    "legacy_business_context": {
                        str(name): str(value)
                        for name, value in legacy_business_context.items()
                        if str(value).strip()
                    },
                    "legacy_validation_failures": list(
                        data.get("validation_failures", [])
                    ),
                }
            )
    return entries


def compare_legacy_cache(
    legacy_cache_dir: str | Path,
    runtime: KnowledgeRuntime,
    profile: IndustryProfile | None,
    *,
    cache_root: str | Path | None = None,
    profile_resolver: object | None = None,
) -> dict[str, Any]:
    entries = load_legacy_signature_entries(legacy_cache_dir)
    stats = AIUsageStats()
    rows: list[dict[str, Any]] = []
    disagreements: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    life_positive: list[dict[str, Any]] = []
    per_profile: dict[str, dict[str, int]] = {}
    for entry in entries:
        fields = entry["fields"]
        entry_profile = profile
        profile_name = ""
        if profile_resolver is not None:
            resolved_profile = profile_resolver(entry["legacy_business_context"])
            if resolved_profile is not None:
                entry_profile = resolved_profile
                profile_name = str(
                    getattr(entry_profile, "profile_name", "")
                )
        resolved = runtime.resolve_transaction_fields(
            fields,
            entry_profile,
            stats=stats,
        )
        knowledge = resolved["final_relevance"]
        legacy = entry["legacy_semantic_judgement"]
        profile_key = profile_name or "default"
        bucket = per_profile.setdefault(
            profile_key,
            {
                "total": 0,
                "agreement": 0,
                "mismatch": 0,
                "undetermined": 0,
            },
        )
        bucket["total"] += 1
        row = {
            "signature_hash": entry["signature_hash"],
            "model": entry["model"],
            "prompt_version": entry["prompt_version"],
            "legacy_semantic_judgement": legacy,
            "knowledge_relevance": knowledge,
            "profile_name": profile_key,
            "concept_id": resolved["semantic"]["concept_id"],
            "concept_source": resolved["semantic"]["source"],
            "relation_source": (
                resolved["relations"][0]["relation_source"]
                if resolved["relations"]
                else ""
            ),
            "constraint_maximum": str(
                resolved["constraints"].get("maximum_allowed_strength", "")
            ),
        }
        rows.append(row)
        if knowledge == "undetermined":
            bucket["undetermined"] += 1
        if legacy and legacy == knowledge:
            bucket["agreement"] += 1
        else:
            bucket["mismatch"] += 1
        if not legacy:
            continue
        if legacy == knowledge:
            continue
        disagreements.append(row)
        if (
            legacy in _STRENGTH_RANK
            and knowledge in _STRENGTH_RANK
            and _STRENGTH_RANK[knowledge] > _STRENGTH_RANK[legacy]
        ):
            violations.append(
                {
                    **row,
                    "violation": "strength_escalation_vs_legacy",
                }
            )
        if (
            legacy in {"none", "undetermined"}
            and knowledge in {"strong", "medium", "weak"}
            and resolved["semantic"]["concept_id"]
            in {
                "dining",
                "medical",
                "telecom",
                "bank_fee",
                "ride_hailing",
            }
        ):
            life_positive.append(
                {
                    **row,
                    "violation": "life_category_positive",
                }
            )

    legacy_counts = Counter(
        row["legacy_semantic_judgement"] for row in rows
    )
    knowledge_counts = Counter(row["knowledge_relevance"] for row in rows)
    agreement = sum(
        1
        for row in rows
        if row["legacy_semantic_judgement"]
        and row["legacy_semantic_judgement"] == row["knowledge_relevance"]
    )
    undetermined_new = sum(
        1
        for row in rows
        if row["legacy_semantic_judgement"] in _STRENGTH_RANK
        and row["knowledge_relevance"] == "undetermined"
    )
    return {
        "legacy_cache_dir": str(legacy_cache_dir),
        "legacy_prompt_version": "business-relevance-mvp-v11",
        "knowledge_version": runtime.version.to_dict(),
        "profile": profile.to_dict() if profile is not None else {},
        "total_entries": len(rows),
        "with_legacy_judgement": sum(
            1 for row in rows if row["legacy_semantic_judgement"]
        ),
        "agreement_count": agreement,
        "agreement_rate": (
            round(agreement / sum(1 for row in rows if row["legacy_semantic_judgement"]), 4)
            if sum(1 for row in rows if row["legacy_semantic_judgement"])
            else 0.0
        ),
        "disagreement_count": len(disagreements),
        "new_undetermined_count": undetermined_new,
        "strength_escalation_count": len(violations),
        "life_positive_count": len(life_positive),
        "legacy_judgement_counts": dict(sorted(legacy_counts.items())),
        "knowledge_relevance_counts": dict(sorted(knowledge_counts.items())),
        "concept_source_counts": dict(
            sorted(Counter(row["concept_source"] for row in rows).items())
        ),
        "relation_source_counts": dict(
            sorted(Counter(row["relation_source"] for row in rows).items())
        ),
        "per_profile": {
            name: dict(counts)
            for name, counts in sorted(per_profile.items())
        },
        "usage_stats": stats.to_dict(),
        "disagreements": disagreements,
        "violations": violations,
        "life_positive_samples": life_positive,
    }


def render_shadow_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# legacy_v11 vs knowledge_v1 Shadow 对比",
        "",
        f"- legacy 缓存：`{report.get('legacy_cache_dir')}`",
        f"- 对比条目：{report.get('total_entries')}",
        f"- 含 legacy 判定条目：{report.get('with_legacy_judgement')}",
        f"- 一致：{report.get('agreement_count')}（{report.get('agreement_rate')}）",
        f"- 不一致：{report.get('disagreement_count')}",
        f"- 新增 undetermined：{report.get('new_undetermined_count')}",
        f"- 相对 legacy 强度上调：{report.get('strength_escalation_count')}",
        f"- 生活类正向样本：{report.get('life_positive_count')}",
        "",
        "## legacy 判定分布",
        "",
    ]
    for key, count in sorted(report.get("legacy_judgement_counts", {}).items()):
        lines.append(f"- {key}：{count}")
    lines.extend(["", "## knowledge_v1 判定分布", ""])
    for key, count in sorted(report.get("knowledge_relevance_counts", {}).items()):
        lines.append(f"- {key}：{count}")
    lines.extend(
        [
            "",
            "## 来源分布",
            "",
            "- 概念来源：" + "、".join(
                f"{key}={count}"
                for key, count in sorted(report.get("concept_source_counts", {}).items())
            ),
            "- 关系来源：" + "、".join(
                f"{key}={count}"
                for key, count in sorted(report.get("relation_source_counts", {}).items())
            ),
            "",
            "## AI 使用统计（shadow 为 0 调用）",
            "",
        ]
    )
    usage = report.get("usage_stats", {})
    if isinstance(usage, Mapping):
        for key, value in sorted(usage.items()):
            lines.append(f"- {key}：{value}")
    lines.extend(["", "## 不一致明细（仅签名哈希与判定，不含原文）", ""])
    disagreements = report.get("disagreements", [])
    if isinstance(disagreements, list) and disagreements:
        lines.append("| 签名哈希 | legacy | knowledge | 概念 | 概念来源 | 关系来源 | 硬上限 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for row in disagreements[:200]:
            lines.append(
                "| " + " | ".join(
                    [
                        str(row.get("signature_hash", "")),
                        str(row.get("legacy_semantic_judgement", "")),
                        str(row.get("knowledge_relevance", "")),
                        str(row.get("concept_id", "")),
                        str(row.get("concept_source", "")),
                        str(row.get("relation_source", "")),
                        str(row.get("constraint_maximum", "")),
                    ]
                ) + " |"
            )
        if len(disagreements) > 200:
            lines.append(f"…（共 {len(disagreements)} 条，仅显示前 200 条）")
    else:
        lines.append("无")
    return "\n".join(lines)


def extended_shadow_metrics(
    legacy_cache_dir: str | Path,
    runtime: KnowledgeRuntime,
    profile: IndustryProfile | None,
    *,
    profile_resolver: object | None = None,
) -> dict[str, Any]:
    """Third-round metrics: fallback needs and knowledge resolution coverage."""
    entries = load_legacy_signature_entries(legacy_cache_dir)
    stats = AIUsageStats()
    unknown_concept = 0
    unknown_relation = 0
    inheritance_hits = 0
    exact_alias_hits = 0
    resolved_concept = 0
    for entry in entries:
        entry_profile = profile
        if profile_resolver is not None:
            resolved_profile = profile_resolver(entry["legacy_business_context"])
            if resolved_profile is not None:
                entry_profile = resolved_profile
        resolved = runtime.resolve_transaction_fields(
            entry["fields"],
            entry_profile,
            stats=stats,
        )
        semantic = resolved["semantic"]
        if semantic["source"] == "undetermined" or not semantic["concept_id"]:
            unknown_concept += 1
            continue
        resolved_concept += 1
        if semantic.get("matched_alias"):
            exact_alias_hits += 1
        relations = resolved["relations"]
        if not relations or all(
            str(item.get("relevance", "")) == "undetermined"
            for item in relations
        ):
            unknown_relation += 1
        inheritance_hits += sum(
            1
            for item in relations
            if item.get("relation_source") == "inherited"
        )
    return {
        "total_entries": len(entries),
        "unknown_concept_count": unknown_concept,
        "unknown_relation_count": unknown_relation,
        "resolved_concept_count": resolved_concept,
        "concept_ai_fallback_theoretical": unknown_concept,
        "relation_ai_fallback_theoretical": unknown_relation,
        "total_ai_fallback_theoretical": unknown_concept + unknown_relation,
        "parent_inheritance_hits": inheritance_hits,
        "exact_alias_hits": exact_alias_hits,
        "semantic_kb_hits": stats.semantic_kb_hits,
        "semantic_cache_hits": stats.semantic_cache_hits,
        "relation_kb_hits": stats.relation_kb_hits,
        "relation_cache_hits": stats.relation_cache_hits,
        "undetermined_total": stats.undetermined_count,
    }
