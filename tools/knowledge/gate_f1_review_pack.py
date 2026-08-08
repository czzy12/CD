"""Gate F1: create blinded Human Review Pack for the frozen Production Holdout."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


BATCH_SIZE = 12


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("holdout_dir", type=Path)
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    sampling = json.loads(
        (args.holdout_dir / "holdout_sampling_report.json").read_text(
            encoding="utf-8"
        )
    )
    membership = sampling["membership"]
    now = datetime.now(timezone.utc).isoformat()
    queue = []
    for index, item in enumerate(membership):
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
                "concept_decision": "",
                "concept_id": "",
                "new_concept_proposal": "",
                "relation_decision": "",
                "final_relevance": "",
                "review_reason": "",
                "reviewed_by": "human",
                "review_source": "interactive_human_review",
                "reviewed_at": "",
                "invalid_sample_reason": "",
            }
        )

    (args.holdout_dir / "holdout_review_queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.holdout_dir / "production_holdout_human_gold.json").write_text(
        json.dumps(
            {
                "holdout_version": "production-holdout-v1",
                "gold_version": "production-holdout-gold-v1",
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
    _write_evaluation_contract(args.holdout_dir)

    batch = queue[: args.batch_size]
    (args.holdout_dir / f"batch_h01.json").write_text(
        json.dumps(batch, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (args.holdout_dir / "batch_h01.md").write_text(
        _render_batch(batch),
        encoding="utf-8",
    )
    (args.holdout_dir / "holdout_review_sheet.md").write_text(
        _render_sheet(queue),
        encoding="utf-8",
    )
    (args.holdout_dir / "gate_f1_report.md").write_text(
        _render_report(
            holdout_dir=args.holdout_dir,
            total=len(queue),
            batch_size=args.batch_size,
        ),
        encoding="utf-8",
    )

    print("status=ok")
    print(f"holdout_total={len(queue)}")
    print(f"reviewed=0 pending={len(queue)}")
    print(f"batch_h01={len(batch)}")
    print(f"output={args.holdout_dir}")
    return 0


def _write_evaluation_contract(holdout_dir: Path) -> None:
    contract = {
        "evaluation_contract_version": "production-holdout-eval-v1",
        "status": "frozen_before_blind_run",
        "concept_quality": [
            "exact_concept_accuracy",
            "existing_concept_recovery",
            "new_concept_detection",
            "insufficient_precision",
            "insufficient_recall",
            "wrong_domain_rate",
        ],
        "relation_quality": [
            "exact_relevance_accuracy",
            "usable_relevance_accuracy",
            "strength_escalation",
            "strength_downgrade",
            "conditional_limitation",
        ],
        "routing": [
            "local_resolved",
            "ai_eligible",
            "ai_invoked",
            "unnecessary_ai_call",
            "missed_ai_call",
        ],
        "safety": [
            "privacy_blocked",
            "unauthorized_sensitive_outbound",
            "malformed_provider_output",
            "provider_failure",
            "fallback_unresolved_safety",
        ],
        "principles": [
            "AI call rate is not itself a promotion target; unnecessary and missed AI calls are judged separately.",
            "Promotion thresholds must be frozen before the blind run, not after results.",
            "Known model expressiveness limits are counted as system error, not removed from Holdout.",
            "No critical privacy violation, no production contract violation, no unexplained error bucket.",
        ],
        "blind_run_gate": "Gate F2 (not started)",
    }
    (holdout_dir / "holdout_evaluation_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _render_batch(batch: list[dict]) -> str:
    lines = [
        "# Holdout Batch H01",
        "",
        "- 状态：human labels pending",
        "- 禁止看到 system prediction；未运行 knowledge_v1。",
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
                f"- declared industry：`{item['declared_industry']}`（pristine pool 无外部行业上下文）",
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
                "### Relation Decision（如 Concept 足够确定且有行业上下文）",
                "",
                "- [ ] strong / medium / weak / none / undetermined",
                "- [ ] conditional_relation_gold（附加条件：____）",
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
        "# Production Holdout Human Review Sheet",
        "",
        f"- total={len(queue)}",
        "- reviewed_by=human only",
        "- system predictions are intentionally absent",
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


def _render_report(holdout_dir: Path, total: int, batch_size: int) -> str:
    manifest = json.loads(
        (holdout_dir / "production_holdout_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    contamination = json.loads(
        (holdout_dir / "holdout_contamination_audit.json").read_text(
            encoding="utf-8"
        )
    )
    return "\n".join(
        [
            "# Gate F1 — Production Holdout Construction + Human Review Preparation",
            "",
            f"- holdout version：`{manifest['holdout_version']}`",
            f"- membership count：{total}",
            f"- source document count：{manifest['source_document_count']}",
            f"- document max contribution：{manifest['document_max_contribution']}",
            f"- independence level：{manifest['independence_level']}",
            f"- independence note：{manifest['independence_note']}",
            "",
            "## Contamination Audit",
            "",
            f"`{json.dumps(contamination, ensure_ascii=False, indent=2)}`",
            "",
            "## Blindness Audit",
            "",
            "- knowledge_v1 resolver run：0",
            "- AI provider call：0",
            "- system prediction exposed to Human：0",
            "- legacy prediction exposed：0",
            "",
            "## Human Review Status",
            "",
            f"- total={total}；reviewed=0；pending={total}",
            f"- Batch H01（{batch_size} 条）已生成，等待 Human Gold。",
            "",
            "## Known Holdout Limitation",
            "",
            "- pristine pool 无外部 declared industry 元数据；relation Gold 在缺少行业上下文时",
            "  只能标 undetermined / none 或依据 Human 从安全证据判断；概念 Gold 不受影响。",
            "- independence = Level 2（document-level exclusion for known development/regression "
            "documents + exact signature exclusion），不是 Level 1 强客户隔离。",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
