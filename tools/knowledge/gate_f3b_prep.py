"""Gate F3B: Human Gold review prep, validation and freeze (no prediction).

AI never fills gold. This module only prepares review files, validates
human-filled enums/refs/invariants, and freezes the final Human Gold.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge.freeze import manifest_checksum


REVIEW_STANDARD_VERSION = "human_gold_review_standard_v1"
RELATION_VALUES = ("strong", "medium", "weak", "none", "undetermined")
ROLE_VALUES = (
    "direct_business",
    "operating_expense",
    "tax_regulatory",
    "financing",
    "settlement_infrastructure",
    "employment_operation",
    "government_interaction",
    "personal_consumption",
    "neutral_transfer",
    "unknown",
)
TRACE_VALUES = ("strong", "medium", "weak", "none", "undetermined")
ROUTE_VALUES = (
    "local_resolved",
    "ai_eligible_transaction",
    "insufficient_transaction",
    "case_aggregation_only",
)
PRESENCE_VALUES = ("strong", "medium", "weak", "none", "undetermined")
CONSISTENCY_VALUES = ("strong", "medium", "weak", "none", "undetermined")
SUFFICIENCY_VALUES = ("sufficient", "partial", "insufficient")
CONFIDENCE_VALUES = ("high", "medium", "low")

TX_GOLD_COLUMNS = (
    "human_industry_direct_relation",
    "human_business_evidence_role",
    "human_business_trace_strength",
    "human_expected_route",
    "human_sufficient_information",
    "human_confidence",
    "supporting_evidence_refs",
    "reviewer_reasoning",
    "reviewer_id",
    "reviewed_at",
    "review_standard_version",
)

CASE_GOLD_COLUMNS = (
    "business_activity_presence",
    "declared_industry_consistency",
    "human_assessment_sufficiency",
    "supporting_evidence_refs",
    "contradictory_evidence_refs",
    "uncertainty_notes",
    "reasoning_summary",
    "reviewer_id",
    "reviewed_at",
    "review_standard_version",
)

TX_REVIEW_INFO_COLUMNS = (
    "holdout_item_id",
    "anonymized_case_id",
    "declared_industry",
    "business_description",
    "normalized_transaction_text",
    "safe_semantic_evidence",
    "date",
    "month",
    "direction",
    "amount",
    "amount_bucket",
    "evidence_refs",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def load_holdout_items(holdout_dir: Path) -> list[dict[str, Any]]:
    path = holdout_dir / "production_transaction_evidence_holdout_v1_items.jsonl"
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def load_case_meta(holdout_dir: Path, output_dir: Path) -> list[dict[str, Any]]:
    case_manifest = json.loads(
        (holdout_dir / "production_case_holdout_v1_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    inventory = json.loads(
        (holdout_dir / "0808_case_inventory.json").read_text(encoding="utf-8")
    )
    by_id = {row["anonymized_case_id"]: row for row in inventory}
    rows: list[dict[str, Any]] = []
    for case_id in case_manifest["case_ids"]:
        row = by_id.get(case_id, {})
        rows.append(
            {
                "anonymized_case_id": case_id,
                "declared_industry": row.get("declared_industry", ""),
                "business_description": row.get("business_description", ""),
                "source_directory": row.get("source_directory", ""),
                "statement_files": row.get("statement_files", []),
                "company_address_available": row.get(
                    "company_address_available",
                    False,
                ),
                "home_address_available": row.get(
                    "home_address_available",
                    False,
                ),
            }
        )
    return rows


def build_transaction_review_csv(items: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=TX_REVIEW_INFO_COLUMNS + TX_GOLD_COLUMNS,
        extrasaction="ignore",
    )
    writer.writeheader()
    for item in sorted(items, key=lambda row: row["holdout_item_id"]):
        writer.writerow(
            {
                "holdout_item_id": item["holdout_item_id"],
                "anonymized_case_id": item["source_case_id"],
                "declared_industry": item["declared_industry"],
                "business_description": item["declared_industry"],
                "normalized_transaction_text": item[
                    "normalized_transaction_text"
                ],
                "safe_semantic_evidence": json.dumps(
                    item["safe_semantic_evidence"],
                    ensure_ascii=False,
                ),
                "date": item["date"],
                "month": item["month"],
                "direction": item["direction"],
                "amount": item["amount"],
                "amount_bucket": item["amount_bucket"],
                "evidence_refs": item["source_evidence_reference"],
                **{column: "" for column in TX_GOLD_COLUMNS},
            }
        )
    return buffer.getvalue()


def build_case_review_csv(cases: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=(
            "anonymized_case_id",
            "declared_industry",
            "business_description",
            "account_source_coverage",
            "company_address_available",
            "home_address_available",
        )
        + CASE_GOLD_COLUMNS,
        extrasaction="ignore",
    )
    writer.writeheader()
    for case in sorted(cases, key=lambda row: row["anonymized_case_id"]):
        writer.writerow(
            {
                "anonymized_case_id": case["anonymized_case_id"],
                "declared_industry": case["declared_industry"],
                "business_description": case["business_description"],
                "account_source_coverage": "|".join(
                    str(doc.get("bank_id", ""))
                    for doc in case["statement_files"]
                    if doc.get("supported")
                ),
                "company_address_available": case[
                    "company_address_available"
                ],
                "home_address_available": case["home_address_available"],
                **{column: "" for column in CASE_GOLD_COLUMNS},
            }
        )
    return buffer.getvalue()


def build_qc_list(items: list[dict[str, Any]], *, count: int = 10) -> str:
    rng = random.Random(20260808)
    selected = sorted(items, key=lambda row: row["holdout_item_id"])
    rng.shuffle(selected)
    selected = selected[:count]
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=(
            "qc_item_id",
            "holdout_item_id",
            "declared_industry",
            "normalized_transaction_text",
            "safe_semantic_evidence",
            "date",
            "direction",
            "amount",
            "blank_for_rereview",
        ),
    )
    writer.writeheader()
    for index, item in enumerate(selected, start=1):
        writer.writerow(
            {
                "qc_item_id": f"QC-{index:02d}",
                "holdout_item_id": item["holdout_item_id"],
                "declared_industry": item["declared_industry"],
                "normalized_transaction_text": item[
                    "normalized_transaction_text"
                ],
                "safe_semantic_evidence": json.dumps(
                    item["safe_semantic_evidence"],
                    ensure_ascii=False,
                ),
                "date": item["date"],
                "direction": item["direction"],
                "amount": item["amount"],
                "blank_for_rereview": "true",
            }
        )
    return buffer.getvalue()


def validate_transaction_gold(
    gold: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    by_id = {item["holdout_item_id"]: item for item in items}
    errors: list[str] = []
    warnings: list[str] = []
    for row in gold:
        item_id = str(row.get("holdout_item_id", ""))
        if item_id not in by_id:
            errors.append(f"{item_id}: unknown holdout item")
            continue
        if str(row.get("human_industry_direct_relation", "")) not in RELATION_VALUES:
            errors.append(f"{item_id}: invalid industry relation")
        if str(row.get("human_business_evidence_role", "")) not in ROLE_VALUES:
            errors.append(f"{item_id}: invalid evidence role")
        if str(row.get("human_business_trace_strength", "")) not in TRACE_VALUES:
            errors.append(f"{item_id}: invalid trace strength")
        if str(row.get("human_expected_route", "")) not in ROUTE_VALUES:
            errors.append(f"{item_id}: invalid route")
        if not str(row.get("reviewer_reasoning", "")).strip():
            errors.append(f"{item_id}: reviewer_reasoning missing")
        if not str(row.get("reviewer_id", "")).strip():
            errors.append(f"{item_id}: reviewer_id missing")
        if (
            row.get("human_industry_direct_relation") == "none"
            and row.get("human_sufficient_information") != "true"
        ):
            warnings.append(
                f"{item_id}: none used without sufficient information"
            )
        if (
            row.get("human_business_evidence_role") == "unknown"
            and row.get("human_business_trace_strength")
            not in {"undetermined", ""}
        ):
            warnings.append(
                f"{item_id}: unknown role with non-undetermined trace"
            )
    return {
        "reviewed_count": len(gold),
        "expected_count": len(items),
        "complete": len(gold) == len(items),
        "errors": errors,
        "warnings": warnings,
    }


def validate_case_gold(
    case_gold: list[dict[str, Any]],
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    case_ids = {case["anonymized_case_id"] for case in cases}
    errors: list[str] = []
    warnings: list[str] = []
    for row in case_gold:
        case_id = str(row.get("anonymized_case_id", ""))
        if case_id not in case_ids:
            errors.append(f"{case_id}: unknown case")
            continue
        if str(row.get("business_activity_presence", "")) not in PRESENCE_VALUES:
            errors.append(f"{case_id}: invalid presence")
        if (
            str(row.get("declared_industry_consistency", ""))
            not in CONSISTENCY_VALUES
        ):
            errors.append(f"{case_id}: invalid consistency")
        if str(row.get("human_assessment_sufficiency", "")) not in SUFFICIENCY_VALUES:
            errors.append(f"{case_id}: invalid sufficiency")
        if not str(row.get("reasoning_summary", "")).strip():
            errors.append(f"{case_id}: reasoning_summary missing")
        if not str(row.get("reviewer_id", "")).strip():
            errors.append(f"{case_id}: reviewer_id missing")
        if (
            row.get("declared_industry_consistency") == "none"
            and row.get("business_activity_presence") in {"none", "undetermined"}
        ):
            warnings.append(
                f"{case_id}: consistency none with weak/no activity presence"
            )
    return {
        "reviewed_count": len(case_gold),
        "expected_count": len(cases),
        "complete": len(case_gold) == len(cases),
        "errors": errors,
        "warnings": warnings,
    }


def freeze_gold(
    *,
    output_dir: Path,
    tx_gold: list[dict[str, Any]],
    case_gold: list[dict[str, Any]],
    qc_results: dict[str, Any],
    reviewer: str,
    reviewed_at_range: list[str],
    candidate_v2_checksum: str,
    holdout_checksum: str,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    tx_path = output_dir / "production_transaction_evidence_human_gold_v1.jsonl"
    case_path = output_dir / "production_case_human_gold_v1.json"
    tx_path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False) + "\n" for row in tx_gold
        ),
        encoding="utf-8",
    )
    case_path.write_text(
        json.dumps(case_gold, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    manifest = {
        "freeze_version": "human-gold-v1",
        "review_standard_version": REVIEW_STANDARD_VERSION,
        "reviewer": reviewer,
        "reviewed_at_range": reviewed_at_range,
        "transaction_item_count": len(tx_gold),
        "case_count": len(case_gold),
        "artifact_checksums": {
            "transaction_gold": _sha256_file(tx_path),
            "case_gold": _sha256_file(case_path),
        },
        "qc_results": qc_results,
        "candidate_v2_checksum": candidate_v2_checksum,
        "holdout_checksum": holdout_checksum,
        "prediction_call_count": 0,
        "provider_call_count": 0,
        "created_at": _utcnow(),
    }
    manifest["aggregate_checksum"] = manifest_checksum(manifest)
    manifest_path = output_dir / "human_gold_freeze_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--holdout-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f3a-1-resume-holdout-20260808"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f3b-human-gold-20260809"
        ),
    )
    parser.add_argument("--qc-count", type=int, default=10)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    items = load_holdout_items(args.holdout_dir)
    cases = load_case_meta(args.holdout_dir, args.output_dir)
    (args.output_dir / "transaction_human_review_v1.csv").write_text(
        build_transaction_review_csv(items),
        encoding="utf-8-sig",
    )
    (args.output_dir / "case_human_review_v1.csv").write_text(
        build_case_review_csv(cases),
        encoding="utf-8-sig",
    )
    (args.output_dir / "transaction_qc_rereview_v1.csv").write_text(
        build_qc_list(items, count=args.qc_count),
        encoding="utf-8-sig",
    )
    (args.output_dir / "case_review_meta.json").write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "gate": "F3B-PREP",
        "review_standard_version": REVIEW_STANDARD_VERSION,
        "transaction_review_rows": len(items),
        "case_review_rows": len(cases),
        "qc_count": args.qc_count,
        "gold_status": "blank",
        "prediction_call_count": 0,
        "provider_call_count": 0,
        "created_at": _utcnow(),
    }
    (args.output_dir / "f3b_prep_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("status=prepared")
    print(f"transaction_review_rows={len(items)}")
    print(f"case_review_rows={len(cases)}")
    print(f"qc_count={args.qc_count}")
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
