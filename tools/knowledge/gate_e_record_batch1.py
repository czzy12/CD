"""Gate E: persist Batch 1 human decisions and classify promotion paths."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import KnowledgeRuntime, versioning
from bankflow_v2.knowledge.gate_e import (
    LEGACY_RELATION_SET_VERSION,
    classify_legacy_relation_promotion,
    validate_legacy_relation_decision,
)


REVIEWED_AT = "2026-08-08T04:00:00+00:00"
BATCH1 = [
    {
        "review_id": "R-Legacy-01",
        "candidate_id": "29a80400af1b4f8d8264194537cca800",
        "industry_id": "internal.building_material_trade",
        "concept_id": "service",
        "original_relevance": "none",
        "review_decision": "modify",
        "final_relevance": "weak",
        "review_reason": (
            "公司网银服务年费属于企业账户运营/金融服务痕迹，能弱度支持经营活动存在，"
            "但不能证明建材贸易主营业务，因此不应为 none，也不能高于 weak。"
        ),
    },
    {
        "review_id": "R-Legacy-02",
        "candidate_id": "0addbdca7681413eaa43c3d86c2d51ff",
        "industry_id": "internal.environmental_engineering",
        "concept_id": "service",
        "original_relevance": "none",
        "review_decision": "modify",
        "final_relevance": "weak",
        "review_reason": (
            "公司网银服务年费可弱度体现企业经营账户活动，但与环保工程具体业务没有"
            "直接对应关系，适合 weak。"
        ),
    },
    {
        "review_id": "R-Legacy-03",
        "candidate_id": "c83c998227064334866f526cbc1da0cd",
        "industry_id": "internal.building_material_trade",
        "concept_id": "settlement",
        "original_relevance": "strong",
        "review_decision": "modify",
        "final_relevance": "weak",
        "review_reason": (
            "单位结算卡年费能证明企业结算账户/经营性金融工具存在，但年费本身不是建材交易"
            "或主营经营收入支出，strong 明显过高，定为 weak。"
        ),
    },
    {
        "review_id": "R-Legacy-04",
        "candidate_id": "dea1133ff43a4a419ff138739bf00f4b",
        "industry_id": "internal.environmental_engineering",
        "concept_id": "settlement",
        "original_relevance": "strong",
        "review_decision": "modify",
        "final_relevance": "weak",
        "review_reason": (
            "单位结算卡年费属于企业结算基础设施痕迹，可弱度支持企业经营存在，但不能直接"
            "证明环保工程业务，定为 weak。"
        ),
    },
    {
        "review_id": "R-Legacy-05",
        "candidate_id": "1206eca88f5a44be86e6085246acf3ad",
        "industry_id": "internal.building_material_trade",
        "concept_id": "service",
        "original_relevance": "none",
        "review_decision": "approve",
        "final_relevance": "none",
        "review_reason": (
            "仅有“河南耕道教育服务有限公司”这一交易对手信息，没有证据表明与建材贸易"
            "经营活动相关；教育服务与目标行业不存在稳定可复用关系。"
        ),
    },
    {
        "review_id": "R-Legacy-06",
        "candidate_id": "72cd8d21d9a8440cad7113dc6534cd53",
        "industry_id": "internal.environmental_engineering",
        "concept_id": "service",
        "original_relevance": "none",
        "review_decision": "approve",
        "final_relevance": "none",
        "review_reason": (
            "仅有教育服务公司名称，无法建立与环保工程行业的稳定经营关系，none 合理。"
        ),
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    args = parser.parse_args()

    queue_path = args.output_dir / "legacy_relation_review_queue.json"
    decisions_path = args.output_dir / "legacy_relation_review_decisions.json"
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    decisions_data = json.loads(decisions_path.read_text(encoding="utf-8"))
    queue_by_id = {str(item["candidate_id"]): item for item in queue}

    runtime = KnowledgeRuntime.load(args.canonical_dir)
    records: list[dict] = []
    promotion_items: list[dict] = []
    for human in BATCH1:
        candidate_id = human["candidate_id"]
        queue_item = queue_by_id[candidate_id]
        original_snapshot = {
            "candidate_id": candidate_id,
            "industry_id": queue_item["industry_id"],
            "concept_id": queue_item["concept_id"],
            "proposed_relevance": queue_item["proposed_relevance"],
            "signature_hash": queue_item["signature_hash"],
            "supporting_semantic_evidence": queue_item[
                "supporting_semantic_evidence"
            ],
        }
        record = {
            "review_id": human["review_id"],
            "candidate_id": candidate_id,
            "review_set_version": LEGACY_RELATION_SET_VERSION,
            "industry_id": human["industry_id"],
            "concept_id": human["concept_id"],
            "original_relevance": human["original_relevance"],
            "review_decision": human["review_decision"],
            "final_relevance": human["final_relevance"],
            "reviewed_by": "human",
            "review_source": "interactive_human_review",
            "review_reason": human["review_reason"],
            "reviewed_at": REVIEWED_AT,
            "promotion_status": "not_promoted",
            "source_provenance": "legacy_v11 acceptance migration",
            "original_candidate": original_snapshot,
            "final_value": {
                "final_relevance": human["final_relevance"],
            },
        }
        if human["review_decision"] != "approve":
            record["error_category"] = (
                "strength_too_high"
                if human["final_relevance"] == "weak"
                and human["original_relevance"] == "strong"
                else "strength_too_low"
            )
        candidate_for_validation = {
            "candidate_id": candidate_id,
            "proposed_relevance": queue_item["proposed_relevance"],
            "industry_id": queue_item["industry_id"],
            "concept_id": queue_item["concept_id"],
        }
        violations = validate_legacy_relation_decision(
            record,
            candidate=candidate_for_validation,
        )
        if violations:
            raise SystemExit(
                f"invalid decision for {candidate_id}: {violations}"
            )

        concept_id = queue_item["concept_id"]
        industry_id = queue_item["industry_id"]
        current_local = runtime.relation_resolver.resolve(
            industry_id=industry_id,
            concept_id=concept_id,
            profile=None,
        ).relevance
        existing_exact = runtime.relations.approved(industry_id, concept_id)
        generic = runtime.relations.approved("generic_business", concept_id)
        classification = classify_legacy_relation_promotion(
            review_decision=human["review_decision"],
            final_relevance=human["final_relevance"],
            current_local_relevance=current_local,
            existing_exact_relevance=(
                existing_exact.relevance if existing_exact is not None else None
            ),
            generic_business_relevance=(
                generic.relevance if generic is not None else None
            ),
        )
        promotion_items.append(
            {
                "review_id": human["review_id"],
                "candidate_id": candidate_id,
                "industry_id": industry_id,
                "concept_id": concept_id,
                "human_decision": human["review_decision"],
                "final_relevance": human["final_relevance"],
                "current_local_relevance": current_local,
                "existing_exact_relevance": (
                    existing_exact.relevance if existing_exact is not None else None
                ),
                "generic_business_relevance": (
                    generic.relevance if generic is not None else None
                ),
                **classification,
            }
        )
        records.append(record)
        queue_item["review_decision"] = human["review_decision"]
        queue_item["final_relevance"] = human["final_relevance"]
        queue_item["reviewed_at"] = REVIEWED_AT
        queue_item["promotion_classification"] = classification["classification"]
        queue_item["promotion_blocker"] = classification["blocker"]

    decisions_data["status"] = "batch1_reviewed_batch2_pending"
    decisions_data["decisions"] = records
    decisions_path.write_text(
        json.dumps(decisions_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    queue_path.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary_counts = {
        "batch1_reviewed": 6,
        "modify": 4,
        "approve": 2,
        "reject": 0,
        "insufficient": 0,
        "pending": 6,
    }
    plan = {
        "status": "batch1_planned_batch2_awaiting",
        "total": 12,
        "batch1": promotion_items,
        "batch2": [
            {
                "review_id": item["review_id"],
                "candidate_id": item["candidate_id"],
                "promotion_eligible": False,
                "blockers": ["awaiting_human_decision"],
            }
            for item in queue
            if item["review_id"] in {f"R-Legacy-{i:02d}" for i in range(7, 13)}
        ],
    }
    (args.output_dir / "legacy_relation_promotion_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    from collections import Counter

    classification_counts = Counter(
        item["classification"] for item in promotion_items
    )
    result = {
        "status": "batch1_promotion_classified",
        "promoted": 0,
        "reused_existing": classification_counts.get(
            "resolved_by_existing_canonical",
            0,
        ),
        "not_required": classification_counts.get("promotion_not_required", 0),
        "blocked": classification_counts.get("blocked_contract", 0),
        "blocked_conditional": 0,
        "blocked_conflict": classification_counts.get("blocked_conflict", 0),
        "new_snapshots": 0,
        "duplicates_prevented": 0,
        "local_resolution_verified": classification_counts.get(
            "resolved_by_existing_canonical",
            0,
        ),
        "items": promotion_items,
    }
    (args.output_dir / "legacy_relation_promotion_result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    (args.output_dir / "relation_version_delta.json").write_text(
        json.dumps(
            {
                "promotion_performed": False,
                "schema_version": "1.17 (unchanged)",
                "knowledge_before": versioning.KNOWLEDGE_VERSION,
                "knowledge_after": versioning.KNOWLEDGE_VERSION,
                "relation_kb_before": versioning.RELATION_KB_VERSION,
                "relation_kb_after": versioning.RELATION_KB_VERSION,
                "resolver_before": versioning.RESOLVER_VERSION,
                "resolver_after": versioning.RESOLVER_VERSION,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate": "E",
        "status": "batch1_reviewed_batch2_pending",
        "batch1": summary_counts,
        "batch1_final_relevance": {
            "weak": 4,
            "none": 2,
        },
        "batch1_promotion": result,
        "remaining_legacy_pending": 6,
        "real_ai_review_set_excluded": True,
        "d3_calibration_pending_excluded": True,
        "d3_1_calibration_pending_excluded": True,
        "human_review_incomplete": True,
        "push_performed": False,
    }
    (args.output_dir / "gate_e_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    batch1_result = {
        "reviewed": 6,
        "modify": 4,
        "approve": 2,
        "reject": 0,
        "insufficient": 0,
        "records": records,
        "promotion": promotion_items,
    }
    (args.output_dir / "batch_r_legacy_01_result.json").write_text(
        json.dumps(batch1_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    batch2 = [item for item in queue if item["review_id"] in {
        f"R-Legacy-{i:02d}" for i in range(7, 13)
    }]
    _write_batch2(args.output_dir, batch2, runtime)
    (args.output_dir / "gate_e_report.md").write_text(
        _render_report(summary, batch2),
        encoding="utf-8",
    )

    print("status=ok")
    print("batch1_reviewed=6")
    print("modify=4 approve=2 reject=0 insufficient=0")
    print("promotion=" + json.dumps(dict(classification_counts), ensure_ascii=False))
    print(f"remaining_legacy_pending={len(batch2)}")
    print(f"output={args.output_dir}")
    return 0


def _write_batch2(output_dir: Path, batch2: list[dict], runtime: KnowledgeRuntime) -> None:
    enriched = []
    for item in batch2:
        evidence = item["supporting_semantic_evidence"]
        name_only = set(evidence).issubset({"counterparty_name", "merchant_name"})
        has_purpose = bool(
            set(evidence).intersection(
                {"summary", "remark", "purpose", "product_description", "merchant_category"}
            )
        )
        generic_relation = runtime.relations.approved(
            "generic_business",
            item["concept_id"],
        )
        enriched.append(
            {
                **item,
                "service_canonical_definition": (
                    runtime.concepts.concept("service").description
                    if runtime.concepts.concept("service")
                    else ""
                ),
                "why_local_weak": (
                    "generic_business × service = weak 是现有 cross-industry baseline；"
                    "在无 exact industry relation 时 resolver 默认落到 generic weak"
                ),
                "why_proposed_none": (
                    "legacy_v11 对该交易判定为与申报行业无关（none）"
                ),
                "safe_transaction_context": evidence,
                "only_counterparty_name": name_only,
                "can_judge_consumption_payment_nature": has_purpose,
                "business_account_context": False,
                "oppo_semantics_note": (
                    "OPPO 客服/服务中心属于设备售后/客服场景，不能仅凭实体名判断"
                    "与建材/环保存在主营 Relation"
                    if "OPPO" in " ".join(str(v) for v in evidence.values())
                    else ""
                ),
                "auto_sales_note": (
                    "汽车销售服务公司属于交易对手行业，不等于客户目标行业存在"
                    "稳定业务 Relation"
                    if "汽车" in " ".join(str(v) for v in evidence.values())
                    else ""
                ),
                "relation_constraint": item["classification_constraints"],
                "similar_approved_relations": (
                    [
                        {
                            "industry_id": "generic_business",
                            "concept_id": item["concept_id"],
                            "relevance": generic_relation.relevance,
                        }
                    ]
                    if generic_relation is not None
                    else []
                ),
                "entity_name_overreach_risk": name_only,
            }
        )
    (output_dir / "batch_r_legacy_02.json").write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "batch_r_legacy_02.md").write_text(
        _render_batch2(enriched),
        encoding="utf-8",
    )


def _render_batch2(items: list[dict]) -> str:
    lines = [
        "# Batch R-Legacy-02（R-Legacy-07 ～ R-Legacy-12）",
        "",
        "- 状态：human decisions pending",
        "- 不要替 Human 裁决；不要按 Batch 1 weak 逻辑自动复制。",
        "",
    ]
    for item in items:
        lines.extend(
            [
                f"## {item['review_id']} — {item['candidate_id'][:12]}",
                "",
                f"- Candidate：`{item['candidate_id']}`",
                f"- Industry：`{item['industry_id']}` {item['industry_name']}",
                f"- Concept：`{item['concept_id']}` {item['concept_name']}",
                f"- Concept definition：{item['concept_description']}",
                f"- service canonical definition：{item['service_canonical_definition']}",
                f"- Proposed relevance：`{item['proposed_relevance']}`",
                f"- Current local：`{item['current_local_resolution']}`",
                f"- Existing KB：`{item['existing_canonical_relation']}`",
                f"- Max / direct：`{item['maximum_allowed_strength']}` / "
                f"`{item['directly_related_allowed']}`",
                "",
                "### Safe transaction context",
                "",
                "```json",
                json.dumps(item["safe_transaction_context"], ensure_ascii=False, indent=2),
                "```",
                "",
                f"- only counterparty name：{item['only_counterparty_name']}",
                f"- can judge consumption/payment nature："
                f"{item['can_judge_consumption_payment_nature']}",
                f"- business account context：{item['business_account_context']}",
                f"- OPPO note：{item['oppo_semantics_note'] or 'N/A'}",
                f"- auto sales note：{item['auto_sales_note'] or 'N/A'}",
                f"- entity-name overreach risk：{item['entity_name_overreach_risk']}",
                "",
                "### Why current local = weak",
                "",
                item["why_local_weak"],
                "",
                "### Why candidate proposed = none",
                "",
                item["why_proposed_none"],
                "",
                "### Similar approved relations",
                "",
                f"`{json.dumps(item['similar_approved_relations'], ensure_ascii=False)}`",
                "",
                "### Decision options",
                "",
                "- [ ] approve（final relevance = none）",
                "- [ ] modify（final relevance：____；reason：____）",
                "- [ ] reject（error category：____）",
                "- [ ] insufficient（error category：____）",
                "",
            ]
        )
    return "\n".join(lines)


def _render_report(summary: dict, batch2: list[dict]) -> str:
    return "\n".join(
        [
            "# Gate E — Batch 1 Recorded / Batch 2 Pending",
            "",
            f"- 状态：{summary['status']}",
            f"- Batch 1 reviewed：{summary['batch1']}",
            f"- Batch 1 final relevance：{summary['batch1_final_relevance']}",
            f"- Batch 1 promotion："
            f"{json.dumps(summary['batch1_promotion'], ensure_ascii=False)}",
            f"- Remaining legacy pending：{summary['remaining_legacy_pending']}",
            "",
            "## Batch 2",
            "",
            "| ID | industry | concept | proposed | local | max/direct |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        + [
            "| "
            + " | ".join(
                [
                    item["review_id"],
                    item["industry_id"],
                    item["concept_id"],
                    item["proposed_relevance"],
                    item["current_local_resolution"],
                    f"{item['maximum_allowed_strength']}/{item['directly_related_allowed']}",
                ]
            )
            + " |"
            for item in batch2
        ]
        + [
            "",
            "human decisions pending",
            "",
            "未 push。",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
