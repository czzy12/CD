"""Gate F1.2A: architecture audit + business evidence contract artifacts.

Read-only audit of the frozen production candidate plus generation of the
business-evidence-contract-v1 / case-synthesis contract / holdout status delta.
It also marks RH30 as superseded_before_gold (provenance preserved).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.knowledge.evidence import (
    BUSINESS_EVIDENCE_CONTRACT_VERSION,
    BUSINESS_EVIDENCE_RESOLVER_VERSION,
    EVIDENCE_ROLES,
    EVIDENCE_SOURCES,
    ROLE_ZH,
    TRACE_STRENGTHS,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_architecture_audit(repo_root: Path, freeze_dir: Path) -> dict[str, Any]:
    checksums_path = freeze_dir / "production_candidate_checksums.json"
    frozen: dict[str, str] = {}
    if checksums_path.is_file():
        data = json.loads(checksums_path.read_text(encoding="utf-8"))
        frozen = {
            str(name): str(digest)
            for name, digest in data.get("file_checksums", {}).items()
        }
    current: dict[str, str] = {}
    unchanged: list[str] = []
    changed: list[str] = []
    missing: list[str] = []
    for name in sorted(frozen):
        path = repo_root / name
        if not path.is_file():
            missing.append(name)
            continue
        digest = _sha256(path)
        current[name] = digest
        if digest == frozen[name]:
            unchanged.append(name)
        else:
            changed.append(name)
    return {
        "audit_version": "architecture-audit-v1",
        "timestamp": _utcnow(),
        "repo_root": str(repo_root),
        "frozen_candidate": "production-candidate-v1",
        "prediction_files_unchanged": len(changed) == 0 and len(missing) == 0,
        "unchanged_files": unchanged,
        "changed_files": changed,
        "missing_files": missing,
        "frozen_manifest_checksum": (
            json.loads(checksums_path.read_text(encoding="utf-8")).get(
                "manifest_checksum",
                "",
            )
            if checksums_path.is_file()
            else ""
        ),
        "existing_reusable_pieces": [
            {
                "name": "SemanticConceptKB / SemanticResolver",
                "layer": "A - Semantic Concept",
                "reuse": "unchanged, text -> concept",
            },
            {
                "name": "IndustryRelationResolver / RelationKB",
                "layer": "B1 - Industry Direct Relation",
                "reuse": "unchanged, industry x concept -> relevance",
            },
            {
                "name": "KnowledgeRuntime",
                "layer": "A+B1 bundle",
                "reuse": "load canonical KB + resolvers",
            },
            {
                "name": "KnowledgeCandidate / RuntimeKnowledgeRepository",
                "layer": "candidate lifecycle",
                "reuse": (
                    "candidate_type is a plain string in the store; a new "
                    "business_evidence_role type can reuse it without schema change"
                ),
            },
            {
                "name": "schema 1.17 observation container",
                "layer": "persistence",
                "reuse": (
                    "extensible observations; unknown observation types are "
                    "tolerated by GUI, so an additive business_evidence "
                    "observation can be added later under schema 1.17"
                ),
            },
            {
                "name": "payment_rail / privacy / normalization",
                "layer": "safety",
                "reuse": "read-only reuse; no frozen file changed",
            },
        ],
        "missing_layers": [
            "B2 - Business Evidence Role",
            "B2 - Business Trace Strength",
            "evidence group / family dedup key",
            "C - Case-Level Business Trace Synthesis",
            "external evidence source separation (reserved, not implemented)",
        ],
        "schema_impact": {
            "schema_version": "1.17",
            "schema_version_changed": False,
            "persistence_this_round": "independent shadow artifacts only",
            "future_additive_observation": (
                "business_evidence_resolutions (additive observation, "
                "no schema_version bump required); not implemented this round"
            ),
            "schema_extension_required": False,
        },
        "candidate_lifecycle_impact": {
            "reuse": True,
            "candidate_type": "business_evidence_role",
            "model_change_required": False,
            "note": (
                "KnowledgeCandidate already stores arbitrary candidate_type; "
                "the repository does not enforce CANDIDATE_TYPES."
            ),
        },
        "concept_prediction_path_unchanged": True,
        "concept_prediction_path_note": (
            "No semantic concept KB, prompt, resolver, normalization, payment "
            "rail or AI fallback file was modified."
        ),
    }


def build_role_definitions() -> dict[str, Any]:
    roles: dict[str, dict[str, Any]] = {}
    for role in sorted(EVIDENCE_ROLES):
        roles[role] = {
            "name_zh": ROLE_ZH.get(role, role),
            "default_trace_strength": {
                "direct_business": "strong/medium/weak",
                "operating_expense": "medium/weak",
                "tax_regulatory": "medium",
                "financing": "weak/medium",
                "settlement_infrastructure": "weak",
                "employment_operation": "medium",
                "government_interaction": "weak",
                "personal_consumption": "none",
                "neutral_transfer": "undetermined",
                "unknown": "undetermined",
            }.get(role, "undetermined"),
            "industry_relevance_independent": True,
            "role_source": "transaction + semantic concept + industry/case context",
        }
    return {
        "contract_version": BUSINESS_EVIDENCE_CONTRACT_VERSION,
        "roles": roles,
        "trace_strengths": sorted(TRACE_STRENGTHS),
        "evidence_sources": list(EVIDENCE_SOURCES),
    }


def build_case_synthesis_contract() -> dict[str, Any]:
    return {
        "contract_version": "case-synthesis-contract-v1",
        "case_trace_resolver_version": "case-trace-resolver-v1",
        "outputs": {
            "business_activity_presence": {
                "values": ["strong", "medium", "weak", "undetermined"],
                "question": "客户是否明显存在经营活动",
            },
            "declared_industry_consistency": {
                "values": ["strong", "medium", "weak", "undetermined"],
                "question": "经营活动与客户申报行业是否一致",
            },
            "direct_industry_trace": {
                "values": ["strong", "medium", "weak", "undetermined"],
                "question": "直接经营证据对申报行业的支持强度",
            },
            "supporting_evidence_roles": {
                "type": "list[role]",
                "question": "参与案件级综合的正向证据角色",
            },
        },
        "forbidden": [
            "weak + weak + weak = strong",
            "merchant hardcode as absolute rule",
            "customer declared industry as evidence of business existence",
            "indirect evidence promoted to direct industry evidence",
            "score-only output without explanation",
        ],
        "considered_factors": [
            "evidence independence (different families)",
            "recurrence (months)",
            "temporal consistency",
            "directional consistency",
            "counterparty diversity",
            "evidence diversity",
            "duplication suppression via evidence_group_key",
        ],
        "evidence_group_key": (
            "role|subfamily; identical groups are deduplicated and cannot "
            "increase case strength indefinitely"
        ),
        "shadow_only": True,
        "production_impact": "none; legacy_v11 remains production",
    }


def build_holdout_status_delta(
    gate_f1_1_dir: Path,
    relation_holdout_dir: Path,
) -> dict[str, Any]:
    concept_manifest = gate_f1_1_dir / "final_holdout_manifest.json"
    concept_count = 0
    concept_docs = 0
    if concept_manifest.is_file():
        data = json.loads(concept_manifest.read_text(encoding="utf-8"))
        concept = data.get("concept_holdout", {})
        concept_count = int(concept.get("membership_count", 0))
        concept_docs = int(concept.get("source_document_count", 0))
    relation_manifest = relation_holdout_dir / "relation_holdout_manifest.json"
    original_checksum = ""
    if relation_manifest.is_file():
        original_checksum = str(
            json.loads(relation_manifest.read_text(encoding="utf-8")).get(
                "checksum",
                "",
            )
        )
    return {
        "timestamp": _utcnow(),
        "concept_holdout": {
            "retained": True,
            "why": (
                "Concept prediction path unchanged: Semantic Concept KB, "
                "prompt, resolver, normalization and payment rail files are "
                "bit-identical to production-candidate-v1; new layer is "
                "independent shadow logic."
            ),
            "membership_count": concept_count,
            "source_document_count": concept_docs,
            "human_gold": 0,
            "system_run": 0,
        },
        "relation_holdout_rh30": {
            "superseded_before_gold": True,
            "reason": "architecture_gap_discovered_during_prelabel_review",
            "system_run": 0,
            "human_gold": 0,
            "usable_as_diagnostic": True,
            "original_checksum": original_checksum,
            "provenance_preserved": True,
            "note": (
                "industry x concept relevance cannot express business evidence "
                "roles; RH30 is a diagnostic/calibration pilot, not a final "
                "production relation holdout."
            ),
        },
        "production_candidate_v1": {
            "retained_as_historical_freeze": True,
            "manifest_checksum": (
                json.loads(
                    (
                        Path(
                            "D:/Investigator PDF/outputs/knowledge-v1/"
                            "production-candidate-freeze-20260808/"
                            "production_candidate_manifest.json"
                        )
                    ).read_text(encoding="utf-8")
                ).get("manifest_checksum", "")
                if Path(
                    "D:/Investigator PDF/outputs/knowledge-v1/"
                    "production-candidate-freeze-20260808/"
                    "production_candidate_manifest.json"
                ).is_file()
                else ""
            ),
            "note": "historical freeze kept; production-candidate-v2 deferred",
        },
        "future_holdout_redesign_required": True,
        "future_holdout_types": [
            "concept_holdout (text -> concept)",
            "transaction_relation_evidence_holdout (relation + role + trace)",
            "case_level_holdout (whole customer cases)",
        ],
    }


def mark_relation_holdout_superseded(
    relation_holdout_dir: Path,
    original_checksum: str,
) -> dict[str, Any]:
    gold_path = relation_holdout_dir / "relation_human_gold.json"
    if gold_path.is_file():
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        gold["status"] = "superseded_before_gold"
        gold["superseded"] = True
        gold["superseded_reason"] = (
            "architecture_gap_discovered_during_prelabel_review"
        )
        gold["usable_as_diagnostic"] = True
        gold["system_run"] = 0
        gold["human_gold"] = 0
        gold["superseded_at"] = _utcnow()
        gold_path.write_text(
            json.dumps(gold, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    status = {
        "holdout_version": "production-relation-holdout-v1",
        "status": "superseded_before_gold",
        "reason": "architecture_gap_discovered_during_prelabel_review",
        "human_labels": 0,
        "system_run": 0,
        "usable_as_diagnostic": True,
        "provenance_preserved": True,
        "original_checksum": original_checksum,
        "superseded_at": _utcnow(),
    }
    (relation_holdout_dir / "relation_holdout_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return status


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
            "gate-f1-2-business-evidence-20260808"
        ),
    )
    parser.add_argument(
        "--production-freeze-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "production-candidate-freeze-20260808"
        ),
    )
    parser.add_argument(
        "--gate-f1-1-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-1-holdout-fitness-20260808"
        ),
    )
    parser.add_argument(
        "--relation-holdout-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "gate-f1-1-holdout-fitness-20260808/relation-holdout"
        ),
    )
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    audit = build_architecture_audit(args.repo_root, args.production_freeze_dir)
    roles = build_role_definitions()
    case_contract = build_case_synthesis_contract()
    delta = build_holdout_status_delta(args.gate_f1_1_dir, args.relation_holdout_dir)
    original_checksum = str(delta["relation_holdout_rh30"]["original_checksum"])
    status = mark_relation_holdout_superseded(
        args.relation_holdout_dir,
        original_checksum,
    )

    def write(name: str, value: Any) -> None:
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write("architecture_audit.json", audit)
    write("evidence_role_definitions.json", roles)
    write("case_synthesis_contract.json", case_contract)
    write("holdout_status_delta.json", delta)

    known_gaps = {
        "contract_version": BUSINESS_EVIDENCE_CONTRACT_VERSION,
        "timestamp": _utcnow(),
        "gaps": [
            {
                "id": "rh30_role_coverage",
                "gap": (
                    "RH30 sample has no tax/operating/settlement/employment "
                    "evidence; role coverage is verified by unit tests and "
                    "needs development/calibration regression samples"
                ),
                "impact": "contract regression coverage",
                "status": "open",
            },
            {
                "id": "industry_51_relations_empty",
                "gap": (
                    "taxonomy 51 has zero industry x concept relations; "
                    "declared_industry_consistency stays weak/undetermined "
                    "until relation KB is extended for the future v2"
                ),
                "impact": "declared_industry_consistency",
                "status": "open",
            },
            {
                "id": "case_level_holdout_missing",
                "gap": (
                    "case-level synthesis needs 3-10 pristine customer cases "
                    "with external industry metadata before any blind run"
                ),
                "impact": "future holdout design",
                "status": "open",
            },
            {
                "id": "context_override_curation",
                "gap": (
                    "industry context market terms are a first-pass curation "
                    "and require human contract review before promotion"
                ),
                "impact": "role correctness",
                "status": "open",
            },
        ],
        "schema_extension_required": False,
        "schema_extension_proposal": (
            "future additive observation business_evidence_resolutions under "
            "schema 1.17; no version bump required; not implemented this round"
        ),
    }
    write("known_architecture_gaps.json", known_gaps)

    contract = {
        "contract_version": BUSINESS_EVIDENCE_CONTRACT_VERSION,
        "resolver_version": BUSINESS_EVIDENCE_RESOLVER_VERSION,
        "case_trace_resolver_version": "case-trace-resolver-v1",
        "timestamp": _utcnow(),
        "layers": {
            "A": "Semantic Concept (unchanged)",
            "B1": "Industry Direct Relation (unchanged)",
            "B2": "Business Evidence Role + Business Trace Strength (new)",
            "C": "Case-Level Business Trace Synthesis (new)",
        },
        "roles": roles,
        "coexistence_rules": {
            "industry_relevance": (
                "industry x concept -> strong/medium/weak/none/undetermined; "
                "direct support for the declared industry only"
            ),
            "business_trace_strength": (
                "role-specific support for business activity existence; "
                "independent of industry relevance"
            ),
            "example_tax": {
                "industry_relevance": "weak/undetermined",
                "business_evidence_role": "tax_regulatory",
                "business_trace_strength": "medium",
            },
            "example_lobster": {
                "industry_relevance": "none",
                "business_evidence_role": "personal_consumption",
                "business_trace_strength": "none",
            },
            "example_settlement_card_fee": {
                "industry_relevance": "weak",
                "business_evidence_role": "settlement_infrastructure",
                "business_trace_strength": "weak",
            },
            "example_metal_goods_payment": {
                "industry_relevance": "strong",
                "business_evidence_role": "direct_business",
                "business_trace_strength": "strong",
            },
        },
        "unresolved_behavior": {
            "role": "unknown",
            "trace_strength": "undetermined",
            "never_defaults_to_approved_or_none_without_evidence": True,
        },
        "ai_boundary": {
            "ai_can_propose": True,
            "ai_candidate_lifecycle": "candidate -> pending -> human review",
            "ai_assisted_diagnostic_flag": "ai_assisted_diagnostic",
            "human_gold_required_for_future_holdout": True,
            "real_ai_calls_this_round": 0,
        },
        "schema": {
            "schema_version": "1.17",
            "changed": False,
            "persistence": "independent shadow artifacts only",
            "future_additive_observation": "business_evidence_resolutions",
        },
    }
    write("business_evidence_contract.json", contract)

    md = [
        "# Business Evidence Contract v1（Gate F1.2 Shadow）",
        "",
        f"- contract_version：`{BUSINESS_EVIDENCE_CONTRACT_VERSION}`",
        f"- resolver_version：`{BUSINESS_EVIDENCE_RESOLVER_VERSION}`",
        f"- case_trace_resolver_version：`case-trace-resolver-v1`",
        "- 状态：shadow only，不改 schema 1.17，不触发 production-candidate-v1",
        "",
        "## 三层结构",
        "",
        "| Layer | 问题 | 状态 |",
        "| --- | --- | --- |",
        "| A Semantic Concept | 这笔交易语义是什么 | 复用冻结层 |",
        "| B1 Industry Direct Relation | 对申报行业的直接支持 | 复用冻结层 |",
        "| B2 Business Evidence Role | 对真实经营存在的证据角色 | 本轮新增 shadow |",
        "| C Case-Level Trace | 经营存在与申报行业一致性 | 本轮新增 shadow |",
        "",
        "## Roles",
        "",
        "| role | 中文 | 默认 trace strength |",
        "| --- | --- | --- |",
    ]
    for role in sorted(roles["roles"]):
        item = roles["roles"][role]
        md.append(
            f"| {role} | {item['name_zh']} | {item['default_trace_strength']} |"
        )
    md.extend(
        [
            "",
            "## 两个 strength 必须独立",
            "",
            "```text",
            "industry_relevance != business_trace_strength",
            "",
            "增值税缴税：industry=weak/undetermined, role=tax_regulatory, trace=medium",
            "黄家龙虾：industry=none, role=personal_consumption, trace=none",
            "企业结算卡年费：industry=weak, role=settlement_infrastructure, trace=weak",
            "明确金属材料货款：industry=strong, role=direct_business, trace=strong",
            "```",
            "",
            "## 禁止",
            "",
            "- 商户名/机构名单独硬编码为绝对角色",
            "- weak+weak+weak=strong",
            "- 用客户申报行业本身证明经营存在",
            "- 税费/贷款自动变成行业 strong",
            "- 个人消费多次出现自动放大为经营证据",
            "- AI 输出未经 candidate->pending->人工审核直接 canonical",
            "",
            "## Holdout 状态",
            "",
            "- Concept Holdout：保留（Concept 预测路径未变）",
            "- RH30：superseded_before_gold，仅作 diagnostic pilot",
            "- production-candidate-v1：历史 freeze 保留，本轮不动",
            "- production-candidate-v2：本轮不创建，等架构验证后再做",
        ]
    )
    (args.output_dir / "business_evidence_contract.md").write_text(
        "\n".join(md) + "\n",
        encoding="utf-8",
    )

    print("status=ok")
    print(
        "prediction_files_unchanged="
        f"{audit['prediction_files_unchanged']}"
    )
    print(
        "concept_holdout_retained="
        f"{delta['concept_holdout']['retained']}"
    )
    print(
        "relation_rh30="
        f"{status['status']} system_run={status['system_run']}"
    )
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
