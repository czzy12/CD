"""Privacy preflight and PII guard for real knowledge AI validation."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .ai_fallback import AI_FIELD_WHITELIST


_ID_CARD_RE = re.compile(r"\b\d{17}[\dXx]\b")
_BANK_CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_WINDOWS_PATH_RE = re.compile(
    r"[A-Za-z]:[\\/][^\s\"']+|\\\\[^\\\s]+\\[^\s\"']+"
)
_IDENTITY_KEYS = frozenset(
    {
        "id_card",
        "id_no",
        "id_number",
        "identity_no",
        "cert_no",
        "certificate_no",
        "customer_id",
        "person_id",
        "证件号",
        "身份证",
    }
)
_ACCOUNT_KEYS = frozenset(
    {
        "account",
        "account_no",
        "account_number",
        "card_no",
        "card_number",
        "bank_account",
        "账号",
        "卡号",
    }
)
_PHONE_KEYS = frozenset({"phone", "mobile", "tel", "telephone", "电话", "手机号"})
_PATH_KEYS = frozenset(
    {"path", "file_path", "local_path", "source_file", "pdf_path", "路径"}
)
_NAME_KEYS = frozenset(
    {"customer_name", "holder_name", "account_name", "id_name", "姓名", "户名"}
)


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    blocked_fields: tuple[str, ...]
    reasons: tuple[str, ...]


def guard_item(fields: Mapping[str, object]) -> GuardResult:
    """Block items carrying customer identity, accounts, phones or local paths.

    Blocked items are never auto-stripped and re-sent; they stop for human
    review instead.
    """
    blocked_fields: list[str] = []
    reasons: list[str] = []
    for key, raw in fields.items():
        key_s = str(key)
        value = str(raw or "")
        if key_s in _IDENTITY_KEYS or key_s in _ACCOUNT_KEYS:
            blocked_fields.append(key_s)
            reasons.append("identity_or_account_key")
            continue
        if key_s in _PHONE_KEYS:
            blocked_fields.append(key_s)
            reasons.append("phone_key")
            continue
        if key_s in _PATH_KEYS:
            blocked_fields.append(key_s)
            reasons.append("local_path_key")
            continue
        if key_s in _NAME_KEYS and key_s not in AI_FIELD_WHITELIST:
            blocked_fields.append(key_s)
            reasons.append("customer_name_key")
            continue
        if key_s not in AI_FIELD_WHITELIST:
            blocked_fields.append(key_s)
            reasons.append("non_whitelist_key")
            continue
        if _ID_CARD_RE.search(value):
            blocked_fields.append(key_s)
            reasons.append("id_card")
            continue
        if _PHONE_RE.search(value):
            blocked_fields.append(key_s)
            reasons.append("phone")
            continue
        if _BANK_CARD_RE.search(value):
            blocked_fields.append(key_s)
            reasons.append("bank_card")
            continue
        if _WINDOWS_PATH_RE.search(value):
            blocked_fields.append(key_s)
            reasons.append("local_path")
            continue
    return GuardResult(
        allowed=not blocked_fields,
        blocked_fields=tuple(dict.fromkeys(blocked_fields)),
        reasons=tuple(dict.fromkeys(reasons)),
    )


def build_privacy_preflight(
    *,
    task: str,
    prompt_version: str,
    provider: str,
    model: str,
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Read-only preflight report; never contains full real field values."""
    item_rows: list[dict[str, object]] = []
    blocked: Counter[str] = Counter()
    payload_keys: set[str] = set()
    blocked_items = 0
    for item in items:
        fields = item.get("fields")
        if not isinstance(fields, Mapping):
            continue
        keys = sorted(str(name) for name in fields)
        payload_keys.update(keys)
        guard = guard_item(fields)
        item_rows.append(
            {
                "signature_hash": str(item.get("signature_hash", ""))[:24],
                "field_keys": keys,
                "blocked": not guard.allowed,
                "blocked_fields": list(guard.blocked_fields),
                "blocked_reasons": list(guard.reasons),
            }
        )
        if not guard.allowed:
            blocked_items += 1
            blocked.update(guard.reasons)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task": task,
        "prompt_version": prompt_version,
        "provider": provider,
        "model": model,
        "signature_count": len(item_rows),
        "payload_keys": sorted(payload_keys),
        "redacted_fields": True,
        "values_never_exported": True,
        "privacy_blocked_count": blocked_items,
        "blocked_reason_counts": dict(sorted(blocked.items())),
        "items": item_rows,
    }


def summarize_guard(
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    allowed = 0
    blocked = 0
    for item in items:
        guard = guard_item(item.get("fields", {}))
        if guard.allowed:
            allowed += 1
        else:
            blocked += 1
    return {
        "allowed_count": allowed,
        "blocked_count": blocked,
        "policy": (
            "blocked items are never sent; no auto-strip-and-continue"
        ),
    }
