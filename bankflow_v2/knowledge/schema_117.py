"""Schema 1.17 contract: business_semantics_resolutions observation + diagnostics."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


SCHEMA_117_OBSERVATION_TYPE = "business_semantics_resolutions"
PRODUCTION_RESOLVER_LEGACY = "legacy_v11"


def _canonical_dir() -> Path:
    return Path(__file__).resolve().parent / "canonical"


def _relation_id(
    industry_id: str,
    concept_id: str,
    relation_kb_version: str,
) -> str:
    digest = hashlib.sha256(
        f"{industry_id}:{concept_id}:{relation_kb_version}".encode("utf-8")
    ).hexdigest()[:16]
    return f"rel-{digest}"


def _concept_source(semantic: Mapping[str, Any]) -> str:
    source = str(semantic.get("source", ""))
    reason = str(semantic.get("reason", ""))
    if source == "knowledge_base" and reason.startswith("别名精确命中"):
        return "exact_alias"
    if source == "knowledge_base":
        return "knowledge_base"
    if source == "cache":
        return "semantic_cache"
    if source == "ai_candidate":
        return "ai_candidate"
    return "unresolved"


def _relation_source(value: str) -> str:
    return {
        "approved_exact": "exact_relation",
        "specialty": "specialty_relation",
        "inherited": "inherited_relation",
        "generic_business": "generic_business_relation",
        "cache": "relation_cache",
        "ai_candidate": "ai_candidate",
        "undetermined": "unresolved",
    }.get(value, "unresolved")


def _inherited_from(
    runtime: Any,
    industry_id: str,
    concept_id: str,
) -> str:
    for node in runtime.taxonomy.parent_chain(industry_id)[1:]:
        if runtime.relations.approved(node.industry_id, concept_id) is not None:
            return node.industry_id
    return ""


def empty_resolutions_observation(
    *,
    migration_status: str = "not_parsed",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Empty schema 1.17 observation + diagnostics (no fabricated history)."""
    observation = {
        "observation_type": SCHEMA_117_OBSERVATION_TYPE,
        "value": {
            "knowledge_version": "",
            "taxonomy_version": "",
            "semantic_kb_version": "",
            "relation_kb_version": "",
            "resolver_version": "",
            "resolutions": [],
        },
        "parameters": {
            "shadow": True,
            "production_resolver": PRODUCTION_RESOLVER_LEGACY,
        },
        "field_coverage": {
            "required_fields": [
                "counterparty_name",
                "summary",
                "remark",
                "purpose",
                "product_description",
                "merchant_name",
                "merchant_category",
            ],
            "eligible_transaction_count": 0,
            "covered_transaction_count": 0,
        },
        "evidence_transaction_ids": [],
    }
    diagnostics = {
        "knowledge_v1": {
            "shadow": True,
            "production_resolver": PRODUCTION_RESOLVER_LEGACY,
            "migration_status": migration_status,
            "resolved_count": 0,
            "unknown_concept_count": 0,
            "unknown_relation_count": 0,
            "concept_ai_fallback_theoretical": 0,
            "relation_ai_fallback_theoretical": 0,
            "legacy_comparison": {},
        }
    }
    return observation, diagnostics


