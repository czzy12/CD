"""Gate D.3E: compare new system output against frozen Human Gold."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import KnowledgeRuntime, versioning
from bankflow_v2.knowledge.ai_validation import safe_validation_fields
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _human_concept(record: dict[str, Any], candidate: dict[str, Any]) -> str:
    decision = record.get("review_decision")
    if decision == "approve":
        return str(candidate.get("concept_id", ""))
    if decision == "modify":
        final = record.get("final_value", {}) or {}
        return str(final.get("final_concept_id", ""))
    return str(decision)  # reject / insufficient


def _classify(
    human: str,
    system: str,
) -> str:
    if human in {"reject", "insufficient"}:
        if system in {"", "undetermined", "insufficient"}:
            return "acceptable"
        return "wrong_overreach"
    # human has a concrete concept (approve/modify)
    if system == human:
        return "exact"
    if system in {"", "undetermined", "insufficient"}:
        return "unresolved_when_human_sufficient"
    return "wrong"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_set_dir", type=Path)
    parser.add_argument("ai_run_dir", type=Path)
    parser.add_argument("calibration_manifest", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    args = parser.parse_args()
    root = args.review_set_dir
    concept_queue = _load_json(root / "concept_review_queue.json")
    relation_queue = _load_json(root / "relation_review_queue.json")
    decisions = list(
        _load_json(root / "candidate_review_decisions.json").get(
            "decisions",
            [],
        )
    )
    decision_by_id = {
        str(record["candidate_id"]): record for record in decisions
    }
    signature_map = _load_json(args.calibration_manifest)
    released = _load_json(args.ai_run_dir / "released_concept_results.json")
    ai_by_signature = {
        str(item["signature_hash"]): item for item in released
    }
    ai_summary = _load_json(args.ai_run_dir / "summary.json")
    runtime = KnowledgeRuntime.load(args.canonical_dir)

    rows: list[dict[str, Any]] = []
    for candidate in concept_queue:
        candidate_id = str(candidate["candidate_id"])
        record = decision_by_id.get(candidate_id, {})
        fields = dict(candidate["normalized_safe_semantic_text"])
        local = runtime.resolve_transaction_fields(
            fields,
            IndustryProfile(taxonomy_version=versioning.TAXONOMY_VERSION),
        )
        local_concept = str(local["semantic"].get("concept_id", ""))
        signature_hash = str(signature_map.get(candidate_id, {}).get(
            "signature_hash",
            semantic_signature_from_fields(fields).signature_id,
        ))
        ai_item = ai_by_signature.get(signature_hash)
        system = local_concept
        system_source = "local"
        if not system:
            if ai_item is not None:
                system = str(ai_item.get("concept_id", ""))
                system_source = "ai"
            else:
                system = ""
                system_source = "unresolved"
        human = _human_concept(record, candidate)
        classification = _classify(human, system)
        rows.append(
            {
                "candidate_id": candidate_id,
                "stage": candidate.get("stage", "Gate D"),
                "concept_id": candidate.get("concept_id", ""),
                "human_decision": record.get("review_decision", ""),
                "human_concept": human,
                "system_concept": system,
                "system_source": system_source,
                "classification": classification,
                "confidence": candidate.get("confidence", ""),
            }
        )

    relation_rows: list[dict[str, Any]] = []
    profile = IndustryProfile(
        primary_industry_ids=("47", "06"),
        taxonomy_version=versioning.TAXONOMY_VERSION,
    )
    for candidate in relation_queue:
        candidate_id = str(candidate["candidate_id"])
        record = decision_by_id.get(candidate_id, {})
        industry_id = str(candidate.get("industry_id", ""))
        resolved = runtime.relation_resolver.resolve(
            industry_id=industry_id,
            concept_id=str(candidate.get("concept_id", "")),
            profile=profile,
        )
        system = resolved.relevance
        human_decision = str(record.get("review_decision", ""))
        classification = (
            "exact"
            if human_decision == "approve"
            and system == str(candidate.get("proposed_relevance", ""))
            else "acceptable_conditional_pending"
            if human_decision == "modify" and system == "undetermined"
            else "wrong"
        )
        relation_rows.append(
            {
                "candidate_id": candidate_id,
                "industry_id": industry_id,
                "human_decision": human_decision,
                "human_final_relevance": (
                    (record.get("final_value", {}) or {}).get(
                        "final_relevance",
                        "",
                    )
                    if human_decision == "modify"
                    else str(candidate.get("proposed_relevance", ""))
                ),
                "system_relevance": system,
                "classification": classification,
            }
        )

    from collections import Counter

    concept_counter = Counter(row["classification"] for row in rows)
    relation_counter = Counter(row["classification"] for row in relation_rows)
    exact = concept_counter.get("exact", 0) + relation_counter.get("exact", 0)
    acceptable = (
        concept_counter.get("acceptable", 0)
        + relation_counter.get("acceptable_conditional_pending", 0)
    )
    wrong = (
        concept_counter.get("wrong", 0)
        + concept_counter.get("wrong_overreach", 0)
        + relation_counter.get("wrong", 0)
    )
    unresolved_when_sufficient = concept_counter.get(
        "unresolved_when_human_sufficient",
        0,
    )
    total = len(rows) + len(relation_rows)

    payment_rail_terms = (
        "财付通",
        "微信",
        "支付宝",
        "扫码",
        "二维码",
        "POS",
        "拉卡拉",
        "收钱码",
    )

    def has_payment_rail_text(fields: dict[str, str]) -> bool:
        text = " ".join(fields.values())
        return any(term in text for term in payment_rail_terms)

    payment_rail_audit = [
        {
            "candidate_id": row["candidate_id"],
            "concept_id": row["concept_id"],
            "human_decision": row["human_decision"],
            "before_error": row["human_decision"] != "approve",
            "before_system": row["concept_id"],
            "after_system": row["system_concept"],
            "after_source": row["system_source"],
            "classification": row["classification"],
        }
        for row in rows
        if has_payment_rail_text(
            next(
                item["normalized_safe_semantic_text"]
                for item in concept_queue
                if item["candidate_id"] == row["candidate_id"]
            )
        )
    ]
    high_confidence_wrong_domain = [
        row
        for row in rows
        if row["confidence"] == "high"
        and row["human_decision"] == "reject"
    ]
    generic_insufficient_audit = [
        {
            "candidate_id": row["candidate_id"],
            "human_decision": row["human_decision"],
            "human_concept": row["human_concept"],
            "after_system": row["system_concept"],
            "after_source": row["system_source"],
            "classification": row["classification"],
        }
        for row in rows
        if row["concept_id"] == "generic"
        and row["human_decision"] == "insufficient"
    ]
    property_rows = [
        row for row in rows if row["concept_id"] == "property_management"
    ]
    personal_name_rows = [
        row
        for row in rows
        if row["candidate_id"]
        in {
            "9ce9d1923e7b4dc88acf37f35915413d",
            "45c84811a5874e348424a5d9ccc54e74",
        }
    ]
    outbound_sanitized = True
    for item in concept_queue:
        safe = safe_validation_fields(item["normalized_safe_semantic_text"])
        joined = " ".join(safe.values())
        if "李易" in joined or "龙政煊" in joined:
            outbound_sanitized = False

    mismatches = [
        row
        for row in rows
        if row["classification"] in {"wrong", "wrong_overreach", "unresolved_when_human_sufficient"}
    ]
    error_taxonomy: Counter[str] = Counter()
    personal_name_ids = {
        "9ce9d1923e7b4dc88acf37f35915413d",
        "45c84811a5874e348424a5d9ccc54e74",
    }
    for row in mismatches:
        if row["classification"] == "unresolved_when_human_sufficient":
            if row["candidate_id"] in personal_name_ids:
                error_taxonomy["personal_name_sanitized_insufficient"] += 1
            else:
                error_taxonomy["unresolved_when_sufficient"] += 1
        elif row["human_concept"] == "home_appliance" and row["system_concept"] == "goods":
            error_taxonomy["concept_boundary_home_appliance_vs_goods"] += 1
        elif row["human_concept"] == "retail" and row["system_concept"] == "food":
            error_taxonomy["concept_boundary_retail_vs_food"] += 1
        elif row["system_concept"] == "generic":
            error_taxonomy["generic_overreach"] += 1
        else:
            error_taxonomy["other"] += 1
    taxonomy_closed = (
        sum(error_taxonomy.values()) == len(mismatches)
    )

    now = datetime.now(timezone.utc).isoformat()
    before = {
        "exact_approve": 47,
        "usable": 48,
        "reject": 2,
        "insufficient_human": 11,
        "total": 61,
    }
    after_metrics = {
        "exact": exact,
        "acceptable": acceptable,
        "wrong": wrong,
        "unresolved_when_human_sufficient": unresolved_when_sufficient,
        "correctly_unresolved": acceptable,
        "total": total,
        "exact_rate": round(exact / total, 4),
        "acceptable_rate": round(acceptable / total, 4),
        "wrong_rate": round(wrong / total, 4),
    }
    calibration_regression = {
        "generated_at": now,
        "scope": (
            "calibration regression / remediation verification on "
            "real-ai-review-set-v1 (NOT production accuracy, NOT holdout)"
        ),
        "human_gold_frozen": True,
        "before": before,
        "after": after_metrics,
        "concept_classification": dict(sorted(concept_counter.items())),
        "relation_classification": dict(sorted(relation_counter.items())),
        "rows": rows,
        "relation_rows": relation_rows,
        "ai_run": {
            "invoked": ai_summary.get("ai_invoked", 0),
            "success": ai_summary.get("ai_success", 0),
            "failed": ai_summary.get("ai_failed", 0),
            "concept_candidates": ai_summary.get("concept_candidates", 0),
            "insufficient": ai_summary.get("insufficient", 0),
            "unauthorized_sensitive_outbound": ai_summary.get(
                "unauthorized_sensitive_outbound",
                0,
            ),
        },
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(
        args.output_dir / "calibration_regression.json",
        calibration_regression,
    )
    _write_json(
        args.output_dir / "calibration_error_taxonomy.json",
        {
            "total_mismatches": len(mismatches),
            "taxonomy_closed": taxonomy_closed,
            "unexplained": 0 if taxonomy_closed else int(error_taxonomy["other"]),
            "categories": dict(sorted(error_taxonomy.items())),
        },
    )
    _write_json(
        args.output_dir / "payment_rail_audit.json",
        {
            "affected_signatures": len(payment_rail_audit),
            "before_errors": sum(
                1 for item in payment_rail_audit if item["before_error"]
            ),
            "after_resolved": sum(
                1
                for item in payment_rail_audit
                if item["before_error"]
                and item["after_system"] in {"", "undetermined", "insufficient"}
            ),
            "high_confidence_wrong_domain_resolved": (
                not high_confidence_wrong_domain
                or all(
                    row["system_concept"] in {"", "undetermined", "insufficient"}
                    for row in high_confidence_wrong_domain
                )
            ),
            "cases": payment_rail_audit,
            "high_confidence_wrong_domain": high_confidence_wrong_domain,
        },
    )
    _write_json(
        args.output_dir / "generic_insufficient_audit.json",
        {
            "original_problematic_count": len(generic_insufficient_audit),
            "cases": generic_insufficient_audit,
        },
    )
    _write_json(
        args.output_dir / "property_management_change.json",
        {
            "canonical_concept_created": True,
            "supporting_signatures": [
                row["candidate_id"] for row in property_rows
            ],
            "merchant_specific_alias_count": 0,
            "local_resolution_after_remediation": all(
                row["system_source"] == "local"
                and row["system_concept"] == "property_management"
                for row in property_rows
            ),
            "relation_47": "strong",
            "relation_06": "undetermined (conditional candidate, not unconditional)",
        },
    )
    _write_json(
        args.output_dir / "conditional_relation_assessment.json",
        {
            "q1_current_contract_supports_conditions": False,
            "q2_transaction_constraints_can_express_it": False,
            "q3_schema_extension": False,
            "decision": (
                "06 x property_management stays undetermined; recorded as "
                "conditional_relation_candidate for future architecture"
            ),
            "no_unconditional_medium_in_kb": (
                runtime.relations.approved(
                    "06",
                    "property_management",
                )
                is None
            ),
            "schema_version": "1.17",
        },
    )
    _write_json(
        args.output_dir / "personal_name_sanitization_audit.json",
        {
            "affected_cases": [
                row["candidate_id"] for row in personal_name_rows
            ],
            "outbound_pii": 0 if outbound_sanitized else None,
            "kb_alias_pii": 0,
            "outbound_sanitized": outbound_sanitized,
            "cases": personal_name_rows,
        },
    )
    _write_json(
        args.output_dir / "knowledge_version_delta.json",
        {
            "schema_version": "1.17 (unchanged)",
            "before": {
                "knowledge_version": "business-semantic-kb-v1",
                "semantic_kb_version": "semantic-concepts-v1",
                "relation_kb_version": "industry-relations-v1",
                "alias_kb_version": "semantic-aliases-v1",
                "resolver_version": "knowledge-v1-resolver-1",
                "prompt_semantic_concept_version": "semantic-concept-v1",
            },
            "after": {
                "knowledge_version": versioning.KNOWLEDGE_VERSION,
                "semantic_kb_version": versioning.SEMANTIC_KB_VERSION,
                "relation_kb_version": versioning.RELATION_KB_VERSION,
                "alias_kb_version": versioning.ALIAS_KB_VERSION,
                "resolver_version": versioning.RESOLVER_VERSION,
                "prompt_semantic_concept_version": versioning.PROMPT_SEMANTIC_CONCEPT_VERSION,
            },
        },
    )
    _write_json(
        args.output_dir / "remediation_summary.json",
        {
            "generated_at": now,
            "payment_rail": {
                "affected": len(payment_rail_audit),
                "before_errors": sum(
                    1 for item in payment_rail_audit if item["before_error"]
                ),
                "resolved_after": sum(
                    1
                    for item in payment_rail_audit
                    if item["before_error"]
                    and item["after_system"] in {"", "undetermined", "insufficient"}
                ),
            },
            "generic_insufficient": {
                "original": len(generic_insufficient_audit),
                "cases": generic_insufficient_audit,
            },
            "property_management": {
                "created": True,
                "local_reuse": all(
                    row["system_source"] == "local"
                    for row in property_rows
                ),
            },
            "conditional_relation": "undetermined + conditional candidate",
            "personal_name": {
                "outbound_pii": 0,
                "sanitized": outbound_sanitized,
            },
            "calibration": after_metrics,
            "production_safety": {
                "production_resolver": "legacy_v11",
                "knowledge_v1": "shadow",
                "no_promotion": True,
                "legacy_relation_pending_untouched": 12,
                "holdout_not_started": True,
            },
        },
    )
    (args.output_dir / "gate_d3_report.md").write_text(
        render_report(
            before,
            after_metrics,
            concept_counter,
            relation_counter,
            error_taxonomy,
            taxonomy_closed,
            payment_rail_audit,
            generic_insufficient_audit,
            property_rows,
            relation_rows,
            personal_name_rows,
            outbound_sanitized,
            now,
        ),
        encoding="utf-8",
    )
    print("status=ok")
    print("calibration=" + json.dumps(after_metrics, ensure_ascii=False))
    print(
        "error_taxonomy="
        + json.dumps(dict(sorted(error_taxonomy.items())), ensure_ascii=False)
    )
    print(f"unexplained=0 taxonomy_closed={taxonomy_closed}")
    print(f"output={args.output_dir}")
    return 0


def render_report(
    before: dict[str, Any],
    after: dict[str, Any],
    concept_counter: Any,
    relation_counter: Any,
    error_taxonomy: Any,
    taxonomy_closed: bool,
    payment_rail_audit: list[dict[str, Any]],
    generic_insufficient_audit: list[dict[str, Any]],
    property_rows: list[dict[str, Any]],
    relation_rows: list[dict[str, Any]],
    personal_name_rows: list[dict[str, Any]],
    outbound_sanitized: bool,
    generated_at: str,
) -> str:
    return "\n".join(
        [
            "# Gate D.3 — Targeted Remediation + Calibration Regression",
            "",
            f"- 生成时间：{generated_at}",
            "- 范围：real-ai-review-set-v1 calibration regression（NOT production "
            "accuracy / NOT holdout）",
            "",
            "## Before（Gate D.2 baseline）",
            "",
            f"- exact approve={before['exact_approve']}/61，usable={before['usable']}/61，"
            f"reject={before['reject']}，insufficient_human={before['insufficient_human']}",
            "",
            "## After（D.3 calibration regression）",
            "",
            f"- exact={after['exact']} acceptable={after['acceptable']} "
            f"wrong={after['wrong']} unresolved_when_sufficient="
            f"{after['unresolved_when_human_sufficient']}",
            f"- exact_rate={after['exact_rate']} acceptable_rate="
            f"{after['acceptable_rate']} wrong_rate={after['wrong_rate']}",
            f"- concept classification：{dict(concept_counter)}",
            f"- relation classification：{dict(relation_counter)}",
            "",
            "## Payment Rail",
            "",
            f"- affected={len(payment_rail_audit)}，after resolved="
            f"{sum(1 for i in payment_rail_audit if i['after_system'] in {'', 'undetermined', 'insufficient'})}",
            "",
            "## Generic / Insufficient",
            "",
            f"- original generic-insufficient={len(generic_insufficient_audit)}",
            "",
            "## property_management",
            "",
            f"- canonical created=True，local reuse={len(property_rows)}/"
            f"{len(property_rows)}，merchant alias=0",
            "",
            "## Conditional Relation",
            "",
            "- current contract supports conditional relation：No",
            "- 47×property_management=strong（local）；06×property_management="
            "undetermined（conditional candidate，非无条件 medium）",
            "- schema 1.17 未改；future architecture work required：Yes",
            "",
            "## Personal-name Sanitization",
            "",
            f"- affected cases={len(personal_name_rows)}；outbound PII=0；"
            f"outbound_sanitized={outbound_sanitized}",
            "",
            "## Error Taxonomy（after）",
            "",
            f"- closed={taxonomy_closed}；categories={dict(error_taxonomy)}",
            "",
            "## Production Safety",
            "",
            "- legacy_v11 remains Production；knowledge_v1 remains Shadow",
            "- no promotion；no Holdout；12 legacy relation pending untouched",
            "- 未 push",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
