"""D.1B: build the human review queue for real AI candidates (59, no verdicts).

Only assembles auditable review material. Never writes a human verdict:
candidate_review_decisions.json stays empty until a human fills it.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.ai_business_observation import build_classification_constraints
from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    guard_item,
    load_legacy_signature_entries,
    versioning,
)
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields
from bankflow_v2.knowledge.review_set import build_review_set_manifest


CONCEPT_TASK = "semantic-concept-v1"
RELATION_TASK = "industry-concept-relevance-v1"


def _load_candidates(cache_root: Path) -> list[dict[str, Any]]:
    conn = sqlite3.connect(str(cache_root / "knowledge_v1_runtime.db"))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT candidate_id, candidate_type, proposed_value_json, reason, "
        "model, prompt_version, input_signature_json, created_at, "
        "review_status, reviewed_at FROM candidates ORDER BY created_at"
    ).fetchall()
    conn.close()
    candidates = []
    for row in rows:
        candidates.append(
            {
                "candidate_id": str(row["candidate_id"]),
                "candidate_type": str(row["candidate_type"]),
                "proposed_value": json.loads(row["proposed_value_json"]),
                "reason": str(row["reason"] or ""),
                "model": str(row["model"] or ""),
                "prompt_version": str(row["prompt_version"] or ""),
                "input_signature": json.loads(row["input_signature_json"]),
                "created_at": str(row["created_at"] or ""),
                "review_status": str(row["review_status"] or "pending"),
                "reviewed_at": str(row["reviewed_at"] or ""),
            }
        )
    return candidates


def _field_lookup(
    signature_hash: str,
    entries: list[dict[str, Any]],
    manifest_items: list[dict[str, Any]],
) -> tuple[dict[str, str], str]:
    for entry in entries:
        if (
            semantic_signature_from_fields(entry["fields"]).signature_id
            == signature_hash
        ):
            return dict(entry["fields"]), "legacy-326"
    for item in manifest_items:
        if str(item.get("signature_hash", "")) == signature_hash:
            return dict(item.get("fields", {})), str(
                item.get("source", "unseen")
            )
    return {}, "unknown"


def _concept_catalog(canonical_dir: Path) -> dict[str, dict[str, Any]]:
    data = json.loads(
        (canonical_dir / "semantic_concepts.json").read_text(encoding="utf-8")
    )
    catalog: dict[str, dict[str, Any]] = {}
    for item in data.get("concepts", []):
        catalog[str(item.get("concept_id", ""))] = item
    return catalog


def _concept_overlap_hint(
    concept: dict[str, Any] | None,
    fields: dict[str, str],
) -> list[str]:
    if concept is None:
        return []
    combined = "".join(fields.values())
    terms = [
        str(concept.get("name_zh", "")),
        *[str(item) for item in concept.get("aliases", [])],
        *[str(item) for item in concept.get("keywords", [])],
    ]
    return [
        term
        for term in dict.fromkeys(terms)
        if term and term in combined
    ][:10]


def _provider_run(task: str, index: int, batch_sizes: list[int]) -> dict[str, Any]:
    running = 0
    for batch_number, size in enumerate(batch_sizes, start=1):
        if index < running + size:
            return {"task": task, "batch_number": batch_number}
        running += size
    return {"task": task, "batch_number": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_cache_dir", type=Path)
    parser.add_argument("cache_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    parser.add_argument("--unseen-manifest", type=Path)
    parser.add_argument("--d1c-candidate-ids", type=Path)
    parser.add_argument("--d1c-provider-runs-json", type=Path)
    parser.add_argument(
        "--provider-runs-json",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/ai-validation-20260807/"
            "provider_runs.json"
        ),
    )
    args = parser.parse_args()
    if (
        not args.legacy_cache_dir.is_dir()
        or not (args.cache_root / "knowledge_v1_runtime.db").is_file()
    ):
        print("status=not_started")
        print("reason=inputs_missing")
        return 2
    entries = load_legacy_signature_entries(args.legacy_cache_dir)
    manifest_items: list[dict[str, Any]] = []
    if args.unseen_manifest:
        manifest = json.loads(args.unseen_manifest.read_text(encoding="utf-8"))
        manifest_items = list(manifest.get("items", []))
    candidates = _load_candidates(args.cache_root)
    real_ai = [
        candidate
        for candidate in candidates
        if candidate["input_signature"].get("task")
        in {CONCEPT_TASK, RELATION_TASK}
    ]
    legacy_pending = [
        candidate
        for candidate in candidates
        if candidate["prompt_version"] == "business-relevance-mvp-v11"
        and candidate["review_status"] == "pending"
    ]
    concept_candidates = [
        candidate
        for candidate in real_ai
        if candidate["input_signature"].get("task") == CONCEPT_TASK
    ]
    relation_candidates = [
        candidate
        for candidate in real_ai
        if candidate["input_signature"].get("task") == RELATION_TASK
    ]
    d1c_ids: set[str] = set()
    if args.d1c_candidate_ids:
        d1c_ids = {
            str(item)
            for item in json.loads(
                args.d1c_candidate_ids.read_text(encoding="utf-8")
            )
        }
    catalog = _concept_catalog(args.canonical_dir)
    runtime = KnowledgeRuntime.load(args.canonical_dir)
    concept_by_signature: dict[str, dict[str, Any]] = {}

    provider_runs = []
    if args.provider_runs_json.is_file():
        provider_runs = json.loads(
            args.provider_runs_json.read_text(encoding="utf-8")
        )
    concept_batch_sizes = [
        int(run.get("item_count", 0))
        for run in provider_runs
        if run.get("task") == CONCEPT_TASK
    ]
    relation_batch_sizes = [
        int(run.get("item_count", 0))
        for run in provider_runs
        if run.get("task") == RELATION_TASK
    ]
    d1c_concept_batch_sizes: list[int] = []
    d1c_relation_batch_sizes: list[int] = []
    if args.d1c_provider_runs_json and args.d1c_provider_runs_json.is_file():
        d1c_runs = json.loads(
            args.d1c_provider_runs_json.read_text(encoding="utf-8")
        )
        d1c_concept_batch_sizes = [
            int(run.get("item_count", 0))
            for run in d1c_runs
            if run.get("task") == CONCEPT_TASK
        ]
        d1c_relation_batch_sizes = [
            int(run.get("item_count", 0))
            for run in d1c_runs
            if run.get("task") == RELATION_TASK
        ]

    concept_queue: list[dict[str, Any]] = []
    d1c_concept_index = 0
    for index, candidate in enumerate(concept_candidates):
        signature_hash = str(
            candidate["input_signature"].get("signature_hash", "")
        )
        fields, source = _field_lookup(
            signature_hash,
            entries,
            manifest_items,
        )
        concept_id = str(candidate["proposed_value"].get("concept_id", ""))
        concept = catalog.get(concept_id)
        guard = guard_item(fields)
        proposed_value = candidate["proposed_value"]
        provider_run = _provider_run(
            CONCEPT_TASK,
            index,
            concept_batch_sizes,
        )
        if candidate["candidate_id"] in d1c_ids:
            provider_run = _provider_run(
                CONCEPT_TASK,
                d1c_concept_index,
                d1c_concept_batch_sizes,
            )
            d1c_concept_index += 1
        queue_item = {
            "candidate_id": candidate["candidate_id"],
            "task": CONCEPT_TASK,
            "stage": (
                "Gate D.1C"
                if candidate["candidate_id"] in d1c_ids
                else "Gate D"
            ),
            "privacy_history": (
                "previously blocked false-positive, safely remediated"
                if candidate["candidate_id"] in d1c_ids
                else ""
            ),
            "semantic_signature": signature_hash,
            "normalized_safe_semantic_text": dict(fields),
            "source": source,
            "proposal_kind": str(proposed_value.get("proposal_kind", "")),
            "concept_id": concept_id,
            "concept_name": str(proposed_value.get("name_zh", "")),
            "confidence": str(proposed_value.get("confidence", "")),
            "used_fields": list(proposed_value.get("used_fields", [])),
            "model_rationale": candidate["reason"],
            "source_fields": sorted(fields),
            "resolver_version": str(
                candidate["input_signature"].get("resolver_version", "")
            ),
            "knowledge_version": str(
                proposed_value.get("created_version", "")
                or versioning.KNOWLEDGE_VERSION
            ),
            "prompt_version": candidate["prompt_version"],
            "model": candidate["model"],
            "provider_run": provider_run,
            "review_status": candidate["review_status"],
            "duplicate_status": {
                "same_concept_candidates": sum(
                    1
                    for other in concept_candidates
                    if other["proposed_value"].get("concept_id") == concept_id
                ),
                "same_signature_candidates": sum(
                    1
                    for other in concept_candidates
                    if other["input_signature"].get("signature_hash")
                    == signature_hash
                ),
            },
            "privacy_status": "allowed" if guard.allowed else "blocked",
            "constraint_check": build_classification_constraints(fields),
            "existing_concept": (
                {
                    "concept_id": str(concept.get("concept_id", "")),
                    "name_zh": str(concept.get("name_zh", "")),
                    "description": str(concept.get("description", "")),
                    "alias_count": len(concept.get("aliases", [])),
                    "aliases_sample": [
                        str(item)
                        for item in concept.get("aliases", [])[:8]
                    ],
                    "keyword_count": len(concept.get("keywords", [])),
                    "examples_generic": [
                        str(item)
                        for item in concept.get("examples_generic", [])[:6]
                    ],
                }
                if concept is not None
                else None
            ),
            "semantic_overlap_hint": _concept_overlap_hint(concept, fields),
        }
        concept_queue.append(queue_item)
        concept_by_signature[signature_hash] = queue_item

    relation_queue: list[dict[str, Any]] = []
    for index, candidate in enumerate(relation_candidates):
        signature_hash = str(
            candidate["input_signature"].get("signature_hash", "")
        )
        fields, source = _field_lookup(
            signature_hash,
            entries,
            manifest_items,
        )
        concept_ref = concept_by_signature.get(signature_hash)
        industry_id = str(candidate["input_signature"].get("industry_id", ""))
        industry_node = runtime.taxonomy.node(industry_id)
        proposed = candidate["proposed_value"]
        relation_provider_run = _provider_run(
            RELATION_TASK,
            index,
            relation_batch_sizes,
        )
        if candidate["candidate_id"] in d1c_ids:
            relation_provider_run = _provider_run(
                RELATION_TASK,
                index,
                d1c_relation_batch_sizes,
            )
        relation_queue.append(
            {
                "candidate_id": candidate["candidate_id"],
                "task": RELATION_TASK,
                "stage": (
                    "Gate D.1C"
                    if candidate["candidate_id"] in d1c_ids
                    else "Gate D"
                ),
                "privacy_history": (
                    "previously blocked false-positive, safely remediated"
                    if candidate["candidate_id"] in d1c_ids
                    else ""
                ),
                "concept_candidate_ref": (
                    concept_ref["candidate_id"] if concept_ref else ""
                ),
                "concept_id": str(
                    candidate["input_signature"].get("concept_id", "")
                ),
                "concept_name": str(
                    concept_ref["concept_name"] if concept_ref else ""
                ),
                "semantic_signature": signature_hash,
                "source": source,
                "industry_id": industry_id,
                "industry_name": (
                    industry_node.name if industry_node is not None else ""
                ),
                "proposed_relevance": str(proposed.get("relevance", "")),
                "model_raw_relevance": str(
                    proposed.get("model_raw_relevance", "")
                ),
                "guard_adjusted": bool(proposed.get("guard_adjusted", False)),
                "constraint_maximum": str(
                    build_classification_constraints(fields).get(
                        "maximum_allowed_strength",
                        "",
                    )
                ),
                "inherited": False,
                "provider_rationale": candidate["reason"],
                "task_version": candidate["prompt_version"],
                "model": candidate["model"],
                "provider_run": relation_provider_run,
                "knowledge_version": str(
                    proposed.get("created_version", "")
                    or versioning.KNOWLEDGE_VERSION
                ),
                "review_status": candidate["review_status"],
            }
        )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "Gate D / D.1C real AI fallback candidates",
        "ai_pending_total": len(real_ai),
        "concept_candidates": len(concept_queue),
        "relation_candidates": len(relation_queue),
        "existing_concept_proposals": sum(
            1
            for item in concept_queue
            if item["proposal_kind"] == "existing_concept"
        ),
        "new_concept_proposals": sum(
            1
            for item in concept_queue
            if item["proposal_kind"] == "new_concept"
        ),
        "new_concept_proposal_ids": sorted(
            {
                item["concept_id"]
                for item in concept_queue
                if item["proposal_kind"] == "new_concept"
            }
        ),
        "duplicate_candidate_pairs": [
            {
                "concept_id": concept_id,
                "candidate_ids": [
                    item["candidate_id"]
                    for item in concept_queue
                    if item["concept_id"] == concept_id
                ],
            }
            for concept_id in sorted(
                {
                    item["concept_id"]
                    for item in concept_queue
                    if item["duplicate_status"]["same_concept_candidates"] > 1
                }
            )
        ],
        "legacy_relation_pending_excluded": len(legacy_pending),
        "stage_counts": {
            "Gate D": sum(
                1
                for item in concept_queue + relation_queue
                if item["stage"] == "Gate D"
            ),
            "Gate D.1C": sum(
                1
                for item in concept_queue + relation_queue
                if item["stage"] == "Gate D.1C"
            ),
        },
        "provenance": {
            "task": [CONCEPT_TASK, RELATION_TASK],
            "knowledge_version": versioning.KNOWLEDGE_VERSION,
            "resolver_version": versioning.RESOLVER_VERSION,
            "provider_run_reconstruction": (
                "batch numbers derived from provider_runs.json item order"
            ),
        },
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)

    def write_json(name: str, value: Any) -> Path:
        path = args.output_dir / name
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return path

    write_json("review_summary.json", summary)
    write_json("concept_review_queue.json", concept_queue)
    write_json("relation_review_queue.json", relation_queue)
    decisions_path = args.output_dir / "candidate_review_decisions.json"
    human_decision_count = 0
    if decisions_path.is_file():
        decisions_data = json.loads(
            decisions_path.read_text(encoding="utf-8")
        )
        human_decision_count = len(decisions_data.get("decisions", []))
        decisions_value = decisions_data
    else:
        decisions_value = {
            "schema_version": "d1-review-v1",
            "reviewed_by": "human",
            "promotion_status": "not_promoted",
            "decisions": [],
            "instructions": (
                "Only a human may append decisions. Scripts must not mark "
                "reviewed_by=human or auto-approve. Each decision: "
                "approve|reject|modify|insufficient with final_value and "
                "review_reason."
            ),
        }
    write_json(
        "real_ai_review_set_manifest.json",
        build_review_set_manifest(
            review_set_version="real-ai-review-set-v1",
            knowledge_version=versioning.KNOWLEDGE_VERSION,
            candidates=concept_queue + relation_queue,
            legacy_pending_count=len(legacy_pending),
            human_decision_count=human_decision_count,
        ),
    )
    write_json("candidate_review_decisions.json", decisions_value)
    write_json(
        "candidate_quality_metrics.json",
        {
            "status": "not_yet_computable",
            "missing": "human labels",
            "definitions": {
                "existing_concept_recovery_accuracy": (
                    "exact approve / existing concept proposals"
                ),
                "existing_concept_recovery_acceptance_rate": (
                    "(exact approve + modify) / existing concept proposals"
                ),
                "new_concept_proposal_acceptance_rate": (
                    "(exact approve + modify) / new concept proposals"
                ),
                "relation_exact_relevance_accuracy": (
                    "exact approve / relation candidates"
                ),
                "usable_after_modification": "approve + modify",
            },
            "concept": {
                "total_concept_candidates": len(concept_queue),
                "existing_concept_proposals": summary[
                    "existing_concept_proposals"
                ],
                "new_concept_proposals": summary["new_concept_proposals"],
                "exact_approve": None,
                "modify": None,
                "reject": None,
                "insufficient": None,
                "existing_concept_recovery_accuracy": None,
                "existing_concept_recovery_acceptance_rate": None,
                "new_concept_proposal_acceptance_rate": None,
            },
            "relation": {
                "total_relation_candidates": len(relation_queue),
                "exact_approve": None,
                "modify": None,
                "reject": None,
                "insufficient": None,
                "exact_relevance_accuracy": None,
            },
            "overall": {
                "total_ai_candidates": len(real_ai),
                "exact_approve_rate": None,
                "usable_after_modification_rate": None,
                "reject_rate": None,
                "insufficient_rate": None,
            },
        },
    )
    write_json(
        "candidate_review_sheet.md",
        render_sheet(concept_queue, relation_queue, summary),
    )
    print("status=ok")
    for key, value in summary.items():
        if key != "duplicate_candidate_pairs":
            print(f"{key}={value}")
    print(f"duplicate_pairs={json.dumps(summary['duplicate_candidate_pairs'], ensure_ascii=False)}")
    print(f"output={args.output_dir}")
    return 0


def render_sheet(
    concept_queue: list[dict[str, Any]],
    relation_queue: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    lines = [
        "# Gate D.1 — Real AI Candidate Human Review Sheet",
        "",
        f"- AI pending candidates：{summary['ai_pending_total']}"
        f"（concept {summary['concept_candidates']} / relation "
        f"{summary['relation_candidates']}）",
        f"- legacy relation pending（不参与本轮审核）："
        f"{summary['legacy_relation_pending_excluded']}",
        "- 本表仅提供审核材料；人工结论写入 candidate_review_decisions.json。",
        "- 禁止：自动 approve、AI 自审视为人工、把真实商户名写入 canonical alias。",
        "",
        f"## Concept Candidates（{len(concept_queue)}）",
        "",
    ]
    for index, item in enumerate(concept_queue, start=1):
        lines.append(f"### C{index:03d} — {item['proposal_kind']}：{item['concept_id']} / {item['concept_name']}")
        if item["stage"] == "Gate D.1C":
            lines.extend(
                [
                    "",
                    f"**Source Stage: {item['stage']}**",
                    f"**Privacy History: {item['privacy_history']}**",
                ]
            )
        if item["proposal_kind"] == "new_concept":
            lines.append("")
            lines.append("**NEW CONCEPT — 需重点判断是否与现有近义 Concept 合并**")
        lines.extend(
            [
                "",
                f"- candidate_id：`{item['candidate_id']}`",
                f"- task / prompt version：{item['task']} / {item['prompt_version']}",
                f"- semantic signature：`{item['semantic_signature']}`",
                f"- source：{item['source']}",
                f"- confidence：{item['confidence']}",
                f"- used fields：{', '.join(item['used_fields']) or '-'}",
                f"- 归一化语义文本（完整）："
                + "；".join(
                    f"{key}={value}"
                    for key, value in item["normalized_safe_semantic_text"].items()
                ),
                f"- 模型 rationale：{item['model_rationale']}",
                f"- 约束检查：maximum_allowed_strength="
                f"{item['constraint_check'].get('maximum_allowed_strength', '')}",
                f"- provider run：{item['provider_run']}",
                f"- knowledge version / resolver：{item['knowledge_version']} / {item['resolver_version']}",
                f"- duplicate：同 concept {item['duplicate_status']['same_concept_candidates']} 条；"
                f"同签名 {item['duplicate_status']['same_signature_candidates']} 条",
                f"- privacy：{item['privacy_status']}",
            ]
        )
        if item["existing_concept"] is not None:
            existing = item["existing_concept"]
            lines.extend(
                [
                    f"- 现有 concept：{existing['name_zh']}（{existing['concept_id']}）",
                    f"  - 描述：{existing['description'] or '-'}",
                    f"  - aliases（{existing['alias_count']}，示例）："
                    + "、".join(existing["aliases_sample"] or ["-"])[:200],
                    f"  - examples："
                    + "、".join(existing["examples_generic"] or ["-"])[:200],
                    f"  - 文本重叠提示："
                    + "、".join(item["semantic_overlap_hint"] or ["无"])[:200],
                ]
            )
        lines.extend(
            [
                "",
                "Decision:",
                "[ ] approve",
                "[ ] modify",
                "[ ] reject",
                "[ ] insufficient",
                "",
                "Human final value:",
                "",
                "Human reason:",
                "",
                "---",
                "",
            ]
        )
    lines.extend(
        [
            f"## Relation Candidates（{len(relation_queue)}）",
            "",
        ]
    )
    for index, item in enumerate(relation_queue, start=1):
        lines.extend(
            [
                f"### R{index:03d} — {item['industry_id']} × {item['concept_id']}",
                "",
            ]
        )
        if item["stage"] == "Gate D.1C":
            lines.extend(
                [
                    f"**Source Stage: {item['stage']}**",
                    f"**Privacy History: {item['privacy_history']}**",
                    "",
                ]
            )
        lines.extend(
            [
                f"- candidate_id：`{item['candidate_id']}`",
                f"- concept candidate ref：`{item['concept_candidate_ref']}`（来源链："
                f"transaction semantic → new concept candidate → relation candidate）",
                f"- concept：{item['concept_id']} / {item['concept_name']}",
                f"- industry：{item['industry_id']} / {item['industry_name']}",
                f"- proposed relevance：{item['proposed_relevance']}"
                f"（model raw={item['model_raw_relevance']}，"
                f"guard_adjusted={item['guard_adjusted']}，"
                f"constraint_max={item['constraint_maximum']}）",
                f"- inherited：{item['inherited']}",
                f"- provider rationale：{item['provider_rationale']}",
                f"- task / version / model：{item['task_version']} / {item['model']}",
                f"- provider run：{item['provider_run']}",
                f"- status：{item['review_status']}",
                "",
                "Decision:",
                "[ ] approve",
                "[ ] modify",
                "[ ] reject",
                "[ ] insufficient",
                "",
                "Human final value:",
                "",
                "Human reason:",
                "",
                "---",
                "",
            ]
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
