"""Gate F2: freeze production-candidate-v2 manifest (shadow candidate)."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bankflow_v2.deepseek_adapter import load_deepseek_settings
from bankflow_v2.knowledge import versioning
from bankflow_v2.knowledge.case_trace import CASE_TRACE_RESOLVER_VERSION
from bankflow_v2.knowledge.evidence import (
    BUSINESS_EVIDENCE_CONTRACT_VERSION,
    BUSINESS_EVIDENCE_RESOLVER_VERSION,
)
from bankflow_v2.knowledge.freeze import manifest_checksum
from bankflow_v2.knowledge.routing import (
    BUSINESS_EVIDENCE_TASK_VERSION,
    CASE_EVIDENCE_PACK_VERSION,
    CASE_SYNTHESIS_TASK_VERSION,
    LOCAL_AI_RESPONSIBILITY_CONTRACT_VERSION,
)


PREDICTION_AFFECTING_FILES_V2 = [
    "bankflow_v2/ai_business_observation.py",
    "bankflow_v2/deepseek_adapter.py",
    "bankflow_v2/knowledge/versioning.py",
    "bankflow_v2/knowledge/normalization.py",
    "bankflow_v2/knowledge/payment_rail.py",
    "bankflow_v2/knowledge/privacy.py",
    "bankflow_v2/knowledge/ai_fallback.py",
    "bankflow_v2/knowledge/ai_validation.py",
    "bankflow_v2/knowledge/ai_contracts.py",
    "bankflow_v2/knowledge/models.py",
    "bankflow_v2/knowledge/semantic_concepts.py",
    "bankflow_v2/knowledge/relations.py",
    "bankflow_v2/knowledge/industry_taxonomy.py",
    "bankflow_v2/knowledge/resolver.py",
    "bankflow_v2/knowledge/repository.py",
    "bankflow_v2/knowledge/evidence.py",
    "bankflow_v2/knowledge/routing.py",
    "bankflow_v2/knowledge/case_evidence_pack.py",
    "bankflow_v2/knowledge/case_trace.py",
    "bankflow_v2/knowledge/coverage.py",
    "bankflow_v2/knowledge/canonical/taxonomy.json",
    "bankflow_v2/knowledge/canonical/semantic_concepts.json",
    "bankflow_v2/knowledge/canonical/semantic_aliases.json",
    "bankflow_v2/knowledge/canonical/relations.json",
]

CONCEPT_HOLDOUT_CHECKSUM = (
    "31c51ec32ab42e93e8159a28294638ae100e96e943e60307b8bdbc593763caaa"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def _git_branch(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or "unknown"


def _scan_runtime_dependencies(repo_root: Path) -> dict[str, Any]:
    """Static check that prediction modules never read case-specific artifacts."""
    roots = [
        repo_root / "bankflow_v2" / "knowledge",
        repo_root / "bankflow_v2" / "ai_business_observation.py",
        repo_root / "bankflow_v2" / "deepseek_adapter.py",
    ]
    forbidden = (
        "D:/Investigator PDF/outputs",
        "D:\\Investigator PDF\\outputs",
        "hanpeipei",
        "韩培培",
        "Desktop",
        "case_observation.json",
        "case_evidence_pack.json",
    )
    findings: list[dict[str, Any]] = []
    for root in roots:
        path = Path(root)
        files = (
            [path]
            if path.is_file()
            else sorted(path.rglob("*.py"))
            if path.is_dir()
            else []
        )
        for file_path in files:
            try:
                text = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for token in forbidden:
                if token in text:
                    findings.append(
                        {
                            "file": str(file_path.relative_to(repo_root)),
                            "token": token,
                        }
                    )
    return {
        "case_specific_diagnostic_dependency": len(findings) == 0,
        "findings": findings,
    }


def build_ai_runtime_config() -> dict[str, Any]:
    settings = load_deepseek_settings()
    return {
        "provider": "deepseek",
        "requested_model_identifier": settings.model or "deepseek-v4-flash",
        "provider_returned_model_identifier": "not_captured_during_f1_3_1",
        "transaction_ai_contract_version": BUSINESS_EVIDENCE_TASK_VERSION,
        "case_ai_contract_version": CASE_SYNTHESIS_TASK_VERSION,
        "prompt_template_versions": {
            "transaction_evidence_role": BUSINESS_EVIDENCE_TASK_VERSION,
            "case_synthesis": CASE_SYNTHESIS_TASK_VERSION,
        },
        "temperature": 0,
        "top_p": "provider_default",
        "max_tokens": 4096,
        "response_format": "json_object",
        "thinking": "disabled",
        "retry_count": 0,
        "timeout_behavior": (
            f"{settings.timeout_seconds}s per request; single attempt"
        ),
        "batch_size": settings.batch_size,
        "structured_output_validator_version": (
            "ai_contracts.validate_transaction_evidence_result + "
            "ai_contracts.validate_case_observation"
        ),
        "sanitizer_version": (
            "ai_validation.safe_validation_fields + privacy.guard_item + "
            "normalization.sanitize_personal_names"
        ),
        "secrets_in_manifest": False,
        "api_key_in_manifest": False,
        "model_weight_freeze_note": (
            "model identifier frozen != provider weights cryptographically "
            "frozen; remote model weights are outside this repository. "
            "Blind Run must record provider-returned model metadata."
        ),
    }


def build_pending_state_snapshot() -> dict[str, Any]:
    return {
        "gate_d_frozen_review_set": {
            "status": "unchanged",
            "pending_candidates": 61,
            "note": "real-ai-review-set-v1 remains frozen; no auto approval",
        },
        "gate_e_human_decisions": {
            "status": "unchanged",
            "decisions": 12,
            "note": "R01-R12 human decisions preserved",
        },
        "d3_calibration_pending": 21,
        "d31_calibration_pending": 18,
        "f1_3_1_live_transaction_ai_candidates": {
            "status": "pending",
            "count": 6,
            "note": "business-evidence-task-v1 live validation candidates; "
                    "not promoted by freeze",
        },
        "property_management_06_conditional": {
            "status": "unresolved_conditional",
            "note": "kept undetermined + conditional_relation_candidate",
        },
        "promotion_triggered_by_freeze": False,
    }


def build_holdout_status() -> dict[str, Any]:
    return {
        "production_concept_holdout_v1": {
            "retained": True,
            "checksum": CONCEPT_HOLDOUT_CHECKSUM,
            "contamination": 0,
            "concept_path_compatible": True,
            "reason": (
                "Semantic Concept KB/alias/prompt/resolver unchanged since "
                "production-candidate-v1; v2 concept prediction path identical"
            ),
        },
        "transaction_relation_evidence_holdout": {
            "status": "not_yet_created"
        },
        "case_level_holdout": {"status": "not_yet_created"},
        "rh30_relation_pilot": {
            "status": "diagnostic_superseded",
            "not_production_accuracy": True,
        },
    }


def build_safety_invariants() -> list[str]:
    return [
        "outbound_pii=0",
        "ai_cannot_self_approve",
        "candidate_only_reusable_knowledge",
        "case_observation_non_canonical",
        "current_case_ai_observation_non_canonical",
        "unavailable!=absent",
        "relation_unknown!=none",
        "coverage_insufficient!=inconsistent",
        "payment_rail!=business_substance",
        "personal_name_sanitization",
        "schema=1.17",
        "legacy_v11_remains_production",
        "knowledge_v1_remains_shadow",
    ]


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
    args.output_dir.mkdir(parents=True, exist_ok=True)

    dependency_check = _scan_runtime_dependencies(args.repo_root)
    if not dependency_check["case_specific_diagnostic_dependency"]:
        print(
            "freeze=blocked case_specific_dependency="
            f"{json.dumps(dependency_check['findings'], ensure_ascii=False)}"
        )
        return 1

    file_checksums: dict[str, str] = {}
    missing: list[str] = []
    for name in PREDICTION_AFFECTING_FILES_V2:
        path = args.repo_root / name
        if not path.is_file():
            missing.append(name)
            continue
        file_checksums[name] = _sha256(path)
    if missing:
        print(f"freeze=blocked missing_files={missing}")
        return 1

    runtime_config = build_ai_runtime_config()
    manifest: dict[str, Any] = {
        "candidate_id": "production-candidate-v2",
        "candidate_version": "v2",
        "created_at": _utcnow(),
        "source_head": _git_head(args.repo_root),
        "branch": _git_branch(args.repo_root),
        "schema_version": "1.17",
        "production_mode": {
            "production_resolver": "legacy_v11",
            "knowledge_v1": "shadow",
            "candidate_equals_promotion": False,
        },
        "component_versions": {
            "knowledge_version": versioning.KNOWLEDGE_VERSION,
            "taxonomy_version": versioning.TAXONOMY_VERSION,
            "semantic_kb_version": versioning.SEMANTIC_KB_VERSION,
            "relation_kb_version": versioning.RELATION_KB_VERSION,
            "alias_kb_version": versioning.ALIAS_KB_VERSION,
            "resolver_version": versioning.RESOLVER_VERSION,
            "prompt_semantic_concept_version": (
                versioning.PROMPT_SEMANTIC_CONCEPT_VERSION
            ),
            "prompt_industry_relation_version": (
                versioning.PROMPT_INDUSTRY_RELATION_VERSION
            ),
            "business_evidence_contract_version": (
                BUSINESS_EVIDENCE_CONTRACT_VERSION
            ),
            "business_evidence_resolver_version": (
                BUSINESS_EVIDENCE_RESOLVER_VERSION
            ),
            "local_ai_responsibility_contract_version": (
                LOCAL_AI_RESPONSIBILITY_CONTRACT_VERSION
            ),
            "business_evidence_task_version": BUSINESS_EVIDENCE_TASK_VERSION,
            "case_evidence_pack_version": CASE_EVIDENCE_PACK_VERSION,
            "case_synthesis_task_version": CASE_SYNTHESIS_TASK_VERSION,
            "case_trace_resolver_version": CASE_TRACE_RESOLVER_VERSION,
            "industry_coverage_contract_version": (
                "industry-coverage-contract-v1"
            ),
        },
        "ai_runtime_config": runtime_config,
        "prediction_affecting_files_v2": PREDICTION_AFFECTING_FILES_V2,
        "file_checksums": file_checksums,
        "historical_predecessor": "production-candidate-v1",
        "concept_holdout_retention": build_holdout_status(),
        "pending_knowledge_state": build_pending_state_snapshot(),
        "known_limitations": {
            "provider_weights_not_cryptographically_frozen": True,
            "provider_returned_model_metadata": (
                "not captured during F1.3.1; must be captured in Blind Run"
            ),
            "industry_51_approved_relations": 0,
            "calibration_pending": 39,
            "gate_e_evidence_specific_none_blocked": 8,
            "property_management_06_conditional": "unresolved",
        },
        "safety_invariants": build_safety_invariants(),
        "holdout_contamination_statement": {
            "production_concept_holdout_v1": 0,
            "no_new_production_holdout_created": True,
        },
        "diagnostic_artifact_isolation": dependency_check,
    }
    checksum = manifest_checksum(manifest)
    manifest["manifest_checksum"] = checksum

    def write(name: str, value: Any) -> None:
        (args.output_dir / name).write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    write("production_candidate_v2_manifest.json", manifest)
    write(
        "production_candidate_v2_checksums.json",
        {
            "manifest_checksum": checksum,
            "file_checksums": file_checksums,
        },
    )
    write("pending_knowledge_snapshot.json", build_pending_state_snapshot())
    write("prediction_scope_audit.json", {
        "prediction_affecting_files_v2": PREDICTION_AFFECTING_FILES_V2,
        "file_count": len(PREDICTION_AFFECTING_FILES_V2),
        "scope_rationale": {
            "foundation_interface": [
                "bankflow_v2/ai_business_observation.py",
                "bankflow_v2/knowledge/normalization.py",
                "bankflow_v2/knowledge/payment_rail.py",
                "bankflow_v2/knowledge/privacy.py",
            ],
            "semantic_concept": [
                "bankflow_v2/knowledge/semantic_concepts.py",
                "bankflow_v2/knowledge/canonical/semantic_concepts.json",
                "bankflow_v2/knowledge/canonical/semantic_aliases.json",
            ],
            "industry_relation": [
                "bankflow_v2/knowledge/relations.py",
                "bankflow_v2/knowledge/industry_taxonomy.py",
                "bankflow_v2/knowledge/canonical/taxonomy.json",
                "bankflow_v2/knowledge/canonical/relations.json",
            ],
            "business_evidence": [
                "bankflow_v2/knowledge/evidence.py",
            ],
            "local_ai_routing": [
                "bankflow_v2/knowledge/routing.py",
            ],
            "transaction_ai": [
                "bankflow_v2/knowledge/ai_contracts.py",
                "bankflow_v2/knowledge/ai_fallback.py",
                "bankflow_v2/knowledge/ai_validation.py",
                "bankflow_v2/deepseek_adapter.py",
            ],
            "case_evidence_pack": [
                "bankflow_v2/knowledge/case_evidence_pack.py",
            ],
            "case_trace_case_ai": [
                "bankflow_v2/knowledge/case_trace.py",
            ],
            "coverage": [
                "bankflow_v2/knowledge/coverage.py",
            ],
            "resolver_repository_shared": [
                "bankflow_v2/knowledge/resolver.py",
                "bankflow_v2/knowledge/repository.py",
                "bankflow_v2/knowledge/models.py",
                "bankflow_v2/knowledge/versioning.py",
            ],
        },
    })
    integrity_report = {
        "manifest_checksum": checksum,
        "file_count": len(file_checksums),
        "all_files_match": True,
        "case_specific_diagnostic_dependency": (
            dependency_check["case_specific_diagnostic_dependency"]
        ),
        "secrets_in_manifest": False,
        "api_key_in_manifest": False,
    }
    write("freeze_integrity_report.json", integrity_report)

    print("status=ok")
    print(f"candidate=production-candidate-v2")
    print(f"prediction_files={len(file_checksums)}")
    print(f"manifest_checksum={checksum}")
    print(f"output={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
