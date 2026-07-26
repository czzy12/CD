import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList
from .number_parser import money_to_decimal


BANK_NAME = "中国工商银行对公"
HEADER_NAME_RE = re.compile(r"(?<![对交])户名\s*[:：]\s*(?P<value>\S+)")
HEADER_ACCOUNT_RE = re.compile(r"(?<![对交])账号\s*[:：]\s*(?P<value>[0-9][0-9\s-]*)")


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _parse_time(raw: str | None) -> datetime | None:
    text = _clean_cell(raw)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d %H:%M:%S"):
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


def _ordered_fields(row: list, index: dict[str, int]) -> tuple[list[str], list[str]]:
    headers = [name for name, _ in sorted(index.items(), key=lambda item: item[1])]
    return [_clean_cell(row[index[name]]) if index[name] < len(row) else "" for name in headers], headers


def _statement_metadata(first_page_text: str) -> StatementMetadata:
    metadata = StatementMetadata()
    name_matches = HEADER_NAME_RE.findall(first_page_text or "")
    account_matches = HEADER_ACCOUNT_RE.findall(first_page_text or "")
    if len(name_matches) != 1 or len(account_matches) != 1:
        return metadata

    account_raw = account_matches[0].strip()
    account_number = re.sub(r"[\s-]+", "", account_raw)
    if not re.fullmatch(r"[0-9]{12,32}", account_number):
        return metadata

    metadata.account_name = name_matches[0].strip()
    metadata.account_number = account_number
    metadata.raw_fields = {"户名": metadata.account_name, "账号": account_raw}
    metadata.field_sources = {
        "account_name": "page=1:document_header:户名",
        "account_number": "page=1:document_header:账号",
    }
    metadata.field_confidence = {"account_name": 1.0, "account_number": 1.0}
    return metadata


def _apply_account_detail_fields(tx: Transaction, row: list, index: dict[str, int]) -> None:
    """Map only the confirmed fields for 工行对公账户明细清单."""
    counterparty_name = _cell(row, index, "对方单位")
    summary = _cell(row, index, "摘要")
    purpose = _cell(row, index, "用途")
    posting_date = _cell(row, index, "入账日期") or _cell(row, index, "记账日期")

    if counterparty_name:
        tx.counterparty_name = counterparty_name
        tx.field_sources["counterparty_name"] = f"raw_headers[{index['对方单位']}]:对方单位"
        tx.field_confidence["counterparty_name"] = 1.0
    if summary:
        tx.summary = summary
        tx.field_sources["summary"] = f"raw_headers[{index['摘要']}]:摘要"
        tx.field_confidence["summary"] = 1.0
    if purpose:
        tx.purpose = purpose
        tx.field_sources["purpose"] = f"raw_headers[{index['用途']}]:用途"
        tx.field_confidence["purpose"] = 1.0
    if posting_date:
        tx.source_fields["posting_date"] = posting_date
        header = "入账日期" if "入账日期" in index else "记账日期"
        tx.field_sources["posting_date"] = f"raw_headers[{index[header]}]:{header}"
        tx.field_confidence["posting_date"] = 1.0

    for field_name, header in (
        ("counterparty_bank_code", "对方行号"),
        ("receipt_customization", "回单个性化信息"),
    ):
        value = _cell(row, index, header)
        if value:
            tx.source_fields[field_name] = value
            tx.field_sources[field_name] = f"raw_headers[{index[header]}]:{header}"
            tx.field_confidence[field_name] = 1.0

    for field_name in ("card_number",):
        tx.field_sources.pop(field_name, None)
        tx.field_confidence.pop(field_name, None)
        tx.source_fields.pop(field_name, None)


