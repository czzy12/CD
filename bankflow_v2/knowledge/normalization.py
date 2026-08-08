"""Text normalization and industry/profile normalization for knowledge_v1."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping

from . import versioning
from .models import IndustryProfile, SemanticSignature
from .versioning import SIGNATURE_VERSION


_WS_RE = re.compile(r"\s+")
_PUNCT_STRIP_RE = re.compile(r"[\s\u3000\t\r\n，,。；;：:、（）()\[\]【】「」『』《》〈〉“”\"'`/|\\_\-—–·]+")
_ASCII_CODE_RE = re.compile(r"^[a-z0-9._/-]+$", re.IGNORECASE)
_ORDER_NUMBER_RE = re.compile(
    r"(?:订单号|order(?:id|no)?)\s*[:：\-]?\s*[a-z0-9._/-]{4,}",
    re.IGNORECASE,
)
_REFERENCE_NUMBER_RE = re.compile(
    r"(?:参考号|流水号|交易号|凭证号|reference|ref)\s*[:：\-]?\s*[a-z0-9._/-]{4,}",
    re.IGNORECASE,
)
_HASH_RE = re.compile(r"^(?:[a-f0-9]{16,}|[a-z0-9+/]{24,}={0,2})$", re.IGNORECASE)
_ASCII_PREFIX_RE = re.compile(r"^[a-z0-9._/-]{6,}(?=[\u3400-\u9fff])", re.IGNORECASE)
_ASCII_SUFFIX_RE = re.compile(r"(?<=[\u3400-\u9fff])[a-z0-9._/-]{6,}$", re.IGNORECASE)
_PERSON_AFTER_ORG_RE = re.compile(
    r"((?:集团|公司|商行|经营部|门市部|中心|厂|店|铺|行|部|处|所|馆|城|园|府|坊|站|"
    r"广场|商场|超市|银行|医院|学校|物业)[\s\-_/|·]+)"
    r"([\u4e00-\u9fa5]{2,3})(?=$|[\s\d])"
)
_PERSON_AFTER_PLATFORM_RE = re.compile(
    r"((?:淘宝|支付宝|微信|京东|拼多多|天猫|抖音|快手)[\s\-_/|·]+)"
    r"([\u4e00-\u9fa5]{2,3})$"
)


def sanitize_personal_names(value: str) -> str:
    """Redact likely personal names while preserving organization semantics.

    Conservative: only a 2-3 character CJK token after an organization marker
    or a known platform marker plus a separator is replaced with [PERSON].
    Bare names and business entities without such structure stay untouched.
    """
    cleaned = _PERSON_AFTER_ORG_RE.sub(
        lambda match: match.group(1) + "[PERSON]",
        str(value or ""),
    )
    cleaned = _PERSON_AFTER_PLATFORM_RE.sub(
        lambda match: match.group(1) + "[PERSON]",
        cleaned,
    )
    return cleaned


def normalize_semantic_text(value: str) -> str:
    """Conservative per-field normalization that preserves distinct identity."""
    normalized = unicodedata.normalize(
        "NFKC",
        sanitize_personal_names(value),
    ).strip()
    normalized = _WS_RE.sub("", normalized)
    if not normalized:
        return ""
    if normalized.isdecimal() or _ASCII_CODE_RE.fullmatch(normalized):
        return ""
    if _HASH_RE.fullmatch(normalized):
        return ""
    cleaned = _ORDER_NUMBER_RE.sub("", normalized)
    cleaned = _REFERENCE_NUMBER_RE.sub("", cleaned)
    cleaned = _ASCII_PREFIX_RE.sub("", cleaned)
    cleaned = _ASCII_SUFFIX_RE.sub("", cleaned)
    cleaned = _PUNCT_STRIP_RE.sub("", cleaned)
    cleaned = cleaned.casefold()
    if len(cleaned) < 2:
        return ""
    return cleaned


def semantic_signature_from_fields(
    fields: Mapping[str, object],
    signature_version: str = SIGNATURE_VERSION,
) -> SemanticSignature:
    pairs: list[tuple[str, str]] = []
    for field_name in sorted(fields):
        cleaned = normalize_semantic_text(str(fields[field_name] or ""))
        if not cleaned:
            continue
        pairs.append((field_name, cleaned))
    signature_id = hashlib.sha256(
        json.dumps(
            [signature_version, pairs],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    return SemanticSignature(
        signature_version=signature_version,
        pairs=tuple(pairs),
        signature_id=signature_id,
    )


def compact_text(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def text_contains_any(value: str, terms: tuple[str, ...]) -> list[str]:
    compact = compact_text(value)
    return [term for term in terms if compact_text(term) in compact]


def build_industry_profile(
    business_context: Mapping[str, object] | None,
    taxonomy: object,
) -> IndustryProfile:
    """Normalize a business context into an industry profile (no customer IDs)."""
    from .industry_taxonomy import IndustryTaxonomy

    taxonomy = taxonomy if isinstance(taxonomy, IndustryTaxonomy) else None
    if taxonomy is None:
        return IndustryProfile(taxonomy_version=versioning.TAXONOMY_VERSION)
    if not isinstance(business_context, Mapping):
        return IndustryProfile(taxonomy_version=taxonomy.version)
    texts: list[str] = []
    for key in (
        "confirmed_primary_business",
        "confirmed_products_or_services",
        "declared_work_description",
    ):
        value = business_context.get(key)
        if isinstance(value, str) and value.strip():
            texts.append(value)
    for key in ("declared_industries", "work_units"):
        values = business_context.get(key)
        if isinstance(values, list):
            texts.extend(str(item) for item in values if str(item).strip())
    primary_ids: list[str] = []
    secondary_ids: list[str] = []
    matched: set[str] = set()
    for text in texts:
        for industry_id, terms in _INDUSTRY_TERMS.items():
            if industry_id in matched:
                continue
            if text_contains_any(text, terms):
                matched.add(industry_id)
                primary_ids.append(industry_id)
                break
    for text in texts:
        for industry_id, terms in _SECONDARY_INDUSTRY_TERMS.items():
            if industry_id in matched or industry_id in primary_ids:
                continue
            if text_contains_any(text, terms):
                matched.add(industry_id)
                secondary_ids.append(industry_id)
                break
    if not primary_ids:
        primary_ids = list(taxonomy.best_guess_industry_ids(texts))
    specialties = taxonomy.resolve_specialty_concepts(texts)
    return IndustryProfile(
        primary_industry_ids=tuple(primary_ids),
        secondary_industry_ids=tuple(secondary_ids),
        specialty_concept_ids=tuple(specialties),
        normalized_products_services=tuple(
            dict.fromkeys(compact_text(text) for text in texts if text)
        ),
        taxonomy_version=taxonomy.version,
    )


_INDUSTRY_TERMS: dict[str, tuple[str, ...]] = {
    "internal.building_material_trade": (
        "建材批发",
        "建筑材料批发",
        "建材销售",
        "建筑材料",
        "砂石",
        "水泥",
    ),
    "internal.environmental_engineering": (
        "环保工程",
        "环境治理",
        "环境保护工程",
        "园林景观",
        "塑木",
        "护栏工程",
    ),
    "47": ("建筑工程", "建筑施工", "房屋建筑", "工程建设", "工程施工"),
    "06": ("煤炭", "煤炭开采", "煤炭销售", "煤矿"),
    "internal.alcohol_tobacco_retail": (
        "烟酒零售",
        "烟酒",
        "酒水",
        "超市经营",
        "超市",
        "便利店经营",
    ),
    "internal.furniture_appliance_sales": (
        "家具电器销售",
        "家具销售",
        "家电销售",
        "家具",
        "家电",
    ),
    "internal.decoration_engineering": (
        "装饰装修",
        "装修",
        "室内装修",
        "装饰工程",
    ),
}

_SECONDARY_INDUSTRY_TERMS: dict[str, tuple[str, ...]] = {
    "internal.environmental_engineering": (
        "环保工程",
        "环境治理",
        "园林景观",
    ),
    "internal.decoration_engineering": (
        "装饰装修",
        "装修工程",
        "室内装修",
    ),
    "06": ("煤炭", "煤矿"),
    "47": ("建筑工程", "建筑施工", "工程施工", "房屋建筑", "土建"),
}
