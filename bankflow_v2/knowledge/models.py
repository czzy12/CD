"""Data models for the business-semantics knowledge base (knowledge_v1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


RELEVANCE_VALUES = frozenset(
    {"strong", "medium", "weak", "none", "undetermined"}
)
REVIEW_STATUS_VALUES = frozenset(
    {"pending", "approved", "rejected", "deprecated"}
)
CANDIDATE_TYPES = frozenset(
    {"new_semantic_concept", "new_industry_relation", "new_alias"}
)
RESOLUTION_SOURCES = frozenset(
    {"deterministic", "knowledge_base", "cache", "ai_candidate", "undetermined"}
)
RELATION_SOURCES = frozenset(
    {
        "approved_exact",
        "specialty",
        "inherited",
        "generic_business",
        "cache",
        "ai_candidate",
        "undetermined",
    }
)
CONCEPT_RESOLUTION_SOURCES = frozenset(
    {"exact_alias", "knowledge_base", "semantic_cache", "ai_candidate", "unresolved"}
)
RELATION_RESOLUTION_SOURCES = frozenset(
    {
        "exact_relation",
        "specialty_relation",
        "inherited_relation",
        "generic_business_relation",
        "relation_cache",
        "ai_candidate",
        "unresolved",
    }
)
SCHEMA_REVIEW_STATUS_VALUES = frozenset({"approved", "unresolved", "candidate"})


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class IndustryNode:
    industry_id: str
    name: str
    parent_id: str
    level: int
    aliases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    status: str = "active"
    source: str = ""
    source_version: str = ""
    knowledge_version: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "IndustryNode":
        return cls(
            industry_id=str(value.get("industry_id", "")),
            name=str(value.get("name", "")),
            parent_id=str(value.get("parent_id", "")),
            level=int(value.get("level", 0)),
            aliases=tuple(str(item) for item in value.get("aliases", [])),
            keywords=tuple(str(item) for item in value.get("keywords", [])),
            status=str(value.get("status", "active")),
            source=str(value.get("source", "")),
            source_version=str(value.get("source_version", "")),
            knowledge_version=str(value.get("knowledge_version", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "industry_id": self.industry_id,
            "name": self.name,
            "parent_id": self.parent_id,
            "level": self.level,
            "aliases": list(self.aliases),
            "keywords": list(self.keywords),
            "status": self.status,
            "source": self.source,
            "source_version": self.source_version,
            "knowledge_version": self.knowledge_version,
        }


@dataclass(frozen=True)
class SemanticConcept:
    concept_id: str
    name_zh: str
    aliases: tuple[str, ...] = ()
    keywords: tuple[str, ...] = ()
    parent_concept_id: str = ""
    description: str = ""
    examples_generic: tuple[str, ...] = ()
    status: str = "active"
    source: str = ""
    knowledge_version: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SemanticConcept":
        return cls(
            concept_id=str(value.get("concept_id", "")),
            name_zh=str(value.get("name_zh", "")),
            aliases=tuple(str(item) for item in value.get("aliases", [])),
            keywords=tuple(str(item) for item in value.get("keywords", [])),
            parent_concept_id=str(value.get("parent_concept_id", "")),
            description=str(value.get("description", "")),
            examples_generic=tuple(
                str(item) for item in value.get("examples_generic", [])
            ),
            status=str(value.get("status", "active")),
            source=str(value.get("source", "")),
            knowledge_version=str(value.get("knowledge_version", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "name_zh": self.name_zh,
            "aliases": list(self.aliases),
            "keywords": list(self.keywords),
            "parent_concept_id": self.parent_concept_id,
            "description": self.description,
            "examples_generic": list(self.examples_generic),
            "status": self.status,
            "source": self.source,
            "knowledge_version": self.knowledge_version,
        }


@dataclass(frozen=True)
class SemanticAlias:
    alias_id: str
    alias_text: str
    concept_id: str
    status: str = "active"
    source: str = ""
    knowledge_version: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SemanticAlias":
        return cls(
            alias_id=str(value.get("alias_id", "")),
            alias_text=str(value.get("alias_text", "")),
            concept_id=str(value.get("concept_id", "")),
            status=str(value.get("status", "active")),
            source=str(value.get("source", "")),
            knowledge_version=str(value.get("knowledge_version", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "alias_id": self.alias_id,
            "alias_text": self.alias_text,
            "concept_id": self.concept_id,
            "status": self.status,
            "source": self.source,
            "knowledge_version": self.knowledge_version,
        }


@dataclass(frozen=True)
class IndustryConceptRelation:
    industry_id: str
    concept_id: str
    relevance: str
    reason_template: str = ""
    source: str = "curated"
    review_status: str = "approved"
    confidence_tier: str = "generic"
    knowledge_version: str = ""
    created_by: str = ""
    reviewed_at: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "IndustryConceptRelation":
        return cls(
            industry_id=str(value.get("industry_id", "")),
            concept_id=str(value.get("concept_id", "")),
            relevance=str(value.get("relevance", "undetermined")),
            reason_template=str(value.get("reason_template", "")),
            source=str(value.get("source", "curated")),
            review_status=str(value.get("review_status", "approved")),
            confidence_tier=str(value.get("confidence_tier", "generic")),
            knowledge_version=str(value.get("knowledge_version", "")),
            created_by=str(value.get("created_by", "")),
            reviewed_at=str(value.get("reviewed_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "industry_id": self.industry_id,
            "concept_id": self.concept_id,
            "relevance": self.relevance,
            "reason_template": self.reason_template,
            "source": self.source,
            "review_status": self.review_status,
            "confidence_tier": self.confidence_tier,
            "knowledge_version": self.knowledge_version,
            "created_by": self.created_by,
            "reviewed_at": self.reviewed_at,
        }


@dataclass(frozen=True)
class IndustryProfile:
    primary_industry_ids: tuple[str, ...] = ()
    secondary_industry_ids: tuple[str, ...] = ()
    specialty_concept_ids: tuple[str, ...] = ()
    normalized_products_services: tuple[str, ...] = ()
    taxonomy_version: str = ""
    profile_version: str = "1"
    profile_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_industry_ids": list(self.primary_industry_ids),
            "secondary_industry_ids": list(self.secondary_industry_ids),
            "specialty_concept_ids": list(self.specialty_concept_ids),
            "normalized_products_services": list(
                self.normalized_products_services
            ),
            "taxonomy_version": self.taxonomy_version,
            "profile_version": self.profile_version,
            "profile_name": self.profile_name,
        }


@dataclass(frozen=True)
class SemanticSignature:
    signature_version: str
    pairs: tuple[tuple[str, str], ...]
    signature_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature_version": self.signature_version,
            "pairs": [list(pair) for pair in self.pairs],
            "signature_id": self.signature_id,
        }


@dataclass(frozen=True)
class SemanticResolution:
    concept_id: str
    concept_name: str
    confidence: str
    source: str
    reason: str
    knowledge_version: str
    concept_resolution_source: str = ""
    ai_used: bool = False
    review_required: bool = False
    matched_alias: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "concept_id": self.concept_id,
            "concept_name": self.concept_name,
            "confidence": self.confidence,
            "source": self.source,
            "reason": self.reason,
            "knowledge_version": self.knowledge_version,
            "concept_resolution_source": self.concept_resolution_source,
            "ai_used": self.ai_used,
            "review_required": self.review_required,
            "matched_alias": self.matched_alias,
        }


@dataclass(frozen=True)
class RelationResolution:
    industry_id: str
    concept_id: str
    relevance: str
    relation_source: str
    knowledge_version: str
    relation_resolution_source: str = ""
    reason: str = ""
    review_required: bool = False
    ai_used: bool = False
    applied_maximum_strength: str = "strong"
    directly_related_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "industry_id": self.industry_id,
            "concept_id": self.concept_id,
            "relevance": self.relevance,
            "relation_source": self.relation_source,
            "knowledge_version": self.knowledge_version,
            "relation_resolution_source": self.relation_resolution_source,
            "reason": self.reason,
            "review_required": self.review_required,
            "ai_used": self.ai_used,
            "applied_maximum_strength": self.applied_maximum_strength,
            "directly_related_allowed": self.directly_related_allowed,
        }


@dataclass
class KnowledgeCandidate:
    candidate_id: str
    candidate_type: str
    proposed_value: dict[str, Any]
    reason: str
    model: str
    prompt_version: str
    input_signature: dict[str, Any]
    created_at: str = field(default_factory=_utcnow)
    review_status: str = "pending"
    reviewed_at: str = ""

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "KnowledgeCandidate":
        return cls(
            candidate_id=str(value.get("candidate_id", "")),
            candidate_type=str(value.get("candidate_type", "")),
            proposed_value=dict(value.get("proposed_value", {})),
            reason=str(value.get("reason", "")),
            model=str(value.get("model", "")),
            prompt_version=str(value.get("prompt_version", "")),
            input_signature=dict(value.get("input_signature", {})),
            created_at=str(value.get("created_at", "")),
            review_status=str(value.get("review_status", "pending")),
            reviewed_at=str(value.get("reviewed_at", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "candidate_type": self.candidate_type,
            "proposed_value": self.proposed_value,
            "reason": self.reason,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "input_signature": self.input_signature,
            "created_at": self.created_at,
            "review_status": self.review_status,
            "reviewed_at": self.reviewed_at,
        }


@dataclass(frozen=True)
class KnowledgeVersion:
    taxonomy_version: str
    semantic_kb_version: str
    relation_kb_version: str
    alias_kb_version: str = ""
    resolver_version: str = ""
    prompt_semantic_concept_version: str = ""
    prompt_industry_relation_version: str = ""

    @property
    def knowledge_version(self) -> str:
        return "business-semantic-kb-v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_version": self.knowledge_version,
            "taxonomy_version": self.taxonomy_version,
            "semantic_kb_version": self.semantic_kb_version,
            "relation_kb_version": self.relation_kb_version,
            "alias_kb_version": self.alias_kb_version,
            "resolver_version": self.resolver_version,
            "prompt_semantic_concept_version": (
                self.prompt_semantic_concept_version
            ),
            "prompt_industry_relation_version": (
                self.prompt_industry_relation_version
            ),
        }


@dataclass
class AIUsageStats:
    semantic_requests: int = 0
    semantic_cache_hits: int = 0
    semantic_kb_hits: int = 0
    relation_requests: int = 0
    relation_cache_hits: int = 0
    relation_kb_hits: int = 0
    parent_inheritance_hits: int = 0
    generic_business_hits: int = 0
    undetermined_count: int = 0
    candidate_count: int = 0
    legacy_alias_hits: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "semantic_requests": self.semantic_requests,
            "semantic_cache_hits": self.semantic_cache_hits,
            "semantic_kb_hits": self.semantic_kb_hits,
            "relation_requests": self.relation_requests,
            "relation_cache_hits": self.relation_cache_hits,
            "relation_kb_hits": self.relation_kb_hits,
            "parent_inheritance_hits": self.parent_inheritance_hits,
            "generic_business_hits": self.generic_business_hits,
            "undetermined_count": self.undetermined_count,
            "candidate_count": self.candidate_count,
            "legacy_alias_hits": self.legacy_alias_hits,
        }
