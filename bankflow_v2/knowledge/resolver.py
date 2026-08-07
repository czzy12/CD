"""Semantic and industry-relation resolvers with conservative fallback order."""

from __future__ import annotations

from collections.abc import Mapping

from ..ai_business_observation import (
    analyze_ai_semantic_fields,
    build_classification_constraints,
)
from . import versioning
from .industry_taxonomy import IndustryTaxonomy
from .models import (
    AIUsageStats,
    IndustryConceptRelation,
    IndustryProfile,
    KnowledgeVersion,
    RelationResolution,
    SemanticResolution,
)
from .normalization import semantic_signature_from_fields
from .relations import RelationKB, cap_strength
from .repository import RuntimeKnowledgeRepository
from .semantic_concepts import SemanticConceptKB


_STRENGTH_RANK = {
    "none": 0,
    "weak": 1,
    "medium": 2,
    "strong": 3,
}
_DIRECT_FIELD_PRIORITY = (
    "summary",
    "remark",
    "purpose",
    "product_description",
    "merchant_category",
)
_NAME_FIELD_PRIORITY = ("counterparty_name", "merchant_name")


def _constraints_for_fields(
    fields: Mapping[str, object],
) -> dict[str, object]:
    analysis = analyze_ai_semantic_fields(
        {str(name): str(value) for name, value in fields.items()}
    )
    usable = analysis.get("usable_fields", {})
    if not isinstance(usable, Mapping):
        usable = {}
    return build_classification_constraints(
        {str(name): str(value) for name, value in usable.items()}
    )


def _best_relevance(
    resolutions: list[RelationResolution],
) -> RelationResolution | None:
    if not resolutions:
        return None
    best: RelationResolution | None = None
    best_rank = -1
    for resolution in resolutions:
        rank = _STRENGTH_RANK.get(resolution.relevance, -1)
        if rank > best_rank:
            best = resolution
            best_rank = rank
    return best


class SemanticResolver:
    def __init__(
        self,
        concepts: SemanticConceptKB,
        repository: RuntimeKnowledgeRepository | None = None,
        version: KnowledgeVersion | None = None,
    ) -> None:
        self._concepts = concepts
        self._repository = repository
        self._version = version or versioning.default_knowledge_version()

    def resolve(
        self,
        fields: Mapping[str, object],
        *,
        stats: AIUsageStats | None = None,
    ) -> SemanticResolution:
        signature = semantic_signature_from_fields(fields)
        if not signature.pairs:
            stats = stats or AIUsageStats()
            stats.undetermined_count += 1
            return SemanticResolution(
                concept_id="",
                concept_name="",
                confidence="none",
                source="undetermined",
                reason="无语义字段",
                knowledge_version=self._version.semantic_kb_version,
            )
        if stats is not None:
            stats.semantic_requests += 1

        ordered_values = [
            str(fields[field_name] or "")
            for field_name in (*_DIRECT_FIELD_PRIORITY, *_NAME_FIELD_PRIORITY)
            if field_name in fields and str(fields[field_name] or "").strip()
        ]
        for field_value in ordered_values:
            matched = self._concepts.resolve_alias(str(field_value or ""))
            if matched is not None:
                concept, alias = matched
                if stats is not None:
                    stats.semantic_kb_hits += 1
                    stats.legacy_alias_hits += 1
                return SemanticResolution(
                    concept_id=concept.concept_id,
                    concept_name=concept.name_zh,
                    confidence="high",
                    source="knowledge_base",
                    reason=f"别名精确命中：{alias.alias_text}",
                    knowledge_version=self._version.semantic_kb_version,
                    matched_alias=alias.alias_text,
                )

        if self._repository is not None:
            cached = self._repository.semantic_cache_get(
                signature.signature_version,
                signature.signature_id,
            )
            if cached is not None and cached.get("review_status") == "approved":
                if stats is not None:
                    stats.semantic_cache_hits += 1
                concept = self._concepts.concept(str(cached.get("concept_id", "")))
                return SemanticResolution(
                    concept_id=str(cached["concept_id"]),
                    concept_name=concept.name_zh if concept else str(cached["concept_id"]),
                    confidence="medium",
                    source="cache",
                    reason="已验收语义缓存命中",
                    knowledge_version=str(cached.get("knowledge_version") or ""),
                )

        for field_value in ordered_values:
            matched_keyword = self._concepts.concept_by_keywords(field_value)
            if matched_keyword is not None:
                concept, term = matched_keyword
                if stats is not None:
                    stats.semantic_kb_hits += 1
                return SemanticResolution(
                    concept_id=concept.concept_id,
                    concept_name=concept.name_zh,
                    confidence="medium",
                    source="knowledge_base",
                    reason=f"通用经营语义关键词命中：{term}",
                    knowledge_version=self._version.semantic_kb_version,
                    matched_alias=term,
                )

        if stats is not None:
            stats.undetermined_count += 1
        return SemanticResolution(
            concept_id="",
            concept_name="",
            confidence="none",
            source="undetermined",
            reason="本地知识库与缓存均未覆盖",
            knowledge_version=self._version.semantic_kb_version,
        )


