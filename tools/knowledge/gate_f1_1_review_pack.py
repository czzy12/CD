"""Gate F1.1: blinded Concept Holdout Human Review Pack."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("fitness_dir", type=Path)
    parser.add_argument("--batch-size", type=int, default=30)
    args = parser.parse_args()

    sampling = json.loads(
        (args.fitness_dir / "final_holdout_sampling_report.json").read_text(
            encoding="utf-8"
        )
    )
    membership = sampling["membership"]
    now = datetime.now(timezone.utc).isoformat()
    queue = []
    for item in membership:
        queue.append(
            {
                "holdout_id": item["holdout_id"],
                "semantic_signature": item["signature_id"],
                "source_document_refs": item["source_documents"],
                "occurrence_count": item["occurrence_count"],
                "safe_semantic_evidence": item["fields"],
                "direction": item["metadata"]["direction"],
                "amount_bucket": item["metadata"]["amount_bucket"],
                "text_length_bucket": item["metadata"]["text_length_bucket"],
                "field_types": item["metadata"]["field_types"],
                "payment_marker": item["metadata"]["payment_marker"],
                "org_marker": item["metadata"]["org_marker"],
                "declared_industry": "not_provided",
                "industry_status": "unavailable",
                "concept_decision": "",
                "concept_id": "",
                "new_concept_proposal": "",
                "review_reason": "",
                "reviewed_by": "human",
                "review_source": "interactive_human_review",
                "reviewed_at": "",
                "invalid_sample_reason": "",
                "relation_decision_required": False,
            }
        )

    (args.fitness_dir / "human_gold.json").write_text(
        json.dumps(
            {
                "gold_version": "production-concept-holdout-gold-v1",
                "status": "human_labels_pending",
                "total": len(queue),
                "reviewed": 0,
                "pending": len(queue),
                "invalid": 0,
                "decisions": [],
                "created_at": now,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.fitness_dir / "human_review_queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.fitness_dir / "human_review_sheet.md").write_text(
        _render_sheet(queue),
        encoding="utf-8",
    )

    batch = queue[: args.batch_size]
    (args.fitness_dir / "batch_h01.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.fitness_dir / "batch_h01.md").write_text(
        _render_batch(batch),
        encoding="utf-8",
    )
    (args.fitness_dir / "gate_f1_1_report.md").write_text(
        _render_report(total=len(queue), batch_size=args.batch_size),
        encoding="utf-8",
    )

    print("status=ok")
    print(f"concept_holdout_total={len(queue)}")
    print(f"reviewed=0 pending={len(queue)}")
    print(f"batch_h01={len(batch)}")
    print(f"output={args.fitness_dir}")
    return 0


def _render_batch(batch: list[dict]) -> str:
    lines = [
        "# Concept Holdout Batch H01（F1.1）",
        "",
        "- 状态：human labels pending",
        "- 仅 Concept Gold；Relation 阶段因 industry context unavailable 暂不要求。",
        "- 系统预测未显示；未运行 knowledge_v1。",
        "",
    ]
    for item in batch:
        lines.extend(
            [
                f"## {item['holdout_id']}",
                "",
                f"- semantic signature：`{item['semantic_signature']}`",
                f"- direction：{item['direction']}；amount bucket：{item['amount_bucket']}",
                f"- field types：{item['field_types']}",
                f"- payment marker：{item['payment_marker']}；org marker：{item['org_marker']}",
                "",
                "### Safe semantic evidence",
                "",
                "```json",
                json.dumps(item["safe_semantic_evidence"], ensure_ascii=False, indent=2),
                "```",
                "",
                "### Concept Decision",
                "",
                "- [ ] existing_concept（concept_id：____）",
                "- [ ] new_concept（proposed id/name：____）",
                "- [ ] insufficient",
                "- [ ] invalid_sample（reason：____）",
                "",
                "### Reason",
                "",
                "____",
                "",
            ]
        )
    return "\n".join(lines)


def _render_sheet(queue: list[dict]) -> str:
    lines = [
        "# Concept Holdout Human Review Sheet",
        "",
        f"- total={len(queue)}",
        "- reviewed_by=human only",
        "- relation_decision_required=False（industry context unavailable）",
        "",
        "| ID | signature | direction | fields |",
        "| --- | --- | --- | --- |",
    ]
    for item in queue:
        lines.append(
            "| "
            + " | ".join(
                [
                    item["holdout_id"],
                    item["semantic_signature"][:12],
                    item["direction"],
                    ",".join(item["field_types"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _render_report(total: int, batch_size: int) -> str:
    return "\n".join(
        [
            "# Gate F1.1 — Final Concept Holdout Review Pack",
            "",
            f"- total={total}；reviewed=0；pending={total}",
            f"- batch size={batch_size}；Batch H01={min(batch_size, total)}",
            "- relation_decision_required=False for all samples",
            "- knowledge_v1 run=0；AI provider call=0；system prediction exposed=0",
            "- 旧 Batch H01（12 条）已标记 superseded_before_human_labeling",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
