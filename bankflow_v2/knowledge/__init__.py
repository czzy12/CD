"""Knowledge V1: cross-customer business-semantics knowledge base (shadow architecture)."""

from . import versioning
from .ai_fallback import DeepSeekKnowledgeAdapter, KnowledgeAIError
from .industry_taxonomy import IndustryTaxonomy
from .models import (
    AIUsageStats,
    IndustryConceptRelation,
    IndustryNode,
    IndustryProfile,
    KnowledgeCandidate,
    KnowledgeVersion,
    RelationResolution,
    SemanticAlias,
    SemanticConcept,
    SemanticResolution,
    SemanticSignature,
)
from .relations import RelationKB, cap_strength
from .repository import RuntimeKnowledgeRepository
from .resolver import (
    IndustryRelationResolver,
    KnowledgeRuntime,
    SemanticResolver,
)
from .review import KnowledgeReviewService
from .semantic_concepts import SemanticConceptKB
from .shadow import (
    compare_legacy_cache,
    extended_shadow_metrics,
    load_legacy_signature_entries,
    render_shadow_markdown,
)
from .validator import validate_knowledge_base

__all__ = [
    "AIUsageStats",
    "DeepSeekKnowledgeAdapter",
    "IndustryConceptRelation",
    "IndustryNode",
    "IndustryProfile",
    "IndustryRelationResolver",
    "IndustryTaxonomy",
    "KnowledgeAIError",
    "KnowledgeCandidate",
    "KnowledgeReviewService",
    "KnowledgeRuntime",
    "KnowledgeVersion",
    "RelationKB",
    "RelationResolution",
    "RuntimeKnowledgeRepository",
    "SemanticAlias",
    "SemanticConcept",
    "SemanticConceptKB",
    "SemanticResolution",
    "SemanticResolver",
    "SemanticSignature",
    "cap_strength",
    "compare_legacy_cache",
    "extended_shadow_metrics",
    "load_legacy_signature_entries",
    "render_shadow_markdown",
    "validate_knowledge_base",
    "versioning",
]
