"""Gate F1.3.1: minimal real AI contracts for evidence role and case synthesis.

Lifecycle separation is strict:

    Transaction-level AI -> KnowledgeCandidate(pending) -> Human Review
    Case-level AI        -> CaseObservation (never KnowledgeCandidate)

This module never self-approves, never writes canonical KB, and never lets a
CaseObservation sink into reusable knowledge.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from ..deepseek_adapter import DeepSeekSettings, _chat_completions_url
from .evidence import EVIDENCE_ROLES, TRACE_STRENGTHS
from .models import KnowledgeCandidate
from .privacy import build_privacy_preflight, guard_item
from .repository import RuntimeKnowledgeRepository
from .routing import (
    BUSINESS_EVIDENCE_TASK_VERSION,
    CASE_SYNTHESIS_TASK_VERSION,
    COVERAGE_VALUES,
)


ROLE_VALUES = sorted(EVIDENCE_ROLES)
STRENGTH_VALUES = sorted(TRACE_STRENGTHS)
CONFIDENCE_VALUES = ("high", "medium", "low")
PRESENCE_VALUES = ("strong", "medium", "weak", "undetermined")
CONSISTENCY_VALUES = ("strong", "medium", "weak", "none", "undetermined")

Transport = Callable[[str, bytes, Mapping[str, str], float], bytes]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_transport(
    url: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _post(
    settings: DeepSeekSettings,
    transport: Transport,
    *,
    task_type: str,
    prompt_version: str,
    payload: Mapping[str, Any],
    output_schema: Mapping[str, Any],
    system_prompt: str,
) -> dict[str, Any]:
    endpoint = _chat_completions_url(settings.base_url)
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    request = {
        "model": settings.model,
        "stream": False,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 4096,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task_type": task_type,
                        "prompt_version": prompt_version,
                        "output_schema": output_schema,
                        **payload,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    try:
        raw = transport(
            endpoint,
            json.dumps(request, ensure_ascii=False).encode("utf-8"),
            headers,
            settings.timeout_seconds,
        )
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise RuntimeError("provider request failed") from exc
    try:
        envelope = json.loads(raw.decode("utf-8"))
        content = envelope["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("provider returned invalid JSON") from exc


def _check_authorized(settings: DeepSeekSettings) -> None:
    if not (
        settings.enabled
        and settings.data_authorized
        and settings.retention_policy_confirmed
        and settings.api_key
    ):
        raise RuntimeError("AI authorization incomplete")


def privacy_preflight_for_items(
    items: list[dict[str, Any]],
    *,
    task: str,
    prompt_version: str,
    provider: str,
    model: str,
) -> tuple[dict[str, Any], list[str]]:
    """Read-only preflight; blocked items are never sent."""
    preflight = build_privacy_preflight(
        task=task,
        prompt_version=prompt_version,
        provider=provider,
        model=model,
        items=items,
    )
    blocked_ids: list[str] = []
    for item in items:
        guard = guard_item(item.get("fields", {}))
        if not guard.allowed:
            blocked_ids.append(str(item.get("item_id", "")))
    return preflight, blocked_ids


def validate_transaction_evidence_result(
    result: Mapping[str, Any],
    item: Mapping[str, Any],
) -> list[str]:
    failures: list[str] = []
    item_id = str(result.get("item_id", ""))
    if item_id != str(item.get("item_id", "")):
        failures.append("item_id_mismatch")
    if str(result.get("role", "")) not in ROLE_VALUES:
        failures.append("role_invalid")
    if str(result.get("trace_strength", "")) not in STRENGTH_VALUES:
        failures.append("trace_strength_invalid")
    if str(result.get("confidence", "")) not in CONFIDENCE_VALUES:
        failures.append("confidence_invalid")
    if not str(result.get("reason", "")).strip():
        failures.append("reason_missing")
    refs = result.get("evidence_refs")
    if not isinstance(refs, list) or not refs:
        failures.append("evidence_refs_missing")
    else:
        allowed = {str(item.get("item_id", ""))}
        if not set(map(str, refs)).issubset(allowed):
            failures.append("evidence_refs_not_allowed")
    return failures


def call_transaction_evidence_ai(
    settings: DeepSeekSettings,
    items: list[dict[str, Any]],
    *,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Real-call business-evidence-task-v1 with strict validation.

    Reusable transaction semantics become pending KnowledgeCandidates only.
    """
    _check_authorized(settings)
    safe_items = [
        {
            "item_id": str(item.get("item_id", "")),
            "fields": {
                str(name): str(value)
                for name, value in item.get("fields", {}).items()
                if str(name) in {
                    "counterparty_name",
                    "merchant_name",
                    "summary",
                    "remark",
                    "purpose",
                    "product_description",
                    "merchant_category",
                }
                and str(value).strip()
            },
            "direction": str(item.get("direction", "")),
            "semantic_concept": str(item.get("semantic_concept", "")),
            "declared_industry": str(item.get("declared_industry", "")),
        }
        for item in items
    ]
    preflight, blocked_ids = privacy_preflight_for_items(
        safe_items,
        task="business_evidence_role",
        prompt_version=BUSINESS_EVIDENCE_TASK_VERSION,
        provider="deepseek",
        model=settings.model,
    )
    if blocked_ids:
        raise RuntimeError(
            "privacy preflight blocked items; nothing was sent: "
            + ",".join(blocked_ids)
        )
    output_schema = {
        "type": "object",
        "required": ["results"],
        "properties": {
            "results": {
                "type": "array",
                "minItems": len(safe_items),
                "maxItems": len(safe_items),
                "items": {
                    "type": "object",
                    "required": [
                        "item_id",
                        "role",
                        "trace_strength",
                        "context_dependency",
                        "reason",
                        "evidence_refs",
                        "confidence",
                    ],
                    "properties": {
                        "item_id": {"type": "string"},
                        "role": {"type": "string", "enum": ROLE_VALUES},
                        "trace_strength": {
                            "type": "string",
                            "enum": STRENGTH_VALUES,
                        },
                        "context_dependency": {"type": "string"},
                        "reason": {"type": "string", "minLength": 1},
                        "evidence_refs": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string"},
                        },
                        "confidence": {
                            "type": "string",
                            "enum": list(CONFIDENCE_VALUES),
                        },
                    },
                },
            }
        },
    }
    response = _post(
        settings,
        transport or _default_transport,
        task_type="business_evidence_role",
        prompt_version=BUSINESS_EVIDENCE_TASK_VERSION,
        payload={
            "items": safe_items,
            "instructions": [
                "role 只允许：direct_business/operating_expense/tax_regulatory/"
                "financing/settlement_infrastructure/employment_operation/"
                "government_interaction/personal_consumption/neutral_transfer/unknown",
                "trace_strength 只允许 strong/medium/weak/none/undetermined",
                "支付渠道（微信/支付宝/财付通/POS/云闪付）本身不构成经营 role",
                "证据不足时允许 unknown/undetermined，不得强行分类",
                "不得输出越权 canonical 决策；你只提出 role/trace 候选",
                "只能引用 item_id 作为 evidence_ref",
            ],
            "output_schema": output_schema,
        },
        output_schema=output_schema,
        system_prompt=(
            "你是银行流水 Business Evidence Role 助手。只做可审计的 role 与 "
            "trace strength 候选判断，不做风控/欺诈/包装/准入结论。"
            "只能引用输入中真实存在的字段与 item_id。不确定时返回 "
            "unknown/undetermined。输出必须严格符合给定 JSON 结构。"
        ),
    )
    results = response.get("results")
    if not isinstance(results, list):
        raise RuntimeError("transaction evidence results must be a list")
    by_id = {str(item["item_id"]): item for item in safe_items}
    accepted: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, Mapping):
            failures.append({"reason": "result_not_object"})
            continue
        item_id = str(result.get("item_id", ""))
        item = by_id.get(item_id)
        if item is None:
            failures.append({"item_id": item_id, "reason": "unknown_item"})
            continue
        item_failures = validate_transaction_evidence_result(result, item)
        if item_failures:
            failures.append(
                {
                    "item_id": item_id,
                    "failures": item_failures,
                }
            )
            continue
        accepted.append(
            {
                **dict(result),
                "fields": dict(item["fields"]),
                "direction": item["direction"],
                "semantic_concept": item["semantic_concept"],
                "declared_industry": item["declared_industry"],
            }
        )
    return {
        "preflight": preflight,
        "provider": "deepseek",
        "model": settings.model,
        "prompt_version": BUSINESS_EVIDENCE_TASK_VERSION,
        "sent_item_count": len(safe_items),
        "accepted_count": len(accepted),
        "failure_count": len(failures),
        "accepted": accepted,
        "failures": failures,
        "outbound_pii": 0,
        "candidate_lifecycle": "pending_only",
        "self_approve": False,
    }


