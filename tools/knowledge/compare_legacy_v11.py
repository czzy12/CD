"""Run legacy_v11 vs knowledge_v1 shadow comparison and write a report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from bankflow_v2.knowledge import (
    KnowledgeRuntime,
    compare_legacy_cache,
    extended_shadow_metrics,
    render_shadow_markdown,
)

from _profiles import PRESETS, classify_profile_name, resolve_profile


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_cache_dir", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--canonical-dir", type=Path, default=Path("bankflow_v2/knowledge/canonical"))
    parser.add_argument("--cache-root", type=Path)
    parser.add_argument("--markdown-path", type=Path)
    parser.add_argument(
        "--profile",
        choices=sorted(
            [
                "building_material",
                "construction_coal",
                "alcohol_retail",
                "furniture_decoration",
            ]
        ),
    )
    parser.add_argument("--profile-json", type=Path)
    parser.add_argument(
        "--per-entry-profile",
        action="store_true",
        help="按 legacy 业务上下文为每条签名使用对应行业画像",
    )
    args = parser.parse_args()
    if not args.legacy_cache_dir.is_dir():
        print("status=not_started")
        print("reason=legacy_cache_dir_not_found")
        return 2
    profile = resolve_profile(
        args.profile,
        str(args.profile_json) if args.profile_json else None,
    )
    runtime = KnowledgeRuntime.load(args.canonical_dir, cache_root=args.cache_root)
    profile_resolver = None
    if args.per_entry_profile:
        def profile_resolver(business_context):
            name = classify_profile_name(business_context)
            return PRESETS.get(name)
    report = compare_legacy_cache(
        args.legacy_cache_dir,
        runtime,
        profile,
        cache_root=args.cache_root,
        profile_resolver=profile_resolver,
    )
    metrics = extended_shadow_metrics(
        args.legacy_cache_dir,
        runtime,
        profile,
        profile_resolver=profile_resolver,
    )
    report["extended_metrics"] = metrics
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if args.markdown_path:
        args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_path.write_text(
            render_shadow_markdown(report) + "\n",
            encoding="utf-8",
        )
    print("status=ok")
    print(f"entries={report['total_entries']}")
    print(f"agreement_rate={report['agreement_rate']}")
    print(f"disagreements={report['disagreement_count']}")
    print(f"new_undetermined={report['new_undetermined_count']}")
    print(f"strength_escalations={report['strength_escalation_count']}")
    print(f"life_positive={report['life_positive_count']}")
    for key in (
        "unknown_concept_count",
        "unknown_relation_count",
        "concept_ai_fallback_theoretical",
        "relation_ai_fallback_theoretical",
        "total_ai_fallback_theoretical",
        "parent_inheritance_hits",
        "exact_alias_hits",
    ):
        print(f"{key}={metrics.get(key)}")
    print(f"output={args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
