"""Generate pending industry x concept relation candidates for uncovered pairs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import (
    KnowledgeReviewService,
    KnowledgeRuntime,
    RuntimeKnowledgeRepository,
)
from bankflow_v2.knowledge import versioning

from _profiles import resolve_profile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path("outputs/knowledge-v1-cache"),
    )
    parser.add_argument(
        "--profile",
        choices=sorted(
            [
                "building_material",
                "construction_coal",
                "alcohol_retail",
                "furniture_decoration",
            ]
        ),
    )
    parser.add_argument("--profile-json", type=Path)
    args = parser.parse_args()
    profile = resolve_profile(
        args.profile,
        str(args.profile_json) if args.profile_json else None,
    )
    runtime = KnowledgeRuntime.load(args.canonical_dir)
    repository = RuntimeKnowledgeRepository(args.cache_root)
    review = KnowledgeReviewService(repository, args.canonical_dir)
    created = 0
    duplicates = 0
    covered = 0
    for concept in runtime.concepts.active_concepts():
        for industry_id in (
            *profile.primary_industry_ids,
            *profile.secondary_industry_ids,
        ):
            relation = runtime.relation_resolver.resolve(
                industry_id=industry_id,
                concept_id=concept.concept_id,
                profile=profile,
            )
            if relation.relevance != "undetermined":
                covered += 1
                continue
            added = review.propose(
                candidate_type="new_industry_relation",
                proposed_value={
                    "industry_id": industry_id,
                    "concept_id": concept.concept_id,
                    "relevance": "undetermined",
                },
                reason="行业×概念关系未被 approved 知识覆盖，转入待审核队列",
                model="knowledge_v1_bootstrap",
                prompt_version="industry-concept-relevance-v1",
                input_signature={
                    "industry_id": industry_id,
                    "concept_id": concept.concept_id,
                },
            )
            if added:
                created += 1
            else:
                duplicates += 1
    print("status=ok")
    print(f"covered_relations={covered}")
    print(f"candidates_created={created}")
    print(f"duplicates_skipped={duplicates}")
    summary = review.summary()
    print("pending=" + str(summary["by_status"].get("pending", 0)))
    repository.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
