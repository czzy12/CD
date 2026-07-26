import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList
from .number_parser import money_to_decimal


BANK_NAME = "中国农业银行"
TABLE_HEADERS = ["交易日期", "交易发生额", "账户余额", "对方账号", "对方户名", "摘要", "备注"]
LINE_RE = re.compile(
    r"^(?P<date>\d{8})(?:\s+(?P<time>\d{6}))?\s+"
    r"(?P<type>\S+)\s+"
    r"(?P<amount>[+-]?\d[\d,]*\.\d{2})\s+"
    r"(?P<balance>\d[\d,]*\.\d{2})(?:\s+(?P<counterparty>.*))?$"
)
CHANNEL_RE = re.compile(
    r"^(?P<counterparty>.*?)\s+(?P<journal>[A-Za-z]?\d+[A-Za-z0-9]*)\s+"
    r"(?P<channel>掌上银行|电子商务|超级网银)(?:\s+(?P<remark>.*))?$"
)
RAW_HEADERS = ["交易日期", "交易时间", "交易摘要", "交易金额", "本次余额", "对手信息", "日志号", "交易渠道", "交易附言"]
HEADER_NAME_RE = re.compile(r"(?<![\u4e00-\u9fff])户名\s*[:：]\s*(?P<value>\S+)")
HEADER_ACCOUNT_RE = re.compile(r"(?<![\u4e00-\u9fff])账户\s*[:：]\s*(?P<value>[0-9][0-9\s-]*)")


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", "").strip()


def _statement_metadata(first_page_text: str) -> StatementMetadata:
    """Extract the confirmed personal-statement header without using transaction text."""
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
    metadata.raw_fields = {"户名": metadata.account_name, "账户": account_raw}
    metadata.field_sources = {
        "account_name": "page=1:document_header:户名",
        "account_number": "page=1:document_header:账户",
    }
    metadata.field_confidence = {"account_name": 1.0, "account_number": 1.0}
    return metadata


def _header_metadata(pdf_path: str) -> StatementMetadata:
    with pdfplumber.open(pdf_path) as pdf:
        first_page_text = pdf.pages[0].extract_text() if pdf.pages else ""
    return _statement_metadata(first_page_text or "")


def _remark_text(value: str) -> str:
    """Keep the meaningful text portion of the agricultural-bank postscript."""
    value = re.sub(r"^[A-Za-z0-9]+", "", value or "").strip()
    return value if re.search(r"[\u4e00-\u9fff]", value) else ""


def _personal_text_fields(value: str) -> tuple[list[str], dict[str, str], dict[str, str]]:
    match = CHANNEL_RE.match(value or "")
    if not match:
        raw_value = (value or "").strip()
        return (
            [raw_value, "", "", ""],
            {"counterparty_info_raw": raw_value} if raw_value else {},
            {"counterparty_info_raw": "raw_headers[5]:对手信息"} if raw_value else {},
        )

    counterparty = match.group("counterparty").strip()
    journal = match.group("journal").strip()
    channel = match.group("channel").strip()
    postscript = _remark_text(match.group("remark") or "")
    fields = [counterparty, journal, channel, match.group("remark") or ""]
    source_fields = {"counterparty_info_raw": counterparty} if counterparty else {}
    field_sources = {
        "counterparty_info_raw": "raw_headers[5]:对手信息",
    }
    if postscript:
        source_fields["transaction_postscript_raw"] = match.group("remark") or ""
        field_sources["transaction_postscript_raw"] = "raw_headers[8]:交易附言"
    return fields, source_fields, field_sources


def parse_abc_amount_and_balance(
    amount_raw: str,
    balance_raw: str,
    transaction_type: str,
    previous_balance: Decimal | None,
) -> tuple[Decimal, Decimal | None, list[str]]:
    amount = money_to_decimal(amount_raw) or Decimal("0.00")
    balance = money_to_decimal(balance_raw)
    issues: list[str] = []

    if balance is None:
        return amount, None, ["余额无法解析"]

    if previous_balance is None:
        return amount, balance, issues

    balance_delta = (balance - previous_balance).quantize(Decimal("0.01"))
    if balance_delta == amount:
        return amount, balance, issues

    # 农行“抹账/自动抹账”明细常显示原交易方向，但余额按冲正方向变化。
    # 这种场景按余额差统计，避免把后续清晰余额截断成后缀值。
    if transaction_type in {"抹账", "自动抹账"} and balance_delta == -amount:
        return balance_delta, balance, issues

    issues.append(f"余额不连续: 期望 {(previous_balance + amount).quantize(Decimal('0.01'))}, 解析 {balance}")
    return amount, balance, issues


