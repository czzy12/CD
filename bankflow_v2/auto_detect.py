from dataclasses import dataclass
import re

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
    "alipay": "支付宝交易流水",
    "boc": "中国银行个人",
    "boc_corp": "中国银行对公",
    "bocom": "交通银行",
    "bocom_corp": "交通银行对公",
    "bazhou_shunfeng_corp": "霸州舜丰村镇银行对公",
    "ccb": "建设银行个人",
    "ccb_corp": "建设银行对公",
    "changsha_bank_corp": "长沙银行对公",
    "chengdu_rural_corp": "成都农村商业银行对公",
    "chongqing": "重庆银行",
    "cmb": "招商银行",
    "cmb_corp": "招商银行对公",
    "citic": "中信银行个人",
    "citic_corp": "中信银行对公",
    "customer_account_corp": "农村商业银行对公",
    "customer_detail_corp": "对公客户账户明细",
    "everbright": "中国光大银行个人",
    "everbright_corp": "中国光大银行对公",
    "foshan_rural": "佛山农村商业银行",
    "fudian": "富滇银行",
    "guilin": "桂林银行个人",
    "guilin_corp": "桂林银行对公",
    "hebei_corp_detail": "河北银行对公",
    "hebei_personal": "河北银行个人",
    "huishang_corp": "徽商银行对公",
    "huaxia": "华夏银行",
    "huaxia_corp": "华夏银行对公",
    "jiujiang": "九江银行",
    "lanzhou": "兰州银行",
    "luzhou": "泸州银行个人",
    "nanjing_corp": "南京银行对公",
    "ningbo": "宁波银行",
    "mybank_corp": "浙江网商银行对公",
    "pingan": "平安银行",
    "cmbc": "民生银行个人",
    "cmbc_corp": "民生银行对公",
    "cib": "兴业银行",
    "icbc": "工商银行个人",
    "icbc_corp": "工商银行对公",
    "psbc": "邮储银行",
    "qilu_corp": "齐鲁银行对公",
    "rural_credit": "农村信用社",
    "rural_commercial": "农村商业银行个人",
    "shanghai": "上海银行个人",
    "shanghai_corp": "上海银行对公",
    "shengjing": "盛京银行",
    "spdb": "上海浦东发展银行个人",
    "spdb_corp": "上海浦东发展银行对公",
    "tianjin_bank": "天津银行个人",
    "tianjin_rural": "天津农村商业银行个人",
    "tianjin_rural_corp": "天津农村商业银行对公",
    "generic_pdf": "通用PDF识别",
    "wechat": "微信流水",
    "xingtai": "邢台银行",
    "zhongyuan": "中原银行",
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


def _has_ordered_chars(text: str, phrase: str, max_gap: int = 80) -> bool:
    position = -1
    for char in phrase:
        next_position = text.find(char, position + 1)
        if next_position == -1:
            return False
        if position != -1 and next_position - position > max_gap:
            return False
        position = next_position
    return True


def _rural_commercial_label(text: str) -> str:
    match = re.search(r"([\u4e00-\u9fa5]{2,20}农村商业银行)", text)
    if match:
        return f"{match.group(1)}个人"
    return BANK_LABELS["rural_commercial"]


