"""Gate F1.2 shadow contract: Business Evidence Role and Business Trace Strength.

Layer B2 is deliberately independent from Layer B1 (Industry Direct Relation):

    industry_relevance  = how strongly a transaction supports the *declared
                          industry* (strong/medium/weak/none/undetermined)
    business_evidence   = what *role* a transaction plays as evidence that a
                          real business activity exists
    trace_strength      = how strongly the transaction supports business
                          activity existence, independent of the declared
                          industry

This module is shadow-only and must never change legacy_v11 production
behaviour or any prediction-affecting file frozen in production-candidate-v1.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .normalization import compact_text
from .payment_rail import is_payment_rail_only
from .routing import (
    ROUTING_AI_ELIGIBLE_TRANSACTION,
    ROUTING_INSUFFICIENT_TRANSACTION,
    ROUTING_LOCAL_RESOLVED,
)


BUSINESS_EVIDENCE_CONTRACT_VERSION = "business-evidence-contract-v1"
BUSINESS_EVIDENCE_RESOLVER_VERSION = "business-evidence-resolver-v1"

EVIDENCE_ROLES = frozenset(
    {
        "direct_business",
        "operating_expense",
        "tax_regulatory",
        "financing",
        "settlement_infrastructure",
        "employment_operation",
        "government_interaction",
        "personal_consumption",
        "neutral_transfer",
        "unknown",
    }
)

TRACE_STRENGTHS = frozenset(
    {"strong", "medium", "weak", "none", "undetermined"}
)

# Reserved for the future external-evidence boundary. Transaction evidence
# never mixes with these sources inside a single resolution.
EVIDENCE_SOURCES = (
    "transaction",
    "external_business_metadata",
    "government_registry",
    "manual_confirmation",
)

ROLE_ZH = {
    "direct_business": "直接经营交易",
    "operating_expense": "经营运营支出",
    "tax_regulatory": "税务/监管/法定经营义务",
    "financing": "经营融资/借贷",
    "settlement_infrastructure": "经营结算基础设施",
    "employment_operation": "用工经营痕迹",
    "government_interaction": "政府/事业单位往来",
    "personal_consumption": "个人消费/生活支出",
    "neutral_transfer": "纯资金移动/中性转账",
    "unknown": "证据不足",
}


_NAME_FIELDS = ("counterparty_name", "merchant_name")
_EVIDENCE_FIELDS = (
    "summary",
    "remark",
    "purpose",
    "product_description",
    "merchant_category",
)

_TAX_MARKERS = (
    "增值税",
    "企业所得税",
    "城建税",
    "印花税",
    "附加税",
    "代扣代缴",
    "扣税",
    "退税",
    "税务退库",
    "缴税",
    "税款",
    "税费",
)

_LOAN_MARKERS = (
    "经营贷",
    "经营贷款",
    "企业贷款",
    "融资",
    "抵押贷",
    "抵押贷款",
    "贷款放款",
    "放款",
    "还贷",
    "还款",
    "借款",
    "借入",
    "借出",
    "信贷",
)

_EMPLOYMENT_MARKERS = (
    "工资",
    "薪资",
    "薪酬",
    "代发工资",
    "社保",
    "社会保险",
    "公积金",
    "住房公积金",
    "奖金",
    "劳务费",
)

_SETTLEMENT_MARKERS = (
    "企业网银",
    "单位结算卡",
    "结算卡",
    "对公账户",
    "企业账户",
    "账户管理费",
    "账户服务费",
    "银行手续费",
    "年费",
    "开户费",
    "网银",
)

_SETTLEMENT_BUSINESS_HINTS = (
    "企业",
    "对公",
    "单位",
    "结算卡",
    "网银",
    "账户",
)

_OPERATING_LOCAL_MARKERS = (
    "房租",
    "租金",
    "场地",
    "物业费",
    "水电",
    "电费",
    "水费",
    "燃气",
    "仓储",
    "仓库",
    "物流",
    "运费",
    "运输",
    "快递",
)

_OPERATING_AMBIGUOUS_MARKERS = (
    "燃油",
    "油费",
    "设备维修",
    "维修",
    "保养",
    "办公用品",
    "文具",
    "广告",
    "推广",
    "包装",
    "装卸",
    "安装",
    "加工",
    "劳务",
)

_GOVERNMENT_NAME_MARKERS = (
    "税务局",
    "税局",
    "财政局",
    "社保局",
    "医保局",
    "市场监督管理局",
    "行政审批",
    "政务",
    "人民政府",
    "政府",
    "机关",
    "事业单位",
    "人民法院",
    "法院",
    "公安",
    "海关",
    "消防",
    "政府采购",
    "住房公积金管理中心",
)

_DIRECT_STRONG_MARKERS = (
    "货款",
    "采购",
    "批发",
    "销售",
    "商品",
    "货物",
    "订单",
    "材料款",
    "工程款",
    "项目款",
    "购货",
    "进货",
    "出货",
    "收货款",
    "付货款",
    "贸易",
)

_DIRECT_AMBIGUOUS_MARKERS = (
    "服务费",
    "咨询费",
    "代理费",
    "结算款",
)

_NEUTRAL_MARKERS = (
    "转账",
    "转存",
    "转支",
    "微信转账",
    "汇款",
    "跨行汇款",
    "内部转账",
    "红包",
    "提现",
    "卡存",
    "取款",
    "账户互转",
    "同名转账",
    "余额转移",
)

_PERSONAL_MARKERS = (
    "餐饮",
    "饭店",
    "餐厅",
    "美食",
    "外卖",
    "美妆",
    "美容",
    "足浴",
    "按摩",
    "娱乐",
    "KTV",
    "电影",
    "超市",
    "便利店",
    "话费",
    "充值",
    "医疗",
    "医院",
    "药店",
    "打车",
    "出行",
    "酒店",
    "住宿",
    "旅游",
    "购物",
    "服装",
    "鞋帽",
    "黄家龙虾",
)

_PERSONAL_CONCEPT_IDS = frozenset(
    {
        "dining",
        "medical",
        "telecom",
        "ride_hailing",
        "supermarket",
        "convenience_store",
        "food",
        "alcohol",
        "tobacco",
        "furniture",
        "home_appliance",
        "entertainment",
        "personal_care",
        "hotel",
        "travel",
        "clothing",
        "parking",
    }
)

_OPERATING_LOCAL_CONCEPT_IDS = frozenset(
    {"rent", "utilities", "warehouse", "logistics"}
)

_OPERATING_AMBIGUOUS_CONCEPT_IDS = frozenset(
    {
        "equipment_maintenance",
        "installation",
        "processing",
        "labor_service",
        "advertising",
        "leasing",
        "decoration",
        "construction",
        "packaging",
        "equipment",
        "hardware_tools",
        "labor_protection",
        "office_supplies",
        "property_management",
    }
)

_DIRECT_CONCEPT_IDS = frozenset(
    {
        "goods_payment",
        "project_payment",
        "wholesale",
        "retail",
        "raw_material",
        "building_material",
        "sand",
        "cement",
        "coal",
        "metal_products",
        "agricultural_products",
        "goods",
        "generic_trade",
    }
)

_GOVERNMENT_CONCEPT_IDS = frozenset({"government_public_service"})
_UNKNOWN_LIFE_CONCEPT_IDS = frozenset({"bank_fee", "financial_service", "charity"})

# Industry context may promote a normally-personal transaction to a direct
# business transaction, but only when the transaction text matches the
# customer's confirmed products/services. Context is never evidence by itself.
_CONTEXT_MARKET_TERMS: dict[str, tuple[str, ...]] = {
    "51": (
        "铝锭",
        "金属材料",
        "金属矿石",
        "金属制品",
        "废旧金属",
        "石墨",
        "碳素",
        "批发",
        "贸易",
        "货款",
        "采购",
        "销售",
        "商品",
        "货物",
    ),
    "internal.building_material_trade": (
        "建材",
        "建筑材料",
        "砂石",
        "水泥",
        "货款",
        "采购",
        "销售",
        "批发",
        "商品",
        "货物",
    ),
    "internal.alcohol_tobacco_retail": (
        "烟酒",
        "酒水",
        "超市",
        "食品",
        "饮料",
        "货款",
        "采购",
        "销售",
        "批发",
        "商品",
        "货物",
    ),
    "internal.furniture_appliance_sales": (
        "家具",
        "家电",
        "电器",
        "货款",
        "采购",
        "销售",
        "批发",
        "商品",
        "货物",
    ),
    "internal.environmental_engineering": (
        "环保",
        "环境",
        "园林",
        "护栏",
        "塑木",
        "材料",
        "工程",
        "项目",
        "货款",
        "采购",
        "销售",
    ),
    "47": (
        "建筑",
        "施工",
        "工程",
        "项目",
        "材料",
        "劳务",
        "工程款",
        "采购",
    ),
    "06": (
        "煤炭",
        "煤矿",
        "原煤",
        "洗煤",
        "货款",
        "采购",
        "销售",
        "批发",
    ),
}

_OPERATING_SUBFAMILY_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("rent", ("房租", "租金", "场地", "物业费", "lease", "leasing")),
    ("utilities", ("水电", "电费", "水费", "燃气", "utility")),
    ("warehouse", ("仓储", "仓库", "warehouse")),
    ("logistics", ("物流", "运费", "运输", "快递", "logistics")),
    ("equipment", ("设备", "维修", "保养", "equipment")),
    ("office", ("办公用品", "文具", "office")),
    ("advertising", ("广告", "推广", "advertising")),
    ("packaging", ("包装", "packaging")),
    ("labor", ("装卸", "劳务", "安装", "加工", "labor")),
)


def _joined(fields: Mapping[str, object]) -> tuple[str, str]:
    name_text = " ".join(
        str(fields[name] or "")
        for name in _NAME_FIELDS
        if str(fields.get(name, "") or "").strip()
    )
    evidence_text = " ".join(
        str(fields[name] or "")
        for name in _EVIDENCE_FIELDS
        if str(fields.get(name, "") or "").strip()
    )
    return evidence_text, name_text


def _contains(text: str, markers: tuple[str, ...]) -> tuple[str, ...]:
    compact = compact_text(text)
    return tuple(
        dict.fromkeys(
            marker for marker in markers if compact_text(marker) in compact
        )
    )


def _profile_industry_ids(profile: Any) -> tuple[str, ...]:
    if profile is None:
        return ()
    primary = tuple(str(item) for item in getattr(profile, "primary_industry_ids", ()))
    secondary = tuple(
        str(item) for item in getattr(profile, "secondary_industry_ids", ())
    )
    return tuple(dict.fromkeys((*primary, *secondary)))


def _context_direct_match(
    fields: Mapping[str, object],
    profile: Any,
) -> tuple[str, ...]:
    if profile is None:
        return ()
    evidence_text, name_text = _joined(fields)
    text = evidence_text + " " + name_text
    matched: list[str] = []
    for industry_id in _profile_industry_ids(profile):
        terms = _CONTEXT_MARKET_TERMS.get(industry_id, ())
        if terms:
            found = _contains(text, terms)
            if found:
                matched.extend(found)
    return tuple(dict.fromkeys(matched))


class BusinessEvidenceResolver:
    """Local deterministic Layer B2 resolver (shadow only, no AI by default)."""

    version = BUSINESS_EVIDENCE_RESOLVER_VERSION

    def resolve(
        self,
        fields: Mapping[str, object],
        *,
        concept_id: str = "",
        direction: str = "",
        profile: Any = None,
        case_context: Mapping[str, object] | None = None,
    ) -> dict[str, Any]:
        """Return a transaction-level business evidence resolution."""
        evidence_text, name_text = _joined(fields)
        combined = evidence_text + " " + name_text
        concept = str(concept_id or "")
        direction = str(direction or "")

        if not evidence_text and not name_text:
            return self._result(
                role="unknown",
                trace="undetermined",
                reason="无语义证据字段",
                fields=fields,
                concept_id=concept,
                unresolved_reason="no_semantic_evidence",
                routing=ROUTING_INSUFFICIENT_TRANSACTION,
            )

        business_terms = ()
        if profile is not None:
            for industry_id in _profile_industry_ids(profile):
                business_terms = (
                    *business_terms,
                    *_CONTEXT_MARKET_TERMS.get(industry_id, ()),
                )
        if is_payment_rail_only(
            fields,
            business_terms=tuple(dict.fromkeys(business_terms)),
        ):
            return self._result(
                role="neutral_transfer",
                trace="undetermined",
                reason="仅支付渠道/收单语义，无独立经营业务对象",
                fields=fields,
                concept_id=concept,
                source="payment_rail_only",
                unresolved_reason="payment_rail_only",
                routing=ROUTING_LOCAL_RESOLVED,
                matched_terms=tuple(
                    marker
                    for marker in (
                        "财付通",
                        "微信支付",
                        "支付宝",
                        "扫码",
                        "POS",
                        "拉卡拉",
                        "银联",
                        "网银",
                    )
                    if marker in combined
                ),
            )

        context_terms = _context_direct_match(fields, profile)
        if context_terms:
            explicit_strong = bool(
                evidence_text
                and _contains(evidence_text, _DIRECT_STRONG_MARKERS)
            )
            concept_direct = concept in _DIRECT_CONCEPT_IDS
            if explicit_strong or (concept_direct and evidence_text):
                return self._result(
                    role="direct_business",
                    trace="strong" if explicit_strong else "medium",
                    reason=(
                        "行业画像确认的经营商品/服务语义命中，判定为直接经营交易"
                        + ("（含货款/采购/销售等强证据）" if explicit_strong else "")
                    ),
                    fields=fields,
                    concept_id=concept,
                    source="context_override_local",
                    matched_terms=context_terms,
                    routing=ROUTING_LOCAL_RESOLVED,
                )
            return self._result(
                role="direct_business",
                trace="weak",
                reason="行业画像语义命中但缺少明确经营动作/对象，需要上下文判断",
                fields=fields,
                concept_id=concept,
                source="context_hint_ai_eligible",
                matched_terms=context_terms,
                unresolved_reason="direct_business_context_dependent",
                routing=ROUTING_AI_ELIGIBLE_TRANSACTION,
            )

        personal_markers = _contains(combined, _PERSONAL_MARKERS)
        if concept in _PERSONAL_CONCEPT_IDS or personal_markers:
            return self._result(
                role="personal_consumption",
                trace="none",
                reason="明显个人/生活消费语义，且无经营上下文支持",
                fields=fields,
                concept_id=concept,
                matched_terms=(
                    (concept,) if concept in _PERSONAL_CONCEPT_IDS else personal_markers
                ),
                routing=ROUTING_LOCAL_RESOLVED,
            )

        tax_markers = _contains(evidence_text, _TAX_MARKERS)
        if tax_markers:
            return self._result(
                role="tax_regulatory",
                trace="medium",
                reason="税务/监管类交易可证明持续经营/纳税活动，但不能单独证明申报行业",
                fields=fields,
                concept_id=concept,
                matched_terms=tax_markers,
                routing=ROUTING_LOCAL_RESOLVED,
            )

        loan_markers = _contains(evidence_text, _LOAN_MARKERS)
        if loan_markers:
            explicit_business_loan = bool(
                _contains(
                    evidence_text,
                    ("经营贷", "经营贷款", "企业贷款", "融资", "抵押贷", "抵押贷款", "贷款放款"),
                )
            )
            return self._result(
                role="financing",
                trace="medium" if explicit_business_loan else "weak",
                reason=(
                    "融资/借贷交易可支持经营活动存在，但不自动证明主营行业"
                    if explicit_business_loan
                    else "仅见借款/还款，无法确认是否经营融资"
                ),
                fields=fields,
                concept_id=concept,
                matched_terms=loan_markers,
                unresolved_reason="financing_context_dependent",
                routing=ROUTING_AI_ELIGIBLE_TRANSACTION,
            )

        employment_markers = _contains(evidence_text, _EMPLOYMENT_MARKERS)
        if employment_markers:
            return self._result(
                role="employment_operation",
                trace="medium",
                reason="工资/社保/公积金等用工支出可证明稳定雇佣经营活动",
                fields=fields,
                concept_id=concept,
                matched_terms=employment_markers,
                routing=ROUTING_LOCAL_RESOLVED,
            )

        settlement_markers = _contains(evidence_text, _SETTLEMENT_MARKERS)
        settlement_business_hint = bool(
            _contains(combined, _SETTLEMENT_BUSINESS_HINTS)
        )
        if settlement_markers and settlement_business_hint:
            return self._result(
                role="settlement_infrastructure",
                trace="weak",
                reason="企业/对公结算基础设施费用，属于弱经营痕迹",
                fields=fields,
                concept_id=concept,
                matched_terms=settlement_markers,
                routing=ROUTING_LOCAL_RESOLVED,
            )

        operating_local_markers = _contains(
            evidence_text,
            _OPERATING_LOCAL_MARKERS,
        )
        operating_ambiguous_markers = _contains(
            evidence_text,
            _OPERATING_AMBIGUOUS_MARKERS,
        )
        if (
            operating_local_markers
            or concept in _OPERATING_LOCAL_CONCEPT_IDS
        ):
            family = self._operating_subfamily(evidence_text, concept)
            return self._result(
                role="operating_expense",
                trace="medium",
                reason=f"经营运营支出（{family}），可支持经营活动存在",
                fields=fields,
                concept_id=concept,
                matched_terms=operating_local_markers or (concept,),
                routing=ROUTING_LOCAL_RESOLVED,
            )
        if (
            operating_ambiguous_markers
            or concept in _OPERATING_AMBIGUOUS_CONCEPT_IDS
        ):
            family = self._operating_subfamily(evidence_text, concept)
            return self._result(
                role="operating_expense",
                trace="weak",
                reason=(
                    f"疑似经营运营支出（{family}），但需上下文区分经营/个人用途"
                ),
                fields=fields,
                concept_id=concept,
                matched_terms=operating_ambiguous_markers or (concept,),
                unresolved_reason="operating_context_dependent",
                routing=ROUTING_AI_ELIGIBLE_TRANSACTION,
            )

        direct_strong_markers = _contains(
            evidence_text,
            _DIRECT_STRONG_MARKERS,
        )
        direct_ambiguous_markers = _contains(
            evidence_text,
            _DIRECT_AMBIGUOUS_MARKERS,
        )
        name_only = bool(evidence_text == "" and name_text)
        if direct_strong_markers and not name_only:
            return self._result(
                role="direct_business",
                trace="strong",
                reason="明确主营采购/销售/货款等直接经营交易",
                fields=fields,
                concept_id=concept,
                matched_terms=direct_strong_markers,
                routing=ROUTING_LOCAL_RESOLVED,
            )
        if (
            concept in {"goods_payment", "project_payment", "wholesale", "retail"}
            and evidence_text
        ):
            return self._result(
                role="direct_business",
                trace="medium",
                reason="语义概念明确指向直接经营交易",
                fields=fields,
                concept_id=concept,
                matched_terms=(concept,),
                routing=ROUTING_LOCAL_RESOLVED,
            )
        if direct_ambiguous_markers or concept in _DIRECT_CONCEPT_IDS:
            return self._result(
                role="direct_business",
                trace="weak",
                reason="存在直接经营候选语义，但需上下文确认角色与强度",
                fields=fields,
                concept_id=concept,
                matched_terms=direct_ambiguous_markers or (concept,),
                unresolved_reason="direct_business_context_dependent",
                routing=ROUTING_AI_ELIGIBLE_TRANSACTION,
            )

        government_name_markers = _contains(name_text, _GOVERNMENT_NAME_MARKERS)
        if government_name_markers and not _contains(
            evidence_text,
            _PERSONAL_MARKERS,
        ):
            return self._result(
                role="government_interaction",
                trace="weak",
                reason="与政府/事业单位往来，但仅有机构名称，不能单独确认经营作用",
                fields=fields,
                concept_id=concept,
                matched_terms=government_name_markers,
                unresolved_reason="government_role_uncertain",
                routing=ROUTING_AI_ELIGIBLE_TRANSACTION,
            )

        neutral_markers = _contains(evidence_text, _NEUTRAL_MARKERS)
        if neutral_markers:
            return self._result(
                role="neutral_transfer",
                trace="undetermined",
                reason="纯资金移动，当前证据不能确认经营作用",
                fields=fields,
                concept_id=concept,
                matched_terms=neutral_markers,
                unresolved_reason="neutral_transfer",
                routing=ROUTING_LOCAL_RESOLVED,
            )

        if concept in _UNKNOWN_LIFE_CONCEPT_IDS:
            routing = (
                ROUTING_AI_ELIGIBLE_TRANSACTION
                if concept in {"bank_fee", "financial_service"}
                else ROUTING_INSUFFICIENT_TRANSACTION
            )
            return self._result(
                role="unknown",
                trace="undetermined",
                reason=f"概念 {concept} 无法确认是否经营证据",
                fields=fields,
                concept_id=concept,
                unresolved_reason=f"concept_{concept}_business_role_uncertain",
                routing=routing,
            )

        return self._result(
            role="unknown",
            trace="undetermined",
            reason="存在语义但本地无法稳定判断经营证据角色，需要上下文/推理",
            fields=fields,
            concept_id=concept,
            unresolved_reason="context_dependent_unknown",
            routing=ROUTING_AI_ELIGIBLE_TRANSACTION,
        )

    def _result(
        self,
        *,
        role: str,
        trace: str,
        reason: str,
        fields: Mapping[str, object],
        concept_id: str,
        source: str = "local_rule",
        matched_terms: tuple[str, ...] = (),
        unresolved_reason: str = "",
        routing: str = ROUTING_INSUFFICIENT_TRANSACTION,
    ) -> dict[str, Any]:
        return {
            "role": role,
            "role_zh": ROLE_ZH.get(role, role),
            "trace_strength": trace,
            "role_source": source,
            "reason": reason,
            "evidence_group_key": self._evidence_group_key(role, fields, concept_id),
            "matched_terms": list(dict.fromkeys(matched_terms)),
            "unresolved_reason": unresolved_reason,
            "routing_state": routing,
            "evidence_source": "transaction",
            "resolver_version": self.version,
        }

    @staticmethod
    def _operating_subfamily(
        evidence_text: str,
        concept_id: str,
    ) -> str:
        for family, terms in _OPERATING_SUBFAMILY_TERMS:
            if _contains(evidence_text, terms):
                return family
        if concept_id in {
            "rent",
            "utilities",
            "warehouse",
            "logistics",
            "equipment",
            "office_supplies",
            "advertising",
            "packaging",
            "labor_service",
        }:
            return concept_id
        return "operating"

    @staticmethod
    def _evidence_group_key(
        role: str,
        fields: Mapping[str, object],
        concept_id: str,
    ) -> str:
        if role == "direct_business":
            subfamily = concept_id or "trade"
        elif role == "operating_expense":
            evidence_text, _ = _joined(fields)
            subfamily = BusinessEvidenceResolver._operating_subfamily(
                evidence_text,
                concept_id,
            )
        elif role == "personal_consumption":
            subfamily = concept_id or "personal"
        else:
            subfamily = {
                "tax_regulatory": "tax",
                "financing": "financing",
                "settlement_infrastructure": "settlement",
                "employment_operation": "employment",
                "government_interaction": "government",
                "neutral_transfer": "transfer",
                "unknown": "unknown",
            }.get(role, role)
        return f"{role}|{subfamily}"


# Gate F1.3 audit registry: every decision path in the local resolver.
# Classification values: KEEP_LOCAL / AI_ELIGIBLE / REMOVE_OR_RESTRICT.
RULE_REGISTRY: list[dict[str, Any]] = [
    {
        "rule_id": "evidence_missing",
        "role": "unknown",
        "trigger": "无语义证据字段",
        "current_behavior": "unknown / undetermined",
        "classification": "KEEP_LOCAL",
        "routing_state": "insufficient_transaction",
        "reason": "无证据时无需 AI，直接 unresolved",
        "precision_risk": "low",
        "context_dependency": "none",
    },
    {
        "rule_id": "payment_rail_only",
        "role": "neutral_transfer",
        "trigger": "仅支付渠道/收单语义（微信/支付宝/财付通/POS/云闪付）",
        "current_behavior": "neutral_transfer / undetermined",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "支付渠道是传输元数据，不能形成经营 role",
        "precision_risk": "low",
        "context_dependency": "none",
    },
    {
        "rule_id": "context_override_strong",
        "role": "direct_business",
        "trigger": "行业画像商品/服务语义命中 + 明确货款/采购/销售等强标记",
        "current_behavior": "direct_business strong/medium",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "行业上下文 + 明确经营动作，属于高精度确定性组合",
        "precision_risk": "low-medium",
        "context_dependency": "industry context required but deterministic",
    },
    {
        "rule_id": "context_hint",
        "role": "direct_business",
        "trigger": "行业画像语义命中但缺少明确经营动作/对象（如仅商户名）",
        "current_behavior": "direct_business weak candidate",
        "classification": "REMOVE_OR_RESTRICT",
        "routing_state": "ai_eligible_transaction",
        "reason": "仅实体名/上下文提示不足以本地定稿，需推理",
        "precision_risk": "medium",
        "context_dependency": "high",
    },
    {
        "rule_id": "personal_explicit",
        "role": "personal_consumption",
        "trigger": "明确餐饮/足浴/美妆/娱乐等生活消费语义",
        "current_behavior": "personal_consumption / none",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "无经营上下文时生活消费高置信",
        "precision_risk": "low",
        "context_dependency": "low",
    },
    {
        "rule_id": "tax_explicit",
        "role": "tax_regulatory",
        "trigger": "明确增值税/企业所得税/城建税/纳税/税务退库等",
        "current_behavior": "tax_regulatory / medium",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "税费事实确定性高；不决定行业一致性",
        "precision_risk": "low",
        "context_dependency": "low",
    },
    {
        "rule_id": "financing_loan",
        "role": "financing",
        "trigger": "贷款/借款/融资/还贷等",
        "current_behavior": "financing weak/medium candidate",
        "classification": "REMOVE_OR_RESTRICT",
        "routing_state": "ai_eligible_transaction",
        "reason": "借款可能是个人/股东往来/临时拆借，不能本地定稿经营融资",
        "precision_risk": "medium",
        "context_dependency": "high",
    },
    {
        "rule_id": "employment_explicit",
        "role": "employment_operation",
        "trigger": "明确工资/社保/公积金/代发工资",
        "current_behavior": "employment_operation / medium",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "用工支出事实确定性高；role 与 case conclusion 分离",
        "precision_risk": "low",
        "context_dependency": "low",
    },
    {
        "rule_id": "settlement_explicit",
        "role": "settlement_infrastructure",
        "trigger": "企业网银/单位结算卡/企业账户管理费",
        "current_behavior": "settlement_infrastructure / weak",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "明确企业结算基础设施费用",
        "precision_risk": "low",
        "context_dependency": "low",
    },
    {
        "rule_id": "operating_local",
        "role": "operating_expense",
        "trigger": "明确房租/水电/仓储/物流/运输",
        "current_behavior": "operating_expense / medium",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "明确经营场地/能源/物流支出",
        "precision_risk": "low",
        "context_dependency": "low",
    },
    {
        "rule_id": "operating_ambiguous",
        "role": "operating_expense",
        "trigger": "燃油/维修/广告/办公用品/安装/加工/劳务等",
        "current_behavior": "operating_expense weak candidate",
        "classification": "REMOVE_OR_RESTRICT",
        "routing_state": "ai_eligible_transaction",
        "reason": "可能属个人用途（车辆/家居），需上下文区分",
        "precision_risk": "medium",
        "context_dependency": "high",
    },
    {
        "rule_id": "direct_local_strong",
        "role": "direct_business",
        "trigger": "明确货款/采购/销售/批发/商品/货物/工程款/材料款",
        "current_behavior": "direct_business / strong",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "明确直接经营交易事实",
        "precision_risk": "low",
        "context_dependency": "low",
    },
    {
        "rule_id": "direct_concept_medium",
        "role": "direct_business",
        "trigger": "语义概念明确为 goods_payment/project_payment/wholesale/retail 且有证据文本",
        "current_behavior": "direct_business / medium",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "已批准语义概念 + 证据文本，确定性较高",
        "precision_risk": "low-medium",
        "context_dependency": "low",
    },
    {
        "rule_id": "direct_ambiguous",
        "role": "direct_business",
        "trigger": "服务费/咨询费/代理费/结算款或仅直接概念名称",
        "current_behavior": "direct_business weak candidate",
        "classification": "REMOVE_OR_RESTRICT",
        "routing_state": "ai_eligible_transaction",
        "reason": "服务费/企业名称本身含义宽泛，需上下文",
        "precision_risk": "medium",
        "context_dependency": "high",
    },
    {
        "rule_id": "government_name",
        "role": "government_interaction",
        "trigger": "税务局/财政局/机关/事业单位等机构名称",
        "current_behavior": "government_interaction weak candidate",
        "classification": "REMOVE_OR_RESTRICT",
        "routing_state": "ai_eligible_transaction",
        "reason": "机构往来性质需理解，不能无条件视为经营",
        "precision_risk": "medium",
        "context_dependency": "high",
    },
    {
        "rule_id": "neutral_transfer",
        "role": "neutral_transfer",
        "trigger": "转账/转存/提现/红包等纯资金移动",
        "current_behavior": "neutral_transfer / undetermined",
        "classification": "KEEP_LOCAL",
        "routing_state": "local_resolved",
        "reason": "纯资金移动不构成经营证据，无需 AI",
        "precision_risk": "low",
        "context_dependency": "low",
    },
    {
        "rule_id": "concept_bank_fee_financial",
        "role": "unknown",
        "trigger": "bank_fee / financial_service 概念",
        "current_behavior": "unknown / undetermined",
        "classification": "AI_ELIGIBLE",
        "routing_state": "ai_eligible_transaction",
        "reason": "银行费用/金融服务需上下文判断是否经营结算",
        "precision_risk": "medium",
        "context_dependency": "high",
    },
    {
        "rule_id": "concept_charity",
        "role": "unknown",
        "trigger": "charity 概念",
        "current_behavior": "unknown / undetermined",
        "classification": "KEEP_LOCAL",
        "routing_state": "insufficient_transaction",
        "reason": "公益捐赠不自动构成经营证据，直接 unresolved 无需 AI",
        "precision_risk": "low",
        "context_dependency": "low",
    },
    {
        "rule_id": "final_unknown_with_evidence",
        "role": "unknown",
        "trigger": "有语义但本地无稳定 role 规则",
        "current_behavior": "unknown / undetermined",
        "classification": "AI_ELIGIBLE",
        "routing_state": "ai_eligible_transaction",
        "reason": "存在语义但本地无法判断，应进入 AI/上下文推理",
        "precision_risk": "low (no forced role)",
        "context_dependency": "high",
    },
]
