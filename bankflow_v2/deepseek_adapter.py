"""DeepSeek Chat Completions adapter for guarded MVP AI observations."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .ai_business_observation import (
    AI_MODEL_JUDGEMENTS,
    AI_OUTPUT_CONTRACT_VERSION,
    ai_semantic_signature,
    semantic_signature_id,
    validate_ai_response_collecting,
)


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"
DEFAULT_TIMEOUT_SECONDS = 60.0
DEFAULT_BATCH_SIZE = 50

Transport = Callable[[str, bytes, Mapping[str, str], float], bytes]


class DeepSeekProviderError(RuntimeError):
    """Raised when a provider response cannot be safely adopted."""

    def __init__(
        self,
        message: str,
        *,
        failure_reason: str = "ai_provider_failed",
        safe_diagnostic: str = "",
    ) -> None:
        super().__init__(message)
        self.failure_reason = failure_reason
        self.safe_diagnostic = safe_diagnostic


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
    cache_dir: str = ""

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
        cache_dir=values.get("BANKFLOW_AI_CACHE_DIR", "").strip(),
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


def _response_results(
    raw_response: bytes,
    batch_number: int,
) -> list[dict[str, object]]:
    try:
        envelope = json.loads(raw_response.decode("utf-8"))
        content = envelope["choices"][0]["message"]["content"]
        result_object = json.loads(content)
        results = result_object["results"]
    except (KeyError, IndexError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeepSeekProviderError(
            "DeepSeek returned an invalid JSON response",
            failure_reason="ai_response_invalid",
            safe_diagnostic=f"batch_{batch_number}:provider_json_invalid",
        ) from exc
    if not isinstance(results, list):
        raise DeepSeekProviderError(
            "DeepSeek results must be a JSON list",
            failure_reason="ai_response_invalid",
            safe_diagnostic=f"batch_{batch_number}:results_not_list",
        )
    return results


def _request_body(
    settings: DeepSeekSettings,
    payload: Mapping[str, object],
    transactions: list[dict[str, object]],
) -> bytes:
    constrained_transactions = [
        {
            "transaction_id": transaction.get("transaction_id"),
            "fields": transaction.get("fields"),
            "classification_constraints": transaction.get(
                "classification_constraints"
            ),
        }
        for transaction in transactions
    ]
    user_payload = {
        "task_type": payload.get("task_type"),
        "prompt_version": payload.get("prompt_version"),
        "output_contract_version": payload.get("output_contract_version"),
        "business_context": payload.get("business_context"),
        "allowed_model_judgements": payload.get(
            "allowed_model_judgements"
        ),
        "instructions": payload.get("instructions"),
        "transactions": constrained_transactions,
        "output_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["results"],
            "properties": {
                "results": {
                    "type": "array",
                    "minItems": len(constrained_transactions),
                    "maxItems": len(constrained_transactions),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "transaction_id",
                            "semantic_judgement",
                            "reason",
                            "used_fields",
                        ],
                        "properties": {
                            "transaction_id": {"type": "string"},
                            "semantic_judgement": {
                                "type": "string",
                                "enum": sorted(AI_MODEL_JUDGEMENTS),
                            },
                            "reason": {
                                "type": "string",
                                "minLength": 1,
                            },
                            "used_fields": {
                                "type": "array",
                                "minItems": 1,
                                "items": {"type": "string"},
                            },
                        },
                    },
                }
            },
        },
        "output_example": {
            "results": [
                {
                    "transaction_id": "必须原样复制输入交易ID",
                    "semantic_judgement": "medium",
                    "reason": "简明说明实际使用的字段依据",
                    "used_fields": ["purpose"],
                }
            ]
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
                    "具体产品或服务优先作为中等候选；货款不得把具体产品或服务降为弱提示。"
                    "只有缺少具体产品、服务、项目或用途时，泛化的实业、贸易、科技、工业或工程公司类型及货款才只能作为弱提示。"
                    "classification_constraints由本地确定性代码生成，模型不得覆盖或忽略。"
                    "每笔不得超过maximum_allowed_strength；directly_related_allowed为false时绝对禁止判直接相关。"
                    "你只判断semantic_judgement：strong、medium、weak、none或undetermined；分类由本地代码派生。"
                    "semantic_judgement必须严格使用用户消息output_schema中的五值enum，不能输出其他词。"
                    "企业或商户名称不能单独支持直接相关。"
                    "所有正向分类必须与business_context中的申报行业或工作单位明确体现的行业语义相关。"
                    "对建筑材料或环保工程上下文，建材、护栏、栏杆、围栏、塑木、园林景观设计是具体相关产品或服务，货款不得将其中等候选降为弱提示。"
                    "无具体课题、产品、项目或行业对象的泛化咨询费、材料费或采购款不得仅凭可能性判中等候选。"
                    "餐饮、便利店、话费、银行服务、医疗、打车等无关生活服务不得仅因具体而判正向。"
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


def _json_fingerprint(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class AiResponseCache:
    """Local cache without credentials, keyed by task, model, prompt and semantics."""

    def __init__(self, root: str | Path | None) -> None:
        self.root = Path(root) if root else None

    def _signature_path(
        self,
        task_type: str,
        model: str,
        prompt_version: str,
        signature: tuple[tuple[str, str], ...],
    ) -> Path | None:
        if self.root is None:
            return None
        namespace = _json_fingerprint(
            {
                "task_type": task_type,
                "provider": "deepseek",
                "model": model,
                "prompt_version": prompt_version,
            }
        )[:16]
        return (
            self.root
            / "signatures"
            / namespace
            / f"{semantic_signature_id(signature)}.json"
        )

    @staticmethod
    def input_fingerprint(
        settings: DeepSeekSettings,
        payload: Mapping[str, object],
        transaction: Mapping[str, object],
    ) -> str:
        return _json_fingerprint(
            {
                "task_type": payload.get("task_type"),
                "provider": "deepseek",
                "model": settings.model,
                "prompt_version": payload.get("prompt_version"),
                "output_contract_version": payload.get(
                    "output_contract_version"
                ),
                "business_context": payload.get("business_context"),
                "instructions": payload.get("instructions"),
                "fields": transaction.get("fields"),
                "classification_constraints": transaction.get(
                    "classification_constraints"
                ),
            }
        )

    def load(
        self,
        settings: DeepSeekSettings,
        payload: Mapping[str, object],
        transaction: Mapping[str, object],
    ) -> dict[str, object] | None:
        fields = transaction.get("fields")
        if not isinstance(fields, Mapping):
            return None
        signature = ai_semantic_signature(
            {str(name): str(value) for name, value in fields.items()}
        )
        path = self._signature_path(
            str(payload.get("task_type", "")),
            settings.model,
            str(payload.get("prompt_version", "")),
            signature,
        )
        if path is None or not path.is_file():
            return None
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(entry, dict):
            return None
        if entry.get("input_fingerprint") == self.input_fingerprint(
            settings,
            payload,
            transaction,
        ):
            return entry
        cached_input = entry.get("input")
        if not isinstance(cached_input, Mapping):
            return None
        compatible = (
            entry.get("output_contract_version") is None
            and payload.get("output_contract_version")
            == AI_OUTPUT_CONTRACT_VERSION
            and entry.get("task_type") == payload.get("task_type")
            and entry.get("provider") == "deepseek"
            and entry.get("model") == settings.model
            and entry.get("prompt_version") == payload.get("prompt_version")
            and entry.get("semantic_signature")
            == [list(pair) for pair in signature]
            and cached_input.get("fields") == transaction.get("fields")
            and cached_input.get("classification_constraints")
            == transaction.get("classification_constraints")
            and cached_input.get("business_context")
            == payload.get("business_context")
        )
        if not compatible:
            return None
        return {**entry, "output_contract_compatible_replay": True}

    def store_request(
        self,
        *,
        settings: DeepSeekSettings,
        payload: Mapping[str, object],
        request_body: bytes,
        raw_response: bytes,
        batch_number: int,
        validation: Mapping[str, object],
    ) -> str:
        if self.root is None:
            return ""
        request_hash = _json_fingerprint(
            {
                "request": request_body.decode("utf-8", errors="replace"),
                "response": raw_response.decode("utf-8", errors="replace"),
            }
        )
        path = self.root / "requests" / f"{request_hash}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "cache_schema_version": 2,
                    "task_type": payload.get("task_type"),
                    "provider": "deepseek",
                    "model": settings.model,
                    "prompt_version": payload.get("prompt_version"),
                    "output_contract_version": payload.get(
                        "output_contract_version"
                    ),
                    "batch_number": batch_number,
                    "request_body_without_credentials": request_body.decode(
                        "utf-8",
                        errors="replace",
                    ),
                    "raw_response": raw_response.decode(
                        "utf-8",
                        errors="replace",
                    ),
                    "validation": dict(validation),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return str(path)

    def store_signature(
        self,
        settings: DeepSeekSettings,
        payload: Mapping[str, object],
        transaction: Mapping[str, object],
        *,
        response_item: object,
        validation_failures: list[dict[str, object]],
        request_cache_path: str,
    ) -> None:
        fields = transaction.get("fields")
        if self.root is None or not isinstance(fields, Mapping):
            return
        signature = ai_semantic_signature(
            {str(name): str(value) for name, value in fields.items()}
        )
        path = self._signature_path(
            str(payload.get("task_type", "")),
            settings.model,
            str(payload.get("prompt_version", "")),
            signature,
        )
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "cache_schema_version": 2,
                    "task_type": payload.get("task_type"),
                    "provider": "deepseek",
                    "model": settings.model,
                    "prompt_version": payload.get("prompt_version"),
                    "output_contract_version": payload.get(
                        "output_contract_version"
                    ),
                    "semantic_signature": [list(pair) for pair in signature],
                    "input_fingerprint": self.input_fingerprint(
                        settings,
                        payload,
                        transaction,
                    ),
                    "input": {
                        "fields": dict(fields),
                        "classification_constraints": transaction.get(
                            "classification_constraints"
                        ),
                        "business_context": payload.get("business_context"),
                        "instructions": payload.get("instructions"),
                        "output_contract_version": payload.get(
                            "output_contract_version"
                        ),
                    },
                    "response_item": response_item,
                    "validation_failures": validation_failures,
                    "request_cache_path": request_cache_path,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


class DeepSeekEvaluator:
    def __init__(
        self,
        settings: DeepSeekSettings,
        transport: Transport | None = None,
        *,
        cache_dir: str | Path | None = None,
        replay_only: bool = False,
        retry_invalid_cache: bool = False,
    ) -> None:
        self._settings = settings
        self._transport = transport or _default_transport
        self._cache = AiResponseCache(cache_dir or settings.cache_dir)
        self._replay_only = replay_only
        self._retry_invalid_cache = retry_invalid_cache

    def __call__(self, payload: dict[str, object]) -> dict[str, object]:
        transactions = payload.get("transactions")
        if not isinstance(transactions, list):
            raise DeepSeekProviderError("AI payload transactions must be a list")
        if not transactions:
            return {
                "results": [],
                "validation_failures": [],
                "provider_batch_count": 0,
                "cache_hit_count": 0,
                "cache_miss_count": 0,
                "cache_replay_mismatch_count": 0,
                "invalid_cache_entry_count": 0,
                "provider_call_count": 0,
                "unique_semantic_count": 0,
            }

        grouped: dict[str, list[dict[str, object]]] = {}
        for transaction in transactions:
            if not isinstance(transaction, dict):
                raise DeepSeekProviderError("AI transaction must be a JSON object")
            fields = transaction.get("fields")
            if not isinstance(fields, dict):
                raise DeepSeekProviderError("AI transaction fields must be a JSON object")
            signature = json.dumps(
                ai_semantic_signature(
                    {str(name): str(value) for name, value in fields.items()}
                ),
                ensure_ascii=False,
            )
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
        failures: list[dict[str, object]] = []
        uncached: list[dict[str, object]] = []
        cache_hit_count = 0
        cache_miss_count = 0
        cache_replay_mismatch_count = 0
        invalid_cache_entry_count = 0
        for representative in representatives:
            entry = self._cache.load(
                self._settings,
                payload,
                representative,
            )
            if entry is None:
                uncached.append(representative)
                continue
            response_item = entry.get("response_item")
            if isinstance(response_item, Mapping):
                response_item = {
                    **response_item,
                    "transaction_id": representative.get("transaction_id"),
                }
            report = validate_ai_response_collecting(
                [response_item] if response_item is not None else [],
                [representative],
            )
            replayed_reasons = sorted(
                str(item.get("reason", ""))
                for item in report["failures"]
                if isinstance(item, Mapping)
            )
            if (
                self._retry_invalid_cache
                and replayed_reasons == ["semantic_judgement_invalid"]
            ):
                invalid_cache_entry_count += 1
                uncached.append(representative)
                continue
            cache_hit_count += 1
            stored_failures = entry.get("validation_failures", [])
            if not isinstance(stored_failures, list):
                stored_failures = []
            stored_reasons = sorted(
                str(item.get("reason", ""))
                for item in stored_failures
                if isinstance(item, Mapping)
            )
            if stored_reasons != replayed_reasons:
                cache_replay_mismatch_count += 1
            for failure in report["failures"]:
                failures.append(
                    {
                        **failure,
                        "location": f"cache:{failure['location']}",
                        "cache_replay": True,
                    }
                )
            for result in report["accepted"]:
                representative_id = str(result.get("transaction_id", ""))
                for transaction_id in member_ids.get(
                    representative_id,
                    [representative_id],
                ):
                    merged.append({**result, "transaction_id": transaction_id})

        cache_miss_count = len(uncached)
        if self._replay_only and uncached:
            for representative in uncached:
                failures.append(
                    {
                        "location": "cache",
                        "reason": "cache_miss",
                        "transaction_id": str(
                            representative.get("transaction_id", "")
                        ),
                        "representative_fields": dict(
                            representative.get("fields", {})
                        ),
                        "cache_replay": True,
                    }
                )
            uncached = []

        provider_call_count = 0
        provider_batch_count = 0
        for offset in range(0, len(uncached), self._settings.batch_size):
            batch = uncached[offset : offset + self._settings.batch_size]
            batch_number = offset // self._settings.batch_size + 1
            provider_batch_count += 1
            provider_call_count += 1
            request_body = _request_body(self._settings, payload, batch)
            raw_response = self._transport(
                endpoint,
                request_body,
                headers,
                self._settings.timeout_seconds,
            )
            try:
                results = _response_results(raw_response, batch_number)
            except DeepSeekProviderError as exc:
                if exc.failure_reason != "ai_response_invalid":
                    raise
                batch_failure = {
                    "location": f"batch_{batch_number}",
                    "reason": (
                        exc.safe_diagnostic.split(":", 1)[-1]
                        if exc.safe_diagnostic
                        else "provider_response_invalid"
                    ),
                    "transaction_id": "",
                    "representative_fields": {},
                }
                failures.append(batch_failure)
                self._cache.store_request(
                    settings=self._settings,
                    payload=payload,
                    request_body=request_body,
                    raw_response=raw_response,
                    batch_number=batch_number,
                    validation={
                        "accepted": [],
                        "failures": [batch_failure],
                    },
                )
                continue

            report = validate_ai_response_collecting(
                results,
                batch,
            )
            batch_failures = [
                {
                    **failure,
                    "location": f"batch_{batch_number}:{failure['location']}",
                }
                for failure in report["failures"]
            ]
            failures.extend(batch_failures)
            request_cache_path = self._cache.store_request(
                settings=self._settings,
                payload=payload,
                request_body=request_body,
                raw_response=raw_response,
                batch_number=batch_number,
                validation={
                    "accepted_count": report["accepted_count"],
                    "expected_count": report["expected_count"],
                    "failures": batch_failures,
                },
            )
            response_by_id = {
                str(item.get("transaction_id", "")): item
                for item in results
                if isinstance(item, Mapping)
            }
            for representative in batch:
                representative_id = str(
                    representative.get("transaction_id", "")
                )
                relevant_failures = [
                    failure
                    for failure in batch_failures
                    if failure.get("transaction_id") == representative_id
                ]
                self._cache.store_signature(
                    self._settings,
                    payload,
                    representative,
                    response_item=response_by_id.get(representative_id),
                    validation_failures=relevant_failures,
                    request_cache_path=request_cache_path,
                )
            for result in report["accepted"]:
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
        return {
            "results": merged,
            "validation_failures": failures,
            "provider_batch_count": provider_batch_count,
            "cache_hit_count": cache_hit_count,
            "cache_miss_count": cache_miss_count,
            "cache_replay_mismatch_count": cache_replay_mismatch_count,
            "invalid_cache_entry_count": invalid_cache_entry_count,
            "provider_call_count": provider_call_count,
            "unique_semantic_count": len(representatives),
        }


def load_deepseek_runtime(
    environ: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    *,
    cache_dir: str | Path | None = None,
    replay_only: bool = False,
    retry_invalid_cache: bool = False,
) -> tuple[dict[str, object], Callable[[dict[str, object]], object] | None]:
    settings = load_deepseek_settings(environ)
    config = settings.ai_config()
    if replay_only:
        config["api_key_available"] = True
        config["replay_only"] = True
    evaluator = (
        DeepSeekEvaluator(
            settings,
            transport,
            cache_dir=cache_dir,
            replay_only=replay_only,
            retry_invalid_cache=retry_invalid_cache,
        )
        if settings.enabled
        and settings.data_authorized
        and settings.retention_policy_confirmed
        and (bool(settings.api_key) or replay_only)
        else None
    )
    return config, evaluator
