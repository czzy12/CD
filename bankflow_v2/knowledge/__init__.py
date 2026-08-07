"""Knowledge V1: cross-customer business-semantics knowledge base (shadow architecture)."""

from . import versioning
from .ai_fallback import DeepSeekKnowledgeAdapter, KnowledgeAIError
from .ai_validation import (
    build_validation_items,
    call_with_retry,
    run_concept_validation,
    run_relation_validation,
    safe_validation_fields,
    split_guarded,
    write_validation_package,
)
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
from .privacy import build_privacy_preflight, guard_item
from .shadow import (
    MISMATCH_TYPES,
    classify_mismatch,
    compare_legacy_cache,
    extended_shadow_metrics,
    load_legacy_signature_entries,
    mismatch_reason,
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
    "MISMATCH_TYPES",
    "RelationKB",
    "RelationResolution",
    "RuntimeKnowledgeRepository",
    "SemanticAlias",
    "SemanticConcept",
    "SemanticConceptKB",
    "SemanticResolution",
    "SemanticResolver",
    "SemanticSignature",
    "build_privacy_preflight",
    "build_validation_items",
    "cap_strength",
    "call_with_retry",
    "classify_mismatch",
    "compare_legacy_cache",
    "extended_shadow_metrics",
    "guard_item",
    "load_legacy_signature_entries",
    "mismatch_reason",
    "render_shadow_markdown",
    "run_concept_validation",
    "run_relation_validation",
    "safe_validation_fields",
    "split_guarded",
    "validate_knowledge_base",
    "versioning",
    "write_validation_package",
]