def persist_transaction_evidence_candidates(
    repository: RuntimeKnowledgeRepository,
    result: Mapping[str, Any],
    *,
    model: str,
) -> list[dict[str, Any]]:
    """Persist accepted reusable transaction semantics as pending candidates."""
    records: list[dict[str, Any]] = []
    for item in result.get("accepted", []):
        candidate = KnowledgeCandidate(
            candidate_id=uuid.uuid4().hex,
            candidate_type="business_evidence_role",
            proposed_value={
                "role": item.get("role"),
                "trace_strength": item.get("trace_strength"),
                "context_dependency": item.get("context_dependency"),
                "reason": item.get("reason"),
                "evidence_refs": item.get("evidence_refs"),
                "confidence": item.get("confidence"),
            },
            reason=str(item.get("reason", "")),
            model=model,
            prompt_version=BUSINESS_EVIDENCE_TASK_VERSION,
            input_signature={
                "fields": item.get("fields"),
                "direction": item.get("direction"),
                "semantic_concept": item.get("semantic_concept"),
                "declared_industry": item.get("declared_industry"),
            },
            created_at=_utcnow(),
            review_status="pending",
        )
        added = repository.add_candidate(candidate)
        records.append(
            {
                "candidate_id": candidate.candidate_id,
                "added": added,
                "review_status": "pending",
                "role": item.get("role"),
                "trace_strength": item.get("trace_strength"),
            }
        )
    return records


