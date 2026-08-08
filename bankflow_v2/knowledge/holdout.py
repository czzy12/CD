"""Pure selection helpers for Gate F1 holdout construction."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .freeze import manifest_checksum


def dedup_by_signature(
    entries: Iterable[Mapping[str, Any]],
    *,
    signature_key: str = "signature_id",
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for entry in entries:
        signature = str(entry.get(signature_key, ""))
        if not signature:
            continue
        occurrence = int(entry.get("occurrence_count", 1))
        if signature not in result:
            result[signature] = dict(entry)
        else:
            result[signature]["occurrence_count"] = int(
                result[signature].get("occurrence_count", 1)
            ) + occurrence
    return result


def balanced_selection(
    signatures_by_document: Mapping[str, Sequence[str]],
    *,
    max_per_document: int,
    target: int,
) -> list[str]:
    selected: list[str] = []
    selected_set: set[str] = set()
    doc_counts: dict[str, int] = {}
    changed = True
    while changed and len(selected) < target:
        changed = False
        for doc, signatures in sorted(signatures_by_document.items()):
            if len(selected) >= target:
                break
            if doc_counts.get(doc, 0) >= max_per_document:
                continue
            for signature in signatures:
                if signature in selected_set:
                    continue
                selected.append(signature)
                selected_set.add(signature)
                doc_counts[doc] = doc_counts.get(doc, 0) + 1
                changed = True
                break
    return selected


def holdout_manifest_checksum(payload: Mapping[str, Any]) -> str:
    return manifest_checksum(payload)


def classify_industry_availability(
    *,
    has_external_metadata: bool,
    normalized_industry_ids: Sequence[str],
    metadata_conflict: bool = False,
) -> str:
    """Classify one source document's external industry context.

    External ground context only; knowledge_v1 prediction is never a source.
    """
    if metadata_conflict:
        return "invalid_metadata"
    if not has_external_metadata:
        return "unavailable"
    if len(set(normalized_industry_ids)) == 1:
        return "confirmed"
    return "available_but_ambiguous"


def relation_denominator_eligible(industry_status: str) -> bool:
    return industry_status == "confirmed"
