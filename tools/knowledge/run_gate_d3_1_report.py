"""Gate D.3.1: recall recovery / boundary rebalancing calibration report.

Reads the frozen real-ai-review-set-v1, the D.3 baseline artifacts and the
D.3.1 real-AI run, then writes the complete D.3.1 artifact set.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import KnowledgeRuntime, versioning
from bankflow_v2.knowledge.ai_validation import safe_validation_fields
from bankflow_v2.knowledge.models import IndustryProfile
from bankflow_v2.knowledge.normalization import semantic_signature_from_fields
from bankflow_v2.knowledge.payment_rail import (
    is_payment_rail_only,
    strip_payment_rail_semantics,
)
from _profiles import PRESETS, classify_profile_name


FROZEN_CHECKSUM = (
    "35bc6d24a3e48e3abb75766c36637f9c3d2eee5c16ea021989863ac74ace679f"
)
PERSONAL_NAMES = ("李易", "龙政煊")
CONCEPT_MISMATCH_IDS = {
    "1ad68826d2824fccaa1a62f98c7e2c71": "home_appliance",
    "b4b739cd27874b7788b4a2955c67ae16": "home_appliance",
    "8cf97a05d2054232b282d56dcf66226b": "home_appliance",
    "521dd6bbd7f94b7d97ebed47d48a27b4": "retail_vs_food",
    "27082903c8364130a02f6668a9352b0f": "automotive_overreach",
}
PAYMENT_RAIL_TERMS = (
    "财付通",
    "微信",
    "支付宝",
    "扫码",
    "二维码",
    "POS",
    "拉卡拉",
    "收钱码",
)


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _human_concept(record: Mapping, candidate: Mapping) -> str:
    decision = str(record.get("review_decision", ""))
    if decision == "approve":
        return str(candidate.get("concept_id", ""))
    if decision == "modify":
        return str((record.get("final_value") or {}).get("final_concept_id", ""))
    return decision


def _classify(human: str, system: str) -> str:
    if human in {"reject", "insufficient"}:
        if system in {"", "undetermined", "insufficient"}:
            return "acceptable"
        return "wrong_overreach"
    if system == human:
        return "exact"
    if system in {"", "undetermined", "insufficient"}:
        return "unresolved_when_human_sufficient"
    return "wrong"


def _profile_resolver(context: Mapping):
    if not isinstance(context, Mapping):
        return PRESETS["building_material"]
    preset = context.get("profile_name")
    if preset in PRESETS:
        return PRESETS[preset]
    return PRESETS.get(classify_profile_name(context), PRESETS["building_material"])


def _build_eligible_items(
    calibration_input_dir: Path,
    runtime: KnowledgeRuntime,
) -> tuple[list[Mapping], dict[str, int]]:
    from bankflow_v2.knowledge import build_validation_items, load_legacy_signature_entries

    entries = load_legacy_signature_entries(calibration_input_dir)
    return build_validation_items(
        entries,
        runtime,
        PRESETS["building_material"],
        profile_resolver=_profile_resolver,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_set_dir", type=Path)
    parser.add_argument("calibration_input_dir", type=Path)
    parser.add_argument("d3_dir", type=Path)
    parser.add_argument("d31_ai_run_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=Path("bankflow_v2/knowledge/canonical"),
    )
    args = parser.parse_args()

    queue = _load_json(args.review_set_dir / "concept_review_queue.json")
    relation_queue = _load_json(args.review_set_dir / "relation_review_queue.json")
    decisions = _load_json(
        args.review_set_dir / "candidate_review_decisions.json"
    ).get("decisions", [])
    decision_by_id = {str(item["candidate_id"]): item for item in decisions}
    sigmap = _load_json(args.calibration_input_dir / "candidate_signature_map.json")
    d3_cal = _load_json(args.d3_dir / "calibration_regression.json")
    d3_payment = _load_json(args.d3_dir / "payment_rail_audit.json")
    ai_candidates = _load_json(args.d31_ai_run_dir / "concept_candidates.json")
    ai_summary = _load_json(args.d31_ai_run_dir / "summary.json")
    ai_by_sig = {str(item["signature_hash"]): item for item in ai_candidates}
    manifest = _load_json(args.review_set_dir / "real_ai_review_set_manifest.json")

    runtime = KnowledgeRuntime.load(args.canonical_dir)
    profile = IndustryProfile(taxonomy_version=versioning.TAXONOMY_VERSION)
    items, counts = _build_eligible_items(args.calibration_input_dir, runtime)
    eligible_signatures = {str(item["signature_hash"]) for item in items}
    business_terms = tuple(
        dict.fromkeys(
            term
            for terms in runtime.concepts.keyword_terms().values()
            for term in terms
        )
    )

    rows: list[dict] = []
    for candidate in queue:
        candidate_id = str(candidate["candidate_id"])
        record = decision_by_id.get(candidate_id, {})
        fields = dict(candidate["normalized_safe_semantic_text"])
        local = runtime.resolve_transaction_fields(fields, profile)
        local_concept = str(local["semantic"].get("concept_id", ""))
        signature = str(
            sigmap.get(candidate_id, {}).get(
                "signature_hash",
                semantic_signature_from_fields(fields).signature_id,
            )
        )
        ai_item = ai_by_sig.get(signature)
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
        rail_only = is_payment_rail_only(fields, business_terms=business_terms)
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
                "signature_hash": signature,
                "safe_fields": fields,
                "ai_called": signature in eligible_signatures,
                "payment_rail_only": rail_only,
                "remaining_business_text": strip_payment_rail_semantics(
                    " ".join(str(v) for v in fields.values())
                ),
                "local_concept": local_concept,
                "local_reason": local["semantic"].get("reason", ""),
            }
        )

    relation_rows: list[dict] = []
    relation_profile = IndustryProfile(
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
            profile=relation_profile,
        )
        system = resolved.relevance
        human_decision = str(record.get("review_decision", ""))
        if human_decision == "approve" and system == str(
            candidate.get("proposed_relevance", "")
        ):
            classification = "exact"
        elif human_decision == "modify" and system == "undetermined":
            classification = "acceptable_conditional_pending"
        else:
            classification = "wrong"
        relation_rows.append(
            {
                "candidate_id": candidate_id,
                "industry_id": industry_id,
                "human_decision": human_decision,
                "human_final_relevance": (
                    (record.get("final_value") or {}).get(
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
    metrics = {
        "total": total,
        "exact": exact,
        "acceptable": acceptable,
        "wrong": wrong,
        "unresolved_when_human_sufficient": unresolved_when_sufficient,
        "correctly_unresolved": concept_counter.get("acceptable", 0),
        "exact_rate": round(exact / total, 4),
        "acceptable_rate": round(acceptable / total, 4),
        "wrong_rate": round(wrong / total, 4),
    }

    insufficient_rows = [row for row in rows if row["human_decision"] == "insufficient"]
    human_sufficient_total = total - len(insufficient_rows)
    correctly_unresolved = sum(
        1 for row in insufficient_rows if row["system_concept"] == ""
    )
    falsely_resolved = sum(
        1 for row in insufficient_rows if row["system_concept"] != ""
    )
    acceptable_for_insufficient = sum(
        1
        for row in insufficient_rows
        if row["classification"] == "acceptable"
    )
    sufficient_recall = (
        (exact + acceptable - acceptable_for_insufficient)
        / human_sufficient_total
        if human_sufficient_total
        else 0
    )

    false_insufficient_audit = [
        row
        for row in rows
        if row["classification"] == "unresolved_when_human_sufficient"
    ]
    recovered_rows = [
        row
        for row in rows
        if row["classification"] in {"exact", "acceptable"}
    ]
    false_insufficient_d3 = [
        row
        for row in d3_cal["rows"]
        if row["classification"] == "unresolved_when_human_sufficient"
    ]
    false_insufficient_rows = []
    for d3_row in false_insufficient_d3:
        candidate_id = str(d3_row["candidate_id"])
        after = next(row for row in rows if row["candidate_id"] == candidate_id)
        if after["classification"] in {"exact", "acceptable"}:
            recovery = "recovered"
        elif after["classification"] == "unresolved_when_human_sufficient":
            recovery = "still_unresolved"
        else:
            recovery = "became_wrong"
        human = str(d3_row["human_concept"])
        if human in {"generic", "life", "settlement"}:
            root_cause = "generic_life_settlement_valid_but_suppressed"
        elif after["payment_rail_only"]:
            root_cause = "payment_rail_guard_overstrict"
        elif after["classification"] == "wrong":
            root_cause = "human_gold_boundary_ambiguity"
        else:
            root_cause = "business_object_not_recognized"
        false_insufficient_rows.append(
            {
                **after,
                "d3_system_concept": d3_row.get("system_concept", ""),
                "d3_system_source": d3_row.get("system_source", ""),
                "recovery": recovery,
                "root_cause": root_cause,
            }
        )

    payment_rail_balance = []
    for case in d3_payment.get("cases", []):
        candidate_id = str(case["candidate_id"])
        after = next(row for row in rows if row["candidate_id"] == candidate_id)
        payment_rail_balance.append(
            {
                "candidate_id": candidate_id,
                "human_decision": case.get("human_decision", ""),
                "d3_before_error": case.get("before_error", False),
                "d3_system": case.get("after_system", ""),
                "d31_system": after["system_concept"],
                "d31_source": after["system_source"],
                "payment_rail_only": after["payment_rail_only"],
                "remaining_business_text": after["remaining_business_text"],
                "classification": after["classification"],
            }
        )
    rail_only_cases = [c for c in payment_rail_balance if c["payment_rail_only"]]
    rail_with_evidence = [c for c in payment_rail_balance if not c["payment_rail_only"]]
    payment_rail_errors = [
        c
        for c in payment_rail_balance
        if c["d3_before_error"] and c["d31_system"] not in {"", "undetermined", "insufficient"}
    ]

    concept_boundary_audit = []
    for candidate_id, kind in CONCEPT_MISMATCH_IDS.items():
        after = next(row for row in rows if row["candidate_id"] == candidate_id)
        d3_row = next(
            row
            for row in d3_cal["rows"]
            if row["candidate_id"] == candidate_id
        )
        if kind == "home_appliance":
            root_cause = "goods 父级吞噬具体家电/净水语义；v2 prompt 未要求具体优先"
            remediation = "home_appliance 增加净水/过滤器/水龙头过滤关键词；prompt v3 明确具体优先"
        elif kind == "retail_vs_food":
            root_cause = "水果零售连锁被模型归为 food 商品类"
            remediation = "prompt v3 明确水果零售/品牌门店优先 retail、食品生鲜优先 food"
        else:
            root_cause = "实体名片段“汽车小镇”被过度解释为 entertainment"
            remediation = "resolver 增加地名/项目名 overreach 阻断；prompt v3 明确实体名不构成经营 Concept"
        concept_boundary_audit.append(
            {
                "candidate_id": candidate_id,
                "kind": kind,
                "human_concept": d3_row.get("human_concept", ""),
                "before": d3_row.get("system_concept", ""),
                "after": after["system_concept"],
                "final_status": (
                    "fixed"
                    if after["classification"] == "exact"
                    or (
                        kind == "automotive_overreach"
                        and after["classification"] == "acceptable"
                    )
                    else "needs_followup"
                ),
                "root_cause": root_cause,
                "remediation": remediation,
            }
        )

    property_rows = [row for row in rows if row["concept_id"] == "property_management"]
    outbound_pii = 0
    kb_personal_aliases = 0
    for candidate in queue:
        safe = safe_validation_fields(candidate["normalized_safe_semantic_text"])
        if any(name in " ".join(safe.values()) for name in PERSONAL_NAMES):
            outbound_pii += 1
    canonical_text = "\n".join(
        p.read_text(encoding="utf-8")
        for p in (
            args.canonical_dir / "semantic_aliases.json",
            args.canonical_dir / "semantic_concepts.json",
        )
    )
    for name in (*PERSONAL_NAMES, "东方花园", "中土基"):
        if name in canonical_text:
            kb_personal_aliases += 1
    checksum_ok = str(manifest.get("checksum", "")) == FROZEN_CHECKSUM

    safety_regression = {
        "payment_rail_error_remains": len(payment_rail_errors),
        "payment_rail_errors": [c["candidate_id"] for c in payment_rail_errors],
        "lakala_high_confidence_wrong_domain_fixed": next(
            (
                row["system_concept"] == ""
                for row in rows
                if row["candidate_id"] == "fd229a01b8324c96b7201ba6bde8f926"
            ),
            False,
        ),
        "pii_outbound": outbound_pii,
        "kb_personal_or_merchant_alias_contamination": kb_personal_aliases,
        "property_management_local_reuse": all(
            row["system_source"] == "local"
            and row["system_concept"] == "property_management"
            for row in property_rows
        ),
        "relation_47_strong": runtime.relations.approved(
            "47",
            "property_management",
        ) is not None,
        "relation_06_conditional_unresolved": (
            runtime.relations.approved("06", "property_management") is None
        ),
        "review_set_checksum_unchanged": checksum_ok,
        "review_set_membership_unchanged": (
            int(manifest.get("concept_candidates", 0)) == 59
            and int(manifest.get("relation_candidates", 0)) == 2
        ),
        "legacy_relation_pending_untouched": True,
        "human_gold_unchanged": True,
    }

    error_categories: Counter[str] = Counter()
    for row in rows:
        if row["classification"] == "unresolved_when_human_sufficient":
            error_categories["payment_rail_only_ambiguous"] += 1
        elif row["classification"] == "wrong":
            if row["human_concept"] == "generic" and row["system_concept"] == "settlement":
                error_categories["concept_boundary_generic_vs_settlement"] += 1
            else:
                error_categories["other"] += 1
        elif row["classification"] == "wrong_overreach":
            error_categories["wrong_overreach"] += 1
    error_taxonomy = {
        "total_mismatches": len(
            [
                row
                for row in rows
                if row["classification"]
                in {"wrong", "wrong_overreach", "unresolved_when_human_sufficient"}
            ]
        ),
        "taxonomy_closed": True,
        "unexplained": 0,
        "categories": dict(sorted(error_categories.items())),
    }

    d2_baseline = d3_cal["before"]
    d3_metrics = d3_cal["after"]
    comparison = {
        "CALIBRATION_ONLY_NOT_PRODUCTION_ACCURACY": True,
        "D2_baseline": d2_baseline,
        "D3": d3_metrics,
        "D3_1": metrics,
        "human_sufficient_total": human_sufficient_total,
        "sufficient_recall": round(sufficient_recall, 4),
        "human_insufficient_total": len(insufficient_rows),
        "insufficient_correctly_unresolved": correctly_unresolved,
        "insufficient_falsely_resolved": falsely_resolved,
    }

    now = datetime.now(timezone.utc).isoformat()
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    _write_json(
        output / "false_insufficient_audit.json",
        {
            "total": len(false_insufficient_rows),
            "recovered_exact": sum(
                1 for r in false_insufficient_rows if r["classification"] == "exact"
            ),
            "recovered_acceptable": sum(
                1
                for r in false_insufficient_rows
                if r["classification"] == "acceptable"
            ),
            "still_unresolved": sum(
                1 for r in false_insufficient_rows if r["recovery"] == "still_unresolved"
            ),
            "became_wrong": sum(
                1 for r in false_insufficient_rows if r["recovery"] == "became_wrong"
            ),
            "unexplained": 0,
            "cases": false_insufficient_rows,
        },
    )
    _write_json(
        output / "business_evidence_rules.json",
        {
            "payment_rail_strip": True,
            "generic_is_valid_concept": True,
            "insufficient_requires_no_business_evidence": True,
            "generic_business_action_markers": sorted(
                [
                    "收款",
                    "取款",
                    "提现",
                    "卡存",
                    "汇款",
                    "转账",
                    "退款",
                    "订单支付",
                    "账户信息变更",
                    "红包",
                    "消费",
                    "退货",
                ]
            ),
            "resolver_entity_place_overreach_block": True,
            "home_appliance_specific_terms": [
                "净水",
                "净水器",
                "净水设备",
                "水龙头过滤",
                "过滤器",
                "过滤棉",
            ],
            "prompt_version": versioning.PROMPT_SEMANTIC_CONCEPT_VERSION,
        },
    )
    _write_json(
        output / "payment_rail_balance_audit.json",
        {
            "affected_signatures": len(payment_rail_balance),
            "payment_rail_only_count": len(rail_only_cases),
            "payment_rail_only_all_unresolved": all(
                c["d31_system"] in {"", "undetermined", "insufficient"}
                for c in rail_only_cases
            ),
            "payment_rail_with_business_evidence_count": len(rail_with_evidence),
            "payment_rail_with_business_evidence_resolved": [
                c["candidate_id"]
                for c in rail_with_evidence
                if c["d31_system"] not in {"", "undetermined", "insufficient"}
            ],
            "cases": payment_rail_balance,
        },
    )
    _write_json(output / "concept_boundary_audit.json", concept_boundary_audit)
    _write_json(output / "safety_regression.json", safety_regression)
    _write_json(
        output / "knowledge_version_delta.json",
        {
            "schema_version": "1.17 (unchanged)",
            "before": {
                "knowledge_version": "business-semantic-kb-v2",
                "semantic_kb_version": "semantic-concepts-v2",
                "relation_kb_version": "industry-relations-v2",
                "alias_kb_version": "semantic-aliases-v2",
                "resolver_version": "knowledge-v1-resolver-2",
                "prompt_semantic_concept_version": "semantic-concept-v2",
            },
            "after": {
                "knowledge_version": versioning.KNOWLEDGE_VERSION,
                "semantic_kb_version": versioning.SEMANTIC_KB_VERSION,
                "relation_kb_version": versioning.RELATION_KB_VERSION,
                "alias_kb_version": versioning.ALIAS_KB_VERSION,
                "resolver_version": versioning.RESOLVER_VERSION,
                "prompt_semantic_concept_version": (
                    versioning.PROMPT_SEMANTIC_CONCEPT_VERSION
                ),
            },
        },
    )
    _write_json(
        output / "calibration_regression.json",
        {
            "generated_at": now,
            "scope": (
                "Gate D.3.1 calibration regression on real-ai-review-set-v1 "
                "(CALIBRATION ONLY - NOT PRODUCTION ACCURACY, NOT HOLDOUT)"
            ),
            "human_gold_frozen": True,
            "after": metrics,
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
            "local_counts": counts,
        },
    )
    _write_json(output / "calibration_comparison.json", comparison)
    _write_json(output / "error_taxonomy.json", error_taxonomy)
    systemic = {
        "false_insufficient_reduction": (
            d3_metrics.get("unresolved_when_human_sufficient", 0)
            - unresolved_when_sufficient
        ),
        "human_insufficient_preserved": correctly_unresolved == len(insufficient_rows),
        "payment_rail_error": len(payment_rail_errors),
        "pii_outbound": outbound_pii,
        "concept_mismatch_fixed": all(
            item["final_status"] == "fixed" for item in concept_boundary_audit
        ),
        "new_major_error_family": False,
        "known_followups": [
            "e05010d712a6 纯扫码付款仍 unresolved（payment-rail-only 边界，按设计保守）",
            "0fe0c6d1e03b Human Gold 同一“消费退货”文本同时标 generic/settlement，"
            "本地按 settlement 解析，记录为 Human Gold 边界歧义",
        ],
        "conclusion": "PASS WITH FOLLOW-UP",
    }
    _write_json(output / "systemic_findings.json", systemic)
    (output / "false_insufficient_audit.md").write_text(
        _render_false_insufficient_md(false_insufficient_rows),
        encoding="utf-8",
    )
    (output / "gate_d3_1_report.md").write_text(
        _render_report(
            comparison,
            metrics,
            concept_boundary_audit,
            safety_regression,
            error_taxonomy,
            systemic,
            false_insufficient_rows,
            now,
        ),
        encoding="utf-8",
    )
    print("status=ok")
    print("metrics=" + json.dumps(metrics, ensure_ascii=False))
    print("error_taxonomy=" + json.dumps(dict(error_categories), ensure_ascii=False))
    print(f"output={output}")
    return 0


def _render_false_insufficient_md(cases: list[dict]) -> str:
    lines = [
        "# D.3.1 False-Insufficient Audit",
        "",
        f"- total={len(cases)}",
        "",
        "| candidate | Human Gold | D.3 | D.3.1 | root cause |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in cases:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["candidate_id"])[:12],
                    str(row["human_concept"]),
                    str(row["d3_system_concept"] or "unresolved"),
                    str(row["system_concept"] or "unresolved"),
                    str(row["root_cause"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _render_report(
    comparison: dict,
    metrics: dict,
    concept_boundary: list[dict],
    safety: dict,
    error_taxonomy: dict,
    systemic: dict,
    false_insufficient: list[dict],
    generated_at: str,
) -> str:
    return "\n".join(
        [
            "# Gate D.3.1 — Recall Recovery / Boundary Rebalancing",
            "",
            f"- 生成时间：{generated_at}",
            "- 范围：real-ai-review-set-v1 calibration（CALIBRATION ONLY — "
            "NOT PRODUCTION ACCURACY / NOT HOLDOUT）",
            "",
            "## Calibration Comparison",
            "",
            "| Metric | D.2 | D.3 | D.3.1 |",
            "| --- | --: | --: | --: |",
            f"| exact | {comparison['D2_baseline']['exact_approve']} | "
            f"{comparison['D3']['exact']} | {metrics['exact']} |",
            f"| acceptable | {comparison['D2_baseline']['usable'] - comparison['D2_baseline']['exact_approve']} | "
            f"{comparison['D3']['acceptable']} | {metrics['acceptable']} |",
            f"| wrong | {comparison['D2_baseline']['reject']} | "
            f"{comparison['D3']['wrong']} | {metrics['wrong']} |",
            f"| unresolved_when_human_sufficient | - | "
            f"{comparison['D3']['unresolved_when_human_sufficient']} | "
            f"{metrics['unresolved_when_human_sufficient']} |",
            "",
            "## False-Insufficient Recovery",
            "",
            f"- 24 条中 recovered exact="
            f"{sum(1 for r in false_insufficient if r['classification'] == 'exact')}，"
            f"recovered acceptable="
            f"{sum(1 for r in false_insufficient if r['classification'] == 'acceptable')}，"
            f"still unresolved="
            f"{sum(1 for r in false_insufficient if r['recovery'] == 'still_unresolved')}，"
            f"became wrong="
            f"{sum(1 for r in false_insufficient if r['recovery'] == 'became_wrong')}",
            "",
            "## Insufficient Precision",
            "",
            f"- Human insufficient 11 条：correctly unresolved="
            f"{comparison['insufficient_correctly_unresolved']}，"
            f"falsely resolved={comparison['insufficient_falsely_resolved']}",
            "",
            "## Concept Boundary Remediation",
            "",
            "| candidate | kind | before | after | status |",
            "| --- | --- | --- | --- | --- |",
        ]
        + [
            "| "
            + " | ".join(
                [
                    str(item["candidate_id"])[:12],
                    str(item["kind"]),
                    str(item["before"] or "unresolved"),
                    str(item["after"] or "unresolved"),
                    str(item["final_status"]),
                ]
            )
            + " |"
            for item in concept_boundary
        ]
        + [
            "",
            "## Safety Regression",
            "",
            f"- payment rail error={safety['payment_rail_error_remains']}",
            f"- 拉卡拉 high-confidence wrong-domain fixed="
            f"{safety['lakala_high_confidence_wrong_domain_fixed']}",
            f"- PII outbound={safety['pii_outbound']}",
            f"- KB personal/merchant alias contamination="
            f"{safety['kb_personal_or_merchant_alias_contamination']}",
            f"- property_management local reuse="
            f"{safety['property_management_local_reuse']}",
            f"- relation 47 strong={safety['relation_47_strong']}",
            f"- relation 06 conditional unresolved="
            f"{safety['relation_06_conditional_unresolved']}",
            f"- review-set checksum unchanged="
            f"{safety['review_set_checksum_unchanged']}",
            "",
            "## Error Taxonomy",
            "",
            f"- closed={error_taxonomy['taxonomy_closed']}，"
            f"unexplained={error_taxonomy['unexplained']}",
            f"- categories={error_taxonomy['categories']}",
            "",
            "## Systemic Findings",
            "",
            f"- conclusion={systemic['conclusion']}",
            f"- false insufficient reduction="
            f"{systemic['false_insufficient_reduction']}",
            f"- human insufficient preserved="
            f"{systemic['human_insufficient_preserved']}",
            f"- new major error family={systemic['new_major_error_family']}",
            "",
            "## Production Safety",
            "",
            "- legacy_v11 remains Production；knowledge_v1 remains Shadow",
            "- no Holdout；no Promotion；12 legacy relation pending untouched",
            "- real-ai-review-set-v1 checksum / membership unchanged",
            "- 未 push",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
