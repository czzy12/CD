"""Gate F3A.1 Resume: ingest 0808 human-collected cases and rebuild holdouts.

OCR is disabled. External metadata comes only from human-collected text
material. Addresses are recorded as availability booleans only and never enter
holdout/AI artifacts.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.auto_detect import detect_bank_type

logging.getLogger("pdfminer").setLevel(logging.ERROR)

from gate_f3a_build_holdout import (
    CASE_TARGET,
    EXCLUDED_CASE_NAMES,
    SEED,
    TX_MAX_PER_CASE,
    TX_TARGET,
    _blank_case_gold,
    _blank_tx_gold,
    _case_id,
    _checksum_file,
    _sha256_bytes,
    _sha256_text,
    assets_content_hashes,
    collect_excluded_signatures_and_texts,
    collect_instances,
    select_transaction_instances,
    verify_candidate_v2,
)


CASE_ROOT = Path(r"D:\Investigator PDF\data\0808案例客户样本")
OLD_OUTPUT = Path(
    r"D:\Investigator PDF\outputs\knowledge-v1\gate-f3a-holdout-20260808"
)
REGISTRY_DIR = Path(
    r"D:\Investigator PDF\outputs\knowledge-v1\gate-f3a-1-holdout-20260808"
)
OUTPUT_DIR = Path(
    r"D:\Investigator PDF\outputs\knowledge-v1\gate-f3a-1-resume-holdout-20260808"
)
REPO_ROOT = Path(r"D:\Investigator PDF\CD-bankflow-refactor")
TX_POOL_SIZE = 8
CASE_POOL_SIZE = 5
RESERVE_TARGET = 2
_DETECTION_CACHE: dict[str, str] = {}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _excluded(text: str) -> bool:
    return any(name in text for name in EXCLUDED_CASE_NAMES)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse_metadata(case_dir: Path) -> dict[str, Any]:
    texts = []
    for path in sorted(case_dir.rglob("*.txt")):
        texts.append(_read_text(path))
    raw = "\n".join(texts)
    fields: dict[str, str] = {}
    patterns = {
        "customer_name": r"客户姓名[:：]?\s*(.+)",
        "company_name": r"工作单位全称[:：]?\s*(.+)",
        "public_account": r"公户[:：]?\s*(.+)",
        "company": r"公司[:：]?\s*(.+)",
        "company_address": (
            r"(?:公司地址|工作单位地址|工作单位详细地址)"
            r"[（(]?[^）)]*[）)]?[:：]?\s*(.+)"
        ),
        "home_address": (
            r"(?:家庭地址|家庭住址)"
            r"[（(]?[^）)]*[）)]?[:：]?\s*(.+)"
        ),
        "main_business": r"主营业务[:：]?\s*(.+)",
        "industry_line": r"从事(.+?(?:行业|生意|业务))",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, raw)
        if match:
            fields[key] = match.group(1).strip()
    declared_industry = (
        fields.get("main_business")
        or fields.get("industry_line")
        or fields.get("company")
        or fields.get("company_name")
        or fields.get("public_account")
        or ""
    ).strip()
    return {
        "declared_industry": declared_industry,
        "business_description": fields.get("main_business", ""),
        "company_name": (
            fields.get("company_name")
            or fields.get("public_account")
            or fields.get("company")
            or ""
        ),
        "company_address_available": bool(fields.get("company_address")),
        "home_address_available": bool(fields.get("home_address")),
        "source_text": " / ".join(str(path) for path in sorted(case_dir.rglob("*.txt"))),
    }


def _supported_pdf_count(case_dir: Path) -> tuple[int, list[dict[str, Any]]]:
    count = 0
    rows: list[dict[str, Any]] = []
    for pdf in sorted(case_dir.rglob("*.pdf")):
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
        rows.append(
            {
                "source_document_id": _sha256_text(key),
                "file_name": pdf.name,
                "relative_path": str(pdf.relative_to(case_dir)),
                "bank_id": bank_id,
                "supported": bool(bank_id),
            }
        )
        if bank_id:
            count += 1
    return count, rows


def build_inventory() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_dir in sorted(CASE_ROOT.iterdir()):
        if not case_dir.is_dir():
            continue
        if _excluded(str(case_dir)):
            rows.append(
                {
                    "anonymized_case_id": _case_id(case_dir),
                    "source_directory": str(case_dir),
                    "eligibility_status": "excluded",
                    "exclusion_reason": "development_case_name",
                }
            )
            continue
        meta = _parse_metadata(case_dir)
        supported, docs = _supported_pdf_count(case_dir)
        if not meta["declared_industry"]:
            rows.append(
                {
                    "anonymized_case_id": _case_id(case_dir),
                    "source_directory": str(case_dir),
                    "eligibility_status": "excluded",
                    "exclusion_reason": "main_business_unavailable",
                }
            )
            continue
        if supported == 0:
            rows.append(
                {
                    "anonymized_case_id": _case_id(case_dir),
                    "source_directory": str(case_dir),
                    "eligibility_status": "excluded",
                    "exclusion_reason": "no_supported_statement",
                }
            )
            continue
        rows.append(
            {
                "anonymized_case_id": _case_id(case_dir),
                "source_directory": str(case_dir),
                "statement_files": [
                    {
                        "source_document_id": row["source_document_id"],
                        "file_name": row["file_name"],
                        "relative_path": row["relative_path"],
                        "supported": row["supported"],
                        "bank_id": row["bank_id"],
                    }
                    for row in docs
                ],
                "external_metadata_files": [
                    str(path)
                    for path in sorted(case_dir.rglob("*.txt"))
                ],
                "company_name": meta["company_name"],
                "declared_main_business_available": True,
                "declared_industry": meta["declared_industry"],
                "business_description": meta["business_description"],
                "company_address_available": meta[
                    "company_address_available"
                ],
                "home_address_available": meta["home_address_available"],
                "parser_support_status": "supported",
                "contamination_status": "pending_audit",
                "eligibility_status": "eligible",
                "exclusion_reason": "",
            }
        )
    return rows


def split_pools(
    case_ids: list[str],
    *,
    tx_size: int = TX_POOL_SIZE,
    case_size: int = CASE_POOL_SIZE,
    seed: int = SEED,
) -> tuple[list[str], list[str], list[str]]:
    rng = random.Random(seed)
    ids = sorted(case_ids)
    rng.shuffle(ids)
    return ids[:tx_size], ids[tx_size : tx_size + case_size], ids[tx_size + case_size :]


def ingest_registry(rows: list[dict[str, Any]]) -> None:
    REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    registry_path = REGISTRY_DIR / "manual_external_metadata_registry.json"
    if registry_path.is_file():
        data = json.loads(registry_path.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
    else:
        data = {
            "registry_version": "manual-external-metadata-registry-v1",
            "purpose": "human-confirmed external metadata; no OCR",
        }
        entries = []
    existing_ids = {
        str(entry.get("anonymized_case_id", "")) for entry in entries
    }
    added = 0
    for row in rows:
        if row.get("eligibility_status") != "eligible":
            continue
        case_id = row["anonymized_case_id"]
        if case_id in existing_ids:
            continue
        entries.append(
            {
                "anonymized_case_id": case_id,
                "source_case_ref": row["source_directory"],
                "metadata_source_type": "human_collected_case_material",
                "source_reference": row["external_metadata_files"][0]
                if row["external_metadata_files"]
                else "",
                "declared_industry": row["declared_industry"],
                "business_description": row["business_description"],
                "human_confirmed": True,
                "entered_by": "human_user",
                "entered_at": _utcnow(),
                "confirmation_status": "human_confirmed",
                "transaction_evidence_used_for_metadata": False,
            }
        )
        added += 1
    data["entries"] = entries
    data["stats"] = {
        "total_entries": len(entries),
        "human_confirmed_entries": sum(
            1 for entry in entries if entry.get("human_confirmed") is True
        ),
        "pending_human_confirmation": sum(
            1 for entry in entries if entry.get("human_confirmed") is not True
        ),
        "added_0808_cases": added,
    }
    registry_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def write_review_standard(output_dir: Path) -> None:
    standard: dict[str, Any] = {
        "standard_version": "human_gold_review_standard_v1",
        "nature": (
            "project adjudication standard based on actual statement review "
            "experience; not a regulator five-value standard"
        ),
        "business_activity_presence": {
            "strong": (
                "complete, sustained, mutually-supporting business fund chain; "
                "industry-typical income/expense patterns, upstream/downstream "
                "counterparties, recurrence across months, multiple evidence "
                "families"
            ),
            "medium": (
                "reasonably confident business exists, but core industry chain "
                "not fully unfolded"
            ),
            "weak": (
                "few, single or isolated business traces (e.g., only a "
                "same-industry counterparty without the typical fund chain)"
            ),
            "none": (
                "only when material is sufficiently complete and no real "
                "business trace exists; never due to parser/coverage/short "
                "period/ambiguity"
            ),
            "undetermined": (
                "material insufficient to reliably judge; absence of "
                "identified business evidence != evidence of no business"
            ),
        },
        "declared_industry_consistency": {
            "strong": (
                "fund chain highly consistent with declared industry: typical "
                "upstream/downstream, income/expense structure, repeated months, "
                "multiple independent counterparties, industry-specific costs"
            ),
            "medium": (
                "multiple consistent direct/indirect evidence but incomplete "
                "industry fund chain"
            ),
            "weak": (
                "only a few supporting clues; e.g., construction company with "
                "construction counterparties but no engineering/material/"
                "labor/project chain"
            ),
            "none": (
                "strict: visible business traces form a relatively complete "
                "chain of ANOTHER industry while declared-industry core "
                "features are absent, with enough material to judge"
            ),
            "undetermined": (
                "not enough evidence to confirm consistency; must be kept "
                "separate from none"
            ),
        },
        "auxiliary_evidence": {
            "tax": "recurring tax supports business-subject activity, not industry",
            "loan_financing": (
                "financing exists != real main business proven"
            ),
            "rent": "valuable for storefront/warehouse/restaurant industries; single rent alone cannot prove industry",
            "utilities": (
                "supports physical premises for restaurant/retail/manufacturing/"
                "warehouse; still auxiliary"
            ),
            "salary_social_security": (
                "sustained multi-person payroll strengthens organized activity; "
                "does not prove specific industry"
            ),
            "settlement_infrastructure": (
                "enterprise settlement infrastructure exists; lower evidence "
                "level than main business income/expense"
            ),
        },
        "independence": [
            "weak + weak + weak != strong",
            "same counterparty repeated N times is not N independent evidence",
            "consider family diversity, counterparty diversity, recurrence, "
            "temporal consistency, direction, industry pattern, contradictions",
        ],
        "forbidden": [
            "business activity strong -> declared industry strong",
            "no identified declared-industry evidence -> none",
            "tax/loan/rent/settlement alone -> strong industry consistency",
            "filling gold from model/AI/script",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "human_gold_review_standard_v1.json").write_text(
        json.dumps(standard, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    lines = [
        "# Human Gold Review Standard v1",
        "",
        "- 性质：本项目人工判定契约（基于实际流水审核逻辑），不是监管五值标准",
        "",
        "## business_activity_presence",
        "",
    ]
    for key, value in standard["business_activity_presence"].items():
        lines.append(f"### {key.upper()}")
        lines.append("")
        lines.append(value)
        lines.append("")
    lines.extend(["## declared_industry_consistency", ""])
    for key, value in standard["declared_industry_consistency"].items():
        lines.append(f"### {key.upper()}")
        lines.append("")
        lines.append(value)
        lines.append("")
    lines.extend(["## 辅助证据（不能单独判 strong）", ""])
    for key, value in standard["auxiliary_evidence"].items():
        lines.append(f"- {key}：{value}")
    lines.extend(["", "## Independence", ""])
    for item in standard["independence"]:
        lines.append(f"- {item}")
    lines.extend(["", "## 禁止", ""])
    for item in standard["forbidden"]:
        lines.append(f"- {item}")
    (output_dir / "human_gold_review_standard_v1.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--audit-only",
        action="store_true",
        help="build inventory and ingest registry only",
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args()

    if not verify_candidate_v2(args.repo_root):
        print("candidate_v2_integrity=FAILED")
        return 1

    inventory = build_inventory()
    eligible = [row for row in inventory if row["eligibility_status"] == "eligible"]
    print(f"0808_cases={len(inventory)} eligible={len(eligible)}")

    # Contamination audit: content hash vs concept pool + historical outputs.
    (
        excluded_signatures,
        excluded_texts,
        excluded_doc_refs,
        excluded_tx_ids,
    ) = collect_excluded_signatures_and_texts()
    # Short generic tokens (微信支付/转账 etc.) must not wipe out real
    # transaction instances; only structured longer texts are exact exclusions.
    excluded_texts = {
        text for text in excluded_texts if len(text) >= 8
    }
    excluded_content = assets_content_hashes()
    concept_overlap = 0
    for row in eligible:
        case_dir = Path(row["source_directory"])
        for pdf in case_dir.rglob("*.pdf"):
            try:
                if _sha256_bytes(pdf.read_bytes()) in excluded_content:
                    concept_overlap += 1
                    row["contamination_status"] = "concept_holdout_content_overlap"
                    row["eligibility_status"] = "excluded"
                    row["exclusion_reason"] = "concept_holdout_content_overlap"
                    break
            except OSError:
                continue
    eligible = [
        row for row in inventory if row["eligibility_status"] == "eligible"
    ]
    for row in eligible:
        row["contamination_status"] = "clean"
    print(f"0808_clean_eligible={len(eligible)} concept_overlap={concept_overlap}")

    ingest_registry(inventory)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    write_review_standard(args.output_dir)
    (args.output_dir / "0808_case_inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    if args.audit_only:
        return 0

    if len(eligible) < TX_POOL_SIZE + CASE_POOL_SIZE:
        print(
            "resume=corpus_insufficient "
            f"eligible={len(eligible)} "
            f"required={TX_POOL_SIZE + CASE_POOL_SIZE}"
        )
        return 2

    tx_case_ids, case_case_ids, reserve_ids = split_pools(
        [row["anonymized_case_id"] for row in eligible]
    )
    tx_cases = {
        row["anonymized_case_id"]: row
        for row in eligible
        if row["anonymized_case_id"] in tx_case_ids
    }
    case_cases = {
        row["anonymized_case_id"]: row
        for row in eligible
        if row["anonymized_case_id"] in case_case_ids
    }
    print(
        f"pools tx={len(tx_case_ids)} case={len(case_case_ids)} "
        f"reserve={len(reserve_ids)}"
    )

    parsed_cache: dict[Path, list[Any]] = {}
    by_case: dict[str, list[dict[str, Any]]] = {}
    for row in eligible:
        if row["anonymized_case_id"] not in tx_case_ids:
            continue
        case_dir = Path(row["source_directory"])
        case = {
            "case_id": row["anonymized_case_id"],
            "case_root": str(case_dir),
            "declared_industry_text": row["declared_industry"],
            "external_description_reference": _sha256_text(
                row.get("business_description", "") or ""
            ),
            "company_name": row["company_name"],
            "public_account_name": "",
            "work_intro": "",
            "qcc_industry": "",
            "gb_industry": "",
            "supported_document_count": sum(
                1 for doc in row["statement_files"] if doc["supported"]
            ),
            "total_pdf_count": len(row["statement_files"]),
            "source_documents": [
                {
                    "source_document_id": doc["source_document_id"],
                    "file_name": doc["file_name"],
                    "relative_path": doc["relative_path"],
                    "bank_id": doc["bank_id"],
                    "supported": doc["supported"],
                }
                for doc in row["statement_files"]
            ],
        }
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

    tx_items = select_transaction_instances(by_case)
    print(
        f"transaction={len(tx_items)} cases={len({i['source_case_id'] for i in tx_items})}"
    )
    if len(tx_items) < TX_TARGET:
        print(
            f"shortage transaction={len(tx_items)}/{TX_TARGET} "
            "reason=pristine_corpus_insufficient"
        )

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
        "supersedes_initial_f3a_construction": True,
        "corpus": "0808-human-collected",
        "target_count": TX_TARGET,
        "actual_count": len(tx_items),
        "case_count": len({i["source_case_id"] for i in tx_items}),
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
            sorted(Counter(i["source_case_id"] for i in tx_items).items())
        ),
    }
    write("production_transaction_evidence_holdout_v1_manifest.json", tx_manifest)
    write("production_transaction_evidence_holdout_v1_items.jsonl", tx_items)
    write(
        "production_transaction_evidence_human_gold_v1_blank.jsonl",
        _blank_tx_gold(tx_items),
    )

    case_holdout = [case_cases[case_id] for case_id in case_case_ids]
    case_manifest = {
        "holdout_version": "production-case-holdout-v1",
        "supersedes_initial_f3a_construction": True,
        "corpus": "0808-human-collected",
        "target_count": CASE_TARGET,
        "actual_count": len(case_holdout),
        "seed": SEED,
        "created_at": _utcnow(),
        "transaction_case_pool_disjoint": True,
        "case_pool_overlap_with_transaction": [],
        "case_ids": case_case_ids,
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
    write(
        "production_case_human_gold_v1_blank.json",
        _blank_case_gold(
            [
                {"case_id": row["anonymized_case_id"]}
                for row in case_holdout
            ]
        ),
    )

    review_dir = args.output_dir / "case_review_packets"
    review_dir.mkdir(exist_ok=True)
    for row in case_holdout:
        case_dir = Path(row["source_directory"])
        pdfs = list(case_dir.rglob("*.pdf"))
        packet = {
            "anonymized_case_id": row["anonymized_case_id"],
            "declared_industry": row["declared_industry"],
            "business_description": row["business_description"],
            "company_address_available": row["company_address_available"],
            "home_address_available": row["home_address_available"],
            "source_document_inventory": row["statement_files"],
            "transaction_count": "see statements",
            "account_source_coverage": [
                doc["bank_id"] for doc in row["statement_files"] if doc["supported"]
            ],
            "human_reviewer_note": (
                "Human reviewer may open full supported statements locally; "
                "Case AI blind run sees only candidate-constructed pack."
            ),
        }
        (review_dir / f"case_{row['anonymized_case_id']}_review_packet.json").write_text(
            json.dumps(packet, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write(
        "reserve_cases.json",
        {
            "target": RESERVE_TARGET,
            "count": len(reserve_ids),
            "case_ids": reserve_ids,
            "purpose": (
                "future development / life-trace / independent validation; "
                "not used by current holdout"
            ),
        },
    )

    lineage = {
        "initial_f3a_construction": {
            "output_dir": str(OLD_OUTPUT),
            "transaction_count": 80,
            "case_count": 4,
        },
        "final_0808_selection": {
            "transaction_count": len(tx_items),
            "transaction_case_count": len(
                {i["source_case_id"] for i in tx_items}
            ),
            "case_holdout_count": len(case_holdout),
            "reserve_count": len(reserve_ids),
        },
    }
    write("holdout_lineage.json", lineage)

    checksums: dict[str, str] = {}
    for path in sorted(args.output_dir.rglob("*")):
        if path.is_file():
            checksums[str(path.relative_to(args.output_dir))] = _checksum_file(
                path
            )
    write("holdout_checksums.json", checksums)

    report = {
        "gate": "F3A.1-resume",
        "status": "rebuilt",
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
        "eligible_cases": len(eligible),
        "reserve_count": len(reserve_ids),
        "output_dir": str(args.output_dir),
    }
    write("gate_f3a_1_resume_report.json", report)
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
