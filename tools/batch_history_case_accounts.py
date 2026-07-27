"""Read-only v1C/v1D batch run for leaf case folders containing PDFs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.case_accounts import (
    scan_case_account_candidates,
    verification_context_from_manifest,
)
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.result_export import build_bankflow_result, write_bankflow_json


def _leaf_case_folders(root: Path) -> list[Path]:
    return sorted(
        (
            folder
            for folder in root.rglob("*")
            if folder.is_dir()
            and not any(child.is_dir() for child in folder.iterdir())
            and any(child.is_file() and child.suffix.casefold() == ".pdf" for child in folder.iterdir())
        ),
        key=lambda folder: str(folder).casefold(),
    )


def _case_summary(manifest: dict[str, object], result: dict[str, object] | None) -> dict[str, object]:
    files = manifest["files"]
    file_counts: dict[str, int] = {}
    ignored_reasons: dict[str, int] = {}
    for item in files:
        status = str(item.get("scan_status", "unknown"))
        file_counts[status] = file_counts.get(status, 0) + 1
        if status == "ignored":
            reason = str(item.get("reason", "unknown"))
            ignored_reasons[reason] = ignored_reasons.get(reason, 0) + 1
    summary: dict[str, object] = {
        "file_counts": file_counts,
        "ignored_reasons": ignored_reasons,
        "reliable_header_account_count": len(manifest["accounts"]),
        "v1c_status": manifest["v1c_status"],
        "v1d_status": manifest["v1d_status"],
        "v1d_pair_attempt_count": len(manifest["candidate_pairs"]),
        "v1d_preflight_reason": manifest["reason"],
    }
    if result is not None:
        observations = {
            item["observation_type"]: item
            for item in result["result"]["observations"]
        }
        v1c = observations["confirmed_own_account_transfer_candidates"]["value"]
        v1d = observations["confirmed_own_account_transfer_pair_candidates"]["value"]
        summary["v1c"] = {
            "available": v1c["available"],
            "matched_transaction_count": v1c["matched_transaction_count"],
            "reason": v1c.get("reason"),
        }
        summary["v1d"] = {
            "available": v1d["available"],
            "unique_pair_count": len(v1d["paired"]),
            "single_sided_candidate_count": len(v1d["single_sided_candidates"]),
            "ambiguous_candidate_count": len(v1d["ambiguous_candidates"]),
            "reason": v1d.get("reason"),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="批量扫描历史客户末级案例目录并运行 v1C/v1D")
    parser.add_argument("root", help="历史客户根目录")
    parser.add_argument("output", help="输出目录")
    parser.add_argument("--file-timeout", type=float, default=30.0)
    args = parser.parse_args()

    root = Path(args.root)
    output = Path(args.output)
    index: list[dict[str, object]] = []
    header_coverage_unavailable: list[dict[str, object]] = []
    timeout_review: list[dict[str, object]] = []
    for number, folder in enumerate(_leaf_case_folders(root), start=1):
        case_id = f"case-{number:03d}"
        case_output = output / case_id
        summary_path = case_output / "summary.json"
        if summary_path.is_file():
            cached_manifest = json.loads((case_output / "account-scan.json").read_text(encoding="utf-8"))
            for item in cached_manifest["files"]:
                source_file = str(item.get("source_file", ""))
                record = {"case_id": case_id, "case_folder": str(folder), "source_file": source_file, "source_path": str(folder / source_file), "source_file_id": item.get("source_file_id"), "bank_id": item.get("bank_id"), "bank_label": item.get("bank_label"), "reason": item.get("reason")}
                if item.get("reason") == "reliable_header_account_unavailable":
                    header_coverage_unavailable.append(record)
                elif item.get("reason") == "file_timeout":
                    timeout_review.append(record)
            index.append(
                {"case_id": case_id, "case_folder": str(folder), **json.loads(summary_path.read_text(encoding="utf-8"))}
            )
            print(f"{case_id}: resumed")
            continue
        manifest = scan_case_account_candidates(folder, args.file_timeout)
        context = verification_context_from_manifest(manifest)
        transactions = []
        for item in manifest["files"]:
            if item.get("scan_status") not in {"scanned", "masked_scanned"}:
                continue
            path = folder / str(item["source_file"])
            transactions.extend(extract_transactions(str(path), str(item["bank_id"])))
        result = build_bankflow_result(transactions, verification_context=context) if transactions else None
        case_output.mkdir(parents=True, exist_ok=True)
        (case_output / "account-scan.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        if result is not None:
            write_bankflow_json(result, case_output / "v1c-v1d-result.json")
        summary = _case_summary(manifest, result)
        for item in manifest["files"]:
            source_file = str(item.get("source_file", ""))
            record = {"case_id": case_id, "case_folder": str(folder), "source_file": source_file, "source_path": str(folder / source_file), "source_file_id": item.get("source_file_id"), "bank_id": item.get("bank_id"), "bank_label": item.get("bank_label"), "reason": item.get("reason")}
            if item.get("reason") == "reliable_header_account_unavailable":
                header_coverage_unavailable.append(record)
            elif item.get("reason") == "file_timeout":
                timeout_review.append(record)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        index.append({"case_id": case_id, "case_folder": str(folder), **summary})
        print(f"{case_id}: {folder}")
    output.mkdir(parents=True, exist_ok=True)
    (output / "batch-index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "header-coverage-unavailable.json").write_text(
        json.dumps(header_coverage_unavailable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "file-timeout-review.json").write_text(
        json.dumps(timeout_review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
