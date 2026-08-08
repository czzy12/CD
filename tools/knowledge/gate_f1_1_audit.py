"""Gate F1.1: industry-context audit and holdout fitness decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge.holdout import (
    classify_industry_availability,
    holdout_manifest_checksum,
)


INDUSTRY_KEYWORDS = (
    "行业",
    "主营",
    "经营内容",
    "建筑材料",
    "建材",
    "环保工程",
    "环境治理",
    "建筑工程",
    "建筑施工",
    "煤炭",
    "烟酒",
    "家具",
    "家电",
    "装饰装修",
    "装修",
    "贸易",
    "科技",
    "教育",
    "汽车",
    "物流",
    "餐饮",
)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _expand_regression_path(value: str, assets: Path) -> Path:
    expanded = str(value).replace("${CD_ASSETS}", str(assets))
    expanded = os.path.expandvars(expanded)
    return Path(expanded).expanduser().resolve()


def _sidecar_metadata_text(path: Path) -> str:
    texts: list[str] = []
    directory = path.parent
    stem = path.stem
    for candidate in directory.iterdir():
        if candidate == path or not candidate.is_file():
            continue
        if candidate.suffix.lower() not in {".md", ".json", ".txt", ".csv"}:
            continue
        if stem not in candidate.name and path.name not in candidate.name:
            continue
        try:
            texts.append(candidate.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
    return "\n".join(texts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--holdout-v1-dir",
        type=Path,
        default=Path("D:/Investigator PDF/outputs/knowledge-v1/production-holdout-v1-20260808"),
    )
    parser.add_argument("--assets", type=Path, default=Path("D:/Codex data/CD_assets"))
    parser.add_argument("--mvp-input", type=Path, default=Path("D:/Investigator PDF/MVP-input"))
    parser.add_argument(
        "--regression-cases",
        type=Path,
        default=Path("D:/Investigator PDF/CD-bankflow-refactor/tools/regression_cases.json"),
    )
    parser.add_argument("--max-documents", type=int, default=80)
    args = parser.parse_args()

    mvp_docs = {p.resolve() for p in args.mvp_input.rglob("*.pdf")}
    regression = json.loads(args.regression_cases.read_text(encoding="utf-8"))
    regression_docs = {
        _expand_regression_path(str(case.get("path", "")), args.assets).resolve()
        for case in regression
    }
    excluded_docs = mvp_docs | regression_docs
    pristine_pdfs = sorted(
        [
            p
            for p in args.assets.rglob("*.pdf")
            if p.resolve() not in excluded_docs
        ],
        key=lambda p: (_sha256_text(str(p.resolve())), str(p.resolve())),
    )[: args.max_documents]
    ref_to_path = {
        _sha256_text(str(p.resolve()))[:24]: p.resolve() for p in pristine_pdfs
    }

    v1_manifest = json.loads(
        (args.holdout_v1_dir / "production_holdout_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    source_refs = sorted(v1_manifest["source_document_refs"])
    path_map = {
        ref: str(ref_to_path[ref]) for ref in source_refs if ref in ref_to_path
    }

    doc_audit: list[dict[str, Any]] = []
    counts = {
        "confirmed": 0,
        "available_but_ambiguous": 0,
        "unavailable": 0,
        "invalid_metadata": 0,
    }
    source_types = {
        "external_case_metadata": 0,
        "sidecar_metadata": 0,
        "none": 0,
    }
    for ref in source_refs:
        path = ref_to_path.get(ref)
        if path is None:
            doc_audit.append(
                {
                    "source_document_ref": ref,
                    "status": "unavailable",
                    "reason": "path not in pristine mapping",
                }
            )
            counts["unavailable"] += 1
            source_types["none"] += 1
            continue
        sidecar_text = _sidecar_metadata_text(path)
        has_external = bool(sidecar_text.strip())
        matched = [
            keyword
            for keyword in INDUSTRY_KEYWORDS
            if keyword in sidecar_text
        ]
        status = classify_industry_availability(
            has_external_metadata=has_external,
            normalized_industry_ids=[] if not has_external else ["unknown"],
            metadata_conflict=False,
        )
        if has_external:
            status = "available_but_ambiguous" if len(set(matched)) != 1 else "confirmed"
        counts[status] += 1
        source_types["sidecar_metadata" if has_external else "none"] += 1
        doc_audit.append(
            {
                "source_document_ref": ref,
                "holdout_signature_count": sum(
                    1
                    for member in v1_manifest["signature_ids"]
                    if ref in member_refs_for_signature(
                        args.holdout_v1_dir,
                        member,
                    )
                ),
                "industry_metadata_available": has_external,
                "source_type": "sidecar_metadata" if has_external else "none",
                "raw_declared_industry_available": has_external,
                "normalized_industry_id": "unknown" if has_external else "",
                "normalization_confidence_status": "unavailable" if not has_external else "ambiguous",
                "source_provenance": (
                    "sidecar metadata scan (external ground context only)"
                ),
                "determined_before_system_prediction": True,
                "ambiguity": bool(matched) and len(set(matched)) != 1,
                "conflict": False,
                "status": status,
            }
        )

    summary = {
        "holdout_documents_total": len(source_refs),
        **counts,
        "source_provenance_types": source_types,
        "relation_denominator_eligible": counts["confirmed"],
    }

    decision = {
        "decision": "split_required_relation_blocked",
        "reason": (
            "pristine source documents have no external declared industry "
            "metadata; relation gold cannot be produced without guessing industry"
        ),
        "concept_holdout": "ready",
        "relation_holdout": "blocked",
        "relation_blocker": "insufficient_confirmed_industry_context",
    }

    superseded = {
        "holdout_version": "production-holdout-v1",
        "superseded_before_human_labeling": True,
        "reason": "relation context unavailable",
        "human_decisions": 0,
        "replacement": "production-concept-holdout-v1 + production-relation-holdout-v1",
    }

    concept_payload = {
        "holdout_version": "production-concept-holdout-v1",
        "membership_count": len(v1_manifest["signature_ids"]),
        "source_document_count": len(source_refs),
        "signature_ids": v1_manifest["signature_ids"],
        "source_document_refs": source_refs,
        "industry_context_required": False,
    }
    relation_payload = {
        "holdout_version": "production-relation-holdout-v1",
        "membership_count": 0,
        "source_document_count": 0,
        "signature_ids": [],
        "source_document_refs": [],
        "industry_context_required": True,
        "blocked": True,
        "blocker": "insufficient_confirmed_industry_context",
    }
    final_manifest = {
        "fitness_decision": decision,
        "concept_holdout": {
            **concept_payload,
            "checksum": holdout_manifest_checksum(concept_payload),
        },
        "relation_holdout": {
            **relation_payload,
            "checksum": holdout_manifest_checksum(relation_payload),
        },
        "independence_level": v1_manifest["independence_level"],
        "independence_note": v1_manifest["independence_note"],
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)

    def write(name: str, value: Any) -> None:
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write("industry_context_source_audit.json", {"sources": source_types})
    write("industry_context_document_audit.json", doc_audit)
    write("industry_availability_summary.json", summary)
    write("holdout_fitness_decision.json", decision)
    write("superseded_holdout_v1.json", superseded)
    write("final_holdout_manifest.json", final_manifest)
    contamination = json.loads(
        (args.holdout_v1_dir / "holdout_contamination_audit.json").read_text(
            encoding="utf-8"
        )
    )
    write("final_holdout_contamination_audit.json", contamination)
    sampling = json.loads(
        (args.holdout_v1_dir / "holdout_sampling_report.json").read_text(
            encoding="utf-8"
        )
    )
    sampling["note"] = "concept-only; relation denominator not applicable"
    write("final_holdout_sampling_report.json", sampling)
    write(
        "human_review_protocol.json",
        {
            "version": "holdout-human-review-protocol-v1",
            "step1": "concept gold only (no industry context required)",
            "step2": "relation gold only for samples with confirmed industry context",
            "batch_size_recommendation": "25-30 per batch",
            "system_predictions_hidden": True,
            "knowledge_v1_run": 0,
            "ai_provider_call": 0,
        },
    )
    write("source_document_path_map.json", path_map)
    (args.output_dir / "gate_f1_1_report.md").write_text(
        _render_report(summary, decision, final_manifest, contamination),
        encoding="utf-8",
    )

    print("status=ok")
    print(json.dumps(summary, ensure_ascii=False))
    print(json.dumps(decision, ensure_ascii=False))
    print(f"output={args.output_dir}")
    return 0


def member_refs_for_signature(holdout_dir: Path, signature_id: str) -> set[str]:
    sampling = json.loads(
        (holdout_dir / "holdout_sampling_report.json").read_text(encoding="utf-8")
    )
    for item in sampling["membership"]:
        if item["signature_id"] == signature_id:
            return set(item["source_documents"])
    return set()


def _render_report(
    summary: dict,
    decision: dict,
    final_manifest: dict,
    contamination: dict,
) -> str:
    return "\n".join(
        [
            "# Gate F1.1 — Holdout Fitness Fix",
            "",
            f"- 生成时间：{datetime.now(timezone.utc).isoformat()}",
            "",
            "## Industry Context Audit",
            "",
            f"- documents total：{summary['holdout_documents_total']}",
            f"- confirmed：{summary['confirmed']}",
            f"- available_but_ambiguous：{summary['available_but_ambiguous']}",
            f"- unavailable：{summary['unavailable']}",
            f"- invalid_metadata：{summary['invalid_metadata']}",
            "",
            "## Fitness Decision",
            "",
            f"- decision：{decision['decision']}",
            f"- reason：{decision['reason']}",
            "",
            "## Final Holdout",
            "",
            f"- concept：{json.dumps(final_manifest['concept_holdout'], ensure_ascii=False)}",
            f"- relation：{json.dumps(final_manifest['relation_holdout'], ensure_ascii=False)}",
            "",
            "## Contamination",
            "",
            f"`{json.dumps(contamination, ensure_ascii=False)}`",
            "",
            "## Blindness",
            "",
            "- knowledge_v1 run=0；AI provider call=0；prediction exposure=0",
            "",
            "## Conclusion",
            "",
            "**BLOCKED for Relation Holdout**；Concept Holdout ready for Human Gold.",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
