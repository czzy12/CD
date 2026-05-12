from .icbc import extract_icbc
from .models import Transaction


def extract_transactions(pdf_path: str, bank: str = "icbc") -> list[Transaction]:
    if bank != "icbc":
        raise ValueError(f"v2 暂未适配该银行: {bank}")
    return extract_icbc(pdf_path)
