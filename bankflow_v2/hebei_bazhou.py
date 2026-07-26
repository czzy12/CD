from __future__ import annotations

import re
from datetime import datetime, time
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


HEBEI_PERSONAL_BANK = "河北银行个人"
HEBEI_CORP_DETAIL_BANK = "河北银行对公"
BAZHOU_CORP_BANK = "霸州舜丰村镇银行对公"
ZERO = Decimal("0.00")

PERSONAL_HEADERS = ["交易日期", "借贷", "交易金额", "账户余额", "对方账户", "对方户名", "流水号", "摘要", "备注"]
HEBEI_CORP_HEADERS = ["交易日期", "交易金额", "借贷标志", "交易后余额", "交易对手账号", "交易对手名称", "交易对手开户行", "摘要", "备注"]
CORP_HEADERS = ["交易日期", "对方账户", "对方户名", "对方开户行名", "汇出金额", "汇入金额", "余额", "摘要", "用途"]

PERSONAL_RE = re.compile(
    r"^(?P<date>\d{8})\s+(?P<direction>[借贷])\s+"
    r"(?P<amount>-?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})\s+"
    r"(?P<balance>(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2})\s+(?P<rest>.*)$"
)
CORP_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\b")
TIME_RE = re.compile(r"\b(\d{2}:\d{2}:\d{2})\b")
MONEY_RE = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}")


def _extract_text(pdf_path: str) -> str:
    chunks: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            chunks.append(page.extract_text(x_tolerance=1, y_tolerance=3) or "")
    return "\n".join(chunks)


def _money(text: str | None) -> Decimal:
    value = money_to_decimal(text)
    return value if value is not None else ZERO


def _cell(row: list, index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).replace("\n", " ").strip()


def _personal_amounts(direction: str, signed_amount: Decimal) -> tuple[Decimal, Decimal, str]:
    amount = abs(signed_amount)
    if direction == "贷" and signed_amount >= ZERO:
        return amount, ZERO, "收入"
    if direction == "贷":
        return ZERO, amount, "支出(冲账)"
    if signed_amount < ZERO:
        return amount, ZERO, "收入(冲账)"
    return ZERO, amount, "支出"


def _amounts_from_direction(direction: str, signed_amount: Decimal) -> tuple[Decimal, Decimal]:
    amount = abs(signed_amount)
    if "贷" in direction and signed_amount >= ZERO:
        return amount, ZERO
    if "贷" in direction:
        return ZERO, amount
    if "借" in direction and signed_amount < ZERO:
        return amount, ZERO
    if "借" in direction:
        return ZERO, amount
    return ZERO, ZERO


