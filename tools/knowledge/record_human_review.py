"""Gate D.2: record validated human review decisions (interactive batches).

Input is a batch-decisions JSON:
[
  {
    "candidate_id": "...",
    "review_decision": "approve|modify|reject|insufficient",
    "review_reason": "...",
    "error_category": "..." (required when not approve),
    "final_value": {} (required for modify)
  }
]
The tool builds full records (original_candidate preserved from the frozen
review queue), validates them, and appends to candidate_review_decisions.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge.human_review import (
    REVIEW_SET_VERSION,
    compute_quality_metrics,
    validate_decision_record,
    validate_relation_dependency,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _candidate_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "candidate_id",
        "candidate_type",
        "task",
        "semantic_signature",
        "concept_id",
        "concept_name",
        "proposal_kind",
        "confidence",
        "proposed_relevance",
        "concept_candidate_ref",
        "stage",
        "review_status",
    )
    return {
        key: candidate.get(key, "")
        for key in keys
        if key in candidate
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_set_dir", type=Path)
    parser.add_argument("batch_decisions_json", type=Path)
    args = parser.parse_args()
    root = args.review_set_dir
    decisions_path = root / "candidate_review_decisions.json"
    if not decisions_path.is_file():
        print("status=blocked")
        print("reason=decisions_file_missing")
        return 2
    existing = _load_json(decisions_path)
    existing_records = list(existing.get("decisions", []))
    existing_ids = {
        str(record.get("candidate_id", "")) for record in existing_records
    }
    concept_queue = _load_json(root / "concept_review_queue.json")
    relation_queue = _load_json(root / "relation_review_queue.json")
    candidates = {
        str(item["candidate_id"]): item
        for item in concept_queue + relation_queue
    }
    inputs = _load_json(args.batch_decisions_json)
    if not isinstance(inputs, list):
        print("status=blocked")
        print("reason=batch_decisions_must_be_list")
        return 2
    now = datetime.now(timezone.utc).isoformat()
    added: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    concept_decisions: dict[str, str] = {}
    for entry in inputs:
        candidate_id = str(entry.get("candidate_id", ""))
        candidate = candidates.get(candidate_id)
        if candidate is None:
            errors.append({"candidate_id": candidate_id, "reason": "unknown_candidate"})
            continue
        if candidate_id in existing_ids:
            errors.append({"candidate_id": candidate_id, "reason": "already_reviewed"})
            continue
        record = {
            "candidate_id": candidate_id,
            "review_set_version": REVIEW_SET_VERSION,
            "review_decision": str(entry.get("review_decision", "")),
            "reviewed_by": "human",
            "reviewed_at": now,
            "review_reason": str(entry.get("review_reason", "")),
            "original_candidate": _candidate_snapshot(candidate),
            "final_value": dict(entry.get("final_value", {}) or {}),
            "error_category": str(entry.get("error_category", "") or ""),
            "promotion_status": "not_promoted",
            "review_source": "interactive_human_review",
        }
        violations = validate_decision_record(record, candidate=candidate)
        if violations:
            errors.append(
                {
                    "candidate_id": candidate_id,
                    "reason": "validation_failed",
                    "violations": violations,
                }
            )
            continue
        added.append(record)
        existing_ids.add(candidate_id)
        if str(candidate.get("task", "")) == "semantic-concept-v1":
            concept_decisions[candidate_id] = str(
                record.get("review_decision", "")
            )

    relation_errors: list[dict[str, Any]] = []
    for record in added:
        candidate = candidates[str(record["candidate_id"])]
        if str(candidate.get("task", "")) == "industry-concept-relevance-v1":
            violations = validate_relation_dependency(
                record,
                candidate,
                concept_decisions,
            )
            if violations:
                relation_errors.append(
                    {
                        "candidate_id": record["candidate_id"],
                        "violations": violations,
                    }
                )

    if relation_errors:
        # dependency violations are blocking for this batch
        for record in added:
            candidate = candidates[str(record["candidate_id"])]
            if str(candidate.get("task", "")) == "industry-concept-relevance-v1":
                existing_ids.discard(str(record["candidate_id"]))
        added = [
            record
            for record in added
            if str(candidates[str(record["candidate_id"])].get("task", ""))
            != "industry-concept-relevance-v1"
        ]
        print("status=blocked")
        print("reason=relation_dependency_violation")
        print(json.dumps(relation_errors, ensure_ascii=False))
        return 1

    merged = existing_records + added
    existing["decisions"] = merged
    existing["updated_at"] = now
    decisions_path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    summary_path = root / "human_review_summary.json"
    if summary_path.is_file():
        summary = _load_json(summary_path)
        summary["reviewed"] = len(merged)
        summary["pending"] = int(
            summary.get("total_candidates", 0)
        ) - len(merged)
        summary["decisions"] = [
            {
                "candidate_id": record["candidate_id"],
                "review_decision": record["review_decision"],
                "reviewed_at": record["reviewed_at"],
            }
            for record in merged
        ]
        summary["status"] = (
            "completed" if summary["pending"] == 0 else "awaiting_human_labels"
        )
        summary["updated_at"] = now
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    metrics = compute_quality_metrics(
        merged,
        list(candidates.values()),
    )
    metrics_path = root / "candidate_quality_metrics.json"
    if metrics_path.is_file():
        existing_metrics = _load_json(metrics_path)
        existing_metrics.update(
            {
                "status": metrics["status"],
                "missing_human_labels": metrics["missing_human_labels"],
                "concept": metrics["concept"],
                "existing_concept_recovery": metrics[
                    "existing_concept_recovery"
                ],
                "new_concept_proposals": metrics["new_concept_proposals"],
                "relation": metrics["relation"],
                "overall": metrics["overall"],
                "confidence_calibration": metrics["confidence_calibration"],
                "error_taxonomy": metrics["error_taxonomy"],
                "updated_at": now,
            }
        )
        metrics_path.write_text(
            json.dumps(existing_metrics, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print("status=ok")
    print(f"added={len(added)}")
    print(f"errors={len(errors)}")
    print(f"reviewed_total={len(merged)}")
    print(f"pending={int(summary.get('total_candidates', 0)) - len(merged)}")
    if errors:
        print(json.dumps(errors, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
