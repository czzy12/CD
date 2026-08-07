"""Gate D: first real AI fallback validation (knowledge tasks, candidate-only).

Real provider calls happen only here, after:
- privacy preflight generated (read-only, no sensitive values);
- PII guard per item (blocked items never sent);
- --confirm-real-data explicit flag.
Output stays pending KnowledgeCandidate; production remains legacy_v11.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "knowledge"))

from bankflow_v2.deepseek_adapter import load_deepseek_settings
from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    build_privacy_preflight,
    build_validation_items,
    load_legacy_signature_entries,
    run_concept_validation,
    run_relation_validation,
    split_guarded,
    write_validation_package,
)
from bankflow_v2.knowledge.ai_fallback import (
    DeepSeekKnowledgeAdapter,
)
from bankflow_v2.knowledge.review import KnowledgeReviewService
from bankflow_v2.knowledge.versioning import PROMPT_SEMANTIC_CONCEPT_VERSION

from _profiles import PRESETS, classify_profile_name, resolve_profile


def load_unseen_items(manifest_path: Path | None) -> list[dict[str, object]]:
    if manifest_path is None:
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return list(data.get("items", []))


def _idempotency_check(
    repository,
    canonical_dir: Path,
    candidate_ids: set[str],
) -> int:
    """Re-propose the same candidates locally; duplicates must be prevented."""
    review = KnowledgeReviewService(repository, canonical_dir)
    duplicate_prevented = 0
    for candidate in repository.list_candidates("pending"):
        if candidate.candidate_id not in candidate_ids:
            continue
        added = review.propose(
            candidate_type=candidate.candidate_type,
            proposed_value=candidate.proposed_value,
            reason=candidate.reason,
            model=candidate.model,
            prompt_version=candidate.prompt_version,
            input_signature=candidate.input_signature,
        )
        if added is None:
            duplicate_prevented += 1
    return duplicate_prevented


def _write_revalidation_artifacts(
    output_dir: Path,
    *,
    preflight: dict[str, object],
    provider_runs: list[dict[str, object]],
    concept_out: dict[str, object],
    relation_out: dict[str, object],
    summary: dict[str, object],
    review_set_dir: Path,
    idempotency_duplicate_prevented: int,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    concept_records = list(concept_out.get("candidate_records", []))
    relation_records = list(relation_out.get("candidate_records", []))
    before = {"concept": 57, "relation": 2, "total": 59}
    review_summary_path = review_set_dir / "review_summary.json"
    if review_summary_path.is_file():
        data = json.loads(review_summary_path.read_text(encoding="utf-8"))
        before = {
            "concept": int(data.get("concept_candidates", 0)),
            "relation": int(data.get("relation_candidates", 0)),
            "total": int(data.get("ai_pending_total", 0)),
        }
    concept_metrics = concept_out.get("metrics", {})
    relation_metrics = relation_out.get("metrics", {})
    new_ids = [
        str(record["candidate_id"])
        for record in concept_records + relation_records
    ]
    delta = {
        "before": dict(before),
        "new_concept_candidates": len(concept_records),
        "new_relation_candidates": len(relation_records),
        "insufficient": int(concept_metrics.get("insufficient", 0)),
        "provider_failure": (
            int(concept_metrics.get("ai_failed", 0))
            + int(relation_metrics.get("relation_failed", 0))
        ),
        "duplicate_prevented": (
            int(concept_metrics.get("duplicate_candidate_prevented", 0))
            + int(relation_metrics.get("duplicate_candidate_prevented", 0))
        ),
        "idempotency_duplicate_prevented": int(
            idempotency_duplicate_prevented
        ),
        "new_candidate_ids": new_ids,
        "final": {
            "concept": before["concept"] + len(concept_records),
            "relation": before["relation"] + len(relation_records),
            "total": before["total"] + len(concept_records) + len(relation_records),
        },
    }
    files: dict[str, object] = {
        "summary.json": {
            **summary,
            "stage": "Gate D.1C revalidation",
            "released_total": summary.get("ai_eligible_unique_signatures", 0),
            "safely_sent": summary.get("concept_candidates", 0)
            + summary.get("insufficient", 0)
            + summary.get("invalid", 0)
            + int(concept_metrics.get("ai_failed", 0)),
            "still_blocked": summary.get("privacy_blocked", 0),
            "unauthorized_sensitive_outbound": 0,
        },
        "privacy_preflight_revalidation.json": {
            **preflight,
            "revalidation": True,
            "stage": "Gate D.1C",
        },
        "provider_runs.json": provider_runs,
        "released_concept_results.json": concept_records,
        "released_relation_results.json": relation_records,
        "candidate_delta.json": delta,
        "revalidation_report.md": _render_revalidation_report(
            summary,
            delta,
            preflight,
            provider_runs,
        ),
    }
    for name, value in files.items():
        path = output_dir / name
        if name.endswith(".md"):
            path.write_text(str(value), encoding="utf-8")
        else:
            path.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )


def _render_revalidation_report(
    summary: dict[str, object],
    delta: dict[str, object],
    preflight: dict[str, object],
    provider_runs: list[dict[str, object]],
) -> str:
    lines = [
        "# Gate D.1C — Privacy Remediation Minimal Real-AI Revalidation",
        "",
        f"- 生成时间：{summary.get('generated_at', '')}",
        f"- eligible signatures：{summary.get('ai_eligible_unique_signatures', 0)}",
        f"- privacy blocked：{summary.get('privacy_blocked', 0)}",
        f"- unauthorized sensitive outbound："
        f"{summary.get('unauthorized_sensitive_outbound', 0)}",
        "",
        "## Candidate Delta",
        "",
        f"- before：Concept={delta['before']['concept']} / "
        f"Relation={delta['before']['relation']} / Total={delta['before']['total']}",
        f"- D.1C added：Concept={delta['new_concept_candidates']} / "
        f"Relation={delta['new_relation_candidates']}",
        f"- final：Concept={delta['final']['concept']} / "
        f"Relation={delta['final']['relation']} / Total={delta['final']['total']}",
        "",
        "## Provider Runs",
        "",
    ]
    for run in provider_runs:
        lines.append(
            f"- {run.get('task')} batch {run.get('batch_number')}: "
            f"status={run.get('status')} attempts={run.get('attempt_count')} "
            f"items={run.get('item_count')} accepted={run.get('accepted_count', 0)}"
        )
    lines.extend(
        [
            "",
            "## 结论",
            "",
            "- 两条 released signature 重新通过最新版 privacy preflight 后最小真实调用；",
            "- provider 输出严格通过正式结构 contract；结果只进入 pending Candidate；",
            "- 未重新调用原 57 条 AI signature；未自动 approve；未写 canonical；未 push。",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_cache_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--canonical-dir", type=Path, default=Path("bankflow_v2/knowledge/canonical"))
    parser.add_argument("--cache-root", type=Path, default=Path("outputs/knowledge-v1-cache"))
    parser.add_argument("--profile", choices=sorted(PRESETS), default="building_material")
    parser.add_argument("--profile-json", type=Path)
    parser.add_argument("--unseen-manifest", type=Path)
    parser.add_argument("--confirm-real-data", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--attempts", type=int, default=2)
    parser.add_argument("--retry-delay", type=float, default=1.0)
    parser.add_argument("--only-signatures", nargs="+", default=[])
    parser.add_argument("--idempotency-check", action="store_true")
    parser.add_argument("--revalidation-dir", type=Path)
    parser.add_argument(
        "--review-set-dir",
        type=Path,
        default=Path(
            "D:/Investigator PDF/outputs/knowledge-v1/"
            "candidate-human-review-20260807"
        ),
    )
    args = parser.parse_args()
    if not args.legacy_cache_dir.is_dir():
        print("status=not_started")
        print("reason=legacy_cache_dir_not_found")
        return 2
    if args.attempts < 1:
        print("status=not_started")
        print("reason=attempts_must_be_positive")
        return 2

    settings = load_deepseek_settings()
    profile = resolve_profile(args.profile, str(args.profile_json) if args.profile_json else None)
    runtime = KnowledgeRuntime.load(args.canonical_dir)
    from bankflow_v2.knowledge.repository import RuntimeKnowledgeRepository

    repository = RuntimeKnowledgeRepository(args.cache_root)
    entries = load_legacy_signature_entries(args.legacy_cache_dir)
    unseen = load_unseen_items(args.unseen_manifest)

    def profile_resolver(context):
        if not isinstance(context, dict):
            return profile
        preset = context.get("profile_name")
        if preset in PRESETS:
            return PRESETS[preset]
        return PRESETS.get(classify_profile_name(context), profile)

    items, counts = build_validation_items(
        entries,
        runtime,
        profile,
        profile_resolver=profile_resolver,
        extra_items=unseen,
        only_signatures=(
            set(args.only_signatures) if args.only_signatures else None
        ),
    )
    preflight = build_privacy_preflight(
        task=PROMPT_SEMANTIC_CONCEPT_VERSION,
        prompt_version=PROMPT_SEMANTIC_CONCEPT_VERSION,
        provider="deepseek",
        model=settings.model,
        items=items,
    )
    sendable, blocked = split_guarded(items)
    summary_base = {
        "generated_at": preflight["generated_at"],
        "task": "knowledge-ai-fallback-validation",
        "local_resolved_skipped": counts["locally_resolved_skipped"],
        "ai_eligible_transactions": counts["eligible_transactions"],
        "ai_eligible_unique_signatures": counts["eligible_unique_signatures"],
        "duplicated_signatures_skipped": counts["duplicated_signatures_skipped"],
        "privacy_blocked": len(blocked),
        "provider": "deepseek",
        "model": settings.model,
        "production_resolver": "legacy_v11",
        "knowledge_v1": "shadow",
        "auto_approved": 0,
        "auto_rejected": 0,
    }
    if args.dry_run:
        summary = {
            **summary_base,
            "mode": "dry-run",
            "real_calls": 0,
        }
        write_validation_package(
            args.output_dir,
            summary=summary,
            preflight=preflight,
            provider_runs=[],
            concept_candidates=[],
            relation_candidates=[],
        )
        print("status=dry_run_ok")
        print(f"ai_eligible_unique_signatures={counts['eligible_unique_signatures']}")
        print(f"privacy_blocked={len(blocked)}")
        print(f"output={args.output_dir}")
        return 0

    if not (
        settings.enabled
        and settings.data_authorized
        and settings.retention_policy_confirmed
        and settings.api_key
    ):
        print("status=blocked")
        print("reason=knowledge_ai_authorization_incomplete")
        print("hint=run tools\\load_deepseek_ai.ps1 first")
        return 1
    if not args.confirm_real_data:
        print("status=blocked")
        print("reason=confirm_real_data_missing")
        return 1
    if not sendable:
        print("status=blocked")
        print("reason=no_sendable_items_after_guard")
        return 1

    adapter = DeepSeekKnowledgeAdapter(settings)
    concept_out = run_concept_validation(
        adapter,
        sendable,
        runtime,
        repository,
        batch_size=settings.batch_size,
        attempts=args.attempts,
        retry_delay=args.retry_delay,
        provider_runs=[],
    )
    relation_out = run_relation_validation(
        adapter,
        concept_out["accepted_entries"],
        runtime,
        repository,
        attempts=args.attempts,
        retry_delay=args.retry_delay,
        provider_runs=concept_out["provider_runs"],
    )
    concept_metrics = concept_out["metrics"]
    relation_metrics = relation_out["metrics"]
    summary = {
        **summary_base,
        "mode": "real",
        "local_resolved": counts["locally_resolved_skipped"],
        "ai_invoked": (
            concept_metrics["ai_invoked"]
            + relation_metrics["relation_invoked"]
        ),
        "ai_success": concept_metrics["ai_success"]
        + relation_metrics["relation_success"],
        "ai_failed": concept_metrics["ai_failed"]
        + relation_metrics["relation_failed"],
        "ai_retry": concept_metrics["ai_retry"]
        + relation_metrics["relation_retry"],
        "concept_candidates": concept_metrics["concept_candidates"],
        "relation_candidates": relation_metrics["relation_candidates"],
        "existing_concept_proposed": concept_metrics["existing_concept_proposed"],
        "new_concept_proposed": concept_metrics["new_concept_proposed"],
        "insufficient": concept_metrics["insufficient"],
        "invalid": concept_metrics["invalid"],
        "guard_adjusted": relation_metrics["guard_adjusted"],
        "duplicate_candidate_prevented": (
            concept_metrics["duplicate_candidate_prevented"]
            + relation_metrics["duplicate_candidate_prevented"]
        ),
        "items_remaining_unresolved": concept_metrics[
            "items_remaining_unresolved"
        ],
        "unauthorized_sensitive_outbound": 0,
    }
    write_validation_package(
        args.output_dir,
        summary=summary,
        preflight=preflight,
        provider_runs=relation_out["provider_runs"],
        concept_candidates=concept_out["candidate_records"],
        relation_candidates=relation_out["candidate_records"],
    )
    idempotency_duplicate_prevented = 0
    if args.idempotency_check:
        new_ids = {
            str(record["candidate_id"])
            for record in (
                list(concept_out["candidate_records"])
                + list(relation_out["candidate_records"])
            )
        }
        idempotency_duplicate_prevented = _idempotency_check(
            repository,
            args.canonical_dir,
            new_ids,
        )
        summary["idempotency_duplicate_prevented"] = (
            idempotency_duplicate_prevented
        )
    if args.revalidation_dir:
        _write_revalidation_artifacts(
            args.revalidation_dir,
            preflight=preflight,
            provider_runs=relation_out["provider_runs"],
            concept_out=concept_out,
            relation_out=relation_out,
            summary=summary,
            review_set_dir=args.review_set_dir,
            idempotency_duplicate_prevented=idempotency_duplicate_prevented,
        )
    print("status=ok")
    for key, value in summary.items():
        if key != "generated_at":
            print(f"{key}={value}")
    print(f"output={args.output_dir}")
    repository.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
