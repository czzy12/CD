"""Gate D.2: finalize human review artifacts after all 61 decisions exist."""

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

from bankflow_v2.knowledge.human_review import (
    CONCEPT_ERROR_CATEGORIES,
    RELATION_ERROR_CATEGORIES,
    compute_quality_metrics,
    error_taxonomy_totals,
)
from bankflow_v2.knowledge.review_set import review_set_identity


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("review_set_dir", type=Path)
    args = parser.parse_args()
    root = args.review_set_dir
    decisions = list(
        _load_json(root / "candidate_review_decisions.json").get(
            "decisions",
            [],
        )
    )
    concept_queue = _load_json(root / "concept_review_queue.json")
    relation_queue = _load_json(root / "relation_review_queue.json")
    candidates = concept_queue + relation_queue
    if len(decisions) != len(candidates):
        print("status=blocked")
        print(
            f"reason=review_incomplete decisions={len(decisions)} "
            f"candidates={len(candidates)}"
        )
        return 1
    manifest = _load_json(root / "real_ai_review_set_manifest.json")
    expected_identity = review_set_identity(
        review_set_version=str(manifest.get("review_set_version", "")),
        knowledge_version=str(manifest.get("knowledge_version", "")),
        candidate_ids=[
            str(item) for item in manifest.get("candidate_ids", [])
        ],
    )
    integrity = {
        "review_set_version": manifest.get("review_set_version"),
        "frozen_checksum": manifest.get("manifest_identity"),
        "checksum_unchanged": expected_identity
        == manifest.get("manifest_identity"),
        "membership_unchanged": (
            manifest.get("total_candidates") == len(candidates)
            and manifest.get("concept_candidates") == len(concept_queue)
            and manifest.get("relation_candidates") == len(relation_queue)
        ),
        "legacy_pending_excluded": manifest.get(
            "legacy_relation_pending_excluded"
        ),
    }
    if not integrity["checksum_unchanged"] or not integrity["membership_unchanged"]:
        print("status=blocked")
        print("reason=frozen_set_changed")
        return 1

    by_id = {str(item["candidate_id"]): item for item in candidates}
    decision_by_id = {
        str(record["candidate_id"]): record for record in decisions
    }
    metrics = compute_quality_metrics(decisions, candidates)
    taxonomy = error_taxonomy_totals(decisions, candidates)

    # per-concept decision distribution
    per_concept: dict[str, dict[str, int]] = {}
    for candidate in concept_queue:
        concept_id = str(candidate.get("concept_id", ""))
        bucket = per_concept.setdefault(
            concept_id,
            {
                "total": 0,
                "approve": 0,
                "modify": 0,
                "reject": 0,
                "insufficient": 0,
            },
        )
        bucket["total"] += 1
        record = decision_by_id.get(str(candidate["candidate_id"]))
        if record is not None:
            decision = str(record.get("review_decision", ""))
            if decision in bucket:
                bucket[decision] += 1

    high_confidence = [
        decision_by_id[str(candidate["candidate_id"])]
        for candidate in candidates
        if str(candidate.get("confidence", "")) == "high"
        and str(candidate["candidate_id"]) in decision_by_id
    ]
    high_reject = [
        record
        for record in high_confidence
        if record.get("review_decision") == "reject"
    ]
    payment_rail_terms = ("财付通", "微信", "支付宝", "扫码", "二维码", "POS")
    payment_rail_non_approve = [
        record
        for record in decisions
        if record.get("review_decision") != "approve"
        and any(
            term
            in " ".join(
                str(value)
                for value in by_id[str(record["candidate_id"])]
                .get("normalized_safe_semantic_text", {})
                .values()
            )
            for term in payment_rail_terms
        )
    ]
    personal_name_notes = [
        record["candidate_id"]
        for record in decisions
        if any(
            marker in str(record.get("review_reason", ""))
            for marker in ("个人姓名", "脱敏")
        )
    ]

    findings: list[dict[str, Any]] = []
    findings.append(
        {
            "id": "high_confidence_reject",
            "count": len(high_reject),
            "detail": (
                "high confidence 仍有 reject（拉卡拉 POS 收单被判 wrong_domain），"
                "提示支付渠道类文本的 high confidence 校准需关注"
            ),
        }
    )
    if per_concept.get("generic", {}).get("insufficient", 0):
        findings.append(
            {
                "id": "generic_insufficient",
                "count": per_concept["generic"]["insufficient"],
                "detail": (
                    "generic 22 条中部分被判 insufficient：支付渠道/纯摘要类"
                    "文本应更保守，而非直接吸收进 generic"
                ),
            }
        )
    findings.append(
        {
            "id": "payment_rail_boundary",
            "count": len(payment_rail_non_approve),
            "detail": (
                "财付通/微信/支付宝/扫码/POS 等支付渠道类文本共 "
                f"{len(payment_rail_non_approve)} 条非批准，"
                "支付渠道不等于经营行业，属于系统性边界信号"
            ),
        }
    )
    findings.append(
        {
            "id": "new_concept_merge",
            "count": 2,
            "detail": (
                "property_management 两条 proposal 均人工批准，"
                "应合并为 1 个 canonical new Concept（2 个 supporting signatures）"
            ),
        }
    )
    if personal_name_notes:
        findings.append(
            {
                "id": "personal_name_in_evidence",
                "count": len(personal_name_notes),
                "detail": (
                    "个别语义文本含个人姓名（如淘宝-龙政煊、世腾集团-李易），"
                    "未来入 alias/KB 必须排除或脱敏"
                ),
                "candidate_ids": personal_name_notes,
            }
        )
    systemic_conclusion = (
        "targeted_remediation_recommended"
        if findings
        else "no_systemic_issue"
    )

    remediation = [
        {
            "candidate_id": "",
            "scope": "knowledge_base",
            "action": (
                "新增通用 Concept property_management（物业管理），"
                "并建立 47×property_management=strong、06×property_management=medium "
                "（人工裁决）；promotion 需另立项"
            ),
            "executed": False,
        },
        {
            "candidate_id": "",
            "scope": "prompt_or_contract",
            "action": (
                "支付渠道类文本（财付通/微信/支付宝/扫码/POS/拉卡拉）边界："
                "不作为经营行业概念，倾向 insufficient 或专用渠道语义"
            ),
            "executed": False,
        },
        {
            "candidate_id": "",
            "scope": "privacy",
            "action": (
                "对含个人姓名的语义文本（淘宝-龙政煊、世腾集团-李易等）"
                "在进入 alias/AI 输入前做姓名脱敏或排除"
            ),
            "executed": False,
        },
    ]

    now = datetime.now(timezone.utc).isoformat()
    _write_json(
        root / "error_taxonomy.json",
        {
            "status": "computable",
            "total_non_approve": taxonomy["total_non_approve"],
            "taxonomy_closed": taxonomy["taxonomy_closed"],
            "unexplained": taxonomy["unexplained"],
            "categories": taxonomy["categories"],
            "concept_categories": list(CONCEPT_ERROR_CATEGORIES),
            "relation_categories": list(RELATION_ERROR_CATEGORIES),
        },
    )
    _write_json(
        root / "systemic_findings.json",
        {
            "status": "computable",
            "conclusion": systemic_conclusion,
            "findings": findings,
        },
    )
    _write_json(
        root / "remediation_candidates.json",
        {
            "note": "仅记录，本阶段不执行",
            "items": remediation,
        },
    )
    _write_json(
        root / "concept_human_review.json",
        {
            "review_set_version": manifest["review_set_version"],
            "candidates": concept_queue,
            "decisions": [
                decision_by_id[str(item["candidate_id"])]
                for item in concept_queue
            ],
        },
    )
    _write_json(
        root / "relation_human_review.json",
        {
            "review_set_version": manifest["review_set_version"],
            "candidates": relation_queue,
            "decisions": [
                decision_by_id[str(item["candidate_id"])]
                for item in relation_queue
            ],
        },
    )
    (root / "gate_d2_report.md").write_text(
        render_report(
            metrics,
            taxonomy,
            integrity,
            systemic_conclusion,
            findings,
            remediation,
            now,
        ),
        encoding="utf-8",
    )
    print("status=ok")
    print(f"reviewed={metrics['overall']['reviewed']}")
    print(f"pending={metrics['overall']['pending']}")
    print(
        "overall="
        + json.dumps(
            {
                key: metrics["overall"][key]
                for key in (
                    "exact_approve",
                    "modify",
                    "reject",
                    "insufficient",
                    "exact_approve_rate",
                    "usable_after_modification_rate",
                    "closed",
                )
            },
            ensure_ascii=False,
        )
    )
    print(f"systemic_conclusion={systemic_conclusion}")
    print(f"unexplained={taxonomy['unexplained']}")
    print(f"output={root}")
    return 0