def build_business_semantics_resolutions(
    transactions: Iterable[Any],
    case_context: Mapping[str, object] | None,
    *,
    runtime: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write knowledge_v1 shadow resolutions into a schema 1.17 observation."""
    from ..ai_business_observation import AI_INPUT_FIELDS
    from .normalization import build_industry_profile, semantic_signature_from_fields
    from .resolver import KnowledgeRuntime

    if runtime is None:
        canonical = _canonical_dir()
        if not (canonical / "taxonomy.json").is_file():
            return empty_resolutions_observation(migration_status="not_parsed")
        runtime = KnowledgeRuntime.load(canonical)
    profile_input: dict[str, object] = {}
    if isinstance(case_context, Mapping):
        business_context = case_context.get("business_context")
        if isinstance(business_context, Mapping):
            profile_input.update(
                {
                    str(name): value
                    for name, value in business_context.items()
                    if str(name)
                    in {
                        "confirmed_primary_business",
                        "confirmed_products_or_services",
                        "declared_work_description",
                    }
                }
            )
        search_context = case_context.get("search_context")
        if isinstance(search_context, Mapping):
            for key in ("declared_industries", "work_units"):
                value = search_context.get(key)
                if isinstance(value, list):
                    profile_input[key] = value
    profile = build_industry_profile(profile_input, runtime.taxonomy)
    grouped: dict[str, dict[str, Any]] = {}
    evidence_ids: list[str] = []
    for transaction in transactions:
        fields: dict[str, str] = {}
        for field_name in AI_INPUT_FIELDS:
            value = str(getattr(transaction, field_name, "") or "").strip()
            if value and transaction.field_confidence.get(field_name) == 1.0:
                fields[field_name] = value
        signature = semantic_signature_from_fields(fields)
        if not signature.pairs:
            continue
        evidence_ids.append(transaction.transaction_id)
        bucket = grouped.setdefault(
            signature.signature_id,
            {
                "signature_id": signature.signature_id,
                "fields": fields,
                "transaction_ref": transaction.transaction_id,
                "transaction_ids": [],
            },
        )
        bucket["transaction_ids"].append(transaction.transaction_id)

    resolutions: list[dict[str, Any]] = []
    unknown_concept = 0
    unknown_relation = 0
    for bucket in grouped.values():
        resolved = runtime.resolve_transaction_fields(bucket["fields"], profile)
        semantic = resolved["semantic"]
        if semantic["source"] == "undetermined" or not semantic["concept_id"]:
            unknown_concept += 1
            continue
        concept_id = str(semantic["concept_id"])
        final_relevance = str(resolved["final_relevance"])
        if final_relevance == "undetermined":
            unknown_relation += 1
            continue
        best = next(
            (
                relation
                for relation in resolved["relations"]
                if str(relation.get("relevance", "")) == final_relevance
            ),
            None,
        )
        if best is None:
            unknown_relation += 1
            continue
        industry_id = str(best.get("industry_id", ""))
        relation_source = str(best.get("relation_source", "undetermined"))
        inherited = relation_source == "inherited"
        resolutions.append(
            {
                "resolution_id": f"res-{len(resolutions) + 1:06d}",
                "transaction_ref": bucket["transaction_ref"],
                "semantic_signature_ref": bucket["signature_id"],
                "concept_id": concept_id,
                "concept_name_snapshot": str(
                    semantic.get("concept_name", "")
                ),
                "concept_resolution_source": _concept_source(semantic),
                "industry_id": industry_id,
                "industry_name_snapshot": (
                    runtime.taxonomy.node(industry_id).name
                    if runtime.taxonomy.node(industry_id)
                    else ""
                ),
                "relation_id": _relation_id(
                    industry_id,
                    concept_id,
                    runtime.version.relation_kb_version,
                ),
                "relation_resolution_source": _relation_source(
                    relation_source
                ),
                "relevance": final_relevance,
                "inherited": inherited,
                "inherited_from_industry_id": (
                    _inherited_from(runtime, industry_id, concept_id)
                    if inherited
                    else ""
                ),
                "review_status": "approved",
            }
        )

    observation = {
        "observation_type": SCHEMA_117_OBSERVATION_TYPE,
        "value": {
            "knowledge_version": runtime.version.knowledge_version,
            "taxonomy_version": runtime.version.taxonomy_version,
            "semantic_kb_version": runtime.version.semantic_kb_version,
            "relation_kb_version": runtime.version.relation_kb_version,
            "resolver_version": runtime.version.resolver_version,
            "resolutions": resolutions,
        },
        "parameters": {
            "shadow": True,
            "production_resolver": PRODUCTION_RESOLVER_LEGACY,
        },
        "field_coverage": {
            "required_fields": list(AI_INPUT_FIELDS),
            "eligible_transaction_count": len(evidence_ids),
            "covered_transaction_count": len(evidence_ids),
        },
        "evidence_transaction_ids": list(dict.fromkeys(evidence_ids)),
    }
    diagnostics = {
        "knowledge_v1": {
            "shadow": True,
            "production_resolver": PRODUCTION_RESOLVER_LEGACY,
            "migration_status": "parsed",
            "resolved_count": len(resolutions),
            "unknown_concept_count": unknown_concept,
            "unknown_relation_count": unknown_relation,
            "concept_ai_fallback_theoretical": unknown_concept,
            "relation_ai_fallback_theoretical": unknown_relation,
            "legacy_comparison": {},
        }
    }
    return observation, diagnostics