def _parse_format_a(row: list, index: dict[str, int], page_no: int, row_no: int) -> Transaction | None:
    tx_time = _parse_time(_cell(row, index, "交易时间"))
    if tx_time is None:
        return None

    amount = money_to_decimal(_cell(row, index, "发生额"))
    balance = money_to_decimal(_cell(row, index, "余额"))
    direction = _cell(row, index, "借贷标志")
    issues: list[str] = []

    if amount is None:
        issues.append("金额无法解析")
        amount = Decimal("0.00")
    if balance is None:
        issues.append("余额无法解析")

    if direction == "贷":
        income = amount
        expense = Decimal("0.00")
    elif direction == "借":
        income = Decimal("0.00")
        expense = amount
    else:
        income = Decimal("0.00")
        expense = Decimal("0.00")
        issues.append("借贷方向无法解析")

    raw_fields, raw_headers = _ordered_fields(row, index)
    tx = Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_cell(row, index, "交易时间"),
        raw_amount=_cell(row, index, "发生额"),
        raw_balance=_cell(row, index, "余额"),
        raw_text=" | ".join(raw_fields),
        raw_fields=raw_fields,
        raw_headers=raw_headers,
        status="ok" if not issues else "review",
        issues=issues,
    )
    _apply_account_detail_fields(tx, row, index)
    tx.preserve_signed_columns = True
    return tx


def _parse_format_b(row: list, index: dict[str, int], page_no: int, row_no: int) -> Transaction | None:
    tx_time = _parse_time(_cell(row, index, "交易时间"))
    if tx_time is None:
        return None

    debit = money_to_decimal(_cell(row, index, "借方发生额"))
    credit = money_to_decimal(_cell(row, index, "贷方发生额"))
    balance = money_to_decimal(_cell(row, index, "余额"))
    direction = _cell(row, index, "借/贷")
    issues: list[str] = []

    if direction == "贷":
        income = credit or Decimal("0.00")
        expense = Decimal("0.00")
        raw_amount = _cell(row, index, "贷方发生额")
        if credit is None:
            issues.append("贷方金额无法解析")
    elif direction == "借":
        income = Decimal("0.00")
        expense = debit or Decimal("0.00")
        raw_amount = _cell(row, index, "借方发生额")
        if debit is None:
            issues.append("借方金额无法解析")
    else:
        income = Decimal("0.00")
        expense = Decimal("0.00")
        raw_amount = ""
        issues.append("借贷方向无法解析")

    if balance is None:
        issues.append("余额无法解析")

    tx = Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_cell(row, index, "交易时间"),
        raw_amount=raw_amount,
        raw_balance=_cell(row, index, "余额"),
        status="ok" if not issues else "review",
        issues=issues,
    )
    tx.preserve_signed_columns = True
    return tx


def _parse_format_c(row: list, index: dict[str, int], page_no: int, row_no: int) -> Transaction | None:
    tx_time = _parse_time(_cell(row, index, "交易时间"))
    if tx_time is None:
        return None

    debit = money_to_decimal(_cell(row, index, "借方发生额"))
    credit = money_to_decimal(_cell(row, index, "贷方发生额"))
    balance = money_to_decimal(_cell(row, index, "余额"))
    issues: list[str] = []

    if debit is None:
        issues.append("借方金额无法解析")
        debit = Decimal("0.00")
    if credit is None:
        issues.append("贷方金额无法解析")
        credit = Decimal("0.00")
    if balance is None:
        issues.append("余额无法解析")

    if debit != Decimal("0.00") and credit != Decimal("0.00"):
        issues.append("借贷金额同时存在")

    income = credit
    expense = debit
    raw_amount = _cell(row, index, "贷方发生额") if credit != Decimal("0.00") else _cell(row, index, "借方发生额")

    return Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_cell(row, index, "交易时间"),
        raw_amount=raw_amount,
        raw_balance=_cell(row, index, "余额"),
        raw_text=" | ".join(_clean_cell(cell) for cell in row),
        raw_fields=[_clean_cell(cell) for cell in row],
        raw_headers=[name for name, _ in sorted(index.items(), key=lambda item: item[1])],
        status="ok" if not issues else "review",
        issues=issues,
    )


