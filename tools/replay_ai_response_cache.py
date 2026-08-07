"""Replay cached provider items through current validators without network access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.ai_business_observation import (
    build_ai_business_observation,
    select_ai_input_from_manifest,
)
from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.case_context import (
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)
from bankflow_v2.deepseek_adapter import (
    DEFAULT_MODEL,
    DeepSeekEvaluator,
    DeepSeekSettings,
)
from bankflow_v2.pipeline import extract_transactions


def _sources(case_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(case_dir.glob("*.txt")):
        rows.append(
            {
                "source_ref": path.name,
                "source_role": (
                    SOURCE_ROLE_RISK_INVESTIGATION_REPORT
                    if "调查报告" in path.name
                    else SOURCE_ROLE_SYSTEM_CUSTOMER_DATA
                ),
                "text": path.read_text(encoding="utf-8"),
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("cache_dir", type=Path)
    parser.add_argument("output_json", type=Path)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--business-confirmation", type=Path)
    parser.add_argument("--sample-manifest", type=Path)
    parser.add_argument(
        "--split",
        choices=["development", "reserved_acceptance"],
        default="development",
    )
    args = parser.parse_args()
    if not args.case_dir.is_dir() or not args.cache_dir.is_dir():
        print("status=not_started")
        print("reason=case_or_cache_directory_not_found")
        return 2
    if (
        args.business_confirmation
        and not args.business_confirmation.is_file()
    ):
        print("status=not_started")
        print("reason=business_confirmation_not_found")
        return 2
    if args.sample_manifest and not args.sample_manifest.is_file():
        print("status=not_started")
        print("reason=sample_manifest_not_found")
        return 2

    confirmation = (
        json.loads(
            args.business_confirmation.read_text(encoding="utf-8-sig")
        )
        if args.business_confirmation
        else None
    )
    context = build_case_context(
        args.case_dir.name,
        _sources(args.case_dir),
        business_confirmation=confirmation,
    )
    transactions = []
    for path in sorted(args.case_dir.glob("*.pdf")):
        detection = detect_bank_type(str(path))
        if detection.bank_id:
            transactions.extend(
                extract_transactions(str(path), detection.bank_id)
            )
    eligible_unique_semantic_count = 0
    if args.sample_manifest:
        manifest = json.loads(
            args.sample_manifest.read_text(encoding="utf-8-sig")
        )
        try:
            transactions, eligible_unique_semantic_count = (
                select_ai_input_from_manifest(
                    transactions,
                    context,
                    manifest,
                    allow_business_names=True,
                    split=args.split,
                )
            )
        except ValueError as exc:
            print("status=not_started")
            print(f"reason=sample_manifest_invalid:{exc}")
            return 2
    settings = DeepSeekSettings(
        api_key="",
        model=args.model,
        enabled=True,
        data_authorized=True,
        retention_policy_confirmed=True,
        allow_business_names=True,
        cache_dir=str(args.cache_dir),
    )
    evaluator = DeepSeekEvaluator(
        settings,
        cache_dir=args.cache_dir,
        replay_only=True,
        transport=lambda *_args: (_ for _ in ()).throw(
            AssertionError("offline replay attempted network transport")
        ),
    )
    config = settings.ai_config()
    config["api_key_available"] = True
    config["replay_only"] = True
    observation = build_ai_business_observation(
        transactions,
        context,
        config,
        evaluator,
    )
    value = observation["value"]
    provider_execution = value.get("provider_execution", {})
    if not isinstance(provider_execution, dict):
        provider_execution = {}
    cache_hit_count = int(provider_execution.get("cache_hit_count", 0) or 0)
    cache_miss_count = int(provider_execution.get("cache_miss_count", 0) or 0)
    provider_call_count = int(
        provider_execution.get("provider_call_count", 0) or 0
    )
    replay_mismatch_count = int(
        provider_execution.get("cache_replay_mismatch_count", 0) or 0
    )
    output = {
        "replay_source": str(args.cache_dir),
        "sample_manifest": (
            str(args.sample_manifest) if args.sample_manifest else ""
        ),
        "eligible_unique_semantic_count": (
            eligible_unique_semantic_count
        ),
        "task_type": observation["parameters"]["task_type"],
        "prompt_version": observation["parameters"]["prompt_version"],
        "model": args.model,
        "available": value["available"],
        "reason": value["reason"],
        "ai_input_candidate_count": value["ai_input_candidate_count"],
        "adopted_result_count": len(value["ai_candidates"]),
        "provisional_valid_result_count": len(
            value["provisional_ai_candidates"]
        ),
        "validation_failure_summary": value[
            "validation_failure_summary"
        ],
        "cache_hit_count": cache_hit_count,
        "cache_miss_count": cache_miss_count,
        "provider_call_count": provider_call_count,
        "cache_replay_mismatch_count": replay_mismatch_count,
        "replay_consistent": (
            cache_miss_count == 0
            and provider_call_count == 0
            and replay_mismatch_count == 0
        ),
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print("status=ok")
    print(f"available={output['available']}")
    print(
        "validation_failures="
        f"{output['validation_failure_summary']['total']}"
    )
    print(f"cache_hits={cache_hit_count}")
    print(f"cache_misses={cache_miss_count}")
    print(f"provider_calls={provider_call_count}")
    print(f"replay_mismatches={replay_mismatch_count}")
    print(f"replay_consistent={str(output['replay_consistent']).lower()}")
    print(f"output={args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
