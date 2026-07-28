"""Run one guarded AI sample batch against a real, user-authorized case."""

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
from bankflow_v2.ai_sample_acceptance import render_ai_sample_markdown
from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.case_context import (
    SOURCE_ROLE_RISK_INVESTIGATION_REPORT,
    SOURCE_ROLE_SYSTEM_CUSTOMER_DATA,
    build_case_context,
)
from bankflow_v2.deepseek_adapter import (
    load_deepseek_runtime,
    load_deepseek_settings,
)
from bankflow_v2.pipeline import extract_transactions


def _sources(case_dir: Path) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for text_path in sorted(case_dir.glob("*.txt")):
        role = (
            SOURCE_ROLE_RISK_INVESTIGATION_REPORT
            if "调查报告" in text_path.name
            else SOURCE_ROLE_SYSTEM_CUSTOMER_DATA
        )
        sources.append(
            {
                "source_ref": text_path.name,
                "source_role": role,
                "text": text_path.read_text(encoding="utf-8"),
            }
        )
    return sources


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("case_dir", type=Path)
    parser.add_argument("output_path", type=Path)
    parser.add_argument("--sample-manifest", type=Path, required=True)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("output/ai-response-cache"),
    )
    parser.add_argument("--confirm-real-data", action="store_true")
    parser.add_argument("--retry-invalid-cache", action="store_true")
    parser.add_argument("--expected-retry-count", type=int)
    args = parser.parse_args()

    if (
        args.retry_invalid_cache
        and (
            args.expected_retry_count is None
            or args.expected_retry_count < 1
        )
    ):
        print("status=not_started")
        print("reason=expected_retry_count_required")
        return 2
    if not args.confirm_real_data:
        print("status=not_started")
        print("reason=confirm_real_data_required")
        return 2
    if not args.case_dir.is_dir():
        print("status=not_started")
        print("reason=case_directory_not_found")
        return 2

    settings = load_deepseek_settings()
    ai_config, evaluator = load_deepseek_runtime(
        cache_dir=args.cache_dir,
        retry_invalid_cache=args.retry_invalid_cache,
    )
    if evaluator is None:
        print("status=not_started")
        print("reason=ai_configuration_or_authorization_incomplete")
        return 2
    if not args.sample_manifest.is_file():
        print("status=not_started")
        print("reason=sample_manifest_not_found")
        return 2

    case_context = build_case_context(args.case_dir.name, _sources(args.case_dir))
    transactions = []
    for pdf_path in sorted(args.case_dir.glob("*.pdf")):
        detection = detect_bank_type(str(pdf_path))
        if not detection.bank_id:
            print(f"ignored_unrecognized_pdf={pdf_path.name}")
            continue
        print(f"parsing={pdf_path.name}")
        transactions.extend(extract_transactions(str(pdf_path), detection.bank_id))

    manifest = json.loads(args.sample_manifest.read_text(encoding="utf-8"))
    try:
        sampled_transactions, eligible_count = select_ai_input_from_manifest(
            transactions,
            case_context,
            manifest,
            allow_business_names=settings.allow_business_names,
            split="development",
        )
    except ValueError as exc:
        print("status=not_started")
        print(f"reason=sample_manifest_invalid:{exc}")
        return 2
    if len(sampled_transactions) > settings.batch_size:
        print("status=not_started")
        print("reason=fixed_sample_must_fit_one_configured_batch")
        return 2
    print(f"parsed_transactions={len(transactions)}")
    print(f"eligible_ai_candidates={eligible_count}")
    print(f"sampled_transactions={len(sampled_transactions)}")
    if not sampled_transactions:
        print("status=not_started")
        print("reason=no_eligible_ai_candidates")
        return 2

    observation = build_ai_business_observation(
        sampled_transactions,
        case_context,
        ai_config,
        evaluator,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(
        render_ai_sample_markdown(
            case_name=args.case_dir.name,
            provider=str(ai_config.get("provider", "")),
            model=str(ai_config.get("model", "")),
            eligible_count=eligible_count,
            sampled_transactions=sampled_transactions,
            observation=observation,
        )
        + "\n",
        encoding="utf-8",
    )
    if not observation["value"]["available"]:
        print("status=failed_closed")
        print(f"reason={observation['value']['reason']}")
        print(
            "validation_failures="
            f"{observation['value']['validation_failure_summary']['total']}"
        )
        print(f"report={args.output_path}")
        return 1

    provider_execution = observation["value"]["provider_execution"]
    invalid_cache_entry_count = int(
        provider_execution.get("invalid_cache_entry_count", 0)
    )
    if (
        args.retry_invalid_cache
        and invalid_cache_entry_count != args.expected_retry_count
    ):
        print("status=failed_closed")
        print("reason=invalid_cache_retry_scope_mismatch")
        print(f"invalid_cache_entries={invalid_cache_entry_count}")
        print(f"expected_retry_count={args.expected_retry_count}")
        print(f"report={args.output_path}")
        return 1
    print("status=ok")
    print(f"accepted_ai_results={len(observation['value']['ai_candidates'])}")
    print(f"cache_hits={provider_execution['cache_hit_count']}")
    print(f"invalid_cache_entries={invalid_cache_entry_count}")
    print(f"provider_calls={provider_execution['provider_call_count']}")
    print(f"report={args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
