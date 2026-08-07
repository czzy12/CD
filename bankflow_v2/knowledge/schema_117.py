"""Schema 1.17 contract: business_semantics_resolutions observation + diagnostics."""

from __future__ import annotations

from typing import Any


SCHEMA_117_OBSERVATION_TYPE = "business_semantics_resolutions"
PRODUCTION_RESOLVER_LEGACY = "legacy_v11"


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
