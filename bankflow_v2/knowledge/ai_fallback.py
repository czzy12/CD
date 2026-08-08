"""Provider-neutral AI fallback contracts and DeepSeek implementation."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from ..deepseek_adapter import DeepSeekSettings, _chat_completions_url
from .models import KnowledgeCandidate
from .versioning import (
    PROMPT_INDUSTRY_RELATION_VERSION,
    PROMPT_SEMANTIC_CONCEPT_VERSION,
)


AI_FIELD_WHITELIST = frozenset(
    {
        "counterparty_name",
        "merchant_name",
        "summary",
        "remark",
        "purpose",
        "product_description",
        "merchant_category",
    }
)
RELEVANCE_VALUES = frozenset(
    {"strong", "medium", "weak", "none", "undetermined"}
)
CONFIDENCE_VALUES = frozenset({"high", "medium", "low"})
Transport = Callable[[str, bytes, Mapping[str, str], float], bytes]


class KnowledgeAIError(RuntimeError):
    pass


def _json_response(raw: bytes) -> dict[str, Any]:
    try:
        envelope = json.loads(raw.decode("utf-8"))
        content = envelope["choices"][0]["message"]["content"]
        return json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise KnowledgeAIError("provider returned invalid JSON") from exc


def _post(
    settings: DeepSeekSettings,
    transport: Transport,
    *,
    task_type: str,
    prompt_version: str,
    payload: Mapping[str, Any],
    output_schema: Mapping[str, Any],
) -> dict[str, Any]:
    endpoint = _chat_completions_url(settings.base_url)
    headers = {
        "Authorization": f"Bearer {settings.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
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
                    "你是银行流水文字的经营语义与行业关系知识助手。"
                    "只做语义分类和知识候选生成，不做风控、欺诈、包装、准入或资金判断。"
                    "只能引用用户消息中真实提供的字段和条目，不得推测不存在的内容。"
                    "不确定时返回 undetermined 或 low，不允许为了覆盖率强行分类。"
                    "输出必须严格符合用户给定 JSON 结构，不得输出 Markdown。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task_type": task_type,
                        "prompt_version": prompt_version,
                        "output_schema": output_schema,
                        **payload,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    try:
        raw = transport(
            endpoint,
            json.dumps(request, ensure_ascii=False).encode("utf-8"),
            headers,
            settings.timeout_seconds,
        )
    except (TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        raise KnowledgeAIError("provider request failed") from exc
    return _json_response(raw)


class DeepSeekKnowledgeAdapter:
    """DeepSeek implementation of the two knowledge AI tasks."""

    def __init__(
        self,
        settings: DeepSeekSettings,
        transport: Transport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport or _default_transport
        self.prompt_semantic_concept_version = PROMPT_SEMANTIC_CONCEPT_VERSION
        self.prompt_industry_relation_version = PROMPT_INDUSTRY_RELATION_VERSION

    @property
    def model(self) -> str:
        return str(self._settings.model)

    def _check_authorized(self) -> None:
        if not (
            self._settings.enabled
            and self._settings.data_authorized
            and self._settings.retention_policy_confirmed
            and self._settings.api_key
        ):
            raise KnowledgeAIError("knowledge AI authorization incomplete")

    def resolve_concepts(
        self,
        items: list[dict[str, Any]],
        *,
        concept_candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self._check_authorized()
        safe_items = []
        for item in items:
            fields = {
                str(name): str(value)
                for name, value in item.get("fields", {}).items()
                if str(name) in AI_FIELD_WHITELIST and str(value).strip()
            }
            safe_items.append(
                {
                    "item_id": str(item.get("item_id", "")),
                    "fields": fields,
                }
            )
        output_schema = {
            "type": "object",
            "required": ["results"],
            "properties": {
                "results": {
                    "type": "array",
                    "minItems": len(safe_items),
                    "maxItems": len(safe_items),
                    "items": {
                        "type": "object",
                        "required": [
                            "item_id",
                            "concept_id",
                            "confidence",
                            "reason",
                            "used_fields",
                        ],
                        "properties": {
                            "item_id": {"type": "string"},
                            "concept_id": {"type": "string"},
                            "confidence": {
                                "type": "string",
                                "enum": sorted(CONFIDENCE_VALUES),
                            },
                            "reason": {"type": "string"},
                            "used_fields": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "new_concept_candidate": {
                                "type": ["object", "null"],
                                "properties": {
                                    "suggested_concept_id": {"type": "string"},
                                    "name_zh": {"type": "string"},
                                    "reason": {"type": "string"},
                                },
                            },
                        },
                    },
                }
            },
        }
        response = _post(
            self._settings,
            self._transport,
            task_type="semantic_concept_resolution",
            prompt_version=self.prompt_semantic_concept_version,
            payload={
                "concept_candidates": concept_candidates,
                "items": safe_items,
                "instructions": [
                    "支付渠道、支付工具、收单机构（如财付通、微信支付、支付宝、扫码、POS、"
                    "拉卡拉、银联等）本身不构成经营 Concept；应忽略支付渠道语义，"
                    "不得把支付渠道或收单机构映射到任何经营 Concept。",
                    "如果支付渠道之外存在独立充分的业务语义（商户类别、商品/服务描述、"
                    "用途、组织类型、可识别经营动作），必须根据剩余业务语义判断 Concept。",
                    "generic 是合法的宽泛经营 Concept；存在真实经营/交易业务语义但无法"
                    "归属更具体概念时可以使用 generic，不得把 generic 当作“无法判断”。",
                    "只有剩余非敏感证据确实不足以推断稳定可复用语义时才返回 undetermined；"
                    "不得为了减少 insufficient 而强行分类，也不得把纯支付渠道文本映射 generic。",
                    "地名、项目名、实体名片段本身不构成经营 Concept（例如“汽车小镇”不是"
                    "汽车销售或娱乐的依据），除非文本同时包含明确业务动作、商品或服务。",
                    "带有位置限定（行政区/道路/楼层等）且没有明确商品或服务类别的门店名，"
                    "不足以推断 Concept，应 undetermined。",
                    "简短品牌门店名（品牌+编号+店，如“鲁泰37店”）且无位置限定时，"
                    "可判 retail；餐饮品牌门店应优先 dining；只有位置限定而无明确类别时才 undetermined。",
                    "党政机关、兵团师市、政务事业单位的分公司/分支机构应优先 "
                    "government_public_service。",
                    "仅含支付/交易动作（如经营码交易、扫码付款）而没有业务对象时，"
                    "应 undetermined，不得映射 generic。",
                    "明确家用电器/净水设备/水龙头过滤类商品应优先 home_appliance，"
                    "而不是泛化 goods；水果零售/品牌门店应优先 retail，而不是 food；"
                    "鲜肉/生鲜/食品门店应优先 food，而不是 retail；"
                    "便利连锁门店应优先 convenience_store；平台商户/电商提现应优先 ecommerce。",
                    "不得把真实商户名或个人姓名作为新 Concept 名称。",
                ],
            },
            output_schema=output_schema,
        )
        results = response.get("results")
        if not isinstance(results, list):
            raise KnowledgeAIError("semantic concept results must be a list")
        return _validate_concept_results(results, safe_items)

    def resolve_relations(
        self,
        items: list[dict[str, Any]],
        *,
        industry_nodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self._check_authorized()
        output_schema = {
            "type": "object",
            "required": ["results"],
            "properties": {
                "results": {
                    "type": "array",
                    "minItems": len(items),
                    "maxItems": len(items),
                    "items": {
                        "type": "object",
                        "required": [
                            "item_id",
                            "relevance",
                            "reason",
                            "constraint_acknowledged",
                        ],
                        "properties": {
                            "item_id": {"type": "string"},
                            "relevance": {
                                "type": "string",
                                "enum": sorted(RELEVANCE_VALUES),
                            },
                            "reason": {"type": "string"},
                            "constraint_acknowledged": {"type": "boolean"},
                        },
                    },
                }
            },
        }
        response = _post(
            self._settings,
            self._transport,
            task_type="industry_concept_relevance",
            prompt_version=self.prompt_industry_relation_version,
            payload={
                "industry_nodes": industry_nodes,
                "items": [
                    {
                        "item_id": str(item.get("item_id", "")),
                        "industry_id": str(item.get("industry_id", "")),
                        "concept_id": str(item.get("concept_id", "")),
                        "concept_name": str(item.get("concept_name", "")),
                        "specialty": item.get("specialty", []),
                        "constraints": item.get("constraints", {}),
                    }
                    for item in items
                ],
            },
            output_schema=output_schema,
        )
        results = response.get("results")
        if not isinstance(results, list):
            raise KnowledgeAIError("relation results must be a list")
        return _validate_relation_results(results, items)


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
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return response.read()


def _validate_concept_results(
    results: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(item["item_id"]): item for item in items}
    valid: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, Mapping):
            raise KnowledgeAIError("concept result must be an object")
        item_id = str(result.get("item_id", ""))
        item = by_id.get(item_id)
        if item is None:
            raise KnowledgeAIError(f"concept result references unknown item: {item_id}")
        confidence = str(result.get("confidence", ""))
        if confidence not in CONFIDENCE_VALUES:
            raise KnowledgeAIError("concept confidence invalid")
        used_fields = result.get("used_fields", [])
        if not isinstance(used_fields, list) or not used_fields:
            raise KnowledgeAIError("concept used_fields empty")
        allowed = set(item["fields"])
        if not set(map(str, used_fields)).issubset(allowed):
            raise KnowledgeAIError("concept used_fields not allowed")
        new_candidate = result.get("new_concept_candidate")
        if new_candidate is not None and not isinstance(new_candidate, Mapping):
            raise KnowledgeAIError("new_concept_candidate must be null or object")
        if not str(result.get("concept_id", "")) and new_candidate is None:
            raise KnowledgeAIError("concept_id missing")
        if not str(result.get("reason", "")).strip():
            raise KnowledgeAIError("concept reason missing")
        valid.append(dict(result))
    return valid


def _validate_relation_results(
    results: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {str(item["item_id"]): item for item in items}
    valid: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, Mapping):
            raise KnowledgeAIError("relation result must be an object")
        item_id = str(result.get("item_id", ""))
        if item_id not in by_id:
            raise KnowledgeAIError(f"relation result references unknown item: {item_id}")
        relevance = str(result.get("relevance", ""))
        if relevance not in RELEVANCE_VALUES:
            raise KnowledgeAIError("relation relevance invalid")
        if result.get("constraint_acknowledged") is not True:
            raise KnowledgeAIError("relation constraint not acknowledged")
        if not str(result.get("reason", "")).strip():
            raise KnowledgeAIError("relation reason missing")
        valid.append(dict(result))
    return valid


def build_knowledge_candidate(
    *,
    candidate_type: str,
    proposed_value: Mapping[str, Any],
    reason: str,
    model: str,
    prompt_version: str,
    input_signature: Mapping[str, Any],
) -> KnowledgeCandidate:
    import uuid

    return KnowledgeCandidate(
        candidate_id=uuid.uuid4().hex,
        candidate_type=candidate_type,
        proposed_value=dict(proposed_value),
        reason=reason,
        model=model,
        prompt_version=prompt_version,
        input_signature=dict(input_signature),
    )