def build_transaction_evidence_observations(
    result: Mapping[str, Any],
    *,
    provider: str,
    model: str,
) -> list[dict[str, Any]]:
    """Current-case non-canonical observations from accepted AI results.

    These observations may feed the current CaseEvidencePack, but they never
    become canonical knowledge by being used. Reusable knowledge must go
    through KnowledgeCandidate(pending) -> Human Review.
    """
    observations: list[dict[str, Any]] = []
    for item in result.get("accepted", []):
        observations.append(
            {
                "observation_type": "TransactionEvidenceObservation",
                "source": "ai",
                "provider": provider,
                "model": model,
                "contract_version": BUSINESS_EVIDENCE_TASK_VERSION,
                "evidence_refs": list(item.get("evidence_refs", [])),
                "confidence": str(item.get("confidence", "")),
                "uncertainty": str(item.get("context_dependency", "")),
                "role": str(item.get("role", "")),
                "trace_strength": str(item.get("trace_strength", "")),
                "reason": str(item.get("reason", "")),
                "non_canonical": True,
            }
        )
    return observations


def validate_case_observation(
    observation: Mapping[str, Any],
    pack: Mapping[str, Any],
    *,
    coverage: Mapping[str, Any] | None = None,
) -> list[str]:
    failures: list[str] = []
    if str(observation.get("business_activity_presence", "")) not in PRESENCE_VALUES:
        failures.append("business_activity_presence_invalid")
    if (
        str(observation.get("declared_industry_consistency", ""))
        not in CONSISTENCY_VALUES
    ):
        failures.append("declared_industry_consistency_invalid")
    if (
        str(observation.get("industry_consistency_evidence_coverage", ""))
        not in COVERAGE_VALUES
    ):
        failures.append("industry_consistency_evidence_coverage_invalid")
    if not str(observation.get("reasoning_summary", "")).strip():
        failures.append("reasoning_summary_missing")
    allowed_refs = set(map(str, pack.get("evidence_refs", [])))
    for key in ("supporting_evidence_refs", "contradictory_evidence_refs"):
        refs = observation.get(key)
        if not isinstance(refs, list):
            failures.append(f"{key}_missing")
            continue
        if not set(map(str, refs)).issubset(allowed_refs):
            failures.append(f"{key}_not_in_pack")
    if (
        pack.get("evidence_availability", {})
        .get("semantics", {})
        .get("unavailable_not_absent")
        is not True
    ):
        failures.append("pack_availability_semantics_missing")
    # Coverage logic guards: missing knowledge must never be read as
    # inconsistency, and partial coverage must not be over-confident.
    coverage_value = str(
        (coverage or {}).get("value")
        or pack.get("industry_consistency_evidence_coverage")
        or "unavailable"
    )
    if coverage_value in {
        "insufficient",
        "unavailable",
    }:
        if (
            str(observation.get("declared_industry_consistency", ""))
            != "undetermined"
        ):
            failures.append("coverage_insufficient_must_be_undetermined")
    elif coverage_value == "partial":
        if (
            str(observation.get("declared_industry_consistency", ""))
            == "strong"
        ):
            failures.append("coverage_partial_must_not_be_strong")
    return failures


