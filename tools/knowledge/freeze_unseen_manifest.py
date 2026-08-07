"""Freeze unseen AI-eligible signatures from a real standard result (repo-external).

Unseen means: not in the calibration legacy cache, locally concept-unresolved,
guard-passed. The frozen manifest is the AI validation input for Gate D.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    load_legacy_signature_entries,
    safe_validation_fields,
)
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields
from bankflow_v2.knowledge.privacy import guard_item

from _profiles import PRESETS, resolve_profile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("standard_result_json", type=Path)
    parser.add_argument("legacy_cache_dir", type=Path)
    parser.add_argument("output_manifest", type=Path)
    parser.add_argument("--canonical-dir", type=Path, default=Path("bankflow_v2/knowledge/canonical"))
    parser.add_argument("--profile", choices=sorted(PRESETS), required=True)
    parser.add_argument("--max-items", type=int, default=20)
    parser.add_argument("--source-label", default="unseen")
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()
    if not args.standard_result_json.is_file():
        print("status=not_started")
        print("reason=standard_result_not_found")
        return 2
    if not args.legacy_cache_dir.is_dir():
        print("status=not_started")
        print("reason=legacy_cache_dir_not_found")
        return 2

    runtime = KnowledgeRuntime.load(args.canonical_dir)
    profile = resolve_profile(args.profile)
    calibration = {
        semantic_signature_from_fields(entry["fields"]).signature_id
        for entry in load_legacy_signature_entries(args.legacy_cache_dir)
    }
    data = json.loads(args.standard_result_json.read_text(encoding="utf-8"))
    transactions = data["result"]["original_transactions"]

    seen: set[str] = set()
    manifest_items: list[dict[str, object]] = []
    stats = {
        "transactions": len(transactions),
        "calibration_signatures": len(calibration),
        "new_signature_candidates": 0,
        "locally_resolved_skipped": 0,
        "guard_blocked": 0,
        "frozen_items": 0,
    }
    for transaction in transactions:
        if len(manifest_items) >= args.max_items:
            break
        raw_fields: dict[str, str] = {}
        standard_fields = transaction.get("standard_fields", {})
        if not isinstance(standard_fields, dict):
            continue
        for field_name in (
            "counterparty_name",
            "merchant_name",
            "summary",
            "remark",
            "purpose",
            "product_description",
            "merchant_category",
        ):
            meta = standard_fields.get(field_name)
            if isinstance(meta, dict):
                value = str(meta.get("value") or "")
                confidence = str(meta.get("confidence") or "")
                if value and confidence == "1.0":
                    raw_fields[field_name] = value
            else:
                value = str(meta or "")
                if value:
                    raw_fields[field_name] = value
        fields = safe_validation_fields(raw_fields)
        if not fields:
            continue
        signature = semantic_signature_from_fields(fields)
        if not signature.pairs:
            continue
        if signature.signature_id in calibration or signature.signature_id in seen:
            continue
        seen.add(signature.signature_id)
        stats["new_signature_candidates"] += 1
        resolved = runtime.resolve_transaction_fields(fields, profile)
        if resolved["semantic"].get("concept_id"):
            stats["locally_resolved_skipped"] += 1
            continue
        guard = guard_item(fields)
        if not guard.allowed:
            stats["guard_blocked"] += 1
            continue
        manifest_items.append(
            {
                "item_id": f"sig-{signature.signature_id}",
                "signature_hash": signature.signature_id,
                "fields": fields,
                "profile_name": args.profile,
                "source": args.source_label,
            }
        )
    stats["frozen_items"] = len(manifest_items)
    output = {
        "source_result": str(args.standard_result_json),
        "created_for_task": "semantic-concept-v1",
        "profile": args.profile,
        "stats": stats,
        "items": manifest_items,
    }
    args.output_manifest.parent.mkdir(parents=True, exist_ok=True)
    args.output_manifest.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(
            json.dumps(
                {
                    "status": "ok",
                    "stats": stats,
                    "signature_hashes": [
                        item["signature_hash"] for item in manifest_items
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    print("status=ok")
    for key, value in stats.items():
        print(f"{key}={value}")
    print(f"output={args.output_manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
