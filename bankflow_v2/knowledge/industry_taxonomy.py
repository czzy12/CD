"""Industry taxonomy loading, lookup and conservative parent inheritance."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path

from . import versioning
from .models import IndustryNode
from .normalization import compact_text, text_contains_any


class IndustryTaxonomy:
    """Versioned official-core taxonomy with internal child nodes."""

    def __init__(
        self,
        nodes: Iterable[IndustryNode],
        *,
        version: str = versioning.TAXONOMY_VERSION,
        source: str = "",
        source_version: str = "",
        updated_at: str = "",
    ) -> None:
        self.version = version
        self.source = source
        self.source_version = source_version
        self.updated_at = updated_at
        self._nodes: dict[str, IndustryNode] = {
            node.industry_id: node for node in nodes
        }
        self._alias_index: dict[str, str] = {}
        for node in self._nodes.values():
            for alias in (*node.aliases, node.name):
                key = compact_text(alias)
                if key and key not in self._alias_index:
                    self._alias_index[key] = node.industry_id

    @classmethod
    def load(cls, path: str | Path) -> "IndustryTaxonomy":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "IndustryTaxonomy":
        nodes = [
            IndustryNode.from_dict(item)
            for item in data.get("nodes", [])
            if isinstance(item, Mapping)
        ]
        return cls(
            nodes,
            version=str(data.get("version") or versioning.TAXONOMY_VERSION),
            source=str(data.get("source") or ""),
            source_version=str(data.get("source_version") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )

    def node(self, industry_id: str) -> IndustryNode | None:
        return self._nodes.get(industry_id)

    def resolve_id(self, value: str) -> str:
        direct = self._nodes.get(value)
        if direct is not None:
            return direct.industry_id
        return self._alias_index.get(compact_text(value), "")

    def parent_chain(
        self,
        industry_id: str,
    ) -> list[IndustryNode]:
        chain: list[IndustryNode] = []
        seen: set[str] = set()
        current_id = industry_id
        while current_id and current_id not in seen:
            seen.add(current_id)
            node = self._nodes.get(current_id)
            if node is None:
                break
            chain.append(node)
            current_id = node.parent_id
        return chain

    def best_guess_industry_ids(
        self,
        texts: Iterable[str],
    ) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for text in texts:
            if not str(text or "").strip():
                continue
            for node in sorted(
                self._nodes.values(),
                key=lambda item: item.level,
            ):
                if node.industry_id in seen:
                    continue
                if text_contains_any(text, (*node.aliases, node.name, *node.keywords)):
                    seen.add(node.industry_id)
                    found.append(node.industry_id)
                    break
        return found

    def resolve_specialty_concepts(
        self,
        texts: Iterable[str],
    ) -> list[str]:
        from .semantic_concepts import load_concept_keywords

        keywords = load_concept_keywords()
        found: list[str] = []
        seen: set[str] = set()
        for text in texts:
            if not str(text or "").strip():
                continue
            for concept_id in sorted(keywords):
                if concept_id in seen:
                    continue
                if text_contains_any(text, keywords[concept_id]):
                    seen.add(concept_id)
                    found.append(concept_id)
        return found

    def to_dict(self) -> dict[str, object]:
        return {
            "format": "industry-taxonomy",
            "version": self.version,
            "source": self.source,
            "source_version": self.source_version,
            "updated_at": self.updated_at,
            "nodes": [
                self._nodes[key].to_dict()
                for key in sorted(self._nodes)
            ],
        }
