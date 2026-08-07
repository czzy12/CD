"""Knowledge candidate review and promotion service."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import versioning
from .ai_fallback import build_knowledge_candidate
from .models import KnowledgeCandidate
from .repository import RuntimeKnowledgeRepository


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class KnowledgeReviewService:
    """Review queue + guarded promotion into canonical Git knowledge files."""

    def __init__(
        self,
        repository: RuntimeKnowledgeRepository,
        canonical_dir: str | Path,
        *,
        reviewer: str = "knowledge_v1_review_cli",
    ) -> None:
        self.repository = repository
        self.canonical_dir = Path(canonical_dir)
        self.reviewer = reviewer

    def propose(
        self,
        *,
        candidate_type: str,
        proposed_value: Mapping[str, Any],
        reason: str,
        model: str,
        prompt_version: str,
        input_signature: Mapping[str, Any],
    ) -> KnowledgeCandidate:
        candidate = build_knowledge_candidate(
            candidate_type=candidate_type,
            proposed_value=proposed_value,
            reason=reason,
            model=model,
            prompt_version=prompt_version,
            input_signature=input_signature,
        )
        if candidate.candidate_type not in {
            "new_semantic_concept",
            "new_industry_relation",
            "new_alias",
        }:
            raise ValueError(f"unknown candidate type: {candidate.candidate_type}")
        self.repository.add_candidate(candidate)
        return candidate

    def list_pending(self) -> list[KnowledgeCandidate]:
        return self.repository.list_candidates("pending")

    def summary(self) -> dict[str, Any]:
        rows = self.repository.list_candidates()
        by_status: Counter[str] = Counter()
        by_type: Counter[str] = Counter()
        for candidate in rows:
            by_status[candidate.review_status] += 1
            by_type[candidate.candidate_type] += 1
        return {
            "total": len(rows),
            "by_status": dict(sorted(by_status.items())),
            "by_type": dict(sorted(by_type.items())),
        }

    def approve(self, candidate_id: str) -> KnowledgeCandidate | None:
        candidate = next(
            (
                item
                for item in self.repository.list_candidates("pending")
                if item.candidate_id == candidate_id
            ),
            None,
        )
        if candidate is None:
            return None
        self._promote(candidate)
        return self.repository.review_candidate(candidate_id, "approved")

    def reject(self, candidate_id: str) -> KnowledgeCandidate | None:
        return self.repository.review_candidate(candidate_id, "rejected")

    def _promote(self, candidate: KnowledgeCandidate) -> None:
        if candidate.candidate_type == "new_semantic_concept":
            self._append_concept(candidate.proposed_value)
        elif candidate.candidate_type == "new_industry_relation":
            self._append_relation(candidate.proposed_value)
        elif candidate.candidate_type == "new_alias":
            self._append_alias(candidate.proposed_value)
        else:
            raise ValueError(f"cannot promote candidate type: {candidate.candidate_type}")

    def _append_concept(self, value: Mapping[str, Any]) -> None:
        path = self.canonical_dir / "semantic_concepts.json"
        data = _load_json(path)
        concepts = data.setdefault("concepts", [])
        concept_id = str(value.get("concept_id", ""))
        if any(
            str(item.get("concept_id", "")) == concept_id
            for item in concepts
            if isinstance(item, Mapping)
        ):
            raise ValueError(f"concept already exists: {concept_id}")
        concepts.append(
            {
                "concept_id": concept_id,
                "name_zh": str(value.get("name_zh", "")),
                "aliases": [
                    str(item) for item in value.get("aliases", [])
                ],
                "keywords": [
                    str(item) for item in value.get("keywords", [])
                ],
                "parent_concept_id": str(
                    value.get("parent_concept_id", "")
                ),
                "description": str(value.get("description", "")),
                "examples_generic": [
                    str(item) for item in value.get("examples_generic", [])
                ],
                "status": "active",
                "source": f"reviewed:{self.reviewer}",
                "knowledge_version": versioning.KNOWLEDGE_VERSION,
            }
        )
        concepts.sort(key=lambda item: str(item.get("concept_id", "")))
        data["version"] = versioning.SEMANTIC_KB_VERSION
        data["updated_at"] = _utcnow()
        _write_json(path, data)

    def _append_relation(self, value: Mapping[str, Any]) -> None:
        path = self.canonical_dir / "relations.json"
        data = _load_json(path)
        relations = data.setdefault("relations", [])
        industry_id = str(value.get("industry_id", ""))
        concept_id = str(value.get("concept_id", ""))
        if any(
            str(item.get("industry_id", "")) == industry_id
            and str(item.get("concept_id", "")) == concept_id
            for item in relations
            if isinstance(item, Mapping)
        ):
            raise ValueError(
                f"relation already exists: {industry_id} x {concept_id}"
            )
        relations.append(
            {
                "industry_id": industry_id,
                "concept_id": concept_id,
                "relevance": str(value.get("relevance", "undetermined")),
                "reason_template": str(value.get("reason_template", "")),
                "source": f"reviewed:{self.reviewer}",
                "review_status": "approved",
                "confidence_tier": str(
                    value.get("confidence_tier", "reviewed")
                ),
                "knowledge_version": versioning.KNOWLEDGE_VERSION,
                "created_by": self.reviewer,
                "reviewed_at": _utcnow(),
            }
        )
        relations.sort(
            key=lambda item: (
                str(item.get("industry_id", "")),
                str(item.get("concept_id", "")),
            )
        )
        data["version"] = versioning.RELATION_KB_VERSION
        data["updated_at"] = _utcnow()
        _write_json(path, data)

    def _append_alias(self, value: Mapping[str, Any]) -> None:
        path = self.canonical_dir / "semantic_aliases.json"
        data = _load_json(path)
        aliases = data.setdefault("aliases", [])
        alias_text = str(value.get("alias_text", ""))
        concept_id = str(value.get("concept_id", ""))
        if any(
            str(item.get("alias_text", "")) == alias_text
            and str(item.get("concept_id", "")) == concept_id
            for item in aliases
            if isinstance(item, Mapping)
        ):
            raise ValueError(f"alias already exists: {alias_text}")
        aliases.append(
            {
                "alias_id": f"alias:{alias_text}",
                "alias_text": alias_text,
                "concept_id": concept_id,
                "status": "active",
                "source": f"reviewed:{self.reviewer}",
                "knowledge_version": versioning.KNOWLEDGE_VERSION,
            }
        )
        aliases.sort(
            key=lambda item: (
                str(item.get("concept_id", "")),
                str(item.get("alias_text", "")),
            )
        )
        data["version"] = versioning.ALIAS_KB_VERSION
        data["updated_at"] = _utcnow()
        _write_json(path, data)
