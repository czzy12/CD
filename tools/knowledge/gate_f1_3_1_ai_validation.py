"""Gate F1.3.1: minimal real AI validation (transaction + case contracts).

Fail-visible: any privacy block, provider failure, or output contract
violation exits non-zero. No fallback to local final on failure.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.deepseek_adapter import load_deepseek_settings
from bankflow_v2.knowledge.ai_contracts import (
    call_case_synthesis_ai,
    call_transaction_evidence_ai,
    persist_transaction_evidence_candidates,
)
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.repository import RuntimeKnowledgeRepository
from bankflow_v2.knowledge.resolver import KnowledgeRuntime


REPO_ROOT = Path("D:/Investigator PDF/CD-bankflow-refactor")


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _development_transaction_items(runtime: KnowledgeRuntime) -> list[dict[str, Any]]:
    profile = IndustryProfile(
        primary_industry_ids=("51",),
        normalized_products_services=(
            "铝锭大宗贸易",
            "金属材料销售",
        ),
        profile_name="dev-51-wholesale",
    )
    samples = [
        ("dev-service-fee", {"summary": "项目服务费"}, "expense"),
        ("dev-loan-ambiguous", {"summary": "借款"}, "expense"),
        (
            "dev-government-ambiguous",
            {"counterparty_name": "XX市财政局", "summary": "往来款"},
            "expense",
        ),
        ("dev-company-name-only", {"counterparty_name": "某某贸易有限公司"}, "expense"),
        (
            "dev-context-merchant",
            {"merchant_name": "某建材批发市场"},
            "expense",
        ),
        ("dev-operating-ambiguous", {"summary": "设备维修"}, "expense"),
    ]
    items: list[dict[str, Any]] = []
    for item_id, fields, direction in samples:
        semantic = runtime.semantic_resolver.resolve(fields)
        items.append(
            {
                "item_id": item_id,
                "fields": fields,
                "direction": direction,
                "semantic_concept": str(semantic.concept_id or ""),
                "declared_industry": "51 批发业",
            }
        )
    return items


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_transaction_validation(
    *,
    output_dir: Path,
    cache_root: Path,
) -> int:
    settings = load_deepseek_settings()
    runtime = KnowledgeRuntime.load(REPO_ROOT / "bankflow_v2" / "knowledge" / "canonical")
    items = _development_transaction_items(runtime)
    _write_json(output_dir / "transaction_sanitized_input.json", items)

    try:
        result = call_transaction_evidence_ai(settings, items)
    except Exception as exc:  # fail-visible
        _write_json(
            output_dir / "transaction_provider_error.json",
            {
                "status": "failed_closed",
                "error": str(exc),
                "timestamp": _utcnow(),
            },
        )
        print(f"transaction_ai=failed_closed error={exc}")
        return 1

    if result["failure_count"] or result["outbound_pii"]:
        _write_json(output_dir / "transaction_provider_result.json", result)
        print(
            "transaction_ai=contract_failure "
            f"failures={result['failure_count']} pii={result['outbound_pii']}"
        )
        return 1

    repository = RuntimeKnowledgeRepository(cache_root)
    candidates = persist_transaction_evidence_candidates(
        repository,
        result,
        model=settings.model,
    )
    repository.close()
    candidate_status = {
        "lifecycle": "transaction_ai_knowledge_candidate_lifecycle",
        "review_status": "pending",
        "self_approve": False,
        "canonical_written": False,
        "candidates": candidates,
        "candidate_count": len(candidates),
    }
    _write_json(output_dir / "transaction_provider_result.json", result)
    _write_json(output_dir / "transaction_candidate_status.json", candidate_status)
    report = [
        "# Transaction Evidence AI Validation（Gate F1.3.1）",
        "",
        f"- provider：deepseek",
        f"- model：{settings.model}",
        f"- prompt_version：business-evidence-task-v1",
        f"- sent items：{result['sent_item_count']}",
        f"- accepted：{result['accepted_count']}",
        f"- failures：{result['failure_count']}",
        f"- outbound PII：{result['outbound_pii']}",
        f"- candidate status：pending（{len(candidates)}）",
        f"- lifecycle：{candidate_status['lifecycle']}",
        "",
        "## Accepted",
        "",
    ]
    for item in result["accepted"]:
        report.append(
            f"- {item['item_id']}: role={item['role']} "
            f"trace={item['trace_strength']} confidence={item['confidence']}"
        )
    (output_dir / "transaction_ai_validation_report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )
    print(
        "transaction_ai=ok "
        f"accepted={result['accepted_count']} "
        f"candidates_pending={len(candidates)}"
    )
    return 0


def run_case_validation(
    *,
    output_dir: Path,
    pack_path: Path,
    diagnostic_path: Path,
) -> int:
    settings = load_deepseek_settings()
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    coverage = diagnostic.get("coverage", {})
    _write_json(output_dir / "case_input_pack_summary.json", {
        "pack_version": pack.get("pack_version"),
        "evidence_group_count": pack.get("evidence_group_count"),
        "evidence_ref_count": pack.get("evidence_ref_count"),
        "evidence_availability": pack.get("evidence_availability"),
        "coverage": coverage,
        "full_raw_statement_sent": False,
        "sent_structure": "compressed CaseEvidencePack",
    })
    try:
        result = call_case_synthesis_ai(
            settings,
            pack,
            coverage=coverage,
        )
    except Exception as exc:  # fail-visible
        _write_json(
            output_dir / "case_provider_error.json",
            {
                "status": "failed_closed",
                "error": str(exc),
                "timestamp": _utcnow(),
            },
        )
        print(f"case_ai=failed_closed error={exc}")
        return 1
    _write_json(output_dir / "case_observation.json", result.get("observation", {}))
    _write_json(output_dir / "case_validation_result.json", result)
    if not result["validated"]:
        print(
            "case_ai=contract_failure "
            f"failures={result['validation_failures']}"
        )
        return 1
    report = [
        "# Case AI Validation（Gate F1.3.1）",
        "",
        f"- provider：deepseek",
        f"- model：{settings.model}",
        f"- prompt_version：case-synthesis-task-v1",
        f"- lifecycle：case_observation_only",
        f"- knowledge_candidate_created：{result['knowledge_candidate_created']}",
        f"- canonical_written：{result['canonical_written']}",
        f"- validation failures：{result['validation_failures']}",
        "",
        "## CaseObservation",
        "",
    ]
    observation = result.get("observation", {})
    for key in (
        "business_activity_presence",
        "declared_industry_consistency",
        "industry_consistency_evidence_coverage",
        "reasoning_summary",
        "uncertainty_reason",
    ):
        report.append(f"- {key}：{observation.get(key, '')}")
    (output_dir / "case_ai_validation_report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )
    print(
        "case_ai=ok "
        f"presence={observation.get('business_activity_presence')} "
        f"consistency={observation.get('declared_industry_consistency')} "
        f"coverage={observation.get('industry_consistency_evidence_coverage')}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["transaction", "case", "both"], default="both")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-3-1-ai-validation-20260808"
        ),
    )
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-3-1-ai-validation-20260808/cache"
        ),
    )
    parser.add_argument(
        "--case-evidence-pack",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-3-local-ai-boundary-20260808/"
            "hanpeipei_case_evidence_pack.json"
        ),
    )
    parser.add_argument(
        "--case-diagnostic",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-3-local-ai-boundary-20260808/"
            "hanpeipei_case_diagnostic.json"
        ),
    )
    parser.add_argument(
        "--confirm-real-data",
        action="store_true",
        required=True,
        help="explicit confirmation required for real provider calls",
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    code = 0
    if args.mode in {"transaction", "both"}:
        code |= run_transaction_validation(
            output_dir=args.output_dir,
            cache_root=args.cache_root,
        )
    if args.mode in {"case", "both"}:
        code |= run_case_validation(
            output_dir=args.output_dir,
            pack_path=args.case_evidence_pack,
            diagnostic_path=args.case_diagnostic,
        )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