def call_case_synthesis_ai(
    settings: DeepSeekSettings,
    pack: Mapping[str, Any],
    *,
    coverage: Mapping[str, Any] | None = None,
    transport: Transport | None = None,
) -> dict[str, Any]:
    """Real-call case-synthesis-ai-v1 -> CaseObservation (never candidate)."""
    _check_authorized(settings)
    output_schema = {
        "type": "object",
        "required": [
            "business_activity_presence",
            "declared_industry_consistency",
            "industry_consistency_evidence_coverage",
            "supporting_evidence_refs",
            "contradictory_evidence_refs",
            "reasoning_summary",
            "uncertainty_reason",
        ],
        "properties": {
            "business_activity_presence": {
                "type": "string",
                "enum": list(PRESENCE_VALUES),
            },
            "declared_industry_consistency": {
                "type": "string",
                "enum": list(CONSISTENCY_VALUES),
            },
            "industry_consistency_evidence_coverage": {
                "type": "string",
                "enum": sorted(COVERAGE_VALUES),
            },
            "supporting_evidence_refs": {
                "type": "array",
                "items": {"type": "string"},
            },
            "contradictory_evidence_refs": {
                "type": "array",
                "items": {"type": "string"},
            },
            "reasoning_summary": {"type": "string", "minLength": 1},
            "uncertainty_reason": {"type": "string"},
        },
    }
    response = _post(
        settings,
        transport or _default_transport,
        task_type="case_synthesis",
        prompt_version=CASE_SYNTHESIS_TASK_VERSION,
        payload={
            "case_evidence_pack": dict(pack),
            "industry_consistency_evidence_coverage": (
                coverage or {}
            ).get("value", "unavailable"),
            "coverage_reason": (coverage or {}).get("reason", ""),
            "instructions": [
                "business_activity_presence 与 declared_industry_consistency "
                "是两个独立问题，必须分开判断",
                "knowledge coverage insufficient/partial 不等于行业不一致",
                "evidence unavailable 不等于 evidence absent",
                "只能引用 CaseEvidencePack evidence_refs 中的真实 refs",
                "不得创造不存在的交易",
                "支付渠道语义不构成经营实质",
                "输出是 CaseObservation，不是 reusable knowledge",
            ],
            "output_schema": output_schema,
        },
        output_schema=output_schema,
        system_prompt=(
            "你是案件级经营证据综合助手。基于压缩后的 CaseEvidencePack 做 "
            "CaseObservation 判断，不做风控/欺诈/包装/准入结论。"
            "必须把经营存在与申报行业一致性分开；知识覆盖不足时只能给 "
            "qualified weak/undetermined，绝不能把覆盖不足解释为不一致。"
            "输出必须严格符合给定 JSON 结构。"
        ),
    )
    failures = validate_case_observation(response, pack, coverage=coverage)
    return {
        "provider": "deepseek",
        "model": settings.model,
        "prompt_version": CASE_SYNTHESIS_TASK_VERSION,
        "observation": dict(response),
        "validation_failures": failures,
        "validated": not failures,
        "lifecycle": "case_observation_only",
        "knowledge_candidate_created": False,
        "canonical_written": False,
    }
