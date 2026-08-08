"""Gate E: prepare isolated human review materials for 12 legacy relations."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.ai_business_observation import build_classification_constraints
from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    RuntimeKnowledgeRepository,
    load_legacy_signature_entries,
    versioning,
)
from bankflow_v2.knowledge.ai_validation import safe_validation_fields
from bankflow_v2.knowledge.gate_e import (
    LEGACY_RELATION_SET_VERSION,
    build_legacy_relation_manifest,
    select_legacy_relation_pending,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path("D:/Investigator PDF/outputs/knowledge-v1-cache"),
    )
    parser.add_argument(
        "--legacy-cache-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/shadow-20260807/"
            "legacy-cache-326"
        ),
    )
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    args = parser.parse_args()

    runtime = KnowledgeRuntime.load(args.canonical_dir)
    repository = RuntimeKnowledgeRepository(args.cache_root)
    candidates = repository.list_candidates("pending")
    legacy = select_legacy_relation_pending(candidates)
    entries_by_hash = {
        str(entry["signature_hash"]): entry
        for entry in load_legacy_signature_entries(args.legacy_cache_dir)
    }

    queue: list[dict] = []
    for candidate in legacy:
        proposed = dict(candidate.proposed_value)
        industry_id = str(proposed.get("industry_id", ""))
        concept_id = str(proposed.get("concept_id", ""))
        proposed_relevance = str(proposed.get("relevance", ""))
        signature_hash = str(
            candidate.input_signature.get("signature_hash", "")
        )
        entry = entries_by_hash.get(signature_hash, {})
        fields = dict(entry.get("fields", {}))
        safe = safe_validation_fields(fields)
        constraints = build_classification_constraints(dict(safe) or fields)
        concept = runtime.concepts.concept(concept_id)
        industry = runtime.taxonomy.node(industry_id)
        existing = runtime.relations.approved(industry_id, concept_id)
        resolved = runtime.relation_resolver.resolve(
            industry_id=industry_id,
            concept_id=concept_id,
            profile=None,
        )
        if existing is None:
            conflict_status = "uncovered"
        elif existing.relevance != proposed_relevance:
            conflict_status = "existing_conflict"
        else:
            conflict_status = "existing_same"
        queue.append(
            {
                "review_id": f"R-Legacy-{len(queue) + 1:02d}",
                "candidate_id": candidate.candidate_id,
                "relation_candidate_id": candidate.candidate_id,
                "concept_id": concept_id,
                "concept_name": concept.name_zh if concept else "",
                "concept_description": concept.description if concept else "",
                "industry_id": industry_id,
                "industry_name": industry.name if industry else "",
                "proposed_relevance": proposed_relevance,
                "proposed_source": "legacy_v11 acceptance migration",
                "knowledge_version_when_generated": (
                    "business-semantic-kb-v1 (migration-time inference)"
                ),
                "review_status": candidate.review_status,
                "creation_stage": "legacy-relation-pending-v1",
                "signature_hash": signature_hash,
                "supporting_semantic_evidence": safe or fields,
                "legacy_semantic_judgement": entry.get(
                    "legacy_semantic_judgement",
                    "",
                ),
                "legacy_rationale": entry.get("legacy_reason", ""),
                "legacy_used_fields": list(entry.get("legacy_used_fields", [])),
                "classification_constraints": constraints,
                "maximum_allowed_strength": constraints.get(
                    "maximum_allowed_strength",
                    "strong",
                ),
                "directly_related_allowed": constraints.get(
                    "directly_related_allowed",
                    False,
                ),
                "inherited": False,
                "inherited_from_industry_id": "",
                "existing_canonical_relation": (
                    {
                        "industry_id": existing.industry_id,
                        "concept_id": existing.concept_id,
                        "relevance": existing.relevance,
                        "review_status": existing.review_status,
                    }
                    if existing is not None
                    else None
                ),
                "current_local_resolution": resolved.relevance,
                "conflict_status": conflict_status,
                "conditional_relation_not_expressible": False,
                "review_options": [
                    "approve",
                    "modify",
                    "reject",
                    "insufficient",
                ],
                "review_decision": "",
                "reviewed_by": "human",
                "promotion_status": "not_promoted",
            }
        )

    manifest = build_legacy_relation_manifest(legacy)
    now = datetime.now(timezone.utc).isoformat()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    def write(name: str, value: object) -> None:
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write("legacy_relation_pending_manifest.json", manifest)
    write("legacy_relation_review_queue.json", queue)
    write(
        "legacy_relation_review_decisions.json",
        {
            "review_set_version": LEGACY_RELATION_SET_VERSION,
            "reviewed_by": "human",
            "status": "awaiting_human_labels",
            "decisions": [],
        },
    )
    write(
        "legacy_relation_promotion_plan.json",
        {
            "status": "awaiting_human_decisions",
            "total": len(queue),
            "items": [
                {
                    "candidate_id": item["candidate_id"],
                    "promotion_eligible": False,
                    "blockers": ["awaiting_human_decision"],
                }
                for item in queue
            ],
        },
    )
    write(
        "legacy_relation_promotion_result.json",
        {
            "status": "not_started",
            "promoted": 0,
            "blocked": len(queue),
            "duplicates_prevented": 0,
            "conflicts": 0,
            "local_resolution_verified": 0,
        },
    )
    write(
        "relation_version_delta.json",
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
    )
    summary = {
        "generated_at": now,
        "gate": "E",
        "status": "human_decisions_pending",
        "expected_legacy_relation_pending": 12,
        "actual_legacy_relation_pending": len(queue),
        "unique_signatures": manifest["unique_signatures"],
        "review_set_version": manifest["review_set_version"],
        "manifest_identity": manifest["identity"],
        "real_ai_review_set_excluded": True,
        "d3_calibration_pending_excluded": True,
        "d3_1_calibration_pending_excluded": True,
        "human_review_incomplete": True,
        "promotion_not_started": True,
        "push_performed": False,
    }
    write("gate_e_summary.json", summary)
    (args.output_dir / "legacy_relation_review_sheet.md").write_text(
        _render_sheet(queue),
        encoding="utf-8",
    )
    (args.output_dir / "gate_e_report.md").write_text(
        _render_report(summary, queue),
        encoding="utf-8",
    )
    repository.close()
    print("status=ok")
    print(f"legacy_relation_pending={len(queue)}")
    print(f"unique_signatures={manifest['unique_signatures']}")
    print(f"manifest_identity={manifest['identity']}")
    print(f"output={args.output_dir}")
    return 0


def _render_sheet(queue: list[dict]) -> str:
    lines = [
        "# Gate E Legacy Relation Human Review Sheet",
        "",
        f"- review set：`legacy-relation-pending-v1`",
        f"- total：{len(queue)}",
        "- reviewed_by：human only",
        "- decision：approve / modify / reject / insufficient",
        "",
    ]
    for item in queue:
        lines.extend(
            [
                f"## {item['review_id']} — {item['candidate_id'][:12]}",
                "",
                f"- Candidate ID：`{item['candidate_id']}`",
                f"- Industry：`{item['industry_id']}` {item['industry_name']}",
                f"- Concept：`{item['concept_id']}` {item['concept_name']}",
                f"- Concept definition：{item['concept_description']}",
                f"- Proposed relevance：`{item['proposed_relevance']}`",
                f"- Proposed source：{item['proposed_source']}",
                f"- Knowledge version at generation："
                f"{item['knowledge_version_when_generated']}",
                f"- Creation stage：{item['creation_stage']}",
                f"- Review status：{item['review_status']}",
                "",
                "### Supporting semantic evidence",
                "",
                "```json",
                json.dumps(
                    item["supporting_semantic_evidence"],
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                f"- Legacy judgement：`{item['legacy_semantic_judgement']}`",
                f"- Legacy rationale：{item['legacy_rationale']}",
                f"- Legacy used fields：{item['legacy_used_fields']}",
                "",
                "### Constraints / Current KB",
                "",
                f"- maximum_allowed_strength："
                f"`{item['maximum_allowed_strength']}`",
                f"- directly_related_allowed："
                f"`{item['directly_related_allowed']}`",
                f"- classification_constraints："
                f"`{json.dumps(item['classification_constraints'], ensure_ascii=False)}`",
                f"- inherited：{item['inherited']}",
                f"- existing canonical relation："
                f"`{json.dumps(item['existing_canonical_relation'], ensure_ascii=False)}`",
                f"- current local resolution：`{item['current_local_resolution']}`",
                f"- conflict status：`{item['conflict_status']}`",
                f"- conditional relation expressible："
                f"{not item['conditional_relation_not_expressible']}",
                "",
                "### Decision",
                "",
                "- [ ] approve"
                f"（final relevance = {item['proposed_relevance']}）",
                "- [ ] modify（final relevance：____；reason：____）",
                "- [ ] reject（error category：____）",
                "- [ ] insufficient（error category：____）",
                "",
            ]
        )
    return "\n".join(lines)


def _render_report(summary: dict, queue: list[dict]) -> str:
    return "\n".join(
        [
            "# Gate E — Legacy Relation Pending Human Resolution",
            "",
            f"- 生成时间：{summary['generated_at']}",
            f"- 状态：**{summary['status']}**",
            f"- expected=12，actual={summary['actual_legacy_relation_pending']}",
            f"- unique signatures={summary['unique_signatures']}",
            f"- manifest identity={summary['manifest_identity']}",
            "",
            "## Isolation",
            "",
            f"- real-ai-review-set-v1 excluded："
            f"{summary['real_ai_review_set_excluded']}",
            f"- D.3 calibration pending excluded："
            f"{summary['d3_calibration_pending_excluded']}",
            f"- D.3.1 calibration pending excluded："
            f"{summary['d3_1_calibration_pending_excluded']}",
            "",
            "## Human Review",
            "",
            "- 12 条全部等待人工裁决。",
            "- reviewed_by=human；AI/Codex 不代写裁决。",
            "- 未开始 canonical promotion。",
            "- 未 push。",
            "",
            "## Review Queue",
            "",
            "| ID | industry | concept | proposed | conflict |",
            "| --- | --- | --- | --- | --- |",
        ]
        + [
            "| "
            + " | ".join(
                [
                    item["review_id"],
                    item["industry_id"],
                    item["concept_id"],
                    item["proposed_relevance"],
                    item["conflict_status"],
                ]
            )
            + " |"
            for item in queue
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
