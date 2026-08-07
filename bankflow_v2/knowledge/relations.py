"""Industry x concept relation knowledge base."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from . import versioning
from .models import IndustryConceptRelation, IndustryProfile, RelationResolution


_STRENGTH_RANK = {
    "none": 0,
    "weak": 1,
    "medium": 2,
    "strong": 3,
    "undetermined": -1,
}


def cap_strength(relevance: str, maximum: str) -> str:
    if (
        relevance in _STRENGTH_RANK
        and maximum in _STRENGTH_RANK
        and _STRENGTH_RANK[relevance] > _STRENGTH_RANK[maximum]
    ):
        return maximum
    return relevance


class RelationKB:
    def __init__(
        self,
        relations: Iterable[IndustryConceptRelation],
        *,
        version: str = versioning.RELATION_KB_VERSION,
    ) -> None:
        self.version = version
        self._relations: dict[tuple[str, str], list[IndustryConceptRelation]] = {}
        for relation in relations:
            key = (relation.industry_id, relation.concept_id)
            self._relations.setdefault(key, []).append(relation)

    @classmethod
    def load(cls, path: str | Path) -> "RelationKB":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        relations = [
            IndustryConceptRelation.from_dict(item)
            for item in data.get("relations", [])
            if isinstance(item, Mapping)
        ]
        return cls(
            relations,
            version=str(data.get("version") or versioning.RELATION_KB_VERSION),
        )

    def approved(
        self,
        industry_id: str,
        concept_id: str,
    ) -> IndustryConceptRelation | None:
        for relation in self._relations.get((industry_id, concept_id), []):
            if relation.review_status == "approved":
                return relation
        return None

    def resolve(
        self,
        *,
        industry_id: str,
        concept_id: str,
        profile: IndustryProfile | None,
        parent_chain: Iterable[str],
        knowledge_version: str,
    ) -> RelationResolution | None:
        exact = self.approved(industry_id, concept_id)
        if exact is not None:
            return RelationResolution(
                industry_id=industry_id,
                concept_id=concept_id,
                relevance=exact.relevance,
                relation_source="approved_exact",
                knowledge_version=knowledge_version,
                reason=exact.reason_template,
            )
        if profile is not None and concept_id in profile.specialty_concept_ids:
            generic = self.approved("generic_business", concept_id)
            if generic is not None:
                return RelationResolution(
                    industry_id=industry_id,
                    concept_id=concept_id,
                    relevance=cap_strength(generic.relevance, "medium"),
                    relation_source="specialty",
                    knowledge_version=knowledge_version,
                    reason="行业画像明确列为专项经营概念，采用通用业务关系并保守封顶为 medium",
                )
        for parent_id in parent_chain:
            if parent_id == industry_id:
                continue
            inherited = self.approved(parent_id, concept_id)
            if inherited is not None:
                return RelationResolution(
                    industry_id=industry_id,
                    concept_id=concept_id,
                    relevance=inherited.relevance,
                    relation_source="inherited",
                    knowledge_version=knowledge_version,
                    reason=(
                        f"继承父行业关系：{parent_id} × {concept_id} "
                        f"={inherited.relevance}"
                    ),
                )
        generic = self.approved("generic_business", concept_id)
        if generic is not None:
            return RelationResolution(
                industry_id=industry_id,
                concept_id=concept_id,
                relevance=generic.relevance,
                relation_source="generic_business",
                knowledge_version=knowledge_version,
                reason=generic.reason_template,
            )
        return None
