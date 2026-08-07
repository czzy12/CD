"""Real AI fallback validation pipeline (knowledge tasks, candidate-only).

Everything here keeps knowledge_v1 in shadow mode: AI output may only become
KnowledgeCandidate(pending). No canonical mutation, no production switch.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..ai_business_observation import (
    AI_INPUT_FIELDS,
    _safe_ai_fields,
    analyze_ai_semantic_fields,
    build_classification_constraints,
)
from .ai_fallback import DeepSeekKnowledgeAdapter, KnowledgeAIError
from .models import IndustryProfile
from .normalization import semantic_signature_from_fields
from .privacy import build_privacy_preflight, guard_item
from .relations import cap_strength
from .repository import RuntimeKnowledgeRepository
from .resolver import KnowledgeRuntime
from .review import KnowledgeReviewService
from .versioning import (
    KNOWLEDGE_VERSION,
    PROMPT_INDUSTRY_RELATION_VERSION,
    PROMPT_SEMANTIC_CONCEPT_VERSION,
    RESOLVER_VERSION,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _text_hash(fields: Mapping[str, str]) -> str:
    encoded = json.dumps(
        sorted(fields.items()),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def safe_validation_fields(fields: Mapping[str, object]) -> dict[str, str]:
    """Whitelist + business-name-only + semantic normalization for AI payload."""
    raw = {
        str(name): str(value)
        for name, value in fields.items()
        if str(name) in AI_INPUT_FIELDS and str(value or "").strip()
    }
    safe = _safe_ai_fields(raw, allow_business_names=True)
    analysis = analyze_ai_semantic_fields(safe)
    usable = analysis.get("usable_fields", {})
    if not isinstance(usable, Mapping):
        return {}
    return {
        str(name): str(value)
        for name, value in usable.items()
        if str(value or "").strip()
    }


def _profile_for(
    profile_resolver: Callable[[Mapping[str, Any]], IndustryProfile | None] | None,
    context: Mapping[str, Any],
    default_profile: IndustryProfile | None,
) -> IndustryProfile | None:
    if profile_resolver is not None:
        resolved = profile_resolver(context)
        if resolved is not None:
            return resolved
    return default_profile


def build_validation_items(
    entries: list[Mapping[str, Any]],
    runtime: KnowledgeRuntime,
    default_profile: IndustryProfile | None,
    *,
    profile_resolver: Callable[[Mapping[str, Any]], IndustryProfile | None]
    | None = None,
    source_label: str = "legacy-326",
    extra_items: list[Mapping[str, Any]] | None = None,
    only_signatures: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Dedupe by semantic signature; keep only local-unresolved items."""
    items: list[dict[str, Any]] = []
    by_signature: dict[str, dict[str, Any]] = {}
    counts = {
        "input_entries": 0,
        "no_semantic_fields": 0,
        "locally_resolved_skipped": 0,
        "eligible_transactions": 0,
        "eligible_unique_signatures": 0,
        "duplicated_signatures_skipped": 0,
        "excluded_by_filter": 0,
    }

    def append_entry(
        fields: Mapping[str, object],
        profile: IndustryProfile | None,
        source: str,
        member_count: int,
    ) -> None:
        counts["input_entries"] += member_count
        safe = safe_validation_fields(fields)
        if not safe:
            counts["no_semantic_fields"] += member_count
            return
        signature = semantic_signature_from_fields(safe)
        if not signature.pairs:
            counts["no_semantic_fields"] += member_count
            return
        if (
            only_signatures is not None
            and signature.signature_id not in only_signatures
        ):
            counts["excluded_by_filter"] += member_count
            return
        existing = by_signature.get(signature.signature_id)
        if existing is not None:
            existing["member_count"] += member_count
            counts["duplicated_signatures_skipped"] += member_count
            return
        resolved = runtime.resolve_transaction_fields(safe, profile)
        if resolved["semantic"].get("concept_id"):
            counts["locally_resolved_skipped"] += member_count
            return
        item = {
            "item_id": f"sig-{signature.signature_id}",
            "signature_hash": signature.signature_id,
            "signature_text_hash": _text_hash(safe),
            "fields": safe,
            "profile_name": (
                str(getattr(profile, "profile_name", "") or "")
                if profile is not None
                else ""
            ),
            "industry_ids": (
                list(profile.primary_industry_ids)
                + list(profile.secondary_industry_ids)
                if profile is not None
                else []
            ),
            "source": source,
            "member_count": member_count,
        }
        by_signature[signature.signature_id] = item
        items.append(item)

    for entry in entries:
        context = entry.get("legacy_business_context", {})
        if not isinstance(context, Mapping):
            context = {}
        profile = _profile_for(profile_resolver, context, default_profile)
        append_entry(
            entry.get("fields", {}),
            profile,
            source=source_label,
            member_count=1,
        )
    for extra in extra_items or []:
        context = extra if isinstance(extra, Mapping) else {}
        profile = _profile_for(profile_resolver, context, default_profile)
        append_entry(
            extra.get("fields", {}),
            profile,
            source=str(extra.get("source", "unseen")),
            member_count=1,
        )
    counts["eligible_transactions"] = sum(
        int(item["member_count"]) for item in items
    )
    counts["eligible_unique_signatures"] = len(items)
    return items, counts


