"""Migrate legacy_v11 accepted semantics into pending knowledge candidates."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    KnowledgeReviewService,
    RuntimeKnowledgeRepository,
    load_legacy_signature_entries,
)
from bankflow_v2.knowledge import versioning

from _profiles import resolve_profile


def _signature_text_hash(fields: dict[str, str]) -> str:
    encoded = json.dumps(
        sorted(fields.items()),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_cache_dir", type=Path)
    parser.add_argument("--canonical-dir", type=Path, default=Path("bankflow_v2/knowledge/canonical"))
    parser.add_argument("--cache-root", type=Path, default=Path("outputs/knowledge-v1-cache"))
    parser.add_argument("--profile", choices=sorted(
        ["building_material", "construction_coal", "alcohol_retail", "furniture_decoration"]
    ))
    parser.add_argument("--profile-json", type=Path)
    parser.add_argument("--summary-json", type=Path)
    args = parser.parse_args()
    profile = resolve_profile(args.profile, str(args.profile_json) if args.profile_json else None)
    runtime = KnowledgeRuntime.load(args.canonical_dir)
    repository = RuntimeKnowledgeRepository(args.cache_root)
    review = KnowledgeReviewService(repository, args.canonical_dir)
    entries = load_legacy_signature_entries(args.legacy_cache_dir)
    relation_candidates = 0
    concept_candidates = 0
    duplicates_skipped = 0
    conflicts: list[dict[str, object]] = []
    accepted_relation_proposals = 0
    for entry in entries:
        fields = entry["fields"]
        resolved = runtime.resolve_transaction_fields(fields, profile)
        legacy = entry["legacy_semantic_judgement"]
        concept_id = resolved["semantic"]["concept_id"]
        if not concept_id:
            added = review.propose(
                candidate_type="new_semantic_concept",
                proposed_value={
                    "concept_id": "",
                    "name_zh": "待人工定义",
                    "signature_text_hash": _signature_text_hash(fields),
                    "legacy_semantic_judgement": legacy,
                },
                reason="legacy_v11 已验收但 knowledge_v1 未覆盖，转入待审核队列",
                model=str(entry.get("model", "legacy_v11")),
                prompt_version="business-relevance-mvp-v11",
                input_signature={
                    "signature_hash": entry["signature_hash"],
                    "signature_text_hash": _signature_text_hash(fields),
                },
            )
            if added:
                concept_candidates += 1
            else:
                duplicates_skipped += 1
            continue
        if legacy not in {"strong", "medium", "weak", "none", "undetermined"}:
            continue
        for industry_id in (
            *profile.primary_industry_ids,
            *profile.secondary_industry_ids,
        ):
            relation = runtime.relation_resolver.resolve(
                industry_id=industry_id,
                concept_id=concept_id,
                profile=profile,
            )
            if relation.relevance != "undetermined":
                continue
            existing = runtime.relations.approved(industry_id, concept_id)
            if existing is not None and existing.relevance != legacy:
                conflicts.append(
                    {
                        "industry_id": industry_id,
                        "concept_id": concept_id,
                        "existing": existing.relevance,
                        "legacy": legacy,
                    }
                )
            added = review.propose(
                candidate_type="new_industry_relation",
                proposed_value={
                    "industry_id": industry_id,
                    "concept_id": concept_id,
                    "relevance": legacy,
                },
                reason="由 legacy_v11 验收结果迁移生成，待人工复核",
                model=str(entry.get("model", "legacy_v11")),
                prompt_version="business-relevance-mvp-v11",
                input_signature={
                    "signature_hash": entry["signature_hash"],
                    "signature_text_hash": _signature_text_hash(fields),
                },
            )
            if added:
                relation_candidates += 1
                accepted_relation_proposals += 1
            else:
                duplicates_skipped += 1
    summary = review.summary()
    output = {
        "source": str(args.legacy_cache_dir),
        "legacy_signature_entries": len(entries),
        "concept_candidates_created": concept_candidates,
        "relation_candidates_created": relation_candidates,
        "duplicates_skipped": duplicates_skipped,
        "legacy_conflicts_with_approved": len(conflicts),
        "conflicts": conflicts,
        "candidate_summary": summary,
    }
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print("status=ok")
    print(f"legacy_signature_entries={len(entries)}")
    print(f"concept_candidates={concept_candidates}")
    print(f"relation_candidates={relation_candidates}")
    print(f"duplicates_skipped={duplicates_skipped}")
    print(f"conflicts={len(conflicts)}")
    repository.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
