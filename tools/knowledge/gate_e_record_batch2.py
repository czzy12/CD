"""Gate E: persist Batch 2 human decisions (all approve) and finalize review state."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
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


REVIEWED_AT = "2026-08-08T05:00:00+00:00"
BATCH2_CANDIDATES = [
    ("R-Legacy-07", "45d6bb2089e74835948dcc45a2fe943f", "internal.building_material_trade"),
    ("R-Legacy-08", "c0fa00391f324634acb092a54d50eff1", "internal.environmental_engineering"),
    ("R-Legacy-09", "1439a7b594f2447786aa08fec13bfde1", "internal.building_material_trade"),
    ("R-Legacy-10", "842dbe3414b346b889521ebd9d7ed978", "internal.environmental_engineering"),
    ("R-Legacy-11", "be5a0dda0c1744668144dc39185969a6", "internal.building_material_trade"),
    ("R-Legacy-12", "d3632fcbc95342398877cdbf69a44fd6", "internal.environmental_engineering"),
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
    existing_records = list(decisions_data.get("decisions", []))
    existing_ids = {str(record["candidate_id"]) for record in existing_records}

    runtime = KnowledgeRuntime.load(args.canonical_dir)
    records = list(existing_records)
    promotion_items = list(
        json.loads(
            (args.output_dir / "legacy_relation_promotion_result.json").read_text(
                encoding="utf-8"
            )
        ).get("items", [])
    )

    for review_id, candidate_id, industry_id in BATCH2_CANDIDATES:
        if candidate_id in existing_ids:
            continue
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
            "review_id": review_id,
            "candidate_id": candidate_id,
            "review_set_version": LEGACY_RELATION_SET_VERSION,
            "industry_id": industry_id,
            "concept_id": queue_item["concept_id"],
            "original_relevance": queue_item["proposed_relevance"],
            "review_decision": "approve",
            "final_relevance": queue_item["proposed_relevance"],
            "reviewed_by": "human",
            "review_source": "interactive_human_review",
            "review_reason": (
                "Human confirmed candidate as approve; final relevance remains "
                "the proposed relevance (none)."
            ),
            "reviewed_at": REVIEWED_AT,
            "promotion_status": "not_promoted",
            "source_provenance": "legacy_v11 acceptance migration",
            "original_candidate": original_snapshot,
            "final_value": {
                "final_relevance": queue_item["proposed_relevance"],
            },
        }
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
            raise SystemExit(f"invalid decision for {candidate_id}: {violations}")

        concept_id = queue_item["concept_id"]
        current_local = runtime.relation_resolver.resolve(
            industry_id=queue_item["industry_id"],
            concept_id=concept_id,
            profile=None,
        ).relevance
        existing_exact = runtime.relations.approved(
            queue_item["industry_id"],
            concept_id,
        )
        generic = runtime.relations.approved("generic_business", concept_id)
        classification = classify_legacy_relation_promotion(
            review_decision="approve",
            final_relevance=queue_item["proposed_relevance"],
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
                "review_id": review_id,
                "candidate_id": candidate_id,
                "industry_id": queue_item["industry_id"],
                "concept_id": concept_id,
                "human_decision": "approve",
                "final_relevance": queue_item["proposed_relevance"],
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
        queue_item["review_decision"] = "approve"
        queue_item["final_relevance"] = queue_item["proposed_relevance"]
        queue_item["reviewed_at"] = REVIEWED_AT
        queue_item["promotion_classification"] = classification["classification"]
        queue_item["promotion_blocker"] = classification["blocker"]

    decisions_data["status"] = "all_reviewed"
    decisions_data["decisions"] = records
    decisions_path.write_text(
        json.dumps(decisions_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    queue_path.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    classification_counts = Counter(
        item["classification"] for item in promotion_items
    )
    result = {
        "status": "all_promotion_classified",
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
    (args.output_dir / "legacy_relation_promotion_plan.json").write_text(
        json.dumps(
            {
                "status": "all_planned",
                "total": 12,
                "batch1": [
                    item
                    for item in promotion_items
                    if item["review_id"] in {f"R-Legacy-{i:02d}" for i in range(1, 7)}
                ],
                "batch2": [
                    item
                    for item in promotion_items
                    if item["review_id"] in {f"R-Legacy-{i:02d}" for i in range(7, 13)}
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
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
        "status": "all_human_reviewed_promotion_blocked_by_contract",
        "batch1": {"reviewed": 6, "modify": 4, "approve": 2, "reject": 0, "insufficient": 0},
        "batch2": {"reviewed": 6, "modify": 0, "approve": 6, "reject": 0, "insufficient": 0},
        "total_reviewed": 12,
        "final_relevance": {"weak": 4, "none": 8},
        "promotion": result,
        "remaining_legacy_pending": 0,
        "real_ai_review_set_excluded": True,
        "d3_calibration_pending_excluded": True,
        "d3_1_calibration_pending_excluded": True,
        "human_review_incomplete": False,
        "conclusion": "PASS WITH FOLLOW-UP",
        "push_performed": False,
    }
    (args.output_dir / "gate_e_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "gate_e_report.md").write_text(
        _render_report(summary),
        encoding="utf-8",
    )
    batch2_ids = {candidate_id for _, candidate_id, _ in BATCH2_CANDIDATES}
    (args.output_dir / "batch_r_legacy_02_result.json").write_text(
        json.dumps(
            {
                "reviewed": 6,
                "approve": 6,
                "modify": 0,
                "reject": 0,
                "insufficient": 0,
                "final_relevance": "none (all six)",
                "records": [
                    record
                    for record in records
                    if record["candidate_id"] in batch2_ids
                ],
                "promotion": [
                    item
                    for item in promotion_items
                    if item["candidate_id"] in batch2_ids
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("status=ok")
    print("total_reviewed=12")
    print("batch2_approve=6 modify=0 reject=0 insufficient=0")
    print("promotion=" + json.dumps(dict(classification_counts), ensure_ascii=False))
    print("remaining_legacy_pending=0")
    print(f"output={args.output_dir}")
    return 0


def _render_report(summary: dict) -> str:
    return "\n".join(
        [
            "# Gate E — All Human Decisions Recorded",
            "",
            f"- 状态：{summary['status']}",
            f"- Batch 1：{summary['batch1']}",
            f"- Batch 2：{summary['batch2']}",
            f"- total reviewed：{summary['total_reviewed']}",
            f"- final relevance：{summary['final_relevance']}",
            f"- promotion：{json.dumps(summary['promotion'], ensure_ascii=False)}",
            f"- remaining legacy pending：{summary['remaining_legacy_pending']}",
            f"- conclusion：{summary['conclusion']}",
            "",
            "## 说明",
            "",
            "- 12 条 Human decisions 全部落盘，reviewed_by=human。",
            "- R01～R04 weak 由 generic_business weak 现有 canonical 覆盖；",
            "- R05～R12 none 因 relation model 无法表达 evidence-specific none 而 blocked_contract；",
            "- 未改变 canonical KB；未新增 snapshot；未 bump version；",
            "- 未开始 Production Holdout / Production Promotion；未 push。",
            "",
            "human decisions pending：False",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
