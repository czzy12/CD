"""Gate F3A.1: manual external metadata corpus expansion (no OCR).

OCR is explicitly frozen out. External metadata may only come from
machine-readable text or human-confirmed structured entries.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.auto_detect import detect_bank_type

from gate_f3a_build_holdout import (
    CASE_TARGET,
    EXCLUDED_CASE_NAMES,
    HISTORY_ROOT,
    SEED,
    TX_MAX_PER_CASE,
    TX_TARGET,
    _blank_case_gold,
    _blank_tx_gold,
    _case_id,
    _checksum_file,
    _extract_declared_industry,
    _metadata_files,
    _sha256_bytes,
    _sha256_text,
    assets_content_hashes,
    collect_excluded_signatures_and_texts,
    collect_instances,
    select_case_holdout,
    select_transaction_instances,
    verify_candidate_v2,
)


DESKTOP_0805 = Path(r"C:\Users\lenovo\Desktop\0805")
OLD_OUTPUT = Path(
    r"D:\Investigator PDF\outputs\knowledge-v1\gate-f3a-holdout-20260808"
)
OUTPUT_DIR = Path(
    r"D:\Investigator PDF\outputs\knowledge-v1\gate-f3a-1-holdout-20260808"
)
REPO_ROOT = Path(r"D:\Investigator PDF\CD-bankflow-refactor")
_DETECTION_CACHE: dict[str, str] = {}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _excluded(text: str) -> bool:
    return any(name in text for name in EXCLUDED_CASE_NAMES)


def _screenshot_case_root(image: Path) -> Path:
    if image.parent.name == "基础资料":
        return image.parent.parent
    return image.parent


def find_screenshot_candidates() -> list[dict[str, Any]]:
    rows: dict[Path, dict[str, Any]] = {}
    for root in (HISTORY_ROOT, DESKTOP_0805):
        if not root.is_dir():
            continue
        for image in root.rglob("*"):
            if (
                image.is_file()
                and image.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                and "企查查" in image.name
            ):
                case_root = _screenshot_case_root(image)
                if _excluded(str(case_root)):
                    continue
                entry = rows.setdefault(
                    case_root,
                    {
                        "anonymized_case_id": _case_id(case_root),
                        "source_case_ref": str(case_root),
                        "metadata_source_type": (
                            "manual_screenshot_review"
                        ),
                        "source_reference": str(image),
                        "declared_industry": "",
                        "business_description": "",
                        "human_confirmed": False,
                        "entered_by": "",
                        "entered_at": "",
                        "confirmation_status": "pending_human_confirmation",
                        "transaction_evidence_used_for_metadata": False,
                    },
                )
                if len(entry.get("source_reference", "")) < len(str(image)):
                    entry["source_reference"] = str(image)
    return [
        rows[key]
        for key in sorted(
            rows,
            key=lambda p: (str(p).casefold(),),
        )
    ]


def _supported_pdf_count(case_root: Path) -> int:
    count = 0
    for pdf in case_root.rglob("*.pdf"):
        if _excluded(str(pdf)):
            continue
        key = str(pdf.resolve())
        bank_id = _DETECTION_CACHE.get(key)
        if bank_id is None:
            try:
                if pdf.stat().st_size > 25 * 1024 * 1024:
                    bank_id = ""
                else:
                    bank_id = detect_bank_type(key).bank_id or ""
            except OSError:
                bank_id = ""
            _DETECTION_CACHE[key] = bank_id
        if bank_id:
            count += 1
    return count


def prepare_registry(output_dir: Path) -> int:
    candidates = find_screenshot_candidates()
    rows: list[dict[str, Any]] = []
    skipped_machine_readable = 0
    skipped_no_supported_pdf = 0
    for entry in candidates:
        case_root = Path(entry["source_case_ref"])
        metadata = _extract_declared_industry(case_root)
        if metadata["has_external_declared_industry"]:
            skipped_machine_readable += 1
            continue
        if _supported_pdf_count(case_root) == 0:
            skipped_no_supported_pdf += 1
            continue
        entry["source_case_ref"] = str(case_root)
        rows.append(entry)
    output_dir.mkdir(parents=True, exist_ok=True)
    registry = {
        "registry_version": "manual-external-metadata-registry-v1",
        "purpose": (
            "human-confirmed external business metadata only; no OCR, "
            "no transaction-evidence inference"
        ),
        "created_at": _utcnow(),
        "rules": [
            "declared_industry must come from external/customer/investigation "
            "material, never from statement reverse-inference",
            "transaction_evidence_used_for_metadata must stay false",
            "human_confirmed must be true before expansion",
        ],
        "entries": rows,
        "stats": {
            "candidates_found": len(candidates),
            "skipped_machine_readable": skipped_machine_readable,
            "skipped_no_supported_pdf": skipped_no_supported_pdf,
            "pending_human_confirmation": len(rows),
        },
    }
    (output_dir / "manual_external_metadata_registry.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "registry=prepared "
        f"candidates={len(candidates)} pending={len(rows)} "
        f"machine_skipped={skipped_machine_readable} "
        f"no_pdf_skipped={skipped_no_supported_pdf}"
    )
    return 0


def load_confirmed_entries(registry_path: Path) -> list[dict[str, Any]]:
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = [
        entry
        for entry in data.get("entries", [])
        if entry.get("human_confirmed") is True
        and str(entry.get("declared_industry", "")).strip()
        and entry.get("transaction_evidence_used_for_metadata") is False
    ]
    return entries


def discover_expanded_cases(
    confirmed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Machine-text cases + manual-metadata cases (dedup by case id)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import gate_f3a_build_holdout as f3a

    f3a.HISTORY_ROOT = HISTORY_ROOT
    cases = f3a.discover_cases()
    by_id = {case["case_id"]: case for case in cases}
    for entry in confirmed:
        case_root = Path(entry["source_case_ref"])
        if not case_root.is_dir():
            continue
        case_id = _case_id(case_root)
        pdfs = [
            pdf
            for pdf in case_root.rglob("*.pdf")
            if not _excluded(str(pdf))
        ]
        doc_rows = []
        supported = 0
        for pdf in sorted(pdfs):
            detection = detect_bank_type(str(pdf))
            doc_rows.append(
                {
                    "source_document_id": _sha256_text(str(pdf.resolve())),
                    "file_name": pdf.name,
                    "relative_path": str(pdf.relative_to(case_root)),
                    "bank_id": detection.bank_id or "",
                    "supported": bool(detection.bank_id),
                }
            )
            if detection.bank_id:
                supported += 1
        if supported == 0:
            continue
        case = {
            "case_id": case_id,
            "case_root": str(case_root),
            "declared_industry_text": str(entry["declared_industry"]).strip(),
            "external_description_reference": _sha256_text(
                str(entry.get("business_description", "") or "")
            ),
            "company_name": str(entry.get("business_description", "") or ""),
            "public_account_name": "",
            "work_intro": "",
            "qcc_industry": "",
            "gb_industry": "",
            "supported_document_count": supported,
            "total_pdf_count": len(pdfs),
            "source_documents": doc_rows,
            "manual_metadata": {
                "metadata_source_type": entry.get("metadata_source_type", ""),
                "source_reference": entry.get("source_reference", ""),
                "entered_by": entry.get("entered_by", ""),
                "entered_at": entry.get("entered_at", ""),
                "confirmation_status": entry.get(
                    "confirmation_status",
                    "human_confirmed",
                ),
                "transaction_evidence_used_for_metadata": False,
            },
        }
        by_id[case_id] = case
    return list(by_id.values())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prepare-registry",
        action="store_true",
        help="generate blank manual external metadata registry",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=OUTPUT_DIR / "manual_external_metadata_registry.json",
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()

    if not verify_candidate_v2(args.repo_root):
        print("candidate_v2_integrity=FAILED")
        return 1

    if args.prepare_registry:
        return prepare_registry(args.output_dir)

    confirmed = load_confirmed_entries(args.registry)
    if not confirmed:
        print("expand=no_confirmed_metadata")
        print("expand=awaiting_human_metadata")
        return 0

    cases = discover_expanded_cases(confirmed)
    print(f"expanded_cases={len(cases)}")
    if len(cases) < 6:
        print("expand=corpus_insufficient")
        return 2

    (
        excluded_signatures,
        excluded_texts,
        excluded_doc_refs,
        excluded_tx_ids,
    ) = collect_excluded_signatures_and_texts()
    excluded_content = assets_content_hashes()
    parsed_cache: dict[Path, list[Any]] = {}
    by_case: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        instances = collect_instances(
            case,
            excluded_signatures,
            excluded_texts,
            excluded_content,
            excluded_doc_refs,
            excluded_tx_ids,
            parsed_cache=parsed_cache,
        )
        if instances:
            by_case[case["case_id"]] = instances
            case["instance_count"] = len(instances)
            case["month_count"] = len(
                {str(item["month"]) for item in instances if item["month"]}
            )
            case["transaction_count"] = sum(
                len(
                    parsed_cache[
                        (Path(case["case_root"]) / doc["relative_path"]).resolve()
                    ]
                )
                for doc in case["source_documents"]
                if doc["supported"]
            )

    tx_items = select_transaction_instances(by_case)
    tx_case_ids = {item["source_case_id"] for item in tx_items}
    case_holdout, disjoint, overlap = select_case_holdout(cases, tx_case_ids)
    print(
        f"expand=ok transaction={len(tx_items)} cases={len(tx_case_ids)} "
        f"case_holdout={len(case_holdout)} disjoint={disjoint}"
    )
    if len(tx_items) < TX_TARGET:
        print(
            f"shortage transaction={len(tx_items)}/{TX_TARGET} "
            "reason=pristine_corpus_insufficient"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    def write(name: str, value: Any) -> Path:
        path = args.output_dir / name
        if name.endswith(".jsonl"):
            path.write_text(
                "".join(
                    json.dumps(item, ensure_ascii=False) + "\n"
                    for item in value
                ),
                encoding="utf-8",
            )
        else:
            path.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return path

    tx_manifest = {
        "holdout_version": "production-transaction-evidence-holdout-v1",
        "supersedes": "gate-f3a-initial-construction-80x4",
        "manual_metadata_expansion": True,
        "target_count": TX_TARGET,
        "actual_count": len(tx_items),
        "case_count": len(tx_case_ids),
        "seed": SEED,
        "created_at": _utcnow(),
        "no_candidate_prediction_fields": True,
        "candidate_prediction_calls": {
            "knowledge_v1_inference": 0,
            "business_evidence_resolver": 0,
            "relation_prediction": 0,
            "routing_prediction": 0,
            "transaction_ai_provider": 0,
            "case_ai_provider": 0,
        },
        "case_distribution": dict(
            sorted(Counter(item["source_case_id"] for item in tx_items).items())
        ),
    }
    write("production_transaction_evidence_holdout_v1_manifest.json", tx_manifest)
    write("production_transaction_evidence_holdout_v1_items.jsonl", tx_items)
    write(
        "production_transaction_evidence_human_gold_v1_blank.jsonl",
        _blank_tx_gold(tx_items),
    )

    case_manifest = {
        "holdout_version": "production-case-holdout-v1",
        "supersedes": "gate-f3a-initial-construction-4cases",
        "manual_metadata_expansion": True,
        "target_count": CASE_TARGET,
        "actual_count": len(case_holdout),
        "seed": SEED,
        "created_at": _utcnow(),
        "transaction_case_pool_disjoint": disjoint,
        "case_pool_overlap_with_transaction": overlap,
        "overlap_note": (
            "overlap reported explicitly; never silently reused"
        ),
        "case_ids": [case["case_id"] for case in case_holdout],
        "candidate_prediction_calls": {
            "knowledge_v1_inference": 0,
            "business_evidence_resolver": 0,
            "relation_prediction": 0,
            "routing_prediction": 0,
            "transaction_ai_provider": 0,
            "case_ai_provider": 0,
        },
    }
    write("production_case_holdout_v1_manifest.json", case_manifest)
    write("production_case_human_gold_v1_blank.json", _blank_case_gold(case_holdout))

    trace = {
        "old_construction": {
            "dir": str(OLD_OUTPUT),
            "transaction_count": 80,
            "case_count": 4,
        },
        "expanded_eligible_cases": len(cases),
        "final_selection": {
            "transaction_count": len(tx_items),
            "transaction_case_count": len(tx_case_ids),
            "case_holdout_count": len(case_holdout),
            "disjoint": disjoint,
            "overlap": overlap,
        },
    }
    write("expansion_trace.json", trace)

    checksums: dict[str, str] = {}
    for path in sorted(args.output_dir.rglob("*")):
        if path.is_file():
            checksums[str(path.relative_to(args.output_dir))] = _checksum_file(
                path
            )
    write("holdout_checksums.json", checksums)

    report = {
        "gate": "F3A.1",
        "status": "expanded",
        "ocr_calls": 0,
        "candidate_v2_integrity_at_end": (
            "verified" if verify_candidate_v2(args.repo_root) else "FAILED"
        ),
        "prediction_calls": {
            "knowledge_v1_inference": 0,
            "transaction_ai": 0,
            "case_ai": 0,
            "local_evidence": 0,
            "relation": 0,
            "routing": 0,
        },
        "output_dir": str(args.output_dir),
    }
    write("gate_f3a_1_report.json", report)
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
