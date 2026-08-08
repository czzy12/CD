"""Gate F1.3A: Local/AI responsibility boundary audit and contract artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge.evidence import RULE_REGISTRY
from bankflow_v2.knowledge.routing import (
    BUSINESS_EVIDENCE_TASK_VERSION,
    CASE_AI_LIFECYCLE,
    CASE_EVIDENCE_PACK_VERSION,
    CASE_SYNTHESIS_TASK_VERSION,
    LOCAL_AI_RESPONSIBILITY_CONTRACT_VERSION,
    ROUTING_AI_ELIGIBLE_TRANSACTION,
    ROUTING_INSUFFICIENT_TRANSACTION,
    ROUTING_LOCAL_RESOLVED,
    TRANSACTION_AI_LIFECYCLE,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_audit() -> dict[str, Any]:
    counts = Counter(
        str(rule.get("classification", "")) for rule in RULE_REGISTRY
    )
    high_risk = [
        rule
        for rule in RULE_REGISTRY
        if rule.get("context_dependency") == "high"
        and rule.get("classification") in {"AI_ELIGIBLE", "REMOVE_OR_RESTRICT"}
    ]
    return {
        "audit_version": "local-ai-boundary-audit-v1",
        "timestamp": _utcnow(),
        "total_local_rules": len(RULE_REGISTRY),
        "classification_counts": {
            "KEEP_LOCAL": int(counts.get("KEEP_LOCAL", 0)),
            "AI_ELIGIBLE": int(counts.get("AI_ELIGIBLE", 0)),
            "REMOVE_OR_RESTRICT": int(counts.get("REMOVE_OR_RESTRICT", 0)),
        },
        "high_risk_rules": [
            {
                "rule_id": rule["rule_id"],
                "role": rule["role"],
                "reason": rule["reason"],
            }
            for rule in high_risk
        ],
        "rules": RULE_REGISTRY,
    }


def build_responsibility_contract() -> dict[str, Any]:
    return {
        "contract_version": LOCAL_AI_RESPONSIBILITY_CONTRACT_VERSION,
        "principle": (
            "Local Precision First: local resolver targets high precision, "
            "not maximum coverage; ambiguous items are AI eligible."
        ),
        "routing_states": [
            ROUTING_LOCAL_RESOLVED,
            ROUTING_AI_ELIGIBLE_TRANSACTION,
            ROUTING_INSUFFICIENT_TRANSACTION,
            "case_aggregation_only",
            "case_ai_eligible",
        ],
        "local_responsibilities": [
            "PDF parser / transaction extraction / canonical transaction",
            "raw evidence trace, direction, amount, balance, metadata",
            "transaction_id and parser diagnostics",
            "PII guard, outbound whitelist, name sanitization, privacy preflight",
            "payment rail recognition/stripping, normalized fields",
            "deterministic semantic signature and evidence grouping key",
            "approved semantic KB exact resolution",
            "high-confidence deterministic evidence roles (tax/salary/settlement/"
            "personal/payment-rail/rent-utilities-logistics/direct strong)",
            "evidence grouping, dedup, counts, recurrence, diversity, "
            "CaseEvidencePack construction",
        ],
        "transaction_ai_responsibilities": [
            "ambiguous role and trace strength decisions",
            "context-dependent evidence (service fee, loan, government, "
            "company-name-only, operating ambiguous)",
            "output role/trace_strength/context_dependency/reason/evidence_refs/"
            "confidence via business-evidence-task-v1",
        ],
        "case_ai_responsibilities": [
            "case-level synthesis from CaseEvidencePack",
            "business_activity_presence and declared_industry_consistency",
            "supporting/contradictory refs, reasoning, uncertainty",
            "must never treat missing KB coverage as industry inconsistency",
        ],
        "human_responsibilities": [
            "Human Gold for holdouts",
            "candidate review before canonical knowledge promotion",
            "contract confirmation for role examples",
        ],
        "metrics": [
            "local_resolved",
            "ai_eligible",
            "insufficient",
            "unnecessary_ai_call",
            "missed_ai_call",
            "local_overreach",
            "local_false_confidence",
        ],
        "forbidden": [
            "AI call rate minimisation as the optimisation target",
            "merchant/entity hardcode as absolute role",
            "weak+weak+weak=strong",
            "case-level AI result auto-sinking to canonical KB",
            "relation not known interpreted as relation none",
        ],
        "ai_lifecycles": {
            "transaction_level": {
                "lifecycle": TRANSACTION_AI_LIFECYCLE,
                "flow": "AI -> KnowledgeCandidate -> pending -> Human Review -> approved -> canonical knowledge",
                "notes": [
                    "AI cannot self-approve",
                    "reusable transaction semantics may become candidates",
                ],
            },
            "case_level": {
                "lifecycle": CASE_AI_LIFECYCLE,
                "flow": "CaseEvidencePack -> Case AI -> CaseObservation",
                "notes": [
                    "case observation is case-specific, not reusable canonical KB",
                    "case observation must not become KnowledgeCandidate by default",
                    "reusable knowledge extraction requires a separate Human Review Gate",
                ],
            },
        },
    }


def build_evidence_ai_task_contract() -> dict[str, Any]:
    return {
        "task_version": BUSINESS_EVIDENCE_TASK_VERSION,
        "task": "business-evidence-role-v1",
        "input_whitelist": [
            "normalized semantic evidence",
            "direction",
            "purpose",
            "safe counterparty semantics",
            "semantic concept (if available)",
            "declared industry (only when role requires context)",
            "source field types",
        ],
        "never_send": [
            "customer name",
            "id card",
            "full account",
            "whole statement",
            "file path",
        ],
        "output_contract": {
            "role": "direct_business | operating_expense | tax_regulatory | "
            "financing | settlement_infrastructure | employment_operation | "
            "government_interaction | personal_consumption | neutral_transfer | "
            "unknown",
            "trace_strength": "strong | medium | weak | none | undetermined",
            "context_dependency": "string",
            "reason": "string",
            "evidence_refs": "list[string]",
            "confidence": "high | medium | low",
            "insufficient_behavior": "unknown / undetermined",
        },
        "candidate_behavior": "AI -> KnowledgeCandidate -> pending -> Human Review -> approved -> local knowledge",
        "lifecycle": TRANSACTION_AI_LIFECYCLE,
        "case_level_behavior": CASE_AI_LIFECYCLE,
    }


def build_case_evidence_pack_contract() -> dict[str, Any]:
    return {
        "pack_version": CASE_EVIDENCE_PACK_VERSION,
        "structure": [
            "declared_industry",
            "direct_business_evidence[]",
            "operating_expense_evidence[]",
            "tax_regulatory_evidence[]",
            "financing_evidence[]",
            "settlement_infrastructure_evidence[]",
            "employment_operation_evidence[]",
            "government_interaction_evidence[]",
            "personal_consumption_summary",
            "neutral_transfer_summary",
            "unknown_evidence[]",
            "evidence_group_count",
            "counterparty_diversity",
            "time_span",
            "monthly_recurrence",
            "direction_summary",
            "amount_summary",
            "direct_industry_relation_summary",
        ],
        "evidence_availability": {
            "total_transaction_count": "int",
            "evidence_eligible_transaction_count": "int",
            "insufficient_transaction_count": "int",
            "evidence_availability_ratio": "float or null",
            "unavailable_reason_counts": "dict[str,int]",
            "semantics": {
                "unavailable_not_absent": True,
            },
        },
        "compression": (
            "representative refs, strongest evidence, recurrence statistics, "
            "safe semantic summaries; never the full raw statement"
        ),
        "requirements": [
            "deterministic",
            "PII-safe",
            "auditable",
            "evidence refs traceable",
            "source provenance preserved",
            "provider-neutral",
            "evidence unavailable is never interpreted as evidence absent",
        ],
        "forbidden_identity": [
            "customer name",
            "id card",
            "bank card",
            "phone",
            "full account",
        ],
    }


def build_case_synthesis_ai_task_contract() -> dict[str, Any]:
    return {
        "task_version": CASE_SYNTHESIS_TASK_VERSION,
        "task": "case-synthesis-ai-v1",
        "input": "CaseEvidencePack (compressed, PII-safe)",
        "output_contract": {
            "business_activity_presence": "strong | medium | weak | undetermined",
            "declared_industry_consistency": (
                "strong | medium | weak | none | undetermined"
            ),
            "supporting_evidence_refs": "list[string]",
            "contradictory_evidence_refs": "list[string]",
            "reasoning_summary": "string",
            "uncertainty_reason": "string",
        },
        "hard_rules": [
            "business_activity_presence and declared_industry_consistency "
            "must remain separable",
            "weak consistency must distinguish real inconsistency from "
            "knowledge coverage insufficiency",
            "evidence unavailable != evidence absent; reasoning must "
            "consider evidence coverage limitation",
            "no complex scoring in v1",
            "output is case observation, not canonical KB",
        ],
        "lifecycle": CASE_AI_LIFECYCLE,
        "not_knowledge_candidate": True,
        "no_canonical_sink": True,
    }


def build_industry_coverage_contract() -> dict[str, Any]:
    return {
        "contract_version": "industry-coverage-contract-v1",
        "value_enum": [
            "sufficient",
            "partial",
            "insufficient",
            "unavailable",
        ],
        "core_invariants": [
            "knowledge coverage insufficient != declared industry inconsistent",
            "relation not known != relation none",
            "coverage is about whether enough evidence exists for a reliable "
            "consistency judgement, not about relation row count",
        ],
        "inputs": [
            "relation KB coverage for declared industries",
            "direct evidence existence",
            "unresolved relation proportion",
            "AI evidence availability",
        ],
    }


def build_routing_regression() -> dict[str, Any]:
    cases = [
        {
            "case_id": "reg-tax-explicit",
            "fields": {"summary": "增值税缴税"},
            "expected_routing": ROUTING_LOCAL_RESOLVED,
            "expected_role": "tax_regulatory",
            "category": "local_deterministic",
        },
        {
            "case_id": "reg-salary-explicit",
            "fields": {"summary": "代发工资"},
            "expected_routing": ROUTING_LOCAL_RESOLVED,
            "expected_role": "employment_operation",
            "category": "local_deterministic",
        },
        {
            "case_id": "reg-settlement-explicit",
            "fields": {"summary": "企业结算卡年费"},
            "expected_routing": ROUTING_LOCAL_RESOLVED,
            "expected_role": "settlement_infrastructure",
            "category": "local_deterministic",
        },
        {
            "case_id": "reg-rent-explicit",
            "fields": {"summary": "经营场地租金"},
            "expected_routing": ROUTING_LOCAL_RESOLVED,
            "expected_role": "operating_expense",
            "category": "local_deterministic",
        },
        {
            "case_id": "reg-personal-explicit",
            "fields": {"summary": "餐饮消费"},
            "expected_routing": ROUTING_LOCAL_RESOLVED,
            "expected_role": "personal_consumption",
            "category": "local_deterministic",
        },
        {
            "case_id": "reg-payment-rail-only",
            "fields": {"summary": "微信支付"},
            "expected_routing": ROUTING_LOCAL_RESOLVED,
            "expected_role": "neutral_transfer",
            "category": "local_deterministic",
        },
        {
            "case_id": "reg-service-fee",
            "fields": {"summary": "项目服务费"},
            "expected_routing": ROUTING_AI_ELIGIBLE_TRANSACTION,
            "category": "ai_eligible",
        },
        {
            "case_id": "reg-loan-ambiguous",
            "fields": {"summary": "借款"},
            "expected_routing": ROUTING_AI_ELIGIBLE_TRANSACTION,
            "category": "ai_eligible",
        },
        {
            "case_id": "reg-government",
            "fields": {"counterparty_name": "XX市财政局"},
            "expected_routing": ROUTING_AI_ELIGIBLE_TRANSACTION,
            "category": "ai_eligible",
        },
        {
            "case_id": "reg-company-name-only",
            "fields": {"counterparty_name": "某某贸易有限公司"},
            "expected_routing": ROUTING_AI_ELIGIBLE_TRANSACTION,
            "category": "ai_eligible",
        },
        {
            "case_id": "reg-context-merchant",
            "fields": {"merchant_name": "某建材批发市场"},
            "expected_routing": ROUTING_AI_ELIGIBLE_TRANSACTION,
            "category": "ai_eligible",
            "profile": "51",
        },
        {
            "case_id": "reg-no-evidence",
            "fields": {},
            "expected_routing": ROUTING_INSUFFICIENT_TRANSACTION,
            "category": "insufficient",
        },
    ]
    return {
        "contract_version": "routing-regression-v1",
        "purpose": (
            "verify routing boundary only; not accuracy, not holdout, "
            "not human gold"
        ),
        "cases": cases,
    }


def build_known_followups() -> dict[str, Any]:
    return {
        "timestamp": _utcnow(),
        "followups": [
            {
                "id": "transaction_ai_task_real_call",
                "item": (
                    "minimal real-call validation of business-evidence-task-v1 "
                    "after privacy preflight, when user authorises"
                ),
            },
            {
                "id": "case_ai_task_real_call",
                "item": (
                    "case-synthesis-ai-v1 validation with a prepared "
                    "CaseEvidencePack when user authorises"
                ),
            },
            {
                "id": "industry_51_relation_coverage",
                "item": (
                    "taxonomy 51 still has zero industry relations; "
                    "consistency stays coverage-qualified until relation KB "
                    "or AI evidence is available"
                ),
            },
            {
                "id": "development_regression",
                "item": (
                    "run development regression on known tax/rent/utility/"
                    "salary/settlement/government samples (marked "
                    "development_regression, not holdout)"
                ),
            },
            {
                "id": "human_contract_review",
                "item": (
                    "human review of role examples and context override "
                    "curation before production-candidate-v2 preparation"
                ),
            },
            {
                "id": "production_candidate_v2",
                "item": (
                    "freeze production-candidate-v2 only after F1.3 "
                    "contract confirmation"
                ),
            },
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-3-local-ai-boundary-20260808"
        ),
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    audit = build_audit()
    responsibility = build_responsibility_contract()
    evidence_task = build_evidence_ai_task_contract()
    pack_contract = build_case_evidence_pack_contract()
    case_task = build_case_synthesis_ai_task_contract()
    coverage_contract = build_industry_coverage_contract()
    regression = build_routing_regression()
    followups = build_known_followups()

    def write(name: str, value: Any) -> None:
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write("local_ai_boundary_audit.json", audit)
    write("local_ai_responsibility_contract.json", responsibility)
    write("business_evidence_ai_task_contract.json", evidence_task)
    write("case_evidence_pack_contract.json", pack_contract)
    write("case_synthesis_ai_task_contract.json", case_task)
    write("industry_coverage_contract.json", coverage_contract)
    write("routing_regression.json", regression)
    write("known_followups.json", followups)

    md = [
        "# Local / AI Responsibility Boundary Audit（Gate F1.3A）",
        "",
        f"- 本地规则总数：{audit['total_local_rules']}",
        "- 分类："
        + "、".join(
            f"{key}={value}"
            for key, value in audit["classification_counts"].items()
        ),
        "",
        "## 高风险/需上下文规则",
        "",
    ]
    if audit["high_risk_rules"]:
        for rule in audit["high_risk_rules"]:
            md.append(
                f"- {rule['rule_id']}（{rule['role']}）：{rule['reason']}"
            )
    else:
        md.append("- 无")
    md.extend(
        [
            "",
            "## 原则",
            "",
            "- Local Precision First：高 precision，不追最大 coverage",
            "- 明确可确定 → local_resolved",
            "- 模糊/上下文依赖 → ai_eligible_transaction",
            "- 无证据/纯噪声 → insufficient_transaction（不强制调用 AI）",
            "- 案件级综合 → CaseEvidencePack → case_ai_eligible",
            "- AI 输出始终 Candidate → pending → Human Review",
            "- knowledge coverage insufficient ≠ 业务不一致",
        ]
    )
    (args.output_dir / "local_ai_boundary_audit.md").write_text(
        "\n".join(md) + "\n",
        encoding="utf-8",
    )

    print("status=ok")
    print(
        "classification_counts="
        f"{json.dumps(audit['classification_counts'], ensure_ascii=False)}"
    )
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
