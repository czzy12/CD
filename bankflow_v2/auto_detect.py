from dataclasses import dataclass

import pdfplumber


@dataclass(frozen=True)
class Detection:
    bank_id: str
    label: str
    confidence: int
    reason: str


BANK_LABELS = {
    "abc": "农业银行个人",
    "abc_corp": "农业银行对公",
    "bocom": "交通银行",
    "ccb": "建设银行个人",
    "ccb_corp": "建设银行对公",
    "cmb": "招商银行",
    "cmbc": "民生银行个人",
    "cmbc_corp": "民生银行对公",
    "cib": "兴业银行",
    "icbc": "工商银行个人",
    "icbc_corp": "工商银行对公",
    "psbc": "邮储银行",
    "wechat": "微信流水",
}


def _sample_text(pdf_path: str, max_pages: int = 2) -> str:
    parts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:max_pages]:
            text = page.extract_text() or ""
            parts.append(text)
            for table in page.extract_tables()[:2]:
                for row in table[:4]:
                    parts.append(" ".join(str(cell or "") for cell in row))
    return "\n".join(parts)


def _image_only_reason(pdf_path: str) -> str | None:
    with pdfplumber.open(pdf_path) as pdf:
        pages = pdf.pages[:2]
        if not pages:
            return None

        has_text = False
        has_images = False
        for page in pages:
            if page.chars or (page.extract_text() or "").strip():
                has_text = True
            if page.images:
                has_images = True

    if has_images and not has_text:
        return "PDF为扫描图片，没有可抽取文字层，需要OCR识别后解析"
    return None


def detect_bank_type(pdf_path: str) -> Detection:
    try:
        text = _sample_text(pdf_path)
    except Exception as exc:
        return Detection("", "未识别", 0, f"PDF读取失败: {exc}")

    compact = text.replace(" ", "").replace("\n", "")
    image_only_reason = _image_only_reason(pdf_path)

    if not compact and image_only_reason:
        return Detection("", "图片型PDF", 0, image_only_reason)

    rules = [
        ("icbc_corp", "借/贷借方发生额贷方发生额", 98),
        ("icbc_corp", "凭证号对方账号交易时间借贷标志", 98),
        ("wechat", "微信支付交易明细证明", 98),
        ("wechat", "微信支付账单", 95),
        ("wechat", "交易时间交易类型交易对方商品收/支金额", 95),
        ("abc_corp", "交易时间收入金额支出金额账户余额", 98),
        ("abc", "交易日期交易时间交易摘要交易金额本次余额", 98),
        ("bocom", "交通银行个人客户交易清单", 95),
        ("psbc", "中国邮政储蓄银行借记账户历史明细", 95),
        ("cmb", "TransactionStatementofChinaMerchantsBank", 95),
        ("cmbc", "个人账户对账单客户姓名客户账号", 95),
        ("cmbc", "中国民生银行股份有限公司", 95),
        ("cib", "IndustrialBankTransactionDetails", 95),
        ("cib", "兴业银行交易流水", 95),
        ("ccb_corp", "中国建设银行账户明细信息", 95),
        ("ccb", "中国建设银行个人活期账户全部交易明细", 95),
        ("abc", "中国农业银行银行卡交易明细清单", 95),
        ("abc", "中国农业银行账户活期交易明细清单", 85),
        ("cmbc_corp", "单位账户对账单", 85),
        ("icbc", "中国工商银行账户明细清单", 85),
    ]

    for bank_id, marker, confidence in rules:
        if marker in compact:
            return Detection(bank_id, BANK_LABELS[bank_id], confidence, f"命中关键词: {marker}")

    if "交易时间" in compact and "余额" in compact and "中国工商银行" in compact:
        return Detection("icbc_corp", BANK_LABELS["icbc_corp"], 75, "工商银行表格特征")

    header = "".join((text.splitlines()[:12])).replace(" ", "")
    if "招商银行" in header:
        return Detection("cmb", BANK_LABELS["cmb"], 80, "页眉命中银行名称: 招商银行")

    return Detection("", "未识别", 0, "未适配：未命中已适配银行格式")