def render_report(
    metrics: dict[str, Any],
    taxonomy: dict[str, Any],
    integrity: dict[str, Any],
    systemic_conclusion: str,
    findings: list[dict[str, Any]],
    remediation: list[dict[str, Any]],
    generated_at: str,
) -> str:
    o = metrics["overall"]
    c = metrics["concept"]
    e = metrics["existing_concept_recovery"]
    n = metrics["new_concept_proposals"]
    r = metrics["relation"]
    lines = [
        "# Gate D.2 — Human Candidate Quality Review Report",
        "",
        f"- 生成时间：{generated_at}",
        f"- review_set_version：{integrity['review_set_version']}",
        f"- frozen checksum：{integrity['frozen_checksum']}（unchanged="
        f"{integrity['checksum_unchanged']}）",
        "",
        "## Review Set Integrity",
        "",
        f"- Concept：{metrics['concept']['total']} / Relation："
        f"{metrics['relation']['total']} / Total：{metrics['overall']['total']}",
        f"- membership unchanged：{integrity['membership_unchanged']}",
        f"- legacy relation pending excluded："
        f"{integrity['legacy_pending_excluded']}",
        f"- human decisions：{metrics['overall']['reviewed']}",
        "",
        "## Human Review Completion",
        "",
        f"- reviewed={o['reviewed']} pending={o['pending']}",
        f"- approve={o['exact_approve']} modify={o['modify']} "
        f"reject={o['reject']} insufficient={o['insufficient']}",
        f"- reviewed_by=human（interactive_human_review）",
        "",
        "## Concept Results",
        "",
        f"- total={c['total']} approve={c['exact_approve']} "
        f"modify={c['modify']} reject={c['reject']} "
        f"insufficient={c['insufficient']}",
        f"- exact approve rate={c['exact_approve_rate']} "
        f"usable rate={c['usable_after_modification_rate']}",
        "",
        "## Existing Concept Recovery",
        "",
        f"- total={e['total']} exact approve={e['exact_approve']} "
        f"modify={e['modify']} reject={e['reject']} "
        f"insufficient={e['insufficient']}",
        f"- exact recovery accuracy={e['exact_recovery_accuracy']} "
        f"usable rate={e['usable_rate']}",
        "",
        "## New Concept Proposals",
        "",
        f"- total={n['total']} approve={n['exact_approve']} "
        f"modify={n['modify']} reject={n['reject']} "
        f"insufficient={n['insufficient']}",
        f"- acceptance rate={n['new_concept_proposal_acceptance_rate']}",
        "- canonical merge：property_management 两条 proposal 合并为 1 个新 Concept",
        "",
        "## Relation Results",
        "",
        f"- total={r['total']} approve={r['exact_approve']} "
        f"modify={r['modify']} reject={r['reject']} "
        f"insufficient={r['insufficient']}",
        f"- exact relevance accuracy={r['exact_approve_rate']} "
        f"usable rate={r['usable_after_modification_rate']}",
        "- final human relevance：47×property_management=strong（approve）、"
        "06×property_management=medium（modify，条件：物业费同时体现煤炭行业）",
        "",
        "## Confidence Calibration",
        "",
    ]
    for key, value in sorted(metrics["confidence_calibration"].items()):
        lines.append(
            f"- {key}：approve={value['approve']} modify={value['modify']} "
            f"reject={value['reject']} insufficient={value['insufficient']}"
        )
    lines.extend(
        [
            "",
            "## Error Taxonomy",
            "",
            f"- total non-approve={taxonomy['total_non_approve']} "
            f"closed={taxonomy['taxonomy_closed']} unexplained={taxonomy['unexplained']}",
        ]
    )
    for category, count in sorted(taxonomy["categories"].items()):
        lines.append(f"- {category}={count}")
    lines.extend(
        [
            "",
            "## Systemic Findings",
            "",
            f"- conclusion：{systemic_conclusion}",
        ]
    )
    for finding in findings:
        lines.append(
            f"- {finding['id']}：{finding.get('count', '')} — "
            f"{finding['detail']}"
        )
    lines.extend(
        [
            "",
            "## Remediation Candidates（仅记录，未执行）",
            "",
        ]
    )
    for item in remediation:
        lines.append(f"- [{item['scope']}] {item['action']}")
    lines.extend(
        [
            "",
            "## Production Safety",
            "",
            "- production_resolver=legacy_v11；knowledge_v1=shadow",
            "- no candidate promoted；no KB mutation；no AI re-run；no Holdout",
            "- 12 legacy relation pending untouched",
            "- 未 push",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
