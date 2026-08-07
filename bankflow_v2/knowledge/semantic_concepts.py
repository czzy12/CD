"""Semantic concept knowledge base and alias matching."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from . import versioning
from .models import SemanticAlias, SemanticConcept
from .normalization import compact_text, text_contains_any


def load_concept_keywords(
    concepts: Iterable[SemanticConcept] | None = None,
) -> dict[str, tuple[str, ...]]:
    """Return concept_id -> keyword terms for generic industry profiling."""
    result: dict[str, tuple[str, ...]] = {}
    for concept in concepts or ():
        terms = tuple(
            dict.fromkeys(
                [
                    concept.name_zh,
                    *concept.aliases,
                    *concept.keywords,
                ]
            )
        )
        if terms:
            result[concept.concept_id] = terms
    return result


class SemanticConceptKB:
    def __init__(
        self,
        concepts: Iterable[SemanticConcept],
        aliases: Iterable[SemanticAlias],
        *,
        version: str = versioning.SEMANTIC_KB_VERSION,
        alias_version: str = versioning.ALIAS_KB_VERSION,
    ) -> None:
        self.version = version
        self.alias_version = alias_version
        self._concepts: dict[str, SemanticConcept] = {
            concept.concept_id: concept for concept in concepts
        }
        self._aliases: dict[str, SemanticAlias] = {
            alias.alias_id: alias for alias in aliases
        }
        self._alias_index: dict[str, str] = {}
        for alias in self._aliases.values():
            if alias.status != "active":
                continue
            key = compact_text(alias.alias_text)
            if key and key not in self._alias_index:
                self._alias_index[key] = alias.concept_id

    @classmethod
    def load(
        cls,
        concept_path: str | Path,
        alias_path: str | Path,
    ) -> "SemanticConceptKB":
        concepts_data = json.loads(Path(concept_path).read_text(encoding="utf-8"))
        aliases_data = json.loads(Path(alias_path).read_text(encoding="utf-8"))
        concepts = [
            SemanticConcept.from_dict(item)
            for item in concepts_data.get("concepts", [])
            if isinstance(item, Mapping)
        ]
        aliases = [
            SemanticAlias.from_dict(item)
            for item in aliases_data.get("aliases", [])
            if isinstance(item, Mapping)
        ]
        return cls(
            concepts,
            aliases,
            version=str(concepts_data.get("version") or versioning.SEMANTIC_KB_VERSION),
            alias_version=str(aliases_data.get("version") or versioning.ALIAS_KB_VERSION),
        )

    def concept(self, concept_id: str) -> SemanticConcept | None:
        return self._concepts.get(concept_id)

    def resolve_alias(self, value: str) -> tuple[SemanticConcept, SemanticAlias] | None:
        compact = compact_text(value)
        if not compact:
            return None
        exact = self._alias_index.get(compact)
        if exact is not None:
            concept = self._concepts.get(exact)
            if concept is not None:
                for alias in self._aliases.values():
                    if (
                        alias.status == "active"
                        and alias.concept_id == exact
                        and compact_text(alias.alias_text) == compact
                    ):
                        return concept, alias
        best: tuple[int, SemanticConcept, SemanticAlias] | None = None
        for alias in self._aliases.values():
            if alias.status != "active":
                continue
            term = compact_text(alias.alias_text)
            if not term:
                continue
            if term in compact:
                concept = self._concepts.get(alias.concept_id)
                if concept is None:
                    continue
                if best is None or len(term) > best[0]:
                    best = (len(term), concept, alias)
        if best is not None:
            return best[1], best[2]
        return None

    def concept_by_keywords(
        self,
        value: str,
    ) -> tuple[SemanticConcept, str] | None:
        best: tuple[int, SemanticConcept, str] | None = None
        for concept in self._concepts.values():
            for term in (*concept.aliases, concept.name_zh, *concept.keywords):
                if not term:
                    continue
                if compact_text(term) in compact_text(value):
                    if best is None or len(term) > best[0]:
                        best = (len(term), concept, term)
                    break
        if best is None:
            return None
        return best[1], best[2]

    def parent_chain(
        self,
        concept_id: str,
    ) -> list[SemanticConcept]:
        chain: list[SemanticConcept] = []
        seen: set[str] = set()
        current_id = concept_id
        while current_id and current_id not in seen:
            seen.add(current_id)
            concept = self._concepts.get(current_id)
            if concept is None:
                break
            chain.append(concept)
            current_id = concept.parent_concept_id
        return chain

    def active_concepts(self) -> list[SemanticConcept]:
        return [
            self._concepts[key]
            for key in sorted(self._concepts)
            if self._concepts[key].status == "active"
        ]

    def keyword_terms(self) -> dict[str, tuple[str, ...]]:
        return load_concept_keywords(self._concepts.values())