class IndustryRelationResolver:
    def __init__(
        self,
        relations: RelationKB,
        taxonomy: IndustryTaxonomy,
        repository: RuntimeKnowledgeRepository | None = None,
        version: KnowledgeVersion | None = None,
    ) -> None:
        self._relations = relations
        self._taxonomy = taxonomy
        self._repository = repository
        self._version = version or versioning.default_knowledge_version()

    def resolve(
        self,
        *,
        industry_id: str,
        concept_id: str,
        profile: IndustryProfile | None = None,
        stats: AIUsageStats | None = None,
    ) -> RelationResolution:
        if stats is not None:
            stats.relation_requests += 1
        if self._repository is not None:
            cached = self._repository.relation_cache_get(
                taxonomy_version=self._version.taxonomy_version,
                industry_id=industry_id,
                concept_id=concept_id,
                relation_rules_version=self._version.relation_kb_version,
            )
            if cached is not None and cached.get("review_status") == "approved":
                if stats is not None:
                    stats.relation_cache_hits += 1
                return RelationResolution(
                    industry_id=industry_id,
                    concept_id=concept_id,
                    relevance=str(cached["relevance"]),
                    relation_source=str(cached["relation_source"]),
                    knowledge_version=str(cached.get("knowledge_version") or ""),
                    reason="已验收行业关系缓存命中",
                )
        parent_chain = [
            node.industry_id
            for node in self._taxonomy.parent_chain(industry_id)
        ]
        resolved = self._relations.resolve(
            industry_id=industry_id,
            concept_id=concept_id,
            profile=profile,
            parent_chain=parent_chain,
            knowledge_version=self._version.relation_kb_version,
        )
        if resolved is not None:
            if resolved.relation_source == "inherited" and stats is not None:
                stats.parent_inheritance_hits += 1
            elif resolved.relation_source == "generic_business" and stats is not None:
                stats.generic_business_hits += 1
            elif resolved.relation_source in {"approved_exact", "specialty"} and stats is not None:
                stats.relation_kb_hits += 1
            if self._repository is not None:
                self._repository.relation_cache_put(
                    taxonomy_version=self._version.taxonomy_version,
                    industry_id=industry_id,
                    concept_id=concept_id,
                    relation_rules_version=self._version.relation_kb_version,
                    relevance=resolved.relevance,
                    relation_source=resolved.relation_source,
                    knowledge_version=self._version.relation_kb_version,
                )
            return resolved
        if stats is not None:
            stats.undetermined_count += 1
        return RelationResolution(
            industry_id=industry_id,
            concept_id=concept_id,
            relevance="undetermined",
            relation_source="undetermined",
            knowledge_version=self._version.relation_kb_version,
            reason="本行业、父行业与通用业务关系均未覆盖",
        )


