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
from bankflow_v2.knowledge.versioning import PROMPT_SEMANTIC_CONCEPT_VERSION

from _profiles import PRESETS, classify_profile_name, resolve_profile


def load_unseen_items(manifest_path: Path | None) -> list[dict[str, object]]:
    if manifest_path is None:
        return []
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    return list(data.get("items", []))


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
    print("status=ok")
    for key, value in summary.items():
        if key != "generated_at":
            print(f"{key}={value}")
    print(f"output={args.output_dir}")
    repository.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