def detect_bank_type(pdf_path: str) -> Detection:
    try:
        text = _sample_text(pdf_path)
    except Exception as exc:
        return Detection("", "未识别", 0, f"PDF读取失败: {exc}")

    compact = text.replace(" ", "").replace("\n", "")
    image_only_reason = _image_only_reason(pdf_path)

    if not compact and image_only_reason:
        return Detection("", "图片型PDF", 0, image_only_reason)

    header_text = "\n".join(text.splitlines()[:80])
    header_compact = header_text.replace(" ", "").replace("\n", "")
    if (
        "霸州舜丰村镇银行企业账户交易明细" in header_compact
        and "汇出金额汇入金额余额摘要用途" in compact
    ):
        return Detection("bazhou_shunfeng_corp", BANK_LABELS["bazhou_shunfeng_corp"], 98, "命中霸州舜丰村镇银行企业账户交易明细")

    if (
        "交易明细记录" in header_compact
        and "收支标识" in header_compact
        and "交易日期交易金额借贷标志交易后余额" in compact
        and "交易对手账号交易对手名称交易对手开户行摘要备注" in compact
    ):
        return Detection("hebei_corp_detail", BANK_LABELS["hebei_corp_detail"], 98, "命中河北银行对公交易明细记录")

    if (
        "账户历史交易明细清单" in header_compact
        and "客户账号" in compact
        and "账户名称" in compact
        and "交易日期借贷交易金额账户余额" in compact
        and "对方账户对方户名流水号摘要备注" in compact
    ):
        return Detection("hebei_personal", BANK_LABELS["hebei_personal"], 96, "命中河北银行个人账户历史交易明细清单")

    if (
        "徽商银行" in header_compact
        and "账户交易明细" in header_compact
        and "账户/户名" in header_compact
        and "交易时间收入金额支出金额账户余额对方账号对方户名对方开户行用途流水号附言摘要" in compact
    ):
        return Detection("huishang_corp", BANK_LABELS["huishang_corp"], 98, "命中徽商银行账户交易明细")

    if (
        "泸州银行账户历史明细清单" in header_compact
        and "客户名称" in header_compact
        and "总条数" in header_compact
        and "序号交易时间币种交易金额账户余额对方账号对方户名交易类型摘要交易渠道" in compact
    ):
        return Detection("luzhou", BANK_LABELS["luzhou"], 98, "命中泸州银行账户历史明细清单")

    if (
        "富滇银行交易流水" in header_compact
        and "FudianBankTransactionDetails" in header_compact
        and all(
            marker in compact
            for marker in (
                "序号SerialNumber",
                "交易日期TradingDate",
                "交易金额TradingAmount",
                "账户余额AccountBalance",
                "对方账号CounterpartyAccount",
                "对方户名CounterpartyName",
                "摘要描述TradingDescription",
                "备注Remark",
            )
        )
    ):
        return Detection("fudian", BANK_LABELS["fudian"], 98, "命中富滇银行个人交易流水九列表格")

    if (
        "河北省农村信用社联合社账户历史明细清单" in header_compact
        and "账号" in header_compact
        and "户名" in header_compact
        and "总条数" in header_compact
        and "序号交易日期交易金额金额对方户名对方账号摘要网点来源" in compact
    ):
        return Detection("rural_credit", BANK_LABELS["rural_credit"], 98, "命中河北省农村信用社账户历史明细清单")

    if (
        "天津银行个人账户交易明细清单" in header_compact
        and "户名" in header_compact
        and "账号" in header_compact
        and "序号交易日期交易金额余额交易摘要附言" in compact
    ):
        return Detection("tianjin_bank", BANK_LABELS["tianjin_bank"], 98, "命中天津银行个人账户交易明细清单")

    if (
        "天津农商银行账户交易明细" in header_compact
        and "交易日期交易时间交易摘要交易金额当前余额交易附言对手户名对手账号交易渠道" in compact
    ):
        return Detection("tianjin_rural", BANK_LABELS["tianjin_rural"], 98, "命中天津农商银行个人账户交易明细")

    if (
        "单位账户明细对账单" in header_compact
        and "账户名称" in header_compact
        and "客户账号" in header_compact
        and "账单期初余额" in header_compact
        and "账单期末余额" in header_compact
        and "交易日期交易金额账户余额摘要/备注编号" in compact
    ):
        return Detection("changsha_bank_corp", BANK_LABELS["changsha_bank_corp"], 98, "命中长沙银行单位账户明细对账单")

    if (
        "明细账查询" in compact
        and "交易日期" in compact
        and "支出金额" in compact
        and "收入金额" in compact
        and "账户余额" in compact
        and "交易名称" in compact
        and "对方账号" in compact
        and "对方户名" in compact
    ):
        return Detection("generic_pdf", BANK_LABELS["generic_pdf"], 92, "命中明细账查询通用表格")

    if (
        "用户所属公司" in header_compact
        and "记录数" in header_compact
        and "交易日期借方(出账)贷方(入账)余额摘要" in compact
        and "收(付)方名称" in compact
        and "收(付)方账号" in compact
        and "交易类型" in compact
    ):
        return Detection("cmb_corp", BANK_LABELS["cmb_corp"], 98, "命中招商银行对公借贷余额明细")

    if (
        "对公客户账户明细" in header_compact
        and "客户名称" in header_compact
        and "交易日期交易发生金额账户余额对方账号对方户名摘要备注" in compact
        and "借方合计笔数" in compact
        and "贷方合计笔数" in compact
    ):
        return Detection("customer_detail_corp", BANK_LABELS["customer_detail_corp"], 96, "命中对公客户账户明细")

    if (
        "TransactionStatementofChinaEverbrightBank" in compact
        and "TransAmtDr" in compact
        and "TransAmtCr" in compact
        and "AccountBalance" in compact
    ):
        return Detection("everbright", BANK_LABELS["everbright"], 98, "命中中国光大银行个人账户明细查询清单")

    if (
        "光大" in compact
        and "对公" in compact
        and "借方发生额" in compact
        and "贷方发生额" in compact
        and "借方笔数" in compact
        and "贷方笔数" in compact
        and "序号交易日期时间借/贷交易金额账户余额" in compact
    ):
        return Detection("everbright_corp", BANK_LABELS["everbright_corp"], 98, "命中中国光大银行对公账户对账单")

    if _has_ordered_chars(header_compact, "兴业银行交易流水"):
        return Detection("cib", BANK_LABELS["cib"], 95, "页眉命中银行名称: 兴业银行交易流水")
    if "BankTransactionDetails" in compact and "兴业" in compact and "支出" in compact and "收入" in compact:
        return Detection("cib", BANK_LABELS["cib"], 92, "命中兴业银行交易明细强水印格式")
    if (
        "中国银行" in header_compact
        and "单位人民币活期" in header_compact
        and "借方发生额" in compact
        and "贷方发生额" in compact
        and "承前页余额" in compact
    ):
        return Detection("boc_corp", BANK_LABELS["boc_corp"], 98, "命中中国银行对公活期明细特征")

    if (
        "中国银行交易流水明细清单" in header_compact
        and "记账日期记账时间币别金额余额交易名称" in compact
        and "借记卡号" in compact
    ):
        return Detection("boc", BANK_LABELS["boc"], 98, "命中中国银行个人交易流水明细清单")

    if (
        "中国邮政储蓄银行账户交易明细专用回单" in header_compact
        and "支出金额收入金额余额" in compact
    ):
        return Detection("psbc", BANK_LABELS["psbc"], 98, "命中邮储对公账户交易明细专用回单特征")

    if (
        "中国工商银行账户明细清单" in header_compact
        and "本方账号户名" in compact
        and "转入金额" in compact
        and "转出金额" in compact
        and "余额" in compact
    ):
        return Detection("icbc_corp", BANK_LABELS["icbc_corp"], 98, "命中工商银行对公账户明细清单")

    if (
        "交通银行四川省分行明细对账单" in header_compact
        and "会计日期交易日期交易名称" in compact
        and "借方发生额贷方发生额余额" in compact
    ):
        return Detection("bocom_corp", BANK_LABELS["bocom_corp"], 98, "命中交通银行对公明细对账单")

    if (
        "交通银行" in header_compact
        and "明细对账单" in header_compact
        and "会计日期交易日期交易名称" in compact
        and "借方发生额贷方发生额余额" in compact
    ):
        return Detection("bocom_corp", BANK_LABELS["bocom_corp"], 98, "命中交通银行对公明细对账单")

    if (
        ("账户明细对账单" in header_compact or "账户明细查询" in header_compact)
        and (
            "上海银行" in compact
            or "交易流水号交易时间记账日期交易方向" in compact
            or "序号交易时间借方金额贷方金额余额" in compact
        )
        and (("借方金额贷方金额余额" in compact) or ("借方发生额贷方发生额余额" in compact))
    ):
        return Detection("shanghai_corp", BANK_LABELS["shanghai_corp"], 98, "命中上海银行对公账户明细")

    if "上海银行交易明细" in header_compact and "TransactionDetails" in compact and "交易金额期末金额" in compact:
        return Detection("shanghai", BANK_LABELS["shanghai"], 98, "命中上海银行个人交易明细")

    if "支付宝支付科技有限公司交易流水证明" in compact and "收/支交易对方商品说明收/付款方式金额" in compact:
        return Detection("alipay", BANK_LABELS["alipay"], 98, "命中支付宝交易流水证明")

    if "盛京银行交易流水" in header_compact and "TransactionStatementofShengjingBank" in compact:
        return Detection("shengjing", BANK_LABELS["shengjing"], 98, "命中盛京银行交易流水")

    if "邢台银行账户交易明细" in header_compact and "收入/支出交易金额（元）余额（元）" in compact:
        return Detection("xingtai", BANK_LABELS["xingtai"], 98, "命中邢台银行账户交易明细")

    if "中国建设银行账户明细信息" in header_compact and "借方发生额(支取)贷方发生额(收入)余额" in compact:
        return Detection("ccb_corp", BANK_LABELS["ccb_corp"], 98, "命中建设银行账户明细信息对公表格")

    if "兴业银行交易明细" in compact and "IndustrialBankTransactionDetails" in compact:
        return Detection("cib", BANK_LABELS["cib"], 96, "命中兴业银行交易明细强水印格式")

    if (
        "华夏银行个人账户交易流水" in header_compact
        and "HuaxiaBankPersonalTransactionStatement" in compact
        and "交易金额余额" in compact
    ):
        return Detection("huaxia", BANK_LABELS["huaxia"], 98, "命中华夏银行个人账户交易流水电子版")

    if (
        "账号：" in header_compact
        and "账户名称：" in header_compact
        and "查询日期：" in header_compact
        and "交易方向：全部" in header_compact
        and "排序方向：由近及远" in header_compact
        and "序号交易日期交易时间支出金额收入金额余额对方账号对方户名对方行名核心流水号交易描述摘要凭证号码明细标注记账日期" in compact
    ):
        return Detection("huaxia_corp", BANK_LABELS["huaxia_corp"], 96, "命中华夏银行对公交易明细十五列表格")

    if (
        "平安银行个人账户交易明细清单" in compact
        and "TransactionDetailsListofPersonalAccountofPinganBank" in compact
        and "交易金额余额交易地点摘要" in compact
    ):
        return Detection("pingan", BANK_LABELS["pingan"], 98, "命中平安银行个人账户交易明细清单")

    if (
        "清单编号" in compact
        and "ListNumber" in compact
        and "交易金额余额交易地点摘要备注" in compact
        and "CounterpartyInformation" in compact
    ):
        return Detection("pingan", BANK_LABELS["pingan"], 92, "命中平安银行个人账户交易明细清单续页")

    if "平安银行" in compact and "清单编号" in compact and "交易金额余额交易地点摘要备注" in compact:
        return Detection("pingan", BANK_LABELS["pingan"], 90, "命中平安银行交易明细清单表格")

    if "兴业银行交易明细" in compact and "交易金额" in compact and "账户余额" in compact:
        return Detection("cib", BANK_LABELS["cib"], 92, "命中兴业银行交易明细表格")

    if (
        "账户交易明细" in header_compact
        and "柜员交易号" in compact
        and "动账资金分簿" in compact
        and "借方发生额" in compact
        and "贷方发生额" in compact
        and "余额" in compact
    ):
        return Detection("citic_corp", BANK_LABELS["citic_corp"], 95, "命中中信对公账户交易明细表头")

    if "账务明细清单" in header_compact and "StatementOfAccount" in header_compact and "招商银行" in compact:
        return Detection("cmb_corp", BANK_LABELS["cmb_corp"], 98, "命中招商银行对公账务明细清单")

    if (
        "客户账户明细对账单" in header_compact
        and "账号/卡号" in compact
        and "交易日期摘要借方金额贷方金额余额币种对方账号/户名用途" in compact
        and "借方总笔数" in compact
    ):
        return Detection("customer_account_corp", BANK_LABELS["customer_account_corp"], 92, "命中客户账户明细对账单，银行名由用户确认为农村商业银行")

    if "账户交易流水" in header_compact and "中原银行" in compact and "收支状态" in compact:
        return Detection("zhongyuan", BANK_LABELS["zhongyuan"], 98, "命中中原银行账户交易流水")

    if (
        "成都农村商业银行" in compact
        and "客户明细" in header_compact
        and "借方金额贷方金额余额" in compact
    ):
        return Detection("chengdu_rural_corp", BANK_LABELS["chengdu_rural_corp"], 98, "命中成都农商银行客户明细")

    if (
        "重庆银行账户交易明细" in header_compact
        and "交易金额活期账面余额交易类型/摘要" in compact
    ):
        return Detection("chongqing", BANK_LABELS["chongqing"], 98, "命中重庆银行账户交易明细")

    if (
        "桂林银行企业客户交易清单" in header_compact
        and "交易日期对方账号对方户名收入支出余额" in compact
    ):
        return Detection("guilin_corp", BANK_LABELS["guilin_corp"], 98, "命中桂林银行企业客户交易清单")

    if (
        "桂林银行" in header_compact
        and "交易日期对方账号对方户名收入（元）支出（元）账户余额（元）备注" in compact
    ):
        return Detection("guilin", BANK_LABELS["guilin"], 96, "命中桂林银行个人收支明细表格")

    if (
        "浙江网商银行企业账户交易明细" in header_compact
        and "借方金额（收）贷方金额（支）余额" in compact
    ):
        return Detection("mybank_corp", BANK_LABELS["mybank_corp"], 98, "命中浙江网商银行企业账户交易明细")

    if (
        "交易明细查询" in header_compact
        and "天津农村商业银行" in compact
        and "交易日期收入支出余额对方户名对方账号对方开户行摘要备注" in compact
    ):
        return Detection("tianjin_rural_corp", BANK_LABELS["tianjin_rural_corp"], 98, "命中天津农村商业银行交易明细查询")

    if (
        "卡号/账号" in header_compact
        and "客户名称" in header_compact
        and "总收入" in header_compact
        and "总支出" in header_compact
        and "序号摘要币别钞汇交易日期交易金额账户余额" in compact
    ):
        return Detection("rural_commercial", _rural_commercial_label(text), 96, "命中农村商业银行个人交易明细")

    rules = [
        ("icbc_corp", "借/贷借方发生额贷方发生额", 98),
        ("icbc_corp", "凭证号对方账号交易时间借贷标志", 98),
        ("icbc_corp", "中国工商银行企业存款对账单", 98),
        ("wechat", "微信支付交易明细证明", 98),
        ("wechat", "微信支付账单", 95),
        ("wechat", "交易时间交易类型交易对方商品收/支金额", 95),
        ("abc_corp", "交易时间收入金额支出金额账户余额", 98),
        ("abc", "对私客户账户明细", 98),
        ("abc", "交易日期交易时间交易摘要交易金额本次余额", 98),
        ("icbc", "中国工商银行借记账户历史明细", 98),
        ("icbc", "交易日期账号储种序号币种钞汇摘要地区收入/支出金额余额", 95),
        ("spdb", "上海浦东发展银行个人客户交易流水专用回单", 98),
        ("spdb", "TransactionStatementofShanghaiPudongDevelopmentBank", 95),
        ("spdb_corp", "上海浦东发展银行电子对账单", 98),
        ("spdb_corp", "ShanghaiPudongDevelopmentBankElectronicStatement", 95),
        ("bocom", "交通银行个人客户交易清单", 95),
        ("psbc", "中国邮政储蓄银行借记账户历史明细", 95),
        ("qilu_corp", "单位活期存款账户交易明细", 98),
        ("rural_credit", "交易流水号交易日期交易网点收入/支出交易金额实时余额", 95),
        ("cmb_corp", "账务明细清单StatementOfAccount", 98),
        ("cmb", "TransactionStatementofChinaMerchantsBank", 95),
        ("citic", "账户交易明细Transactiondetails", 95),
        ("citic", "交易日期收入金额支出金额账户余额交易摘要", 90),
        ("jiujiang", "九江银行交易流水", 90),
        ("ningbo", "宁波银行交易流水", 90),
        ("lanzhou", "兰州银行对公账户对账单", 90),
        ("foshan_rural", "佛山农村商业银行", 90),
        ("nanjing_corp", "南京银行对公账户交易明细", 90),
        ("cmbc_corp", "单位账户对账单客户名称客户账号", 98),
        ("cmbc_corp", "单位账户对账单", 95),
        ("cmbc", "个人账户对账单客户姓名客户账号", 95),
        ("cmbc", "中国民生银行股份有限公司", 95),
        ("cib", "IndustrialBankTransactionDetails", 95),
        ("cib", "兴业银行交易流水", 95),
        ("ccb_corp", "中国建设银行股份有限公司活期存款明细账", 98),
        ("ccb_corp", "中国建设银行账户明细信息", 95),
        ("ccb", "中国建设银行个人活期账户交易明细", 96),
        ("ccb", "中国建设银行个人活期账户全部交易明细", 95),
        ("abc", "中国农业银行银行卡交易明细清单", 95),
        ("abc", "中国农业银行账户活期交易明细清单", 85),
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
