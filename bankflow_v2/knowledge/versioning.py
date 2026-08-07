"""Version registry and fingerprints for the knowledge_v1 layers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .models import KnowledgeVersion


KNOWLEDGE_VERSION = "business-semantic-kb-v1"
TAXONOMY_VERSION = "gb-t-4754-2017-core-v1"
SEMANTIC_KB_VERSION = "semantic-concepts-v1"
RELATION_KB_VERSION = "industry-relations-v1"
ALIAS_KB_VERSION = "semantic-aliases-v1"
RESOLVER_VERSION = "knowledge-v1-resolver-1"
SIGNATURE_VERSION = "semantic-signature-v1"
PROMPT_SEMANTIC_CONCEPT_VERSION = "semantic-concept-v1"
PROMPT_INDUSTRY_RELATION_VERSION = "industry-concept-relevance-v1"


def default_knowledge_version() -> KnowledgeVersion:
    return KnowledgeVersion(
        taxonomy_version=TAXONOMY_VERSION,
        semantic_kb_version=SEMANTIC_KB_VERSION,
        relation_kb_version=RELATION_KB_VERSION,
        alias_kb_version=ALIAS_KB_VERSION,
        resolver_version=RESOLVER_VERSION,
        prompt_semantic_concept_version=PROMPT_SEMANTIC_CONCEPT_VERSION,
        prompt_industry_relation_version=PROMPT_INDUSTRY_RELATION_VERSION,
    )


def fingerprint(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_fingerprint(
    *,
    taxonomy_version: str,
    semantic_kb_version: str,
    relation_kb_version: str,
    alias_kb_version: str,
    resolver_version: str,
) -> str:
    return fingerprint(
        {
            "taxonomy_version": taxonomy_version,
            "semantic_kb_version": semantic_kb_version,
            "relation_kb_version": relation_kb_version,
            "alias_kb_version": alias_kb_version,
            "resolver_version": resolver_version,
        }
    )[:16]