def split_guarded(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    sendable: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for item in items:
        guard = guard_item(item["fields"])
        if guard.allowed:
            sendable.append(item)
        else:
            blocked.append(
                {
                    "signature_hash": item["signature_hash"],
                    "blocked_fields": list(guard.blocked_fields),
                    "blocked_reasons": list(guard.reasons),
                    "source": item["source"],
                }
            )
    return sendable, blocked


def call_with_retry(
    call: Callable[[], object],
    *,
    attempts: int = 2,
    delay: float = 1.0,
) -> dict[str, Any]:
    last_error = ""
    for attempt in range(1, attempts + 1):
        try:
            return {
                "status": "ok",
                "attempt_count": attempt,
                "result": call(),
            }
        except KnowledgeAIError as exc:
            last_error = str(exc) or exc.__class__.__name__
            if attempt < attempts:
                time.sleep(delay)
    return {
        "status": "failed",
        "attempt_count": attempts,
        "error": last_error,
    }


def _insufficient_concept(result: Mapping[str, Any]) -> bool:
    concept_id = str(result.get("concept_id", "") or "").strip()
    new_candidate = result.get("new_concept_candidate")
    return (
        concept_id in {"undetermined", "insufficient", "unknown"}
        and new_candidate is None
    )


def run_concept_validation(
    adapter: DeepSeekKnowledgeAdapter,
    items: list[dict[str, Any]],
    runtime: KnowledgeRuntime,
    repository: RuntimeKnowledgeRepository,
    *,
    batch_size: int = 50,
    attempts: int = 2,
    retry_delay: float = 1.0,
    provider_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Call semantic-concept-v1 and persist pending KnowledgeCandidates."""
    runs = provider_runs if provider_runs is not None else []
    review = KnowledgeReviewService(repository, _canonical_dir())
    concept_candidates = [
        {
            "concept_id": concept.concept_id,
            "name_zh": concept.name_zh,
        }
        for concept in runtime.concepts.active_concepts()
    ]
    by_id = {item["item_id"]: item for item in items}
    metrics = {
        "ai_invoked": 0,
        "ai_success": 0,
        "ai_failed": 0,
        "ai_retry": 0,
        "concept_candidates": 0,
        "existing_concept_proposed": 0,
        "new_concept_proposed": 0,
        "insufficient": 0,
        "invalid": 0,
        "duplicate_candidate_prevented": 0,
        "items_remaining_unresolved": 0,
    }
    accepted_entries: list[dict[str, Any]] = []
    candidate_records: list[dict[str, Any]] = []
    for offset in range(0, len(items), batch_size):
        batch = items[offset : offset + batch_size]
        batch_items = [
            {"item_id": item["item_id"], "fields": item["fields"]}
            for item in batch
        ]
        outcome = call_with_retry(
            lambda: adapter.resolve_concepts(
                batch_items,
                concept_candidates=concept_candidates,
            ),
            attempts=attempts,
            delay=retry_delay,
        )
        batch_number = offset // batch_size + 1
        metrics["ai_invoked"] += 1
        if outcome["attempt_count"] > 1:
            metrics["ai_retry"] += 1
        run = {
            "batch_number": batch_number,
            "task": PROMPT_SEMANTIC_CONCEPT_VERSION,
            "attempt_count": outcome["attempt_count"],
            "status": outcome["status"],
            "item_count": len(batch),
            "error": outcome.get("error", ""),
        }
        if outcome["status"] == "failed":
            metrics["ai_failed"] += 1
            metrics["items_remaining_unresolved"] += len(batch)
            run["accepted_count"] = 0
            runs.append(run)
            continue
        metrics["ai_success"] += 1
        results = outcome["result"]
        run["accepted_count"] = len(results)
        runs.append(run)
        for result in results:
            item = by_id.get(str(result.get("item_id", "")))
            if item is None:
                metrics["invalid"] += 1
                continue
            if _insufficient_concept(result):
                metrics["insufficient"] += 1
                metrics["items_remaining_unresolved"] += 1
                continue
            new_candidate = result.get("new_concept_candidate")
            proposal_kind = (
                "new_concept"
                if isinstance(new_candidate, Mapping)
                else "existing_concept"
            )
            if proposal_kind == "new_concept":
                concept_id = str(new_candidate.get("suggested_concept_id", ""))
                concept_name = str(new_candidate.get("name_zh", ""))
                metrics["new_concept_proposed"] += 1
            else:
                concept_id = str(result.get("concept_id", ""))
                concept_obj = runtime.concepts.concept(concept_id)
                concept_name = (
                    concept_obj.name_zh if concept_obj is not None else concept_id
                )
                metrics["existing_concept_proposed"] += 1
            if not concept_id:
                metrics["invalid"] += 1
                metrics["items_remaining_unresolved"] += 1
                continue
            proposed = {
                "concept_id": concept_id,
                "name_zh": concept_name,
                "proposal_kind": proposal_kind,
                "signature_text_hash": item["signature_text_hash"],
                "confidence": str(result.get("confidence", "")),
                "used_fields": list(result.get("used_fields", [])),
                "task": PROMPT_SEMANTIC_CONCEPT_VERSION,
                "created_version": KNOWLEDGE_VERSION,
            }
            candidate = review.propose(
                candidate_type="new_semantic_concept",
                proposed_value=proposed,
                reason=str(result.get("reason", "")),
                model=adapter.model,
                prompt_version=PROMPT_SEMANTIC_CONCEPT_VERSION,
                input_signature={
                    "task": PROMPT_SEMANTIC_CONCEPT_VERSION,
                    "signature_hash": item["signature_hash"],
                    "signature_text_hash": item["signature_text_hash"],
                    "model": adapter.model,
                    "prompt_version": PROMPT_SEMANTIC_CONCEPT_VERSION,
                    "created_version": KNOWLEDGE_VERSION,
                    "resolver_version": RESOLVER_VERSION,
                },
            )
            if candidate is None:
                metrics["duplicate_candidate_prevented"] += 1
            else:
                metrics["concept_candidates"] += 1
                accepted_entries.append(
                    {
                        "item": item,
                        "concept_id": concept_id,
                        "concept_name": concept_name,
                        "proposal_kind": proposal_kind,
                        "candidate_id": candidate.candidate_id,
                    }
                )
                candidate_records.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "signature_hash": item["signature_hash"],
                        "proposal_kind": proposal_kind,
                        "concept_id": concept_id,
                        "name_zh": concept_name,
                        "confidence": str(result.get("confidence", "")),
                        "model": adapter.model,
                        "prompt_version": PROMPT_SEMANTIC_CONCEPT_VERSION,
                        "created_version": KNOWLEDGE_VERSION,
                        "review_status": "pending",
                    }
                )
    metrics["items_remaining_unresolved"] = (
        len(items)
        - metrics["concept_candidates"]
        - metrics["duplicate_candidate_prevented"]
    )
    return {
        "metrics": metrics,
        "accepted_entries": accepted_entries,
        "candidate_records": candidate_records,
        "provider_runs": runs,
    }


def _canonical_dir() -> Path:
    """Canonical dir fallback for review service (promotion is never used here)."""
    return Path(__file__).resolve().parent / "canonical"


def run_relation_validation(
    adapter: DeepSeekKnowledgeAdapter,
    accepted_entries: list[dict[str, Any]],
    runtime: KnowledgeRuntime,
    repository: RuntimeKnowledgeRepository,
    *,
    attempts: int = 2,
    retry_delay: float = 1.0,
    provider_runs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Natural industry-concept-relevance validation for new concepts only."""
    runs = provider_runs if provider_runs is not None else []
    review = KnowledgeReviewService(repository, _canonical_dir())
    industry_nodes = [
        {"industry_id": node.industry_id, "name": node.name}
        for node in runtime.taxonomy.nodes()
    ]
    eligible: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in accepted_entries:
        concept_id = entry["concept_id"]
        if entry["proposal_kind"] != "new_concept":
            continue
        for industry_id in entry["item"]["industry_ids"]:
            key = (industry_id, concept_id)
            if key in seen:
                continue
            if (
                runtime.relations.approved(industry_id, concept_id) is None
                and runtime.relations.approved("generic_business", concept_id)
                is None
            ):
                seen.add(key)
                eligible.append(
                    {
                        "item_id": f"{entry['item']['item_id']}|{industry_id}",
                        "industry_id": industry_id,
                        "concept_id": concept_id,
                        "concept_name": entry["concept_name"],
                        "specialty": (
                            entry["item"].get("industry_ids", [])
                            if isinstance(entry["item"].get("industry_ids"), list)
                            else []
                        ),
                        "constraints": build_classification_constraints(
                            entry["item"]["fields"]
                        ),
                        "item": entry["item"],
                    }
                )
    metrics = {
        "relation_eligible": len(eligible),
        "relation_invoked": 0,
        "relation_success": 0,
        "relation_failed": 0,
        "relation_retry": 0,
        "relation_candidates": 0,
        "guard_adjusted": 0,
        "duplicate_candidate_prevented": 0,
    }
    candidate_records: list[dict[str, Any]] = []
    if not eligible:
        return {
            "metrics": metrics,
            "candidate_records": candidate_records,
            "provider_runs": runs,
        }
    for offset in range(0, len(eligible), 50):
        batch = eligible[offset : offset + 50]
        outcome = call_with_retry(
            lambda: adapter.resolve_relations(
                [
                    {
                        "item_id": item["item_id"],
                        "industry_id": item["industry_id"],
                        "concept_id": item["concept_id"],
                        "concept_name": item["concept_name"],
                        "specialty": item["specialty"],
                        "constraints": item["constraints"],
                    }
                    for item in batch
                ],
                industry_nodes=industry_nodes,
            ),
            attempts=attempts,
            delay=retry_delay,
        )
        metrics["relation_invoked"] += 1
        if outcome["attempt_count"] > 1:
            metrics["relation_retry"] += 1
        run = {
            "batch_number": offset // 50 + 1,
            "task": PROMPT_INDUSTRY_RELATION_VERSION,
            "attempt_count": outcome["attempt_count"],
            "status": outcome["status"],
            "item_count": len(batch),
            "error": outcome.get("error", ""),
        }
        if outcome["status"] == "failed":
            metrics["relation_failed"] += 1
            runs.append(run)
            continue
        metrics["relation_success"] += 1
        results = outcome["result"]
        run["accepted_count"] = len(results)
        runs.append(run)
        by_id = {item["item_id"]: item for item in batch}
        for result in results:
            item = by_id.get(str(result.get("item_id", "")))
            if item is None:
                continue
            model_raw = str(result.get("relevance", "undetermined"))
            maximum = str(
                item["constraints"].get("maximum_allowed_strength", "strong")
            )
            guarded = cap_strength(model_raw, maximum)
            adjusted = guarded != model_raw
            if adjusted:
                metrics["guard_adjusted"] += 1
            candidate = review.propose(
                candidate_type="new_industry_relation",
                proposed_value={
                    "industry_id": item["industry_id"],
                    "concept_id": item["concept_id"],
                    "relevance": guarded,
                    "model_raw_relevance": model_raw,
                    "guard_adjusted": adjusted,
                    "signature_text_hash": item["item"]["signature_text_hash"],
                    "task": PROMPT_INDUSTRY_RELATION_VERSION,
                    "created_version": KNOWLEDGE_VERSION,
                },
                reason=str(result.get("reason", "")),
                model=adapter.model,
                prompt_version=PROMPT_INDUSTRY_RELATION_VERSION,
                input_signature={
                    "task": PROMPT_INDUSTRY_RELATION_VERSION,
                    "signature_hash": item["item"]["signature_hash"],
                    "industry_id": item["industry_id"],
                    "concept_id": item["concept_id"],
                    "model": adapter.model,
                    "prompt_version": PROMPT_INDUSTRY_RELATION_VERSION,
                    "created_version": KNOWLEDGE_VERSION,
                },
            )
            if candidate is None:
                metrics["duplicate_candidate_prevented"] += 1
            else:
                metrics["relation_candidates"] += 1
                candidate_records.append(
                    {
                        "candidate_id": candidate.candidate_id,
                        "industry_id": item["industry_id"],
                        "concept_id": item["concept_id"],
                        "relevance": guarded,
                        "model_raw_relevance": model_raw,
                        "guard_adjusted": adjusted,
                        "model": adapter.model,
                        "prompt_version": PROMPT_INDUSTRY_RELATION_VERSION,
                        "created_version": KNOWLEDGE_VERSION,
                        "review_status": "pending",
                    }
                )
    return {
        "metrics": metrics,
        "candidate_records": candidate_records,
        "provider_runs": runs,
    }


def write_validation_package(
    output_dir: str | Path,
    *,
    summary: Mapping[str, Any],
    preflight: Mapping[str, Any],
    provider_runs: list[Mapping[str, Any]],
    concept_candidates: list[Mapping[str, Any]],
    relation_candidates: list[Mapping[str, Any]],
) -> list[Path]:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    files = {
        "summary.json": summary,
        "privacy_preflight.json": preflight,
        "provider_runs.json": provider_runs,
        "concept_candidates.json": concept_candidates,
        "relation_candidates.json": relation_candidates,
        "candidate_review.md": render_candidate_review(
            concept_candidates,
            relation_candidates,
            summary,
        ),
    }
    written: list[Path] = []
    for name, value in files.items():
        path = root / name
        if name.endswith(".md"):
            path.write_text(str(value), encoding="utf-8")
        else:
            path.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        written.append(path)
    return written


def render_candidate_review(
    concept_candidates: list[Mapping[str, Any]],
    relation_candidates: list[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> str:
    lines = [
        "# 真实 AI Fallback Validation - 人工审核包",
        "",
        f"- 生成时间：{_utcnow()}",
        f"- 新 pending concept candidates：{len(concept_candidates)}",
        f"- 新 pending relation candidates：{len(relation_candidates)}",
        f"- 本阶段自动 approved = 0；自动 rejected = 0",
        "",
        "## Concept Candidates（仅签名哈希与通用语义，无完整敏感字段）",
        "",
        "| candidate_id | 签名哈希 | 提议 | 概念 | 置信度 | 模型 | 任务版本 | 状态 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in concept_candidates:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("candidate_id", "")),
                    str(item.get("signature_hash", ""))[:24],
                    str(item.get("proposal_kind", "")),
                    str(item.get("concept_id", "")) + " / " + str(item.get("name_zh", "")),
                    str(item.get("confidence", "")),
                    str(item.get("model", "")),
                    str(item.get("prompt_version", "")),
                    "pending",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Relation Candidates",
            "",
            "| candidate_id | 行业 | 概念 | 提议强度 | guard 调整 | 状态 |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in relation_candidates:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(item.get("candidate_id", "")),
                    str(item.get("industry_id", "")),
                    str(item.get("concept_id", "")),
                    str(item.get("relevance", "")),
                    str(item.get("guard_adjusted", "")),
                    "pending",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## 审核决策（人工）",
            "",
            "对每条候选可选择：approve / reject / modify / insufficient。",
            "本阶段不得由 AI 或同一执行流程自动写 canonical。",
        ]
    )
    return "\n".join(lines)