def parse_abc_time(raw_date: str, raw_time: str | None = None) -> datetime | None:
    if not raw_date or len(raw_date) != 8 or not raw_date.isdigit():
        return None

    raw_time = raw_time or "000000"
    if len(raw_time) != 6 or not raw_time.isdigit():
        return None

    try:
        return datetime(
            int(raw_date[:4]),
            int(raw_date[4:6]),
            int(raw_date[6:8]),
            int(raw_time[:2]),
            int(raw_time[2:4]),
            int(raw_time[4:6]),
        )
    except ValueError:
        return None


def _parse_personal_table(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                headers: list[str] | None = None
                for row_index, row in enumerate(table, start=1):
                    fields = [_clean_cell(cell) for cell in row]
                    if fields[:7] == TABLE_HEADERS:
                        headers = fields[:7]
                        continue
                    if len(fields) < 3:
                        continue

                    tx_time = parse_abc_time(fields[0])
                    if tx_time is None:
                        continue

                    amount, balance, issues = parse_abc_amount_and_balance(
                        fields[1],
                        fields[2],
                        "",
                        previous_balance,
                    )
                    income = amount if amount > 0 else Decimal("0.00")
                    expense = -amount if amount < 0 else Decimal("0.00")
                    transactions.append(
                        Transaction(
                            transaction_time=tx_time,
                            income=income,
                            expense=expense,
                            balance=balance,
                            bank=BANK_NAME,
                            page_no=page_index,
                            row_no=row_index,
                            raw_time=fields[0],
                            raw_amount=fields[1],
                            raw_balance=fields[2],
                            raw_text=" | ".join(fields[:7]),
                            raw_fields=fields[:7],
                            raw_headers=headers or TABLE_HEADERS,
                            status="ok" if not issues else "review",
                            issues=issues,
                        )
                    )

                    if balance is not None:
                        previous_balance = balance

    return transactions


def extract_abc(pdf_path: str) -> TransactionList:
    metadata = _header_metadata(pdf_path)
    table_transactions = _parse_personal_table(pdf_path)
    if table_transactions:
        return TransactionList(table_transactions, metadata=metadata)

    transactions: list[Transaction] = []
    previous_balance: Decimal | None = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for line_no, line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = line.strip()
                match = LINE_RE.match(line)
                if not match:
                    continue

                tx_time = parse_abc_time(match.group("date"), match.group("time"))
                if tx_time is None:
                    continue

                amount, balance, issues = parse_abc_amount_and_balance(
                    match.group("amount"),
                    match.group("balance"),
                    match.group("type"),
                    previous_balance,
                )

                if amount is None:
                    amount = Decimal("0.00")

                income = amount if amount > 0 else Decimal("0.00")
                expense = -amount if amount < 0 else Decimal("0.00")
                raw_time = match.group("date")
                if match.group("time"):
                    raw_time = f"{raw_time} {match.group('time')}"

                parsed_fields, source_fields, field_sources = _personal_text_fields(match.group("counterparty") or "")
                counterparty_raw, journal, channel, postscript_raw = (parsed_fields + ["", "", "", ""])[:4]
                remark = _remark_text(postscript_raw)
                raw_fields = [
                    match.group("date"),
                    match.group("time") or "",
                    match.group("type"),
                    match.group("amount"),
                    match.group("balance"),
                    counterparty_raw,
                    journal,
                    channel,
                    postscript_raw,
                ]

                transactions.append(
                    Transaction(
                        transaction_time=tx_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_index,
                        row_no=line_no,
                        raw_time=raw_time,
                        raw_amount=match.group("amount"),
                        raw_balance=match.group("balance"),
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=RAW_HEADERS,
                        remark=remark,
                        transaction_method=channel,
                        source_fields=source_fields,
                        field_sources={
                            **field_sources,
                            **({"transaction_method": "raw_headers[7]:交易渠道"} if channel else {}),
                            **({"remark": "raw_headers[8]:交易附言#仅保留文字部分"} if remark else {}),
                        },
                        field_confidence={
                            field_name: 1.0
                            for field_name in {
                                *field_sources,
                                *( {"transaction_method"} if channel else set() ),
                                *( {"remark"} if remark else set() ),
                            }
                        },
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                )

                if balance is not None:
                    previous_balance = balance

    return TransactionList(transactions, metadata=metadata)