class KnowledgeRuntime:
    """Bundle canonical KB + runtime cache + resolvers for one shadow run."""

    def __init__(
        self,
        *,
        taxonomy: IndustryTaxonomy,
        concepts: SemanticConceptKB,
        relations: RelationKB,
        repository: RuntimeKnowledgeRepository | None = None,
        version: KnowledgeVersion | None = None,
    ) -> None:
        self.version = version or versioning.default_knowledge_version()
        self.taxonomy = taxonomy
        self.concepts = concepts
        self.relations = relations
        self.repository = repository
        self.semantic_resolver = SemanticResolver(concepts, repository, self.version)
        self.relation_resolver = IndustryRelationResolver(
            relations,
            taxonomy,
            repository,
            self.version,
        )

    @classmethod
    def load(
        cls,
        canonical_dir: str | object,
        *,
        cache_root: str | object | None = None,
        version: KnowledgeVersion | None = None,
    ) -> "KnowledgeRuntime":
        import os
        from pathlib import Path

        canonical = (
            Path(canonical_dir)
            if isinstance(canonical_dir, (str, os.PathLike))
            else Path(str(canonical_dir))
        )
        taxonomy = IndustryTaxonomy.load(canonical / "taxonomy.json")
        concepts = SemanticConceptKB.load(
            canonical / "semantic_concepts.json",
            canonical / "semantic_aliases.json",
        )
        relations = RelationKB.load(canonical / "relations.json")
        repository = (
            RuntimeKnowledgeRepository(cache_root)
            if cache_root is not None
            else None
        )
        return cls(
            taxonomy=taxonomy,
            concepts=concepts,
            relations=relations,
            repository=repository,
            version=version,
        )

    def resolve_transaction_fields(
        self,
        fields: Mapping[str, object],
        profile: IndustryProfile | None,
        *,
        stats: AIUsageStats | None = None,
    ) -> dict[str, object]:
        stats = stats or AIUsageStats()
        semantic = self.semantic_resolver.resolve(fields, stats=stats)
        if semantic.source == "undetermined" or not semantic.concept_id:
            return {
                "semantic": semantic.to_dict(),
                "relations": [],
                "final_relevance": "undetermined",
                "final_classification": "undetermined",
                "constraints": _constraints_for_fields(fields),
                "stats": stats.to_dict(),
            }
        industry_ids = (
            list(profile.primary_industry_ids) + list(profile.secondary_industry_ids)
            if profile is not None
            else []
        )
        resolutions = [
            self.relation_resolver.resolve(
                industry_id=industry_id,
                concept_id=semantic.concept_id,
                profile=profile,
                stats=stats,
            )
            for industry_id in industry_ids
        ]
        constraints = _constraints_for_fields(fields)
        maximum = str(constraints.get("maximum_allowed_strength", "strong"))
        best = _best_relevance(resolutions)
        if best is not None:
            relevance = cap_strength(best.relevance, maximum)
            if relevance != best.relevance:
                best = RelationResolution(
                    industry_id=best.industry_id,
                    concept_id=best.concept_id,
                    relevance=relevance,
                    relation_source=best.relation_source,
                    knowledge_version=best.knowledge_version,
                    reason=best.reason + f"（本地硬护栏封顶为 {maximum}）",
                    review_required=best.review_required,
                    ai_used=best.ai_used,
                    applied_maximum_strength=maximum,
                    directly_related_allowed=bool(
                        constraints.get("directly_related_allowed")
                    ),
                )
        classification = (
            "directly_related"
            if best is not None and best.relevance == "strong"
            else "possibly_related"
            if best is not None and best.relevance in {"medium", "weak"}
            else "no_relation_evidence"
            if best is not None and best.relevance == "none"
            else "undetermined"
        )
        return {
            "semantic": semantic.to_dict(),
            "relations": [item.to_dict() for item in resolutions],
            "final_relevance": best.relevance if best is not None else "undetermined",
            "final_classification": classification,
            "constraints": constraints,
            "stats": stats.to_dict(),
        }

    def usage_stats(self) -> dict[str, int]:
        return AIUsageStats().to_dict()
