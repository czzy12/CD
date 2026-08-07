"""List, approve or reject pending knowledge candidates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge import (
    KnowledgeReviewService,
    RuntimeKnowledgeRepository,
)


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
        "action",
        choices=["list", "approve", "reject", "summary"],
    )
    parser.add_argument("--candidate-id")
    args = parser.parse_args()
    repository = RuntimeKnowledgeRepository(args.cache_root)
    review = KnowledgeReviewService(repository, args.canonical_dir)
    if args.action == "summary":
        summary = review.summary()
        for key, value in sorted(summary.items()):
            print(f"{key}={value}")
        repository.close()
        return 0
    if args.action == "list":
        for candidate in review.list_pending():
            print(
                f"{candidate.candidate_id} | {candidate.candidate_type} | "
                f"{candidate.proposed_value} | {candidate.prompt_version} | "
                f"{candidate.created_at}"
            )
        repository.close()
        return 0
    if not args.candidate_id:
        print("status=not_started")
        print("reason=candidate_id_required")
        repository.close()
        return 2
    result = (
        review.approve(args.candidate_id)
        if args.action == "approve"
        else review.reject(args.candidate_id)
    )
    if result is None:
        print("status=not_found")
        repository.close()
        return 1
    print("status=ok")
    print(f"candidate_id={result.candidate_id}")
    print(f"review_status={result.review_status}")
    repository.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