def _parse_format_d(row: list, index: dict[str, int], page_no: int, row_no: int) -> Transaction | None:
    tx_time = _parse_time(_cell(row, index, "交易时间"))
    if tx_time is None:
        return None

    income = money_to_decimal(_cell(row, index, "转入金额")) or Decimal("0.00")
    expense = money_to_decimal(_cell(row, index, "转出金额")) or Decimal("0.00")
    balance = money_to_decimal(_cell(row, index, "余额"))
    issues: list[str] = []

    if income != Decimal("0.00") and expense != Decimal("0.00"):
        issues.append("转入和转出金额同时存在")
    if income == Decimal("0.00") and expense == Decimal("0.00"):
        issues.append("转入和转出金额均为空")
    if balance is None:
        issues.append("余额无法解析")

    tx = Transaction(
        transaction_time=tx_time,
        income=income,
        expense=expense,
        balance=balance,
        bank=BANK_NAME,
        page_no=page_no,
        row_no=row_no,
        raw_time=_cell(row, index, "交易时间"),
        raw_amount=f"{_cell(row, index, '转入金额')}|{_cell(row, index, '转出金额')}",
        raw_balance=_cell(row, index, "余额"),
        raw_text=" | ".join(_clean_cell(cell) for cell in row),
        raw_fields=[_clean_cell(cell) for cell in row],
        raw_headers=[name for name, _ in sorted(index.items(), key=lambda item: item[1])],
        status="ok" if not issues else "review",
        issues=issues,
    )
    tx.preserve_signed_columns = True
    return tx


def _looks_like_header(row: list) -> bool:
    text = "|".join(_clean_cell(cell) for cell in row or [])
    return bool(re.search(r"交易时间.*余额", text)) and (
        "借贷标志" in text
        or "借/贷" in text
        or ("借方发生额" in text and "贷方发生额" in text)
        or ("转入金额" in text and "转出金额" in text)
    )


def _balance_chain_score(items: list[Transaction]) -> int:
    score = 0
    for previous, current in zip(items, items[1:]):
        if previous.balance is None or current.balance is None:
            continue
        expected = (previous.balance + current.income - current.expense).quantize(Decimal("0.01"))
        if expected == current.balance.quantize(Decimal("0.01")):
            score += 1
    return score


def _restore_same_time_order(transactions: list[Transaction]) -> list[Transaction]:
    grouped: dict[datetime, list[Transaction]] = {}
    for tx in transactions:
        grouped.setdefault(tx.transaction_time, []).append(tx)

    for tx_time, items in grouped.items():
        if len(items) < 2:
            continue

        forward = sorted(items, key=lambda tx: (tx.page_no, tx.row_no))
        reverse = list(reversed(forward))
        ordered = reverse if _balance_chain_score(reverse) > _balance_chain_score(forward) else forward
        for index, tx in enumerate(ordered):
            tx.transaction_time = tx_time.replace(microsecond=index)

    return transactions


def extract_icbc_corp(pdf_path: str) -> TransactionList:
    transactions: list[Transaction] = []
    metadata = StatementMetadata()

    with pdfplumber.open(pdf_path) as pdf:
        if pdf.pages:
            metadata = _statement_metadata(pdf.pages[0].extract_text() or "")
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                index: dict[str, int] | None = None
                parser = None

                for row_index, row in enumerate(table, start=1):
                    if not row:
                        continue
                    if _looks_like_header(row):
                        index = _header_index(row)
                        if "借/贷" in index:
                            parser = _parse_format_b
                        elif "借方发生额" in index and "贷方发生额" in index:
                            parser = _parse_format_c
                        elif "转入金额" in index and "转出金额" in index:
                            parser = _parse_format_d
                        else:
                            parser = _parse_format_a
                        continue
                    if index is None or parser is None:
                        continue

                    tx = parser(row, index, page_index, row_index)
                    if tx is not None:
                        transactions.append(tx)

    return TransactionList(_restore_same_time_order(transactions), metadata=metadata)
