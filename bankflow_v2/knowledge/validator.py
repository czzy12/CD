"""Canonical knowledge-base validator with sensitive-data guards."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .models import RELEVANCE_VALUES


_ID_CARD_RE = re.compile(r"\b[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])"
                          r"(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx]\b")
_BANK_ACCOUNT_RE = re.compile(r"\b\d{12,19}\b")
_PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")
_PATH_RE = re.compile(
    r"(?:[A-Za-z]:[\\/]|/Users/|/home/|\\\\[^\\]+\\[^\\]+|"
    r"[/\\](?:MVP-input|客户报告|PDF流水|银行流水)[/\\])"
)


@dataclass
class ValidationReport:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "counts": self.counts,
        }


def _node_cycle(
    node_id: str,
    parent_of: Mapping[str, str],
) -> bool:
    seen: set[str] = set()
    current = node_id
    while current:
        if current in seen:
            return True
        seen.add(current)
        current = parent_of.get(current, "")
    return False


def _sensitive(value: object) -> str:
    text = str(value or "")
    if _ID_CARD_RE.search(text):
        return "id_card"
    if _BANK_ACCOUNT_RE.search(text):
        return "bank_account"
    if _PHONE_RE.search(text):
        return "phone"
    if _PATH_RE.search(text):
        return "local_path"
    return ""


def _collect_sensitive(values: Sequence[object]) -> list[str]:
    found: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            found.extend(_collect_sensitive(list(value.values())))
        elif isinstance(value, (list, tuple)):
            found.extend(_collect_sensitive(list(value)))
        else:
            category = _sensitive(value)
            if category:
                found.append(category)
    return found


def validate_knowledge_base(
    canonical_dir: str | Path,
) -> ValidationReport:
    root = Path(canonical_dir)
    errors: list[str] = []
    warnings: list[str] = []

    def load(name: str) -> dict[str, object]:
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"canonical file missing: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{name} must be a JSON object")
        return data

    taxonomy = load("taxonomy.json")
    concepts_data = load("semantic_concepts.json")
    aliases_data = load("semantic_aliases.json")
    relations_data = load("relations.json")

    for name, data in (
        ("taxonomy.json", taxonomy),
        ("semantic_concepts.json", concepts_data),
        ("semantic_aliases.json", aliases_data),
        ("relations.json", relations_data),
    ):
        if not str(data.get("version", "")).strip():
            errors.append(f"{name}: missing version")

    industry_nodes = [
        item for item in taxonomy.get("nodes", []) if isinstance(item, Mapping)
    ]
    concepts = [
        item
        for item in concepts_data.get("concepts", [])
        if isinstance(item, Mapping)
    ]
    aliases = [
        item for item in aliases_data.get("aliases", []) if isinstance(item, Mapping)
    ]
    relations = [
        item
        for item in relations_data.get("relations", [])
        if isinstance(item, Mapping)
    ]

    industry_ids = [str(item.get("industry_id", "")) for item in industry_nodes]
    concept_ids = [str(item.get("concept_id", "")) for item in concepts]
    duplicate_ids = {
        key for key, count in Counter(industry_ids).items() if count > 1
    }
    if duplicate_ids:
        errors.append(f"duplicate industry ids: {sorted(duplicate_ids)}")
    duplicate_concepts = {
        key for key, count in Counter(concept_ids).items() if count > 1
    }
    if duplicate_concepts:
        errors.append(f"duplicate concept ids: {sorted(duplicate_concepts)}")

    industry_set = set(industry_ids)
    concept_set = set(concept_ids)
    industry_parent: dict[str, str] = {}
    concept_parent: dict[str, str] = {}
    for item in industry_nodes:
        industry_id = str(item.get("industry_id", ""))
        parent_id = str(item.get("parent_id", ""))
        if parent_id and parent_id not in industry_set:
            errors.append(f"industry {industry_id}: missing parent {parent_id}")
        industry_parent[industry_id] = parent_id
        if not str(item.get("source", "")):
            errors.append(f"industry {industry_id}: missing source")
    for item in concepts:
        concept_id = str(item.get("concept_id", ""))
        parent_id = str(item.get("parent_concept_id", ""))
        if parent_id and parent_id not in concept_set:
            errors.append(f"concept {concept_id}: missing parent {parent_id}")
        concept_parent[concept_id] = parent_id
        if not str(item.get("source", "")):
            errors.append(f"concept {concept_id}: missing source")
    for industry_id in industry_set:
        if _node_cycle(industry_id, industry_parent):
            errors.append(f"industry parent cycle at {industry_id}")
    for concept_id in concept_set:
        if _node_cycle(concept_id, concept_parent):
            errors.append(f"concept parent cycle at {concept_id}")

    alias_conflicts: dict[str, set[str]] = {}
    for item in aliases:
        alias_text = str(item.get("alias_text", ""))
        concept_id = str(item.get("concept_id", ""))
        alias_conflicts.setdefault(alias_text, set()).add(concept_id)
        if concept_id not in concept_set:
            errors.append(f"alias {alias_text}: unknown concept {concept_id}")
        if not str(item.get("source", "")):
            errors.append(f"alias {alias_text}: missing source")
    for alias_text, ids in alias_conflicts.items():
        if len(ids) > 1:
            errors.append(
                f"alias conflict {alias_text}: {sorted(ids)}"
            )

    relation_keys: Counter[tuple[str, str]] = Counter()
    for item in relations:
        industry_id = str(item.get("industry_id", ""))
        concept_id = str(item.get("concept_id", ""))
        relevance = str(item.get("relevance", ""))
        review_status = str(item.get("review_status", ""))
        if industry_id != "generic_business" and industry_id not in industry_set:
            errors.append(
                f"relation {industry_id} x {concept_id}: unknown industry"
            )
        if concept_id not in concept_set:
            errors.append(
                f"relation {industry_id} x {concept_id}: unknown concept"
            )
        if relevance not in RELEVANCE_VALUES:
            errors.append(
                f"relation {industry_id} x {concept_id}: invalid relevance {relevance}"
            )
        if review_status != "approved":
            errors.append(
                f"relation {industry_id} x {concept_id}: canonical must be approved "
                f"(found {review_status})"
            )
        if review_status in {"candidate", "pending"} or "proposed_value" in item:
            errors.append(
                f"relation {industry_id} x {concept_id}: AI candidate in canonical"
            )
        if not str(item.get("source", "")):
            errors.append(
                f"relation {industry_id} x {concept_id}: missing source"
            )
        if item.get("new_concept_candidate") is not None:
            errors.append(
                f"relation {industry_id} x {concept_id}: AI candidate payload in canonical"
            )
        relation_keys[(industry_id, concept_id)] += 1
    for (industry_id, concept_id), count in relation_keys.items():
        if count > 1:
            values = {
                str(item.get("relevance", ""))
                for item in relations
                if str(item.get("industry_id", "")) == industry_id
                and str(item.get("concept_id", "")) == concept_id
            }
            if len(values) > 1:
                errors.append(
                    f"relation conflict {industry_id} x {concept_id}: {sorted(values)}"
                )

    for item in relations:
        if (
            str(item.get("relevance", "")) == "strong"
            and str(item.get("concept_id", ""))
            in {
                str(alias.get("concept_id", ""))
                for alias in aliases
                if str(alias.get("alias_text", ""))
                in {
                    "餐饮",
                    "餐厅",
                    "饭店",
                    "医院",
                    "门诊",
                    "药房",
                    "话费",
                    "银行年费",
                    "打车",
                    "滴滴",
                }
            }
        ):
            warnings.append(
                f"strong relation on likely life concept: "
                f"{item.get('industry_id')} x {item.get('concept_id')}"
            )

    sensitive_values: list[object] = []
    for container in (industry_nodes, concepts, aliases, relations):
        for item in container:
            sensitive_values.extend(
                [
                    item.get(key, "")
                    for key in (
                        "name",
                        "name_zh",
                        "aliases",
                        "keywords",
                        "description",
                        "examples_generic",
                        "alias_text",
                        "reason_template",
                    )
                    if key in item
                ]
            )
    sensitive_hits = _collect_sensitive(sensitive_values)
    if sensitive_hits:
        errors.append(f"sensitive data patterns in canonical KB: {sorted(set(sensitive_hits))}")

    return ValidationReport(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        counts={
            "industry_nodes": len(industry_nodes),
            "concepts": len(concepts),
            "aliases": len(aliases),
            "relations": len(relations),
        },
    )
