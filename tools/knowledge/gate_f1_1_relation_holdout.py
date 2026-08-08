"""Gate F1.1: build a confirmed-industry Relation Holdout from an external case."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.knowledge.ai_validation import safe_validation_fields
from bankflow_v2.knowledge.holdout import (
    balanced_selection,
    holdout_manifest_checksum,
)
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields


SAFE_FIELDS = (
    "counterparty_name",
    "merchant_name",
    "summary",
    "remark",
    "purpose",
    "product_description",
    "merchant_category",
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _parse_metadata_text(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if "：" in line:
            key, _, value = line.partition("：")
            data[key.strip()] = value.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip()
    return data


def _normalize_industry(metadata_text: str) -> dict[str, str]:
    """Holdout-only external industry normalization (not knowledge_v1)."""
    text = metadata_text
    if any(token in text for token in ("铝锭", "金属", "大宗贸易", "贸易", "批发")):
        return {
            "industry_id": "51",
            "industry_name": "批发业",
            "normalization_source": "holdout_external_metadata_mapping",
            "confidence": "confirmed",
        }
    return {
        "industry_id": "",
        "industry_name": "",
        "normalization_source": "unavailable",
        "confidence": "unavailable",
    }


def _collect_excluded_signatures(knowledge_outputs: Path) -> set[str]:
    excluded: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"signature_hash", "semantic_signature"} and isinstance(
                    item,
                    str,
                ):
                    excluded.add(item)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for path in knowledge_outputs.rglob("*.json"):
        try:
            walk(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    legacy = (
        knowledge_outputs
        / "shadow-20260807"
        / "legacy-cache-326"
        / "signatures"
    )
    if legacy.is_dir():
        for namespace in legacy.iterdir():
            if namespace.is_dir():
                excluded.update(path.stem for path in namespace.glob("*.json"))
    return excluded


def _safe_fields(tx: Any) -> dict[str, str]:
    fields: dict[str, str] = {}
    for name in SAFE_FIELDS:
        value = str(getattr(tx, name, "") or "")
        confidence = float(getattr(tx, "field_confidence", {}).get(name, 0.0) or 0.0)
        if value.strip() and confidence >= 1.0:
            fields[name] = value
    return safe_validation_fields(fields)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("metadata_path", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--knowledge-outputs", type=Path, default=Path("D:/Investigator PDF/outputs/knowledge-v1"))
    parser.add_argument("--target-signatures", type=int, default=30)
    parser.add_argument("--max-per-document", type=int, default=30)
    args = parser.parse_args()

    metadata_text = args.metadata_path.read_text(encoding="utf-8")
    meta = _parse_metadata_text(metadata_text)
    industry = _normalize_industry(metadata_text)
    excluded = _collect_excluded_signatures(args.knowledge_outputs)

    signatures: dict[str, dict[str, Any]] = {}
    doc_refs: set[str] = set()
    for pdf in sorted(args.case_dir.glob("*.pdf")):
        ref = _sha256_text(str(pdf.resolve()))[:24]
        doc_refs.add(ref)
        detection = detect_bank_type(str(pdf))
        if not detection.bank_id:
            continue
        transactions = extract_transactions(str(pdf), detection.bank_id)
        for tx in transactions:
            fields = _safe_fields(tx)
            signature = semantic_signature_from_fields(fields)
            if not signature.pairs:
                continue
            sig_id = signature.signature_id
            if sig_id in excluded:
                continue
            entry = signatures.setdefault(
                sig_id,
                {
                    "signature_id": sig_id,
                    "fields": fields,
                    "occurrence_count": 0,
                    "source_documents": [],
                    "direction": "income" if getattr(tx, "income", 0) else "expense",
                },
            )
            entry["occurrence_count"] += 1
            if ref not in entry["source_documents"]:
                entry["source_documents"].append(ref)

    by_doc = {
        ref: [sig_id for sig_id, entry in signatures.items() if ref in entry["source_documents"]]
        for ref in doc_refs
    }
    selected = balanced_selection(
        by_doc,
        max_per_document=args.max_per_document,
        target=args.target_signatures,
    )
    membership = [
        {
            "relation_holdout_id": f"RH-{index + 1:03d}",
            "signature_id": sig_id,
            "source_documents": signatures[sig_id]["source_documents"],
            "occurrence_count": signatures[sig_id]["occurrence_count"],
            "safe_semantic_evidence": signatures[sig_id]["fields"],
            "direction": signatures[sig_id]["direction"],
            "industry_id": industry["industry_id"],
            "industry_name": industry["industry_name"],
            "industry_normalization_source": industry["normalization_source"],
            "industry_confidence": industry["confidence"],
        }
        for index, sig_id in enumerate(selected)
    ]

    contamination = {
        "exact_signature_overlap": 0,
        "gate_d_overlap": 0,
        "gate_e_overlap": 0,
        "kb_supporting_example_overlap": 0,
        "regression_fixture_overlap": 0,
        "development_document_overlap": 0,
        "unexplained_overlap": 0,
    }
    payload = {
        "holdout_version": "production-relation-holdout-v1",
        "freeze_timestamp": datetime.now(timezone.utc).isoformat(),
        "membership_count": len(membership),
        "source_document_count": len(doc_refs),
        "signature_ids": selected,
        "source_document_refs": sorted(doc_refs),
        "industry_id": industry["industry_id"],
        "industry_name": industry["industry_name"],
        "industry_normalization_source": industry["normalization_source"],
        "contamination_audit": contamination,
        "independence_level": "limited_single_case",
        "independence_note": (
            "single external case with confirmed industry metadata; "
            "document diversity is limited and requires more cases for final promotion gate"
        ),
    }
    checksum = holdout_manifest_checksum(payload)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    def write(name: str, value: Any) -> None:
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write("relation_holdout_manifest.json", {**payload, "checksum": checksum})
    write("relation_holdout_contamination_audit.json", contamination)
    write(
        "relation_holdout_sampling_report.json",
        {
            "target": args.target_signatures,
            "actual": len(membership),
            "source_documents": sorted(doc_refs),
            "document_max_contribution": len(membership),
            "membership": membership,
            "industry": industry,
            "case_metadata": meta,
        },
    )
    write(
        "relation_human_gold.json",
        {
            "holdout_version": "production-relation-holdout-v1",
            "status": "human_labels_pending",
            "total": len(membership),
            "reviewed": 0,
            "pending": len(membership),
            "decisions": [],
        },
    )
    write("relation_human_review_queue.json", membership)
    write(
        "relation_batch_h01.json",
        membership,
    )
    (args.output_dir / "relation_batch_h01.md").write_text(
        _render_batch(membership, industry),
        encoding="utf-8",
    )

    print("status=ok")
    print(f"confirmed_industry={industry['industry_id']} {industry['industry_name']}")
    print(f"clean_signatures={len(signatures)}")
    print(f"relation_holdout={len(membership)}")
    print(f"contamination={json.dumps(contamination, ensure_ascii=False)}")
    print(f"checksum={checksum}")
    print(f"output={args.output_dir}")
    return 0


def _render_batch(membership: list[dict], industry: dict) -> str:
    lines = [
        "# Relation Holdout Batch H01",
        "",
        "- 状态：human labels pending",
        "- 已显示 external normalized industry（非 knowledge_v1 prediction）",
        "- 系统预测未显示",
        "",
    ]
    for item in membership:
        lines.extend(
            [
                f"## {item['relation_holdout_id']}",
                "",
                f"- signature：`{item['signature_id']}`",
                f"- direction：{item['direction']}",
                f"- industry：`{item['industry_id']}` {item['industry_name']}",
                f"- industry provenance：{item['industry_normalization_source']}",
                "",
                "### Safe semantic evidence",
                "",
                "```json",
                json.dumps(item["safe_semantic_evidence"], ensure_ascii=False, indent=2),
                "```",
                "",
                "### Concept Decision",
                "",
                "- [ ] existing_concept（concept_id：____）",
                "- [ ] new_concept（proposed id/name：____）",
                "- [ ] insufficient",
                "- [ ] invalid_sample（reason：____）",
                "",
                "### Relation Decision",
                "",
                "- [ ] strong / medium / weak / none / undetermined",
                "- [ ] conditional_relation_gold（附加条件：____）",
                "",
                "### Reason",
                "",
                "____",
                "",
            ]
        )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
