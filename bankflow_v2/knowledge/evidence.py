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

_OPERATING_MARKERS = (
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

_DIRECT_MARKERS = _DIRECT_STRONG_MARKERS + (
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

_OPERATING_CONCEPT_IDS = frozenset(
    {
        "logistics",
        "warehouse",
        "equipment_maintenance",
        "installation",
        "processing",
        "labor_service",
        "advertising",
        "leasing",
        "decoration",
        "construction",
        "rent",
        "utilities",
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
                _contains(
                    evidence_text,
                    ("货款", "采购", "销售", "批发", "贸易", "收货款", "付货款"),
                )
            )
            return self._result(
                role="direct_business",
                trace="strong" if explicit_strong else "medium",
                reason=(
                    "行业画像确认的经营商品/服务语义命中，判定为直接经营交易"
                    + ("（含货款/采购/销售等强证据）" if explicit_strong else "")
                ),
                fields=fields,
                concept_id=concept,
                source="context_override",
                matched_terms=context_terms,
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
                unresolved_reason=(
                    ""
                    if explicit_business_loan
                    else "financing_business_role_uncertain"
                ),
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
            )

        operating_markers = _contains(evidence_text, _OPERATING_MARKERS)
        if concept in _OPERATING_CONCEPT_IDS or operating_markers:
            medium_families = (
                "rent",
                "utilities",
                "warehouse",
                "logistics",
            )
            family = self._operating_subfamily(evidence_text, concept)
            trace = (
                "medium"
                if family in medium_families or concept in {"rent", "utilities"}
                else "weak"
            )
            return self._result(
                role="operating_expense",
                trace=trace,
                reason=f"经营运营支出（{family}），可支持经营活动存在",
                fields=fields,
                concept_id=concept,
                matched_terms=operating_markers or (concept,),
            )

        direct_markers = _contains(evidence_text, _DIRECT_MARKERS)
        if concept in _DIRECT_CONCEPT_IDS or direct_markers:
            explicit_strong = bool(
                _contains(evidence_text, _DIRECT_STRONG_MARKERS)
            )
            name_only = bool(evidence_text == "" and name_text)
            if explicit_strong and not name_only:
                trace = "strong"
            elif concept in {"goods_payment", "wholesale", "retail"}:
                trace = "medium"
            else:
                trace = "weak"
            return self._result(
                role="direct_business",
                trace=trace,
                reason=(
                    "主营采购/销售/货款等直接经营交易"
                    if explicit_strong
                    else "存在直接经营语义，但缺少明确主营动作/对象"
                ),
                fields=fields,
                concept_id=concept,
                matched_terms=direct_markers or (concept,),
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
            )

        if concept in _UNKNOWN_LIFE_CONCEPT_IDS:
            return self._result(
                role="unknown",
                trace="undetermined",
                reason=f"概念 {concept} 无法确认是否经营证据",
                fields=fields,
                concept_id=concept,
                unresolved_reason=f"concept_{concept}_business_role_uncertain",
            )

        return self._result(
            role="unknown",
            trace="undetermined",
            reason="现有证据不足以判断经营证据角色",
            fields=fields,
            concept_id=concept,
            unresolved_reason="insufficient_evidence",
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
