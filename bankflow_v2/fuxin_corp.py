from datetime import datetime

import pdfplumber

from .ccb_corp import _amount_columns
from .models import Transaction
from .number_parser import money_to_decimal
from .psbc import _restore_same_time_order


BANK_NAME = "阜新银行对公"
HEADERS = ["交易日期", "交易时间", "币种", "借方发生额", "贷方发生额", "余额", "交易类型", "对方账户名称", "对方账号", "对方开户行", "交易机构", "摘要"]


def _cell(row: list, index: int) -> str:
    return str(row[index] or "").replace("\n", " ").strip() if index < len(row) else ""


def extract_fuxin_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 6:
                        continue
                    try:
                        tx_time = datetime.strptime(f"{_cell(row, 0)} {_cell(row, 1)}", "%Y%m%d %H:%M:%S")
                    except ValueError:
                        continue
                    income, expense, issues = _amount_columns(_cell(row, 3), _cell(row, 4))
                    balance = money_to_decimal(_cell(row, 5))
                    raw_fields = [_cell(row, i) for i in range(len(row))]
                    transactions.append(Transaction(
                        transaction_time=tx_time, income=income, expense=expense, balance=balance,
                        bank=BANK_NAME, page_no=page_no, row_no=len(transactions) + 1,
                        raw_time=f"{raw_fields[0]} {raw_fields[1]}",
                        raw_amount=f"{raw_fields[3]}|{raw_fields[4]}", raw_balance=raw_fields[5],
                        raw_text=" | ".join(raw_fields[6:]), raw_fields=raw_fields, raw_headers=HEADERS,
                        status="ok" if not issues else "review", issues=issues,
                    ))
    _restore_same_time_order(transactions)
    return transactions
