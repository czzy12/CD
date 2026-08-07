"""Batch-review pending knowledge candidates against the current canonical KB.

Decisions:
- new_semantic_concept now resolvable by KB -> reject (obsolete)
- new_semantic_concept still unresolvable -> reject (customer-specific / noise)
- new_industry_relation still uncovered -> approve (promote to canonical)
- new_industry_relation covered identically -> reject (obsolete)
- new_industry_relation covered differently -> keep pending and flag conflict
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge import (
    KnowledgeReviewService,
    KnowledgeRuntime,
    RuntimeKnowledgeRepository,
    load_legacy_signature_entries,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-dir", type=Path, default=Path("bankflow_v2/knowledge/canonical"))
    parser.add_argument("--cache-root", type=Path, default=Path("outputs/knowledge-v1-cache"))
    parser.add_argument("--legacy-cache-dir", type=Path, required=True)
    parser.add_argument("--review-json", type=Path)
    parser.add_argument("--review-md", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    runtime = KnowledgeRuntime.load(args.canonical_dir)
    repository = RuntimeKnowledgeRepository(args.cache_root)
    review = KnowledgeReviewService(repository, args.canonical_dir)
    entries_by_hash = {
        entry["signature_hash"]: entry
        for entry in load_legacy_signature_entries(args.legacy_cache_dir)
    }
    pending = review.list_pending()
    rows: list[dict[str, object]] = []
    conflicts: list[dict[str, object]] = []
    for candidate in pending:
        signature_hash = str(
            candidate.input_signature.get("signature_hash", "")
        )
        entry = entries_by_hash.get(signature_hash)
        fields = dict(entry["fields"]) if entry is not None else {}
        row: dict[str, object] = {
            "candidate_id": candidate.candidate_id,
            "candidate_type": candidate.candidate_type,
            "signature_hash": signature_hash,
            "legacy_semantic_judgement": (
                entry["legacy_semantic_judgement"]
                if entry is not None
                else ""
            ),
            "proposed_value": candidate.proposed_value,
            "fields": fields,
            "decision": "",
            "action": "",
            "reason": "",
        }
        if candidate.candidate_type == "new_semantic_concept":
            resolved = runtime.semantic_resolver.resolve(fields)
            if resolved.source != "undetermined":
                row["decision"] = "covered_by_kb"
                row["action"] = "reject"
                row["reason"] = (
                    f"知识库已覆盖为概念 {resolved.concept_id}，候选作废"
                )
            else:
                row["decision"] = "non_generalizable"
                row["action"] = "reject"
                row["reason"] = (
                    "无法泛化为通用经营概念（客户专属店名/品牌/交易类噪声），"
                    "不进入正式知识库"
                )
        elif candidate.candidate_type == "new_industry_relation":
            industry_id = str(candidate.proposed_value.get("industry_id", ""))
            concept_id = str(candidate.proposed_value.get("concept_id", ""))
            proposed_relevance = str(
                candidate.proposed_value.get("relevance", "")
            )
            resolution = runtime.relation_resolver.resolve(
                industry_id=industry_id,
                concept_id=concept_id,
                profile=None,
            )
            if resolution.relevance == "undetermined":
                row["decision"] = "approve_relation"
                row["action"] = "approve"
                row["reason"] = (
                    f"行业×概念关系 {industry_id}×{concept_id} 仍未被覆盖，"
                    f"按 legacy 判定 {proposed_relevance} 验收"
                )
            elif resolution.relevance == proposed_relevance:
                row["decision"] = "covered_by_kb"
                row["action"] = "reject"
                row["reason"] = "当前知识库已覆盖且判定一致，候选作废"
            else:
                row["decision"] = "conflict"
                row["action"] = "keep_pending"
                row["reason"] = (
                    f"知识库现有 {resolution.relevance} 与 legacy 判定 "
                    f"{proposed_relevance} 冲突，保留待人工裁决"
                )
                conflicts.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "industry_id": industry_id,
                        "concept_id": concept_id,
                        "proposed_relevance": proposed_relevance,
                        "current_relevance": resolution.relevance,
                    }
                )
        else:
            row["decision"] = "unknown_type"
            row["action"] = "keep_pending"
            row["reason"] = "未知候选类型，保留待人工处理"
        rows.append(row)

    summary: dict[str, object] = {
        "total_pending": len(rows),
        "by_decision": {},
        "by_action": {},
    }
    for row in rows:
        decision = str(row["decision"])
        action = str(row["action"])
        summary["by_decision"] = {
            **summary["by_decision"],
            decision: int(summary["by_decision"].get(decision, 0)) + 1,
        }
        summary["by_action"] = {
            **summary["by_action"],
            action: int(summary["by_action"].get(action, 0)) + 1,
        }

    if args.apply:
        for row in rows:
            candidate_id = str(row["candidate_id"])
            if row["action"] == "approve":
                review.approve(candidate_id)
            elif row["action"] == "reject":
                review.reject(candidate_id)

    output = {
        "apply": args.apply,
        "summary": summary,
        "conflicts": conflicts,
        "rows": rows,
    }
    if args.review_json:
        args.review_json.parent.mkdir(parents=True, exist_ok=True)
        args.review_json.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.review_md:
        args.review_md.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# knowledge_v1 候选批量验收记录",
            "",
            f"- 复核时间：2026-08-07",
            f"- 应用结果：{'是' if args.apply else '否（仅预览）'}",
            f"- 待复核候选：{summary['total_pending']}",
        ]
        for decision, count in sorted(
            summary["by_decision"].items()
        ):
            lines.append(f"- {decision}：{count}")
        lines.extend(
            [
                "",
                "## 冲突保留项",
                "",
            ]
        )
        if conflicts:
            for conflict in conflicts:
                lines.append(
                    f"- {conflict['industry_id']}×{conflict['concept_id']}："
                    f"知识库 {conflict['current_relevance']} vs "
                    f"legacy {conflict['proposed_relevance']}"
                )
        else:
            lines.append("无")
        lines.extend(
            [
                "",
                "## 说明",
                "",
                "- 概念候选若已被扩充后的知识库覆盖则作废；",
                "- 剩余无法泛化的候选按“客户专属店名/品牌/交易类噪声”拒绝，不进入正式知识库；",
                "- 关系候选按 legacy 验收判定 approve（仍未被覆盖时），冲突项保留 pending。",
            ]
        )
        args.review_md.parent.mkdir(parents=True, exist_ok=True)
        args.review_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("status=ok")
    print(f"total_pending={summary['total_pending']}")
    for decision, count in sorted(summary["by_decision"].items()):
        print(f"decision_{decision}={count}")
    print(f"conflicts={len(conflicts)}")
    print(f"apply={str(args.apply).lower()}")
    repository.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
