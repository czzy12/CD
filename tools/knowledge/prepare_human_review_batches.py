"""Gate D.2: prepare interactive human review batches (no verdicts written)."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import versioning
from bankflow_v2.knowledge.human_review import (
    CONCEPT_ERROR_CATEGORIES,
    CONCEPT_TASK,
    RELATION_ERROR_CATEGORIES,
    RELATION_TASK,
    REVIEW_SET_VERSION,
    VALID_DECISIONS,
)
from bankflow_v2.knowledge.review_set import review_set_identity


def _nearest_alternatives(
    fields: dict[str, str],
    catalog: dict[str, dict[str, Any]],
    proposed_concept_id: str,
    limit: int = 3,
) -> list[dict[str, Any]]:
    combined = "".join(fields.values())
    scored: list[tuple[int, str, str, list[str]]] = []
    for concept_id, concept in catalog.items():
        if concept_id == proposed_concept_id:
            continue
        terms = [
            str(concept.get("name_zh", "")),
            *[str(item) for item in concept.get("aliases", [])],
            *[str(item) for item in concept.get("keywords", [])],
        ]
        hits = [
            term for term in dict.fromkeys(terms) if term and term in combined
        ]
        if hits:
            scored.append(
                (len(hits), concept_id, str(concept.get("name_zh", "")), hits)
            )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        {
            "concept_id": item[1],
            "name_zh": item[2],
            "overlap_terms": item[3][:4],
        }
        for item in scored[:limit]
    ]


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _concept_batch_form(item: dict[str, Any], index: int) -> list[str]:
    lines = [
        f"### {item['candidate_id']}",
        "",
        f"- review index：C{index:03d}",
        f"- candidate_id：`{item['candidate_id']}`",
        f"- semantic_signature：`{item['semantic_signature']}`",
        f"- AI proposed concept：{item['concept_id']} / {item['concept_name']}"
        f"（{item['proposal_kind']}，confidence={item['confidence']}）",
        f"- source field types：{', '.join(item['source_fields']) or '-'}",
        f"- safe semantic evidence（完整）："
        + "；".join(
            f"{key}={value}"
            for key, value in item["normalized_safe_semantic_text"].items()
        ),
        f"- AI rationale：{item['model_rationale']}",
        f"- knowledge version：{item['knowledge_version']}",
        f"- source stage：{item['stage']}",
    ]
    existing = item.get("existing_concept")
    if existing is not None:
        lines.extend(
            [
                f"- canonical definition：{existing['name_zh']}（{existing['concept_id']}）"
                f"：{existing['description'] or '-'}",
                f"- canonical aliases（{existing['alias_count']}）："
                + "、".join(existing["aliases_sample"] or ["-"])[:180],
                f"- canonical examples："
                + "、".join(existing["examples_generic"] or ["-"])[:180],
            ]
        )
    alternatives = item.get("nearest_alternatives", [])
    if alternatives:
        lines.append(
            "- nearest plausible alternatives："
            + "；".join(
                f"{alt['concept_id']} / {alt['name_zh']}"
                f"（重叠：{','.join(alt['overlap_terms'][:3]) or '-'}）"
                for alt in alternatives
            )
        )
    lines.extend(
        [
            "- constraint check：maximum_allowed_strength="
            f"{item['constraint_check'].get('maximum_allowed_strength', '')}",
            "",
            "Decision:",
            "[ ] approve",
            "[ ] modify",
            "[ ] reject",
            "[ ] insufficient",
            "",
            "If modify, final value (concept_id / name):",
            "",
            "Error category (if not approve):",
            "",
            "Human reason:",
            "",
            "---",
            "",
        ]
    )
    return lines


def _relation_batch_form(item: dict[str, Any], index: int) -> list[str]:
    return [
        f"### {item['candidate_id']}",
        "",
        f"- review index：R{index:02d}",
        f"- candidate_id：`{item['candidate_id']}`",
        f"- source concept candidate ref：`{item['concept_candidate_ref']}`",
        f"- concept：{item['concept_id']} / {item['concept_name']}"
        f"（source stage {item['stage']}）",
        f"- industry：{item['industry_id']} / {item['industry_name']}",
        f"- AI proposed relevance：{item['proposed_relevance']}"
        f"（model raw={item['model_raw_relevance']}，"
        f"guard_adjusted={item['guard_adjusted']}，"
        f"constraint_max={item['constraint_maximum']}）",
        f"- provider rationale：{item['provider_rationale']}",
        "",
        "Dependency rule：仅当上游 Concept 为 approve 时 Relation 可 exact approve；",
        "上游 reject/insufficient 时只能 reject 或 insufficient（原因注明 upstream）。",
        "",
        "Decision:",
        "[ ] approve",
        "[ ] modify",
        "[ ] reject",
        "[ ] insufficient",
        "",
        "If modify, final relevance (strong/medium/weak/none/undetermined):",
        "",
        "Error category (if not approve):",
        "",
        "Human reason:",
        "",
        "---",
        "",
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_set_dir", type=Path)
    parser.add_argument("--batch-size", type=int, default=12)
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    args = parser.parse_args()
    if args.batch_size < 1:
        print("status=not_started")
        print("reason=batch_size_must_be_positive")
        return 2
    root = args.review_set_dir
    manifest_path = root / "real_ai_review_set_manifest.json"
    concept_path = root / "concept_review_queue.json"
    relation_path = root / "relation_review_queue.json"
    for path in (manifest_path, concept_path, relation_path):
        if not path.is_file():
            print("status=not_started")
            print(f"reason=missing_{path.name}")
            return 2
    manifest = _load_json(manifest_path)
    concept_queue = _load_json(concept_path)
    relation_queue = _load_json(relation_path)

    expected_identity = review_set_identity(
        review_set_version=str(manifest.get("review_set_version", "")),
        knowledge_version=str(manifest.get("knowledge_version", "")),
        candidate_ids=[
            str(item) for item in manifest.get("candidate_ids", [])
        ],
    )
    integrity = {
        "review_set_version": manifest.get("review_set_version"),
        "frozen_checksum": manifest.get("manifest_identity"),
        "expected_checksum": expected_identity,
        "checksum_ok": expected_identity
        == manifest.get("manifest_identity"),
        "concept_candidates": manifest.get("concept_candidates"),
        "relation_candidates": manifest.get("relation_candidates"),
        "total_candidates": manifest.get("total_candidates"),
        "queue_concept_candidates": len(concept_queue),
        "queue_relation_candidates": len(relation_queue),
        "membership_ok": (
            manifest.get("concept_candidates") == len(concept_queue)
            and manifest.get("relation_candidates") == len(relation_queue)
            and manifest.get("total_candidates")
            == len(concept_queue) + len(relation_queue)
        ),
        "human_decisions_at_prepare": int(
            manifest.get("human_decisions", 0)
        ),
        "legacy_relation_pending_excluded": int(
            manifest.get("legacy_relation_pending_excluded", 0)
        ),
    }
    if not integrity["checksum_ok"] or not integrity["membership_ok"]:
        print("status=blocked")
        print("reason=review_set_integrity_failed")
        print(json.dumps(integrity, ensure_ascii=False))
        return 1

    catalog_data = _load_json(args.canonical_dir / "semantic_concepts.json")
    catalog = {
        str(item.get("concept_id", "")): item
        for item in catalog_data.get("concepts", [])
    }
    for item in concept_queue:
        item["nearest_alternatives"] = _nearest_alternatives(
            item["normalized_safe_semantic_text"],
            catalog,
            str(item.get("concept_id", "")),
        )

    batches: list[dict[str, Any]] = []
    for offset in range(0, len(concept_queue), args.batch_size):
        batch_items = concept_queue[offset : offset + args.batch_size]
        batch_id = f"batch_c{offset // args.batch_size + 1:02d}"
        batches.append(
            {
                "batch_id": batch_id,
                "kind": "concept",
                "items": batch_items,
            }
        )
    if relation_queue:
        batches.append({"batch_id": "batch_r01", "kind": "relation", "items": relation_queue})

    generated_at = datetime.now(timezone.utc).isoformat()
    written: list[Path] = []
    for batch in batches:
        json_path = root / f"{batch['batch_id']}.json"
        md_path = root / f"{batch['batch_id']}.md"
        json_path.write_text(
            json.dumps(batch, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        lines = [
            f"# Gate D.2 {batch['batch_id']} — "
            f"{'Concept' if batch['kind'] == 'concept' else 'Relation'} Review",
            "",
            f"- review_set_version：{manifest['review_set_version']}",
            f"- frozen checksum：{manifest['manifest_identity']}",
            f"- 生成时间：{generated_at}",
            "- 请逐条给出 approve / modify / reject / insufficient；",
            "  modify 需给出 final value，非 approve 需给出 error category 与 reason。",
            "",
        ]
        for index, item in enumerate(batch["items"], start=1):
            if batch["kind"] == "concept":
                lines.extend(_concept_batch_form(item, index))
            else:
                lines.extend(_relation_batch_form(item, index))
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.extend([json_path, md_path])

    summary = {
        "status": "awaiting_human_labels",
        "review_set_version": manifest["review_set_version"],
        "frozen_checksum": manifest["manifest_identity"],
        "total_candidates": manifest["total_candidates"],
        "concept_candidates": manifest["concept_candidates"],
        "relation_candidates": manifest["relation_candidates"],
        "reviewed": 0,
        "pending": manifest["total_candidates"],
        "decisions": [],
        "batches": [
            {
                "batch_id": batch["batch_id"],
                "kind": batch["kind"],
                "item_count": len(batch["items"]),
                "candidate_ids": [
                    item["candidate_id"] for item in batch["items"]
                ],
            }
            for batch in batches
        ],
        "integrity": integrity,
        "generated_at": generated_at,
    }
    (root / "human_review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "concept_human_review.json").write_text(
        json.dumps(
            {
                "review_set_version": REVIEW_SET_VERSION,
                "candidates": concept_queue,
                "decisions": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "relation_human_review.json").write_text(
        json.dumps(
            {
                "review_set_version": REVIEW_SET_VERSION,
                "candidates": relation_queue,
                "decisions": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "error_taxonomy.json").write_text(
        json.dumps(
            {
                "status": "not_yet_computable",
                "missing": "human labels",
                "total_non_approve": 0,
                "taxonomy_closed": True,
                "unexplained": 0,
                "categories": {},
                "concept_categories": list(CONCEPT_ERROR_CATEGORIES),
                "relation_categories": list(RELATION_ERROR_CATEGORIES),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "systemic_findings.json").write_text(
        json.dumps(
            {
                "status": "not_yet_computable",
                "missing": "human labels",
                "conclusion": None,
                "findings": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "remediation_candidates.json").write_text(
        json.dumps(
            {
                "note": "Only recorded after human review reveals issues; none recorded yet.",
                "items": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "gate_d2_report.md").write_text(
        "\n".join(
            [
                "# Gate D.2 — Human Candidate Quality Review",
                "",
                f"- 状态：**awaiting_human_labels**",
                f"- review_set_version：{manifest['review_set_version']}",
                f"- frozen checksum：{manifest['manifest_identity']}",
                f"- reviewed：0 / pending：{manifest['total_candidates']}",
                "- 审核批次已生成："
                + "、".join(batch["batch_id"] for batch in batches),
                "- 未写入任何 human decision；未修改 candidate/canonical/production。",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    written.extend(
        [
            root / "human_review_summary.json",
            root / "concept_human_review.json",
            root / "relation_human_review.json",
            root / "error_taxonomy.json",
            root / "systemic_findings.json",
            root / "remediation_candidates.json",
            root / "gate_d2_report.md",
        ]
    )
    print("status=ok")
    print(f"integrity_checksum_ok={integrity['checksum_ok']}")
    print(f"integrity_membership_ok={integrity['membership_ok']}")
    print(f"concept_batches={sum(1 for b in batches if b['kind']=='concept')}")
    print(f"relation_batches={sum(1 for b in batches if b['kind']=='relation')}")
    for batch in batches:
        print(f"{batch['batch_id']}={len(batch['items'])}")
    print(f"output={root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
