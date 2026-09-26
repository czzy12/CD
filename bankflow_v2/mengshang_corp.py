from .ccb_corp import extract_ccb_corp


BANK_NAME = "蒙商银行对公"


def extract_mengshang_corp(pdf_path: str):
    transactions = extract_ccb_corp(pdf_path)
    for tx in transactions:
        tx.bank = BANK_NAME
        if tx.raw_fields:
            account_no = "".join(char for char in tx.raw_fields[0] if char.isdigit())
            if account_no:
                tx.account_no = account_no
    return transactions
