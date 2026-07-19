from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "交通银行对公"
RAW_HEADERS = [
    "序号",
    "会计日期",
    "交易日期",
    "交易名称",
    "凭证种类",
    "凭证号码",
    "借方发生额",
    "贷方发生额",
    "余额",
    "卡号",
    "交易地点",
    "对方账号",
    "对方户名",
    "对方行名",
    "摘要",
    "流水号",
]


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_date(raw: str | None) -> datetime | None:
    text = _clean_cell(raw)
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def _header_index(row: list) -> dict[str, int]:
    return {_clean_cell(cell): idx for idx, cell in enumerate(row or [])}


def _cell(row: list, index: dict[str, int], name: str) -> str:
    idx = index.get(name)
    if idx is None or idx >= len(row):
        return ""
    return _clean_cell(row[idx])


def _looks_like_header(row: list) -> bool:
    text = "".join(_clean_cell(cell) for cell in row or [])
    return (
        "会计日期" in text
        and "交易日期" in text
        and "借方发生额" in text
        and "贷方发生额" in text
        and "余额" in text
    )


def _parse_row(row: list, index: dict[str, int], page_no: int, row_no: int) -> Transaction | None:
    sequence = _cell(row, index, "序号")
    if not sequence.isdigit():
        return None

    tx_time = _parse_date(_cell(row, index, "交易日期") or _cell(row, index, "会计日期"))
    if tx_time is None:
        return None

    debit = money_to_decimal(_cell(row, index, "借方发生额"))
    credit = money_to_decimal(_cell(row, index, "贷方发生额"))
    balance = money_to_decimal(_cell(row, index, "余额"))
    issues: list[str] = []

    if debit is None:
        debit = Decimal("0.00")
    if credit is None:
        credit = Decimal("0.00")
    if balance is None:
        issues.append("余额无法解析")
    if debit > 0 and credit > 0:
        issues.append("借贷金额同时存在")
    if not debit and not credit:
        issues.append("借贷金额均为空")

    if debit < 0:
        income = -debit
        expense = Decimal("0.00")
    elif credit < 0:
        income = Decimal("0.00")
        expense = -credit
    else:
        income = credit
        expense = debit

    raw_amount = _cell(row, index, "贷方发生额") if credit else _cell(row, index, "借方发生额")
    raw_fields = [_clean_cell(cell) for cell in row]
    source_fields = {
        field_name: _cell(row, index, header)
        for field_name, header in (
            ("accounting_date", "会计日期"),
            ("voucher_number", "凭证号码"),
            ("transaction_reference", "流水号"),
            ("card_number", "卡号"),
        )
        if _cell(row, index, header)
    }
    source_headers = {
        "accounting_date": "会计日期",
        "voucher_number": "凭证号码",
        "transaction_reference": "流水号",
        "card_number": "卡号",
    }
    return Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_cell(row, index, "交易日期") or _cell(row, index, "会计日期"),
        raw_amount=raw_amount,
        raw_balance=_cell(row, index, "余额"),
        raw_text=" | ".join(raw_fields),
        raw_fields=raw_fields,
        raw_headers=[name for name, _idx in sorted(index.items(), key=lambda item: item[1])],
        source_fields=source_fields,
        field_sources={
            field_name: f"raw_headers[{index[source_headers[field_name]]}]:{source_headers[field_name]}"
            for field_name in source_fields
        },
        field_confidence={field_name: 1.0 for field_name in source_fields},
        status="ok" if not issues else "review",
        issues=issues,
    )


def extract_bocom_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                index: dict[str, int] | None = None
                for row_index, row in enumerate(table, start=1):
                    if not row:
                        continue
                    if _looks_like_header(row):
                        index = _header_index(row)
                        continue
                    if index is None:
                        continue
                    tx = _parse_row(row, index, page_index, row_index)
                    if tx is not None:
                        transactions.append(tx)

    return transactions
