"""DeepSeek Chat Completions adapter for guarded MVP AI observations."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_BATCH_SIZE = 50

Transport = Callable[[str, bytes, Mapping[str, str], float], bytes]


class DeepSeekProviderError(RuntimeError):
    """Raised when a provider response cannot be safely adopted."""


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    enabled: bool = False
    data_authorized: bool = False
    retention_policy_confirmed: bool = False
    allow_business_names: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    batch_size: int = DEFAULT_BATCH_SIZE

    def ai_config(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "data_authorized": self.data_authorized,
            "retention_policy_confirmed": self.retention_policy_confirmed,
            "allow_business_names": self.allow_business_names,
            "provider": "deepseek",
            "model": self.model,
            "api_key_available": bool(self.api_key),
        }


def _boolean(value: str | None) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _positive_float(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def _positive_int(value: str | None, default: int) -> int:
    if not value:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


def load_deepseek_settings(
    environ: Mapping[str, str] | None = None,
) -> DeepSeekSettings:
    values = os.environ if environ is None else environ
    return DeepSeekSettings(
        api_key=values.get("BANKFLOW_AI_API_KEY", "").strip(),
        base_url=(
            values.get("BANKFLOW_AI_BASE_URL", DEFAULT_BASE_URL).strip()
            or DEFAULT_BASE_URL
        ),
        model=(
            values.get("BANKFLOW_AI_MODEL", DEFAULT_MODEL).strip()
            or DEFAULT_MODEL
        ),
        enabled=_boolean(values.get("BANKFLOW_AI_ENABLED")),
        data_authorized=_boolean(values.get("BANKFLOW_AI_DATA_AUTHORIZED")),
        retention_policy_confirmed=_boolean(
            values.get("BANKFLOW_AI_RETENTION_CONFIRMED")
        ),
        allow_business_names=_boolean(
            values.get("BANKFLOW_AI_ALLOW_BUSINESS_NAMES")
        ),
        timeout_seconds=_positive_float(
            values.get("BANKFLOW_AI_TIMEOUT_SECONDS"),
            DEFAULT_TIMEOUT_SECONDS,
        ),
        batch_size=_positive_int(
            values.get("BANKFLOW_AI_BATCH_SIZE"),
            DEFAULT_BATCH_SIZE,
        ),
    )


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.netloc:
        raise DeepSeekProviderError("DeepSeek base URL must be an HTTPS URL")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _default_transport(
    url: str,
    body: bytes,
    headers: Mapping[str, str],
    timeout_seconds: float,
) -> bytes:
    request = urllib.request.Request(
        url,
        data=body,
        headers=dict(headers),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.read()
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise DeepSeekProviderError("DeepSeek request failed") from exc


def _response_results(raw_response: bytes) -> list[dict[str, object]]:
    try:
        envelope = json.loads(raw_response.decode("utf-8"))
        content = envelope["choices"][0]["message"]["content"]
        result_object = json.loads(content)
        results = result_object["results"]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeepSeekProviderError("DeepSeek returned an invalid JSON response") from exc
    if not isinstance(results, list):
        raise DeepSeekProviderError("DeepSeek results must be a JSON list")
    return results


def _request_body(
    settings: DeepSeekSettings,
    payload: Mapping[str, object],
    transactions: list[dict[str, object]],
) -> bytes:
    user_payload = {
        "prompt_version": payload.get("prompt_version"),
        "business_context": payload.get("business_context"),
        "allowed_classifications": payload.get("allowed_classifications"),
        "allowed_evidence_strengths": payload.get("allowed_evidence_strengths"),
        "instructions": payload.get("instructions"),
        "transactions": transactions,
        "required_output": {
            "type": "object",
            "required_key": "results",
            "result_fields": [
                "transaction_id",
                "classification",
                "evidence_strength",
                "reason",
                "used_fields",
            ],
            "coverage": "results must contain exactly one item for every input transaction",
        },
    }
    request = {
        "model": settings.model,
        "stream": False,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "temperature": 0,
        "max_tokens": 8192,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是流水文字字段的经营相关性分类助手。"
                    "只依据输入字段分类，不推断欺诈、包装、准入、资金来源或真实经营。"
                    "必须联合查看用途、商品、商户类别、企业或经营部门店名称中的行业语义。"
                    "泛化的实业、贸易、科技、工业或工程公司类型只能作为弱提示。"
                    "分类和理由必须一致。"
                    "必须只输出一个符合用户给定结构的 JSON 对象，不得输出 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(user_payload, ensure_ascii=False),
            },
        ],
    }
    return json.dumps(request, ensure_ascii=False).encode("utf-8")


class DeepSeekEvaluator:
    def __init__(
        self,
        settings: DeepSeekSettings,
        transport: Transport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or _default_transport

    def __call__(self, payload: dict[str, object]) -> list[dict[str, object]]:
        transactions = payload.get("transactions")
        if not isinstance(transactions, list):
            raise DeepSeekProviderError("AI payload transactions must be a list")
        if not transactions:
            return []

        grouped: dict[str, list[dict[str, object]]] = {}
        for transaction in transactions:
            if not isinstance(transaction, dict):
                raise DeepSeekProviderError("AI transaction must be a JSON object")
            fields = transaction.get("fields")
            if not isinstance(fields, dict):
                raise DeepSeekProviderError("AI transaction fields must be a JSON object")
            signature = json.dumps(fields, ensure_ascii=False, sort_keys=True)
            grouped.setdefault(signature, []).append(transaction)
        representatives = [members[0] for members in grouped.values()]
        member_ids = {
            str(members[0]["transaction_id"]): [
                str(member["transaction_id"]) for member in members
            ]
            for members in grouped.values()
        }

        endpoint = _chat_completions_url(self._settings.base_url)
        headers = {
            "Authorization": f"Bearer {self._settings.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        merged: list[dict[str, object]] = []
        for offset in range(0, len(representatives), self._settings.batch_size):
            batch = representatives[offset : offset + self._settings.batch_size]
            raw_response = self._transport(
                endpoint,
                _request_body(self._settings, payload, batch),
                headers,
                self._settings.timeout_seconds,
            )
            for result in _response_results(raw_response):
                representative_id = str(result.get("transaction_id", ""))
                ids = member_ids.get(representative_id)
                if not ids:
                    merged.append(result)
                    continue
                for transaction_id in ids:
                    merged.append(
                        {
                            **result,
                            "transaction_id": transaction_id,
                        }
                    )
        return merged


def load_deepseek_runtime(
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> tuple[dict[str, object], Callable[[dict[str, object]], object] | None]:
    settings = load_deepseek_settings(environ)
    evaluator = (
        DeepSeekEvaluator(settings, transport)
        if settings.enabled
        and settings.data_authorized
        and settings.retention_policy_confirmed
        and bool(settings.api_key)
        else None
    )
    return settings.ai_config(), evaluator