def extract_hebei_personal(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    for line_index, line in enumerate(_extract_text(pdf_path).splitlines(), start=1):
        match = PERSONAL_RE.match(line.strip())
        if not match:
            continue

        tx_time = datetime.strptime(match.group("date"), "%Y%m%d")
        signed_amount = _money(match.group("amount"))
        income, expense, direction_text = _personal_amounts(match.group("direction"), signed_amount)
        balance = _money(match.group("balance"))
        raw_text = line.strip()
        fields = [match.group("date"), match.group("direction"), match.group("amount"), match.group("balance")]
        fields.extend(match.group("rest").split())
        tx = Transaction(
            transaction_time=tx_time,
            income=income,
            expense=expense,
            balance=balance,
            bank=HEBEI_PERSONAL_BANK,
            page_no=1,
            row_no=line_index,
            raw_time=match.group("date"),
            raw_amount=f"{match.group('direction')} {match.group('amount')}",
            raw_balance=match.group("balance"),
            raw_text=raw_text,
            raw_fields=fields,
            raw_headers=PERSONAL_HEADERS,
        )
        raw_counterparty_account = fields[4] if len(fields) > 4 else ""
        if raw_counterparty_account:
            tx.source_fields["counterparty_account_raw"] = raw_counterparty_account
            tx.field_sources["counterparty_account_raw"] = "raw_headers[4]:对方账户"
            tx.field_confidence["counterparty_account_raw"] = 1.0
        tx.direction_text = direction_text
        rows.append(tx)

    # 河北银行个人明细按倒序展示。没有时分秒时，汇总逻辑会用
    # page_no/row_no 排同日顺序，因此这里把行号反转成同日余额链顺序。
    total = len(rows)
    for index, tx in enumerate(rows):
        tx.row_no = total - index
    return rows


def _parse_hebei_corp_time(raw: str) -> datetime | None:
    text = raw.replace("\n", " ").strip()
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        pass
    try:
        return datetime.combine(datetime.strptime(text, "%Y-%m-%d").date(), time(23, 59, 59))
    except ValueError:
        pass
    return None


def extract_hebei_corp_detail(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not table:
                    continue
                for row in table[1:]:
                    if len(row) < 4:
                        continue
                    tx_time = _parse_hebei_corp_time(_cell(row, 0))
                    if tx_time is None:
                        continue
                    amount = _money(_cell(row, 1))
                    balance = _money(_cell(row, 3))
                    direction = _cell(row, 2)
                    income, expense = _amounts_from_direction(direction, amount)

                    raw_fields = [_cell(row, index) for index in range(len(row))]
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=HEBEI_CORP_DETAIL_BANK,
                        page_no=page_no,
                        row_no=len(rows) + 1,
                        raw_time=tx_time.strftime("%Y-%m-%d %H:%M:%S"),
                        raw_amount=f"{direction} {_cell(row, 1)}",
                        raw_balance=_cell(row, 3),
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=HEBEI_CORP_HEADERS,
                    )
                    for field_name, index in (("counterparty_account", 4), ("counterparty_bank", 6)):
                        value = _cell(row, index)
                        if value:
                            setattr(tx, field_name, value)
                            tx.field_sources[field_name] = f"raw_headers[{index}]:{HEBEI_CORP_HEADERS[index]}"
                            tx.field_confidence[field_name] = 1.0
                    rows.append(tx)

    # 明细按倒序展示；同一秒内常见“转账、手续费”也倒序。
    # 给同秒交易补微秒顺序，让汇总排序按余额链顺序检查。
    groups: dict[datetime, list[Transaction]] = {}
    for tx in rows:
        groups.setdefault(tx.transaction_time, []).append(tx)
    for group in groups.values():
        if len(group) <= 1:
            continue
        for microsecond, tx in enumerate(reversed(group)):
            tx.transaction_time = tx.transaction_time.replace(microsecond=microsecond)
    return rows


def _corp_blocks(text: str) -> list[str]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("提示") or stripped.startswith("第"):
            continue
        if CORP_DATE_RE.match(stripped):
            if current:
                blocks.append(current)
            current = [stripped]
        elif current:
            current.append(stripped)
    if current:
        blocks.append(current)
    return [" ".join(block) for block in blocks]


def _corp_time(block: str) -> tuple[datetime | None, str]:
    date_match = CORP_DATE_RE.match(block)
    if not date_match:
        return None, ""
    raw_time = ""
    parsed_time = time(0, 0, 0)
    time_match = TIME_RE.search(block)
    if time_match:
        raw_time = f"{date_match.group(1)} {time_match.group(1)}"
        parsed_time = datetime.strptime(time_match.group(1), "%H:%M:%S").time()
    return datetime.combine(datetime.strptime(date_match.group(1), "%Y-%m-%d").date(), parsed_time), raw_time or date_match.group(1)


def _bazhou_header_index(row: list) -> dict[str, int]:
    return {
        re.sub(r"\s+", "", _cell(row, index)): index
        for index in range(len(row))
        if _cell(row, index)
    }


def _bazhou_table_rows(page, page_no: int) -> list[Transaction]:
    transactions: list[Transaction] = []
    required_headers = {"交易日期", "汇出金额", "汇入金额", "余额", "摘要", "用途"}
    for table in page.extract_tables():
        index: dict[str, int] | None = None
        for row in table:
            if not row:
                continue
            candidate = _bazhou_header_index(row)
            if required_headers.issubset(candidate):
                index = candidate
                continue
            if index is None:
                continue

            raw_date = _cell(row, index["交易日期"])
            tx_time, raw_time = _corp_time(raw_date)
            if tx_time is None:
                continue
            expense = _money(_cell(row, index["汇出金额"]))
            income = _money(_cell(row, index["汇入金额"]))
            balance = _money(_cell(row, index["余额"]))
            raw_headers = [name for name, _ in sorted(index.items(), key=lambda item: item[1])]
            raw_fields = [_cell(row, index[name]) for name in raw_headers]
            tx = Transaction(
                transaction_time=tx_time,
                income=income,
                expense=expense,
                balance=balance,
                bank=BAZHOU_CORP_BANK,
                page_no=page_no,
                row_no=len(transactions) + 1,
                raw_time=raw_time,
                raw_amount=f"汇出:{_cell(row, index['汇出金额'])} 汇入:{_cell(row, index['汇入金额'])}",
                raw_balance=_cell(row, index["余额"]),
                raw_text=" | ".join(raw_fields),
                raw_fields=raw_fields,
                raw_headers=raw_headers,
            )
            account_index = index.get("对方账户")
            if account_index is not None:
                raw_account = _cell(row, account_index)
                if raw_account:
                    tx.source_fields["counterparty_account_raw"] = raw_account
                    tx.field_sources["counterparty_account_raw"] = f"raw_headers[{account_index}]:对方账户"
                    tx.field_confidence["counterparty_account_raw"] = 1.0
            transactions.append(tx)
    return transactions


def extract_bazhou_shunfeng_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            transactions.extend(_bazhou_table_rows(page, page_no))
    if transactions:
        for row_index, tx in enumerate(transactions, start=1):
            tx.row_no = row_index
        return transactions

    for row_index, block in enumerate(_corp_blocks(_extract_text(pdf_path)), start=1):
        tx_time, raw_time = _corp_time(block)
        if tx_time is None:
            continue

        amounts = MONEY_RE.findall(block)
        if len(amounts) < 3:
            continue
        expense = _money(amounts[-3])
        income = _money(amounts[-2])
        balance = _money(amounts[-1])
        transactions.append(
            Transaction(
                transaction_time=tx_time,
                income=income,
                expense=expense,
                balance=balance,
                bank=BAZHOU_CORP_BANK,
                page_no=1,
                row_no=row_index,
                raw_time=raw_time,
                raw_amount=f"汇出:{amounts[-3]} 汇入:{amounts[-2]}",
                raw_balance=amounts[-1],
                raw_text=block,
                raw_fields=block.split(),
                raw_headers=CORP_HEADERS,
            )
        )

    return transactions
