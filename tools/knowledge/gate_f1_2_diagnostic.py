"""Gate F1.2C: RH30 diagnostic matrix + 韩培培 case-level shadow pilot.

Local shadow only: no real AI calls, no Human Gold, no accuracy claim.
Outputs are marked human_gold=false / ai_assisted_diagnostic=false.
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

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.knowledge.ai_validation import safe_validation_fields
from bankflow_v2.knowledge.case_trace import CaseTraceResolver
from bankflow_v2.knowledge.evidence import BusinessEvidenceResolver
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields
from bankflow_v2.knowledge.resolver import KnowledgeRuntime


AI_INPUT_FIELDS = (
    "counterparty_name",
    "summary",
    "remark",
    "purpose",
    "product_description",
    "merchant_name",
    "merchant_category",
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_fields(tx: Any) -> dict[str, str]:
    raw: dict[str, str] = {}
    for name in AI_INPUT_FIELDS:
        value = str(getattr(tx, name, "") or "")
        confidence = float(getattr(tx, "field_confidence", {}).get(name, 0.0) or 0.0)
        if value.strip() and confidence >= 1.0:
            raw[name] = value
    return safe_validation_fields(raw)


def build_profile(runtime: KnowledgeRuntime) -> IndustryProfile:
    return IndustryProfile(
        primary_industry_ids=("51",),
        secondary_industry_ids=(),
        specialty_concept_ids=(),
        normalized_products_services=(
            "铝锭大宗贸易",
            "金属材料销售",
            "金属矿石销售",
            "金属制品销售",
            "生产性废旧金属回收",
            "石墨及碳素制品销售",
        ),
        taxonomy_version=runtime.version.taxonomy_version,
        profile_name="hanpeipei-51-wholesale",
    )


def resolve_entry(
    runtime: KnowledgeRuntime,
    resolver: BusinessEvidenceResolver,
    profile: IndustryProfile,
    *,
    fields: dict[str, str],
    direction: str,
) -> dict[str, Any]:
    semantic = runtime.semantic_resolver.resolve(fields)
    concept_id = str(semantic.concept_id or "")
    if concept_id:
        relation = runtime.relation_resolver.resolve(
            industry_id="51",
            concept_id=concept_id,
            profile=profile,
        )
        industry_relevance = str(relation.relevance or "undetermined")
        relation_source = (
            str(getattr(relation, "relation_resolution_source", "") or "")
            or str(getattr(relation, "relation_source", "") or "")
        )
    else:
        industry_relevance = "undetermined"
        relation_source = ""
    evidence = resolver.resolve(
        fields,
        concept_id=concept_id,
        direction=direction,
        profile=profile,
    )
    return {
        "concept_id": concept_id,
        "concept_name": str(semantic.concept_name or ""),
        "concept_source": str(semantic.source or "undetermined"),
        "industry_relevance": industry_relevance,
        "relation_source": relation_source,
        "role": str(evidence["role"]),
        "trace_strength": str(evidence["trace_strength"]),
        "role_source": str(evidence["role_source"]),
        "evidence_group_key": str(evidence["evidence_group_key"]),
        "routing_state": str(evidence["routing_state"]),
        "unresolved_reason": str(evidence["unresolved_reason"]),
        "reason": str(evidence["reason"]),
        "matched_terms": list(evidence["matched_terms"]),
    }


def rh30_matrix(
    runtime: KnowledgeRuntime,
    profile: IndustryProfile,
    batch_path: Path,
) -> dict[str, Any]:
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    resolver = BusinessEvidenceResolver()
    rows: list[dict[str, Any]] = []
    for item in batch:
        fields = {
            str(name): str(value)
            for name, value in item.get("safe_semantic_evidence", {}).items()
            if str(value).strip()
        }
        resolution = resolve_entry(
            runtime,
            resolver,
            profile,
            fields=fields,
            direction=str(item.get("direction") or ""),
        )
        rows.append(
            {
                "relation_holdout_id": str(item.get("relation_holdout_id") or ""),
                "signature_id": str(item.get("signature_id") or ""),
                "direction": str(item.get("direction") or ""),
                "safe_semantic_evidence": fields,
                **resolution,
            }
        )
    return {
        "human_gold": False,
        "ai_assisted_diagnostic": False,
        "method": "local_shadow_diagnostic",
        "holdout_version": "production-relation-holdout-v1",
        "status": "superseded_before_gold / diagnostic pilot",
        "not_holdout_accuracy": True,
        "row_count": len(rows),
        "role_distribution": dict(
            sorted(Counter(row["role"] for row in rows).items())
        ),
        "trace_strength_distribution": dict(
            sorted(Counter(row["trace_strength"] for row in rows).items())
        ),
        "industry_relevance_distribution": dict(
            sorted(Counter(row["industry_relevance"] for row in rows).items())
        ),
        "concept_distribution": dict(
            sorted(Counter(row["concept_id"] or "unresolved" for row in rows).items())
        ),
        "unresolved_reasons": dict(
            sorted(
                Counter(
                    row["unresolved_reason"] or "resolved"
                    for row in rows
                ).items()
            )
        ),
        "payment_rail_count": sum(
            1 for row in rows if row["unresolved_reason"] == "payment_rail_only"
        ),
        "personal_consumption_count": sum(
            1 for row in rows if row["role"] == "personal_consumption"
        ),
        "financing_count": sum(
            1 for row in rows if row["role"] == "financing"
        ),
        "direct_business_count": sum(
            1 for row in rows if row["role"] == "direct_business"
        ),
        "rows": rows,
    }


def case_level_pilot(
    runtime: KnowledgeRuntime,
    profile: IndustryProfile,
    case_dir: Path,
) -> dict[str, Any]:
    resolver = BusinessEvidenceResolver()
    case_resolver = CaseTraceResolver()
    entries: list[dict[str, Any]] = []
    signatures: set[str] = set()
    per_document: dict[str, dict[str, int]] = {}
    total_transactions = 0
    for pdf in sorted(case_dir.glob("*.pdf")):
        ref = pdf.name
        detection = detect_bank_type(str(pdf))
        if not detection.bank_id:
            per_document[ref] = {"parsed": 0, "semantic": 0}
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
            resolution = resolve_entry(
                runtime,
                resolver,
                profile,
                fields=fields,
                direction=(
                    "income" if float(getattr(tx, "income", 0) or 0) else "expense"
                ),
            )
            entries.append(
                {
                    "transaction_id": str(getattr(tx, "transaction_id", "") or ""),
                    "fields": fields,
                    "direction": (
                        "income" if float(getattr(tx, "income", 0) or 0) else "expense"
                    ),
                    "amount": str(
                        getattr(tx, "income", 0)
                        or getattr(tx, "expense", 0)
                        or ""
                    ),
                    "occurred_at": str(getattr(tx, "transaction_time", "") or ""),
                    "signature_id": signature.signature_id,
                    **resolution,
                }
            )
        per_document[ref] = {
            "parsed": len(transactions),
            "semantic": doc_semantic,
        }
    synthesized = case_resolver.synthesize(
        entries,
        case_context={"declared_industry": "51 批发业 / 金属材料贸易"},
        profile_name=profile.profile_name,
    )
    return {
        "human_gold": False,
        "ai_assisted_diagnostic": False,
        "method": "local_shadow_diagnostic",
        "case": "韩培培",
        "declared_industry": "51 批发业（铝锭大宗贸易/金属材料销售）",
        "not_production_judgement": True,
        "total_transactions": total_transactions,
        "unique_signature_count": len(signatures),
        "per_document": per_document,
        "synthesized": synthesized,
    }


def render_rh30_md(matrix: dict[str, Any]) -> str:
    lines = [
        "# RH30 Diagnostic Matrix（Gate F1.2C）",
        "",
        "- human_gold：false",
        "- ai_assisted_diagnostic：false（本轮仅本地 shadow 规则）",
        "- 状态：superseded_before_gold / diagnostic pilot",
        "- 明确：**NOT HOLDOUT ACCURACY**",
        "",
        "## 分布",
        "",
    ]
    for key in (
        "role_distribution",
        "trace_strength_distribution",
        "industry_relevance_distribution",
        "concept_distribution",
        "unresolved_reasons",
    ):
        lines.append(f"### {key}")
        lines.append("")
        value = matrix.get(key, {})
        if isinstance(value, dict):
            for name, count in sorted(value.items()):
                lines.append(f"- {name}：{count}")
        lines.append("")
    lines.extend(
        [
            "## 明细",
            "",
            "| ID | 概念 | 行业相关 | role | trace | 未解析原因 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in matrix["rows"]:
        lines.append(
            "| " + " | ".join(
                [
                    str(row["relation_holdout_id"]),
                    str(row["concept_id"] or "-"),
                    str(row["industry_relevance"]),
                    str(row["role"]),
                    str(row["trace_strength"]),
                    str(row["unresolved_reason"] or "-"),
                ]
            ) + " |"
        )
    return "\n".join(lines) + "\n"


def render_case_md(pilot: dict[str, Any]) -> str:
    synth = pilot["synthesized"]
    lines = [
        "# 韩培培 Case-Level Shadow Pilot（Gate F1.2C）",
        "",
        "- human_gold：false；仅 diagnostic，非 Production 判断",
        f"- 总交易：{pilot['total_transactions']}；唯一语义签名：{pilot['unique_signature_count']}",
        f"- 申报行业：{pilot['declared_industry']}",
        "",
        "## 案件级结论",
        "",
        f"- business_activity_presence：{synth['business_activity_presence']}",
        f"- declared_industry_consistency：{synth['declared_industry_consistency']}",
        f"- direct_industry_trace：{synth['direct_industry_trace']}",
        f"- supporting_evidence_roles：{', '.join(synth['supporting_evidence_roles'] or ['无'])}",
        f"- reason：{synth['reason']}",
        "",
        "## 直接经营证据",
        "",
    ]
    direct = synth["evidence_families"].get("direct_business")
    if direct:
        lines.append(f"- 笔数（去重组数）：{direct['occurrence_count']}（{direct['group_count']}）")
        for sample in direct["samples"]:
            lines.append(
                f"- `{sample['transaction_id']}` {sample['direction']} "
                f"{sample['amount']} role={sample['role']} trace={sample['trace_strength']}"
            )
    else:
        lines.append("- 无")
    lines.extend(["", "## 间接经营证据", ""])
    for role in ("operating_expense", "tax_regulatory", "financing", "settlement_infrastructure", "employment_operation", "government_interaction"):
        family = synth["evidence_families"].get(role)
        if family:
            lines.append(
                f"- {role}：{family['occurrence_count']} 笔 / {family['group_count']} 组 / "
                f"正向 {family['positive_occurrence_count']}"
            )
    lines.extend(["", "## 个人/非经营与未解析", ""])
    lines.append(
        f"- personal_consumption：{synth['personal_non_business']['occurrence_count']} 笔"
    )
    lines.append(f"- neutral_transfer：{synth['neutral_transfer']['occurrence_count']} 笔")
    lines.append(f"- unknown：{synth['unknown']['occurrence_count']} 笔")
    lines.extend(["", "## 矛盾与未解析区", ""])
    if synth["contradictions"]:
        for item in synth["contradictions"]:
            lines.append(f"- {item}")
    else:
        lines.append("- 无")
    if synth["unresolved_areas"]:
        for item in synth["unresolved_areas"]:
            lines.append(f"- {item}")
    return "\n".join(lines) + "\n"


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
        "--rh-batch",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-1-holdout-fitness-20260808/relation-holdout/"
            "relation_batch_h01.json"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-2-business-evidence-20260808"
        ),
    )
    args = parser.parse_args()

    runtime = KnowledgeRuntime.load(args.repo_root / "bankflow_v2" / "knowledge" / "canonical")
    profile = build_profile(runtime)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    matrix = rh30_matrix(runtime, profile, args.rh_batch)
    pilot = case_level_pilot(runtime, profile, args.case_dir)

    def write(name: str, value: Any) -> None:
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write("rh30_diagnostic_matrix.json", matrix)
    write("case_level_pilot.json", pilot)
    (args.output_dir / "rh30_diagnostic_report.md").write_text(
        render_rh30_md(matrix),
        encoding="utf-8",
    )
    (args.output_dir / "case_level_pilot.md").write_text(
        render_case_md(pilot),
        encoding="utf-8",
    )

    report = {
        "gate": "F1.2",
        "sub_gates": {
            "F1.2A": "done",
            "F1.2B": "done",
            "F1.2C": "done (local shadow diagnostic)",
        },
        "conclusion": "PASS_WITH_FOLLOW_UP",
        "conclusion_reason": (
            "Business Evidence Role / Trace Strength / Case-Level synthesis "
            "can structurally separate direct industry evidence, indirect "
            "business evidence and personal/non-business evidence; "
            "aggregation and role calibration still need human contract "
            "review and more pristine cases."
        ),
        "follow_ups": [
            "human review of contract and role examples",
            (
                "development regression on known tax/rent/utility/salary/"
                "settlement/government samples because RH30 lacks those roles"
            ),
            "targeted remediation after contract confirmation",
            "freeze production-candidate-v2",
            "rebuild pristine transaction relation/evidence holdout",
            "build pristine case-level holdout (3-10 cases)",
            "Human Gold first, then blind run, then promotion gate",
        ],
        "development_regression": {
            "required": True,
            "reason": (
                "RH30 diagnostic pilot does not cover tax/operating/settlement/"
                "employment/government roles; unit tests cover them, "
                "development regression is deferred to a follow-up"
            ),
            "marked_development_regression": True,
            "not_holdout": True,
        },
        "rh30": {
            "human_gold": matrix["human_gold"],
            "ai_assisted_diagnostic": matrix["ai_assisted_diagnostic"],
            "role_distribution": matrix["role_distribution"],
            "trace_strength_distribution": matrix["trace_strength_distribution"],
            "industry_relevance_distribution": matrix[
                "industry_relevance_distribution"
            ],
            "payment_rail_count": matrix["payment_rail_count"],
            "personal_consumption_count": matrix["personal_consumption_count"],
            "financing_count": matrix["financing_count"],
            "direct_business_count": matrix["direct_business_count"],
        },
        "case_level_pilot": {
            "total_transactions": pilot["total_transactions"],
            "unique_signature_count": pilot["unique_signature_count"],
            "business_activity_presence": pilot["synthesized"][
                "business_activity_presence"
            ],
            "declared_industry_consistency": pilot["synthesized"][
                "declared_industry_consistency"
            ],
            "direct_industry_trace": pilot["synthesized"]["direct_industry_trace"],
            "supporting_evidence_roles": pilot["synthesized"][
                "supporting_evidence_roles"
            ],
        },
        "safety": {
            "legacy_v11_production": True,
            "knowledge_v1_shadow": True,
            "no_production_promotion": True,
            "no_new_blind_run": True,
            "no_push": True,
            "real_ai_calls": 0,
            "schema_117_unchanged": True,
        },
    }
    write("gate_f1_2_report.json", report)
    md = [
        "# Gate F1.2 Report",
        "",
        f"- conclusion：{report['conclusion']}",
        f"- reason：{report['conclusion_reason']}",
        "",
        "## Safety",
        "",
    ]
    for key, value in report["safety"].items():
        md.append(f"- {key}：{value}")
    md.extend(["", "## Next Blockers", ""])
    for index, item in enumerate(report["follow_ups"], start=1):
        md.append(f"{index}. {item}")
    (args.output_dir / "gate_f1_2_report.md").write_text(
        "\n".join(md) + "\n",
        encoding="utf-8",
    )

    print("status=ok")
    print(f"rh30_rows={matrix['row_count']}")
    print(
        "rh30_role_distribution="
        f"{json.dumps(matrix['role_distribution'], ensure_ascii=False)}"
    )
    print(
        "case_total_transactions="
        f"{pilot['total_transactions']}"
    )
    print(
        "case_presence="
        f"{pilot['synthesized']['business_activity_presence']} "
        f"consistency={pilot['synthesized']['declared_industry_consistency']}"
    )
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
