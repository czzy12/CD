from .abc import extract_abc
from .abc_corp import extract_abc_corp
from .alipay import extract_alipay
from .boc import extract_boc
from .boc_corp import extract_boc_corp
from .bocom import extract_bocom
from .bocom_corp import extract_bocom_corp
from .cmb import extract_cmb
from .cmb_corp import extract_cmb_corp
from .citic import extract_citic, extract_citic_corp
from .city_commercial import (
    extract_foshan_rural,
    extract_jiujiang,
    extract_lanzhou,
    extract_nanjing_corp,
    extract_ningbo,
)
from .cmbc_corp import extract_cmbc_corp
from .ccb import extract_ccb
from .ccb_corp import extract_ccb_corp
from .chengdu_rural_corp import extract_chengdu_rural_corp
from .chongqing import extract_chongqing
from .cib import extract_cib
from .customer_account_corp import extract_customer_account_corp
from .customer_detail_corp import extract_customer_detail_corp
from .everbright import extract_everbright, extract_everbright_corp
from .generic_pdf import extract_generic_pdf
from .guilin_corp import extract_guilin, extract_guilin_corp
from .huaxia import extract_huaxia
from .icbc import extract_icbc
from .icbc_corp import extract_icbc_corp
from .mybank_corp import extract_mybank_corp
from .models import Transaction
from .pingan import extract_pingan
from .psbc import extract_psbc
from .qilu_corp import extract_qilu_corp
from .rural_credit import extract_rural_credit
from .shanghai import extract_shanghai, extract_shanghai_corp
from .shengjing import extract_shengjing
from .spdb import extract_spdb, extract_spdb_corp
from .tianjin_rural_corp import extract_tianjin_rural_corp
from .wechat import extract_wechat
from .xingtai import extract_xingtai
from .zhongyuan import extract_zhongyuan


def extract_transactions(pdf_path: str, bank: str = "icbc") -> list[Transaction]:
    if bank == "alipay":
        return extract_alipay(pdf_path)
    if bank == "icbc":
        return extract_icbc(pdf_path)
    if bank == "huaxia":
        return extract_huaxia(pdf_path)
    if bank == "guilin":
        return extract_guilin(pdf_path)
    if bank == "guilin_corp":
        return extract_guilin_corp(pdf_path)
    if bank == "icbc_corp":
        return extract_icbc_corp(pdf_path)
    if bank == "ccb":
        return extract_ccb(pdf_path)
    if bank == "ccb_corp":
        return extract_ccb_corp(pdf_path)
    if bank == "chengdu_rural_corp":
        return extract_chengdu_rural_corp(pdf_path)
    if bank == "chongqing":
        return extract_chongqing(pdf_path)
    if bank == "customer_account_corp":
        return extract_customer_account_corp(pdf_path)
    if bank == "customer_detail_corp":
        return extract_customer_detail_corp(pdf_path)
    if bank == "everbright":
        return extract_everbright(pdf_path)
    if bank == "everbright_corp":
        return extract_everbright_corp(pdf_path)
    if bank == "abc":
        return extract_abc(pdf_path)
    if bank == "abc_corp":
        return extract_abc_corp(pdf_path)
    if bank == "boc":
        return extract_boc(pdf_path)
    if bank == "boc_corp":
        return extract_boc_corp(pdf_path)
    if bank == "bocom":
        return extract_bocom(pdf_path)
    if bank == "bocom_corp":
        return extract_bocom_corp(pdf_path)
    if bank == "psbc":
        return extract_psbc(pdf_path)
    if bank == "pingan":
        return extract_pingan(pdf_path)
    if bank == "qilu_corp":
        return extract_qilu_corp(pdf_path)
    if bank == "rural_credit":
        return extract_rural_credit(pdf_path)
    if bank == "rural_commercial":
        return extract_rural_credit(pdf_path)
    if bank == "shengjing":
        return extract_shengjing(pdf_path)
    if bank == "shanghai":
        return extract_shanghai(pdf_path)
    if bank == "shanghai_corp":
        return extract_shanghai_corp(pdf_path)
    if bank == "cmbc_corp":
        return extract_cmbc_corp(pdf_path)
    if bank == "cmb":
        return extract_cmb(pdf_path)
    if bank == "cmb_corp":
        return extract_cmb_corp(pdf_path)
    if bank == "citic":
        return extract_citic(pdf_path)
    if bank == "citic_corp":
        return extract_citic_corp(pdf_path)
    if bank == "jiujiang":
        return extract_jiujiang(pdf_path)
    if bank == "foshan_rural":
        return extract_foshan_rural(pdf_path)
    if bank == "lanzhou":
        return extract_lanzhou(pdf_path)
    if bank == "ningbo":
        return extract_ningbo(pdf_path)
    if bank == "mybank_corp":
        return extract_mybank_corp(pdf_path)
    if bank == "nanjing_corp":
        return extract_nanjing_corp(pdf_path)
    if bank == "spdb":
        return extract_spdb(pdf_path)
    if bank == "spdb_corp":
        return extract_spdb_corp(pdf_path)
    if bank == "tianjin_rural_corp":
        return extract_tianjin_rural_corp(pdf_path)
    if bank == "cmbc":
        return extract_generic_pdf(pdf_path, "民生银行个人")
    if bank == "cib":
        return extract_cib(pdf_path)
    if bank == "generic_pdf":
        return extract_generic_pdf(pdf_path)
    if bank == "wechat":
        return extract_wechat(pdf_path)
    if bank == "xingtai":
        return extract_xingtai(pdf_path)
    if bank == "zhongyuan":
        return extract_zhongyuan(pdf_path)
    raise ValueError(f"v2 暂未适配该银行: {bank}")
