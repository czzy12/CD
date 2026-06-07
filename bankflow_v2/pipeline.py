from .abc import extract_abc
from .abc_corp import extract_abc_corp
from .boc_corp import extract_boc_corp
from .bocom import extract_bocom
from .cmb import extract_cmb
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
from .generic_pdf import extract_generic_pdf
from .icbc import extract_icbc
from .icbc_corp import extract_icbc_corp
from .models import Transaction
from .psbc import extract_psbc
from .qilu_corp import extract_qilu_corp
from .rural_credit import extract_rural_credit
from .spdb import extract_spdb, extract_spdb_corp
from .wechat import extract_wechat


def extract_transactions(pdf_path: str, bank: str = "icbc") -> list[Transaction]:
    if bank == "icbc":
        return extract_icbc(pdf_path)
    if bank == "icbc_corp":
        return extract_icbc_corp(pdf_path)
    if bank == "ccb":
        return extract_ccb(pdf_path)
    if bank == "ccb_corp":
        return extract_ccb_corp(pdf_path)
    if bank == "abc":
        return extract_abc(pdf_path)
    if bank == "abc_corp":
        return extract_abc_corp(pdf_path)
    if bank == "boc_corp":
        return extract_boc_corp(pdf_path)
    if bank == "bocom":
        return extract_bocom(pdf_path)
    if bank == "psbc":
        return extract_psbc(pdf_path)
    if bank == "qilu_corp":
        return extract_qilu_corp(pdf_path)
    if bank == "rural_credit":
        return extract_rural_credit(pdf_path)
    if bank == "cmbc_corp":
        return extract_cmbc_corp(pdf_path)
    if bank == "cmb":
        return extract_cmb(pdf_path)
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
    if bank == "nanjing_corp":
        return extract_nanjing_corp(pdf_path)
    if bank == "spdb":
        return extract_spdb(pdf_path)
    if bank == "spdb_corp":
        return extract_spdb_corp(pdf_path)
    if bank == "cmbc":
        return extract_generic_pdf(pdf_path, "民生银行个人")
    if bank == "cib":
        return extract_generic_pdf(pdf_path, "兴业银行")
    if bank == "generic_pdf":
        return extract_generic_pdf(pdf_path)
    if bank == "wechat":
        return extract_wechat(pdf_path)
    raise ValueError(f"v2 暂未适配该银行: {bank}")
