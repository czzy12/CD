from .abc import extract_abc
from .abc_corp import extract_abc_corp
from .bocom import extract_bocom
from .cmb import extract_cmb
from .cmbc_corp import extract_cmbc_corp
from .ccb import extract_ccb
from .ccb_corp import extract_ccb_corp
from .icbc import extract_icbc
from .models import Transaction
from .psbc import extract_psbc


def extract_transactions(pdf_path: str, bank: str = "icbc") -> list[Transaction]:
    if bank == "icbc":
        return extract_icbc(pdf_path)
    if bank == "ccb":
        return extract_ccb(pdf_path)
    if bank == "ccb_corp":
        return extract_ccb_corp(pdf_path)
    if bank == "abc":
        return extract_abc(pdf_path)
    if bank == "abc_corp":
        return extract_abc_corp(pdf_path)
    if bank == "bocom":
        return extract_bocom(pdf_path)
    if bank == "psbc":
        return extract_psbc(pdf_path)
    if bank == "cmbc_corp":
        return extract_cmbc_corp(pdf_path)
    if bank == "cmb":
        return extract_cmb(pdf_path)
    raise ValueError(f"v2 暂未适配该银行: {bank}")
