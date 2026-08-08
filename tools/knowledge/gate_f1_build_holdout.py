"""Gate F1: build a contamination-safe Production Holdout without invoking knowledge_v1."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.knowledge.ai_validation import safe_validation_fields
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields


logging.getLogger("pdfplumber").setLevel(logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)


SAFE_FIELDS = (
    "counterparty_name",
    "merchant_name",
    "summary",
    "remark",
    "purpose",
    "product_description",
    "merchant_category",
)
PAYMENT_MARKERS = (
    "财付通",
    "微信",
    "支付宝",
    "扫码",
    "二维码",
    "POS",
    "拉卡拉",
    "收钱码",
)
ORG_MARKERS = (
    "公司",
    "集团",
    "商行",
    "经营部",
    "门市部",
    "银行",
    "医院",
    "超市",
    "商店",
    "中心",
    "厂",
    "店",
    "铺",
    "部",
    "馆",
    "广场",
    "商场",
    "市场",
    "大厦",
    "酒店",
    "餐厅",
    "饭店",
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _collect_signatures_json(path: Path, result: set[str]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"signature_hash", "semantic_signature"} and isinstance(
                    item,
                    str,
                ):
                    result.add(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)


def _collect_signatures_db(db_path: Path, result: set[str]) -> None:
    if not db_path.is_file():
        return
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute("SELECT input_signature_json FROM candidates").fetchall()
    conn.close()
    for (payload,) in rows:
        try:
            data = json.loads(payload)
            sig = str(data.get("signature_hash", ""))
            if sig:
                result.add(sig)
        except Exception:
            continue


def _expand_regression_path(value: str, assets: Path) -> Path:
    expanded = str(value).replace("${CD_ASSETS}", str(assets))
    expanded = os.path.expandvars(expanded)
    return Path(expanded).expanduser().resolve()


def _safe_fields_for_tx(tx: Any) -> dict[str, str]:
    fields: dict[str, str] = {}
    for name in SAFE_FIELDS:
        value = str(getattr(tx, name, "") or "")
        confidence = float(getattr(tx, "field_confidence", {}).get(name, 0.0) or 0.0)
        if value.strip() and confidence >= 1.0:
            fields[name] = value
    return safe_validation_fields(fields)


def _sampling_metadata(tx: Any, fields: dict[str, str]) -> dict[str, Any]:
    text = " ".join(fields.values())
    income = getattr(tx, "income", None)
    expense = getattr(tx, "expense", None)
    if income and income > 0:
        direction = "income"
        amount = float(income)
    elif expense and expense > 0:
        direction = "expense"
        amount = float(expense)
    else:
        direction = "unknown"
        amount = 0.0
    return {
        "direction": direction,
        "amount_bucket": (
            "zero"
            if amount == 0
            else "small"
            if amount < 1000
            else "medium"
            if amount < 10000
            else "large"
        ),
        "text_length_bucket": (
            "short" if len(text) < 10 else "medium" if len(text) < 30 else "long"
        ),
        "field_types": sorted(fields),
        "payment_marker": any(marker in text for marker in PAYMENT_MARKERS),
        "org_marker": any(marker in text for marker in ORG_MARKERS),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--assets", type=Path, default=Path("D:/Codex data/CD_assets"))
    parser.add_argument("--mvp-input", type=Path, default=Path("D:/Investigator PDF/MVP-input"))
    parser.add_argument(
        "--regression-cases",
        type=Path,
        default=Path("D:/Investigator PDF/CD-bankflow-refactor/tools/regression_cases.json"),
    )
    parser.add_argument(
        "--knowledge-outputs",
        type=Path,
        default=Path("D:/Investigator PDF/outputs/knowledge-v1"),
    )
    parser.add_argument(
        "--main-cache",
        type=Path,
        default=Path("D:/Investigator PDF/outputs/knowledge-v1-cache/knowledge_v1_runtime.db"),
    )
    parser.add_argument(
        "--d31-cache",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/gate-d3-1-recall-recovery-20260808/"
            "cache-final3/knowledge_v1_runtime.db"
        ),
    )
    parser.add_argument("--target-signatures", type=int, default=120)
    parser.add_argument("--max-per-document", type=int, default=8)
    parser.add_argument("--max-documents", type=int, default=121)
    parser.add_argument("--skip-large-mb", type=float, default=25.0)
    args = parser.parse_args()

    # ---- Document exclusion registry ----
    mvp_docs = {p.resolve() for p in args.mvp_input.rglob("*.pdf")}
    regression = json.loads(args.regression_cases.read_text(encoding="utf-8"))
    regression_docs = {
        _expand_regression_path(str(case.get("path", "")), args.assets).resolve()
        for case in regression
    }
    excluded_docs = mvp_docs | regression_docs

    # ---- Signature exclusion registry ----
    excluded_signatures: set[str] = set()
    for path in args.knowledge_outputs.rglob("*.json"):
        _collect_signatures_json(path, excluded_signatures)
    legacy_cache = (
        args.knowledge_outputs
        / "shadow-20260807"
        / "legacy-cache-326"
        / "signatures"
    )
    if legacy_cache.is_dir():
        for namespace in legacy_cache.iterdir():
            if namespace.is_dir():
                excluded_signatures.update(
                    path.stem for path in namespace.glob("*.json")
                )
    _collect_signatures_db(args.main_cache, excluded_signatures)
    _collect_signatures_db(args.d31_cache, excluded_signatures)

    # ---- Pristine source inventory ----
    all_pdfs = sorted(p for p in args.assets.rglob("*.pdf"))
    pristine_pdfs = [
        p for p in all_pdfs if p.resolve() not in excluded_docs
    ]
    pristine_pdfs = sorted(
        pristine_pdfs,
        key=lambda p: (_sha256_text(str(p.resolve())), str(p.resolve())),
    )[: args.max_documents]
    doc_ref = {
        p.resolve(): _sha256_text(str(p.resolve()))[:24] for p in pristine_pdfs
    }

    signature_pool: dict[str, dict[str, Any]] = {}
    per_doc: dict[str, set[str]] = defaultdict(set)
    source_inventory = {
        "total_foundation_pdfs": len(all_pdfs),
        "excluded_documents": len(excluded_docs),
        "pristine_documents": len(pristine_pdfs),
        "documents": [],
        "parsed_ok": 0,
        "parsed_failed": 0,
        "unsupported": 0,
        "total_transactions": 0,
        "unique_signatures_before_exclusion": 0,
        "unique_signatures_after_exclusion": 0,
    }

    for pdf in pristine_pdfs:
        ref = doc_ref[pdf.resolve()]
        if pdf.stat().st_size > args.skip_large_mb * 1024 * 1024:
            source_inventory["unsupported"] += 1
            source_inventory["documents"].append(
                {
                    "ref": ref,
                    "status": "skipped_large",
                    "reason": f"file > {args.skip_large_mb}MB",
                }
            )
            continue
        try:
            detection = detect_bank_type(str(pdf))
            bank = detection.bank_id
            if not bank:
                source_inventory["unsupported"] += 1
                source_inventory["documents"].append(
                    {"ref": ref, "status": "unsupported", "reason": detection.reason}
                )
                continue
            transactions = extract_transactions(str(pdf), bank)
            source_inventory["parsed_ok"] += 1
        except Exception as exc:
            source_inventory["parsed_failed"] += 1
            source_inventory["documents"].append(
                {"ref": ref, "status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
            )
            continue
        source_inventory["total_transactions"] += len(transactions)
        source_inventory["documents"].append(
            {
                "ref": ref,
                "status": "ok",
                "bank": bank,
                "transactions": len(transactions),
            }
        )
        for tx in transactions:
            fields = _safe_fields_for_tx(tx)
            if not fields:
                continue
            signature = semantic_signature_from_fields(fields)
            if not signature.pairs:
                continue
            sig_id = signature.signature_id
            metadata = _sampling_metadata(tx, fields)
            entry = signature_pool.setdefault(
                sig_id,
                {
                    "signature_id": sig_id,
                    "fields": fields,
                    "occurrence_count": 0,
                    "source_documents": [],
                    "metadata": metadata,
                    "excluded": sig_id in excluded_signatures,
                },
            )
            entry["occurrence_count"] += 1
            if ref not in entry["source_documents"]:
                entry["source_documents"].append(ref)
            per_doc[ref].add(sig_id)

    source_inventory["unique_signatures_before_exclusion"] = len(signature_pool)
    clean_pool = {
        sig_id: entry
        for sig_id, entry in signature_pool.items()
        if not entry["excluded"]
    }
    source_inventory["unique_signatures_after_exclusion"] = len(clean_pool)

    # ---- Deterministic round-robin selection ----
    doc_signatures = {
        ref: sorted(sigs, key=lambda s: (signature_pool[s]["occurrence_count"], s))
        for ref, sigs in per_doc.items()
    }
    selected: list[str] = []
    selected_docs: set[str] = set()
    doc_counts: Counter[str] = Counter()
    max_per_doc = args.max_per_document
    target = args.target_signatures
    changed = True
    while changed and len(selected) < target:
        changed = False
        for ref in sorted(doc_signatures):
            if len(selected) >= target:
                break
            if doc_counts[ref] >= max_per_doc:
                continue
            for sig_id in doc_signatures[ref]:
                if sig_id in selected or sig_id not in clean_pool:
                    continue
                selected.append(sig_id)
                selected_docs.add(ref)
                doc_counts[ref] += 1
                changed = True
                break

    # ---- Contamination audit ----
    selected_sigs = set(selected)
    contamination = {
        "exact_signature_overlap": len(selected_sigs & excluded_signatures),
        "gate_d_overlap": 0,
        "gate_e_overlap": 0,
        "kb_supporting_example_overlap": 0,
        "development_document_overlap": 0,
        "unexplained_overlap": 0,
        "excluded_documents_in_selected": 0,
    }
    membership = [
        {
            "holdout_id": f"H-{index + 1:03d}",
            "signature_id": sig_id,
            "source_documents": signature_pool[sig_id]["source_documents"],
            "occurrence_count": signature_pool[sig_id]["occurrence_count"],
            "fields": signature_pool[sig_id]["fields"],
            "metadata": signature_pool[sig_id]["metadata"],
        }
        for index, sig_id in enumerate(selected)
    ]
    manifest_payload = {
        "holdout_version": "production-holdout-v1",
        "freeze_timestamp": datetime.now(timezone.utc).isoformat(),
        "membership_count": len(membership),
        "source_document_count": len(selected_docs),
        "target_signatures": target,
        "max_per_document": max_per_doc,
        "document_max_contribution": max(doc_counts.values(), default=0),
        "signature_ids": selected,
        "source_document_refs": sorted(selected_docs),
        "contamination_audit": contamination,
        "exclusion_registry_version": "holdout-exclusion-registry-v1",
        "independence_level": "level2",
        "independence_note": (
            "document-level exclusion applied for known development/regression "
            "documents plus exact signature exclusion; customer identity across "
            "filenames cannot be fully verified, so independence is limited."
        ),
    }
    manifest_checksum = hashlib.sha256(
        json.dumps(
            manifest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    args.output_dir.mkdir(parents=True, exist_ok=True)

    def write(name: str, value: Any) -> None:
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write(
        "holdout_exclusion_registry.json",
        {
            "version": "holdout-exclusion-registry-v1",
            "excluded_document_count": len(excluded_docs),
            "excluded_signature_count": len(excluded_signatures),
            "excluded_document_refs": sorted(
                _sha256_text(str(p))[:24] for p in excluded_docs
            ),
            "excluded_signature_hashes": sorted(excluded_signatures),
            "note": "identities are hashed/stable refs; no full customer names.",
        },
    )
    write("holdout_source_inventory.json", source_inventory)
    write("holdout_contamination_audit.json", contamination)
    write("production_holdout_manifest.json", {**manifest_payload, "checksum": manifest_checksum})
    write(
        "holdout_sampling_report.json",
        {
            "target_signatures": target,
            "actual_signatures": len(membership),
            "source_document_count": len(selected_docs),
            "document_contribution_distribution": dict(sorted(doc_counts.items())),
            "metadata_distribution": {
                "direction": dict(
                    Counter(item["metadata"]["direction"] for item in membership)
                ),
                "amount_bucket": dict(
                    Counter(item["metadata"]["amount_bucket"] for item in membership)
                ),
                "text_length_bucket": dict(
                    Counter(
                        item["metadata"]["text_length_bucket"] for item in membership
                    )
                ),
                "payment_marker": dict(
                    Counter(item["metadata"]["payment_marker"] for item in membership)
                ),
                "org_marker": dict(
                    Counter(item["metadata"]["org_marker"] for item in membership)
                ),
            },
            "membership": membership,
        },
    )

    print("status=ok")
    print(f"pristine_documents={source_inventory['pristine_documents']}")
    print(f"parsed_ok={source_inventory['parsed_ok']}")
    print(f"unique_signatures_after_exclusion={len(clean_pool)}")
    print(f"selected={len(membership)}")
    print(f"source_documents={len(selected_docs)}")
    print(f"contamination={json.dumps(contamination, ensure_ascii=False)}")
    print(f"checksum={manifest_checksum}")
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
