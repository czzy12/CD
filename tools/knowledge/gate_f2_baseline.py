"""Gate F2: deterministic development baseline for prediction drift checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge.case_evidence_pack import build_case_evidence_pack
from bankflow_v2.knowledge.coverage import industry_consistency_evidence_coverage
from bankflow_v2.knowledge.evidence import BusinessEvidenceResolver
from bankflow_v2.knowledge.freeze import manifest_checksum
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.resolver import KnowledgeRuntime


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _stable(item)
            for key, item in sorted(value.items())
            if key not in {"generated_at", "created_at", "reviewed_at"}
        }
    if isinstance(value, list):
        return [_stable(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("D:/Investigator PDF/CD-bankflow-refactor"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "production-candidate-v2-freeze-20260808"
        ),
    )
    args = parser.parse_args()
    runtime = KnowledgeRuntime.load(
        args.repo_root / "bankflow_v2" / "knowledge" / "canonical"
    )
    profile51 = IndustryProfile(
        primary_industry_ids=("51",),
        normalized_products_services=("铝锭大宗贸易", "金属材料销售"),
        profile_name="baseline-51-wholesale",
    )
    profile_bm = IndustryProfile(
        primary_industry_ids=("internal.building_material_trade",),
        profile_name="baseline-building-material",
    )
    resolver = BusinessEvidenceResolver()

    concept_rows: list[dict[str, Any]] = []
    for label, fields in {
        "goods_payment": {"summary": "铝锭货款"},
        "tax": {"summary": "增值税缴税"},
        "personal": {"merchant_name": "黄家龙虾", "summary": "消费"},
        "rail": {"summary": "财付通"},
    }.items():
        semantic = runtime.semantic_resolver.resolve(fields)
        concept_rows.append(
            {
                "label": label,
                "fields": fields,
                "concept_id": semantic.concept_id,
                "concept_source": semantic.source,
            }
        )

    relation_rows: list[dict[str, Any]] = []
    for industry_id, profile, concept_id in [
        ("internal.building_material_trade", profile_bm, "goods_payment"),
        ("51", profile51, "goods_payment"),
    ]:
        relation = runtime.relation_resolver.resolve(
            industry_id=industry_id,
            concept_id=concept_id,
            profile=profile,
        )
        relation_rows.append(
            {
                "industry_id": industry_id,
                "concept_id": concept_id,
                "relevance": relation.relevance,
                "source": relation.relation_source,
            }
        )

    evidence_rows: list[dict[str, Any]] = []
    for label, fields, kwargs in [
        ("tax", {"summary": "增值税缴税"}, {}),
        ("salary", {"summary": "代发工资"}, {}),
        ("settlement", {"summary": "企业结算卡年费"}, {}),
        ("service_fee", {"summary": "项目服务费"}, {}),
        ("loan", {"summary": "借款"}, {}),
        ("company_name", {"counterparty_name": "某某贸易有限公司"}, {}),
        ("merchant_context", {"merchant_name": "某建材批发市场"}, {"profile": profile51}),
        ("payment_rail", {"summary": "财付通"}, {}),
    ]:
        result = resolver.resolve(fields, **kwargs)
        evidence_rows.append(
            {
                "label": label,
                "fields": fields,
                "role": result["role"],
                "trace_strength": result["trace_strength"],
                "routing_state": result["routing_state"],
                "unresolved_reason": result["unresolved_reason"],
            }
        )

    pack_entries = [
        {
            "transaction_id": "tx-1",
            "role": "direct_business",
            "trace_strength": "strong",
            "routing_state": "local_resolved",
            "industry_relevance": "undetermined",
            "direction": "expense",
            "amount": "1000",
            "occurred_at": "2026-01-15",
            "evidence_group_key": "direct_business|goods_payment",
            "fields": {"summary": "铝锭货款"},
        },
        {
            "transaction_id": "tx-2",
            "role": "tax_regulatory",
            "trace_strength": "medium",
            "routing_state": "local_resolved",
            "industry_relevance": "undetermined",
            "direction": "expense",
            "amount": "500",
            "occurred_at": "2026-02-10",
            "evidence_group_key": "tax_regulatory|tax",
            "fields": {"summary": "增值税"},
        },
    ]
    pack = build_case_evidence_pack(
        pack_entries,
        case_ref="baseline",
        declared_industry="51 批发业",
        total_transaction_count=3,
        insufficient_transaction_count=1,
    )
    coverage = industry_consistency_evidence_coverage(
        pack_entries,
        relation_kb_covered_count=0,
        relation_kb_total_count=1,
    )

    baseline: dict[str, Any] = {
        "baseline_version": "development-baseline-v1",
        "purpose": (
            "deterministic local development baseline; AI remote responses "
            "are not part of byte-for-byte drift checks"
        ),
        "concept": concept_rows,
        "relation": relation_rows,
        "business_evidence_local": evidence_rows,
        "coverage": coverage,
        "case_evidence_pack": _stable(pack),
    }
    checksum = manifest_checksum(_stable(baseline))
    baseline["baseline_checksum"] = checksum

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "development_baseline.json").write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("status=ok")
    print(f"baseline_checksum={checksum}")
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
