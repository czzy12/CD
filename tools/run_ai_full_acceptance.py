"""Run the guarded full unique-semantic AI acceptance for one real case."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.ai_business_observation import (
    build_ai_business_observation,
    build_ai_input_audit,
    build_ai_input_profile,
    select_ai_input_sample,
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
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("output/ai-response-cache"),
    )
    parser.add_argument("--confirm-real-data", action="store_true")
    parser.add_argument("--confirm-full-run", action="store_true")
    parser.add_argument("--business-confirmation", type=Path)
    args = parser.parse_args()

    if not args.confirm_real_data or not args.confirm_full_run:
        print("status=not_started")
        print("reason=real_data_and_full_run_confirmation_required")
        return 2
    if not args.case_dir.is_dir():
        print("status=not_started")
        print("reason=case_directory_not_found")
        return 2
    if (
        args.business_confirmation
        and not args.business_confirmation.is_file()
    ):
        print("status=not_started")
        print("reason=business_confirmation_not_found")
        return 2

    settings = load_deepseek_settings()
    ai_config, evaluator = load_deepseek_runtime(cache_dir=args.cache_dir)
    if evaluator is None:
        print("status=not_started")
        print("reason=ai_configuration_or_authorization_incomplete")
        return 2

    confirmation = (
        json.loads(
            args.business_confirmation.read_text(encoding="utf-8-sig")
        )
        if args.business_confirmation
        else None
    )
    case_context = build_case_context(
        args.case_dir.name,
        _sources(args.case_dir),
        business_confirmation=confirmation,
    )
    transactions = []
    for pdf_path in sorted(args.case_dir.glob("*.pdf")):
        detection = detect_bank_type(str(pdf_path))
        if not detection.bank_id:
            print(f"ignored_unrecognized_pdf={pdf_path.name}")
            continue
        print(f"parsing={pdf_path.name}")
        transactions.extend(extract_transactions(str(pdf_path), detection.bank_id))

    profile = build_ai_input_profile(
        transactions,
        case_context,
        allow_business_names=settings.allow_business_names,
    )
    ai_candidate_count = int(profile["ai_candidate_count"])
    unique_semantic_count = int(profile["unique_semantic_signature_count"])
    audit = build_ai_input_audit(
        transactions,
        case_context,
        allow_business_names=settings.allow_business_names,
    )
    acceptance_scope_count = int(
        audit["legacy_unique_semantic_signature_count"]
    )
    if not ai_candidate_count or not unique_semantic_count:
        print("status=not_started")
        print("reason=no_eligible_ai_candidates")
        return 2

    eligible_transactions, eligible_count = select_ai_input_sample(
        transactions,
        case_context,
        allow_business_names=settings.allow_business_names,
        sample_size=ai_candidate_count,
    )
    if eligible_count != ai_candidate_count:
        print("status=failed_closed")
        print("reason=ai_candidate_profile_mismatch")
        return 1

    expected_batch_count = math.ceil(
        unique_semantic_count / settings.batch_size
    )
    print(f"parsed_transactions={len(transactions)}")
    print(f"ai_candidate_transactions={ai_candidate_count}")
    print(f"acceptance_scope_unique_semantics={acceptance_scope_count}")
    print(f"unique_semantic_signatures={unique_semantic_count}")
    print(f"expected_provider_batches={expected_batch_count}")

    observation = build_ai_business_observation(
        eligible_transactions,
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
            eligible_count=unique_semantic_count,
            sampled_transactions=eligible_transactions,
            observation=observation,
            full_run=True,
            expected_batch_count=expected_batch_count,
            acceptance_scope_count=acceptance_scope_count,
        )
        + "\n",
        encoding="utf-8",
    )

    value = observation["value"]
    accepted_count = len(value["ai_candidates"])
    if not value["available"] or accepted_count != ai_candidate_count:
        print("status=failed_closed")
        print(f"reason={value['reason'] or 'expanded_result_count_mismatch'}")
        if value.get("failure_detail"):
            print(f"failure_detail={value['failure_detail']}")
        summary = value.get("validation_failure_summary", {})
        if isinstance(summary, dict):
            print(f"validation_failure_count={summary.get('total', 0)}")
            for failure_reason, count in sorted(
                dict(summary.get("counts", {})).items()
            ):
                print(f"validation_failure_{failure_reason}={count}")
        print(
            "provisional_valid_results="
            f"{len(value.get('provisional_ai_candidates', []))}"
        )
        print(f"accepted_ai_results={accepted_count}")
        print(f"report={args.output_path}")
        return 1

    print("status=ok")
    print(f"accepted_ai_results={accepted_count}")
    print(f"report={args.output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
