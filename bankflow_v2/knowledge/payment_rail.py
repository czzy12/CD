"""Payment rail boundary rule: payment channels are not business concepts."""

from __future__ import annotations

import re
from collections.abc import Mapping


PAYMENT_RAIL_MARKERS = (
    "财付通",
    "微信支付",
    "微信",
    "支付宝",
    "扫码",
    "二维码",
    "POS",
    "拉卡拉",
    "收钱码",
    "银联",
    "云闪付",
    "快捷支付",
    "网银",
    "手机银行",
    "支付机构",
)

BUSINESS_OBJECT_MARKERS = (
    "公司",
    "集团",
    "商行",
    "经营部",
    "门市部",
    "银行",
    "税务",
    "医院",
    "超市",
    "商店",
    "中心",
    "厂",
    "店",
    "铺",
    "部",
    "馆",
    "城",
    "园",
    "府",
    "坊",
    "站",
    "所",
    "处",
    "局",
    "校",
    "院",
    "堂",
    "庄",
    "社",
    "广场",
    "商场",
    "市场",
    "大厦",
    "酒店",
    "餐厅",
    "饭店",
    "药房",
    "诊所",
    "学校",
    "物业",
    "商户",
    "平台商户",
    "淘宝",
    "京东",
    "天猫",
    "拼多多",
    "抖音",
    "快手",
    "移动",
    "联通",
    "电信",
)

_PAYMENT_INSTITUTION_RE = re.compile(
    r"(?:拉卡拉支付(?:股份有限公司)?|财付通支付科技(?:有限公司)?|"
    r"支付宝(?:\(中国\))?网络技术(?:有限公司)?|银联商务(?:股份有限公司)?|"
    r"微信支付(?:科技有限公司)?)"
)


def is_payment_rail_only(
    fields: Mapping[str, object],
    *,
    business_terms: tuple[str, ...] = (),
) -> bool:
    """True when fields contain payment-rail text without a business object.

    A payment channel/tool/acquirer (微信/支付宝/财付通/扫码/POS/拉卡拉 etc.)
    is transport metadata, not a business concept. When no organization /
    business-object marker is present, the transaction has no business
    semantics and must not be mapped to any business concept.
    """
    text = " ".join(str(value or "") for value in fields.values())
    if not any(marker in text for marker in PAYMENT_RAIL_MARKERS):
        return False
    business_text = _PAYMENT_INSTITUTION_RE.sub("", text)
    business_text = re.sub(r"(?:股份)?有限公司$", "", business_text).strip()
    has_business_object = any(
        marker in business_text for marker in BUSINESS_OBJECT_MARKERS
    ) or any(term in business_text for term in business_terms)
    return not has_business_object
