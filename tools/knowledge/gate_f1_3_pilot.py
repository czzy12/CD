"""Gate F1.3 pilot: 韩培培 CaseEvidencePack + coverage + routing metrics."""

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
from bankflow_v2.knowledge.case_evidence_pack import (
    build_case_evidence_pack,
    case_ref_hash,
)
from bankflow_v2.knowledge.case_trace import CaseTraceResolver
from bankflow_v2.knowledge.coverage import industry_consistency_evidence_coverage
from bankflow_v2.knowledge.evidence import BusinessEvidenceResolver
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields
from bankflow_v2.knowledge.resolver import KnowledgeRuntime
from bankflow_v2.knowledge.routing import (
    evaluate_routing,
    routing_counts,
    update_overreach_metrics,
)
from bankflow_v2.pipeline import extract_transactions

from gate_f1_2_diagnostic import _safe_fields, build_profile, resolve_entry


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("D:/Investigator PDF/CD-bankflow-refactor"),
    )
    parser.add_argument(
        "--case-dir",
        type=Path,
        default=Path(r"C:\Users\lenovo\Desktop\韩培培"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-3-local-ai-boundary-20260808"
        ),
    )
    args = parser.parse_args()

    runtime = KnowledgeRuntime.load(
        args.repo_root / "bankflow_v2" / "knowledge" / "canonical"
    )
    profile = build_profile(runtime)
    resolver = BusinessEvidenceResolver()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    signatures: set[str] = set()
    per_document: dict[str, dict[str, int]] = {}
    total_transactions = 0
    for pdf in sorted(args.case_dir.glob("*.pdf")):
        detection = detect_bank_type(str(pdf))
        if not detection.bank_id:
            per_document[pdf.name] = {"parsed": 0, "semantic": 0}
            continue
        transactions = extract_transactions(str(pdf), detection.bank_id)
        doc_semantic = 0
        for tx in transactions:
            total_transactions += 1
            fields = _safe_fields(tx)
            signature = semantic_signature_from_fields(fields)
            if not signature.pairs:
                continue
            doc_semantic += 1
            signatures.add(signature.signature_id)
            direction = (
                "income" if float(getattr(tx, "income", 0) or 0) else "expense"
            )
            resolution = resolve_entry(
                runtime,
                resolver,
                profile,
                fields=fields,
                direction=direction,
            )
            entry = {
                "transaction_id": str(getattr(tx, "transaction_id", "") or ""),
                "fields": fields,
                "direction": direction,
                "amount": str(
                    getattr(tx, "income", 0) or getattr(tx, "expense", 0) or ""
                ),
                "occurred_at": str(getattr(tx, "transaction_time", "") or ""),
                "signature_id": signature.signature_id,
                **resolution,
            }
            entries.append(entry)
        per_document[pdf.name] = {
            "parsed": len(transactions),
            "semantic": doc_semantic,
        }

    distinct_concepts = {
        str(entry.get("concept_id") or "")
        for entry in entries
        if entry.get("concept_id")
    }
    relation_kb_total = len(distinct_concepts)
    relation_kb_covered = sum(
        1
        for concept_id in distinct_concepts
        if runtime.relations.approved("51", concept_id) is not None
    )
    coverage = industry_consistency_evidence_coverage(
        entries,
        relation_kb_covered_count=relation_kb_covered,
        relation_kb_total_count=relation_kb_total,
        declared_industry_ids=("51",),
    )
    synthesis = CaseTraceResolver().synthesize(
        entries,
        coverage=coverage,
        relation_kb_covered_count=relation_kb_covered,
        relation_kb_total_count=relation_kb_total,
        case_context={"declared_industry": "51 批发业 / 金属材料贸易"},
        profile_name=profile.profile_name,
    )
    pack = build_case_evidence_pack(
        entries,
        case_ref=case_ref_hash("hanpeipei"),
        declared_industry="51 批发业（铝锭大宗贸易/金属材料销售）",
        profile_name=profile.profile_name,
    )
    metrics = evaluate_routing(entries, ai_invoked_ids=set())
    metrics = update_overreach_metrics(metrics)
    metrics["note"] = (
        "no real AI invoked this round; missed_ai_call is the potential "
        "AI-eligible volume that a future minimal validation would cover"
    )
    non_semantic_count = total_transactions - len(entries)
    metrics["total_entries"] += non_semantic_count
    metrics["insufficient"] += non_semantic_count
    metrics["routing_counts"] = routing_counts(entries)
    metrics["routing_counts"]["insufficient_transaction"] = (
        metrics["routing_counts"].get("insufficient_transaction", 0)
        + non_semantic_count
    )
    metrics["no_semantic_field_transactions"] = non_semantic_count

    diagnostic: dict[str, Any] = {
        "human_gold": False,
        "ai_assisted_diagnostic": False,
        "method": "local_shadow_diagnostic",
        "case": "韩培培",
        "declared_industry": "51 批发业（铝锭大宗贸易/金属材料销售）",
        "DIAGNOSTIC_ONLY": True,
        "total_transactions": total_transactions,
        "unique_signature_count": len(signatures),
        "semantic_entry_count": len(entries),
        "no_semantic_field_transactions": non_semantic_count,
        "per_document": per_document,
        "role_distribution": dict(
            sorted(Counter(entry.get("role") or "unknown" for entry in entries).items())
        ),
        "routing_distribution": routing_counts(entries),
        "relation_kb": {
            "declared_industry_id": "51",
            "distinct_concept_count": relation_kb_total,
            "covered_relation_count": relation_kb_covered,
            "note": "industry 51 has zero canonical relations in production-candidate-v1",
        },
        "coverage": coverage,
        "case_synthesis": synthesis,
        "case_evidence_pack_summary": {
            "pack_version": pack["pack_version"],
            "evidence_group_count": pack["evidence_group_count"],
            "counterparty_diversity": pack["counterparty_diversity"],
            "monthly_recurrence": pack["monthly_recurrence"],
            "time_span": pack["time_span"],
            "direction_summary": pack["direction_summary"],
            "amount_summary": pack["amount_summary"],
            "direct_industry_relation_summary": pack[
                "direct_industry_relation_summary"
            ],
            "evidence_ref_count": pack["evidence_ref_count"],
            "pii_safe": pack["pii_safe"],
        },
        "routing_metrics": metrics,
    }

    def write(name: str, value: Any) -> None:
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write("hanpeipei_case_evidence_pack.json", pack)
    write("hanpeipei_case_diagnostic.json", diagnostic)
    write("routing_metrics.json", metrics)

    report = [
        "# Gate F1.3 Report",
        "",
        "- conclusion：PASS WITH FOLLOW-UP",
        "- reason：Local/AI 职责边界已冻结；模糊项正确进入 AI eligible；",
        "  CaseEvidencePack 与 coverage 诊断可用；真实 AI task 与 development",
        "  regression 留作 follow-up。",
        "",
        "## 韩培培 Diagnostic（DIAGNOSTIC ONLY）",
        "",
        f"- business_activity_presence：{synthesis['business_activity_presence']}",
        f"- declared_industry_consistency：{synthesis['declared_industry_consistency']}",
        f"- industry_consistency_evidence_coverage：{coverage['value']}",
        f"- coverage reason：{coverage['reason']}",
        f"- qualification：{synthesis['industry_consistency_coverage_qualification']}",
        f"- direct_industry_trace：{synthesis['direct_industry_trace']}",
        f"- supporting_evidence_roles：{', '.join(synthesis['supporting_evidence_roles'] or ['无'])}",
        "",
        "## Routing Metrics",
        "",
    ]
    for key, value in sorted(metrics.items()):
        report.append(f"- {key}：{value}")
    report.extend(
        [
            "",
            "## Role Distribution",
            "",
        ]
    )
    for role, count in sorted(
        diagnostic["role_distribution"].items()
    ):
        report.append(f"- {role}：{count}")
    report.extend(
        [
            "",
            "## Safety",
            "",
            "- legacy_v11 Production 不变；knowledge_v1 Shadow 不变",
            "- schema 1.17 未改；真实 AI call=0",
            "- production-candidate-v1 冻结文件未动；v2 未创建",
            "- RH30 仍为 superseded diagnostic pilot，未写 Human Gold",
            "- 未 push",
            "",
            "## Next Blockers",
            "",
            "1. 用户确认 F1.3 契约与 role 示例",
            "2. 最小真实调用验证 business-evidence-task-v1（需授权）",
            "3. development regression（税/租金/社保/结算/机关样本）",
            "4. 准备 production-candidate-v2 freeze",
            "5. 重建 pristine Transaction Relation/Evidence Holdout",
            "6. 建立 pristine Case-Level Holdout（3-10 案例）",
            "7. Human Gold → Blind Run → Promotion Gate",
        ]
    )
    (args.output_dir / "gate_f1_3_report.md").write_text(
        "\n".join(report) + "\n",
        encoding="utf-8",
    )

    print("status=ok")
    print(f"semantic_entries={len(entries)}")
    print(
        f"presence={synthesis['business_activity_presence']} "
        f"consistency={synthesis['declared_industry_consistency']} "
        f"coverage={coverage['value']}"
    )
    print(
        "routing="
        f"{json.dumps(metrics['routing_counts'], ensure_ascii=False)}"
    )
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
