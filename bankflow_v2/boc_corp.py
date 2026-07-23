from datetime import datetime
from decimal import Decimal
import re

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国银行对公"
OPENING_MARKER = "承前页余额"
DATE_RE = re.compile(r"\d{6}|\d{8}")


def _parse_money(raw: str | None) -> Decimal:
    return money_to_decimal((raw or "").strip()) or Decimal("0.00")


def _parse_date(raw: str | None) -> datetime | None:
    match = DATE_RE.search(raw or "")
    if not match:
        return None

    text = match.group()
    if len(text) == 6:
        text = f"20{text}"

    try:
        return datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None


def _opening_balance(text: str) -> Decimal | None:
    index = text.find(OPENING_MARKER)
    if index < 0:
        return None

    match = re.search(r"[\d,]+\.\d{2}", text[index : index + 80])
    if not match:
        return None
    return money_to_decimal(match.group())


def _split_pipe_row(line: str) -> list[str]:
    return [part.strip() for part in line.split("|")]


def _meaningful_text(value: str) -> str:
    parts = [part.strip() for part in (value or "").split("/")]
    text_parts = [part for part in parts if re.search(r"[\u4e00-\u9fff]", part)]
    return "/".join(text_parts)


def _parse_transaction_line(line: str, page_no: int, row_no: int) -> Transaction | None:
    parts = _split_pipe_row(line)
    if len(parts) < 11:
        return None

    serial = parts[1]
    if not serial.isdigit():
        return None

    tx_time = _parse_date(parts[2])
    if tx_time is None:
        return None

    debit_raw = parts[7] if len(parts) > 7 else ""
    credit_raw = parts[8] if len(parts) > 8 else ""
    balance_raw = parts[9] if len(parts) > 9 else ""
    debit = _parse_money(debit_raw)
    credit = _parse_money(credit_raw)
    balance = money_to_decimal(balance_raw)

    issues: list[str] = []
    if debit > 0 and credit > 0:
        issues.append("借方和贷方同时有金额")
    if debit == 0 and credit == 0:
        issues.append("借方和贷方均为零")
    if balance is None:
        issues.append("余额无法解析")

    raw_text_parts = []
    for index in (4, 6, 10, 11):
        if index < len(parts) and parts[index]:
            raw_text_parts.append(parts[index])

    detail_text = _meaningful_text(parts[6] if len(parts) > 6 else "")
    reference = parts[10] if len(parts) > 10 else ""
    note = parts[11] if len(parts) > 11 else ""
    source_fields = {
        field_name: value
        for field_name, value in (
            ("voucher_details_text", detail_text),
            ("operator_reference", reference),
            ("counterparty_info_raw", note),
        )
        if value
    }
    field_sources = {
        "voucher_details_text": "raw_headers[5]:凭证号码/业务编号/用途/摘要#仅保留文字部分",
        "operator_reference": "raw_headers[9]:机构/柜员/流水",
        "counterparty_info_raw": "raw_headers[10]:备注",
    }
    tx = Transaction(
        transaction_time=tx_time,
        income=credit,
        expense=debit,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=parts[2],
        raw_amount=f"{debit_raw}|{credit_raw}",
        raw_balance=balance_raw,
        raw_text=" | ".join(raw_text_parts),
        raw_fields=parts[1:-1] if parts and parts[-1] == "" else parts[1:],
        raw_headers=[
            "序号",
            "记账日",
            "起息日",
            "交易类型",
            "凭证",
            "凭证号码/业务编号/用途/摘要",
            "借方发生额",
            "贷方发生额",
            "余额",
            "机构/柜员/流水",
            "备注",
        ],
        summary=detail_text,
        remark="",
        source_fields=source_fields,
        field_sources={
            **{field_name: field_sources[field_name] for field_name in source_fields},
            **({"summary": field_sources["voucher_details_text"]} if detail_text else {}),
        },
        field_confidence={
            field_name: 1.0
            for field_name in {
                *source_fields,
                *( {"summary"} if detail_text else set() ),
            }
        },
        status="ok" if not issues else "review",
        issues=issues,
    )
    tx.remark = ""
    tx.field_sources.pop("remark", None)
    tx.field_confidence.pop("remark", None)
    tx.merge_key = "|".join([parts[1], parts[2], debit_raw, credit_raw, balance_raw, str(page_no), str(row_no)])
    return tx


def extract_boc_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    first_opening: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if first_opening is None:
                first_opening = _opening_balance(text)

            for row_no, line in enumerate(text.splitlines(), start=1):
                if not line.startswith("|"):
                    continue
                tx = _parse_transaction_line(line, page_no, row_no)
                if tx is None:
                    parts = _split_pipe_row(line)
                    continuation = parts[11] if len(parts) > 11 else ""
                    if transactions and continuation:
                        previous = transactions[-1]
                        previous.source_fields["counterparty_info_raw"] = (
                            f"{previous.source_fields.get('counterparty_info_raw', '')}{continuation}"
                        )
                        previous.field_sources["counterparty_info_raw"] = "raw_headers[10]:备注（续行已合并）"
                        previous.field_confidence["counterparty_info_raw"] = 1.0
                    continue
                transactions.append(tx)

    if transactions and first_opening is not None:
        transactions[0].opening_balance = first_opening

    return transactions
