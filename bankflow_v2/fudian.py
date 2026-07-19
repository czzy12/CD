import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList
from .number_parser import CENT, money_to_decimal


BANK_NAME = "富滇银行"
ZERO = Decimal("0.00")
RAW_HEADERS = [
    "序号 / Serial Number",
    "交易日期 / Trading Date",
    "货币 / Currency",
    "交易金额 / Trading Amount",
    "账户余额 / Account Balance",
    "对方账号 / Counterparty Account",
    "对方户名 / Counterparty Name",
    "摘要描述 / Trading Description",
    "备注 / Remark",
]
COMPACT_HEADERS = [re.sub(r"\s+|/", "", header) for header in RAW_HEADERS]
REMARK_LABEL_RE = re.compile(
    r"(商户名称及地址|二级商户信息|商户代码|附言|商户|商品|摘要|车牌)\s*[:：]"
)


def _compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _cell_text(value: object) -> str:
    return " ".join(str(value or "").split())


def _standard_text(value: object) -> str:
    text = _cell_text(value)
    return re.sub(r"(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])", "", text)


def _is_target_table(table: list[list[object]]) -> bool:
    if not table or len(table[0]) < len(RAW_HEADERS):
        return False
    return [_compact(value) for value in table[0][: len(RAW_HEADERS)]] == COMPACT_HEADERS


def _parse_time(raw: str) -> datetime | None:
    try:
        return datetime.strptime(_compact(raw), "%Y-%m-%d%H:%M:%S")
    except ValueError:
        return None


def _parse_metadata(first_page_text: str, page_count: int) -> StatementMetadata:
    metadata = StatementMetadata()

    period_match = re.search(r"(?<!\d)(\d{8})\s*--\s*(\d{8})(?!\d)", first_page_text)
    if period_match:
        metadata.statement_period_start = datetime.strptime(period_match.group(1), "%Y%m%d").date()
        metadata.statement_period_end = datetime.strptime(period_match.group(2), "%Y%m%d").date()
        metadata.raw_fields["查询区间"] = period_match.group(0)
        for name in ("statement_period_start", "statement_period_end"):
            metadata.field_sources[name] = "first_page_text:查询区间"
            metadata.field_confidence[name] = 1.0

    account_name_match = re.search(
        r"户名\s*\(Account\s*Name\)\s*[:：]\s*(.+?)\s+币种\s*\(Currency\)",
        first_page_text,
        re.I,
    )
    if account_name_match:
        metadata.account_name = account_name_match.group(1).strip()
        metadata.raw_fields["户名 / Account Name"] = metadata.account_name
        metadata.field_sources["account_name"] = "first_page_text:户名 / Account Name"
        metadata.field_confidence["account_name"] = 1.0

    account_number_match = re.search(
        r"银行账号[（(]Bank\s+Accou?n?t[）)]\s*[:：]\s*([0-9*＊]+)",
        first_page_text,
        re.I,
    )
    if account_number_match:
        metadata.account_number = account_number_match.group(1).replace("＊", "*")
        metadata.raw_fields["银行账号 / Bank Account"] = metadata.account_number
        metadata.field_sources["account_number"] = "first_page_text:银行账号 / Bank Account"
        metadata.field_confidence["account_number"] = 1.0

    generated_at_match = re.search(
        r"申请时间\s*\(Print\s*Time\)\s*[:：]\s*(\d{4}/\d{1,2}/\d{1,2}\s+\d{1,2}:\d{2})",
        first_page_text,
        re.I,
    )
    if generated_at_match:
        metadata.generated_at = datetime.strptime(generated_at_match.group(1), "%Y/%m/%d %H:%M")
        metadata.raw_fields["申请时间 / Print Time"] = generated_at_match.group(1)
        metadata.field_sources["generated_at"] = "first_page_text:申请时间 / Print Time"
        metadata.field_confidence["generated_at"] = 1.0

    source_part_match = re.search(r"富滇交易明细\s*-\s*(文件\s*\d+)", first_page_text)
    if source_part_match:
        metadata.source_part_label = _compact(source_part_match.group(1))
        metadata.raw_fields["文件分段标识"] = metadata.source_part_label
        metadata.field_sources["source_part_label"] = "first_page_text:文件分段标识"
        metadata.field_confidence["source_part_label"] = 1.0

    page_total_match = re.search(r"共\s*(\d+)\s*页", first_page_text)
    if page_total_match:
        metadata.page_total = int(page_total_match.group(1))
        metadata.raw_fields["总页数"] = page_total_match.group(1)
        metadata.field_sources["page_total"] = "first_page_text:页码 / 总页数"
        metadata.field_confidence["page_total"] = 1.0
    elif page_count:
        metadata.page_total = page_count
        metadata.raw_fields["总页数"] = str(page_count)
        metadata.field_sources["page_total"] = "pdf.pages"
        metadata.field_confidence["page_total"] = 1.0

    return metadata


def _parse_remark_fields(remark: str) -> tuple[str, dict[str, object], dict[str, str]]:
    text = _standard_text(remark)
    matches = list(REMARK_LABEL_RE.finditer(text))
    if not matches:
        return "", {}, {}

    labeled: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        labeled[match.group(1)] = text[match.end() : end].strip(" ,，")

    merchant_name_and_address = labeled.get("商户名称及地址", "")
    merchant_name = merchant_name_and_address or labeled.get("商户", "")
    source_fields: dict[str, object] = {}
    source_labels: dict[str, str] = {}
    for field_name, label in (
        ("merchant_code", "商户代码"),
        ("merchant_name_and_address_raw", "商户名称及地址"),
        ("secondary_merchant_info", "二级商户信息"),
        ("postscript", "附言"),
    ):
        value = labeled.get(label, "")
        if value:
            source_fields[field_name] = _compact(value) if field_name in {"merchant_code", "secondary_merchant_info"} else value
            source_labels[field_name] = label

    remaining = {
        label: value
        for label, value in labeled.items()
        if label not in {"商户代码", "商户名称及地址", "二级商户信息", "附言", "商户"}
        and value
    }
    prefix = text[: matches[0].start()].strip(" ,，")
    if prefix:
        remaining["原文前缀"] = prefix
    if remaining:
        source_fields["remark_details"] = remaining
        source_labels["remark_details"] = "备注剩余结构"

    return merchant_name, source_fields, source_labels


def extract_fudian(pdf_path: str) -> TransactionList:
    transactions: list[Transaction] = []
    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return TransactionList()
        first_page_text = pdf.pages[0].extract_text() or ""
        first_page = _compact(first_page_text)
        if "富滇银行交易流水" not in first_page or "FudianBankTransactionDetails" not in first_page:
            return TransactionList()
        metadata = _parse_metadata(first_page_text, len(pdf.pages))

        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not table:
                    continue
                start_index = 1 if _is_target_table(table) else 0
                for row in table[start_index:]:
                    if len(row) < len(RAW_HEADERS):
                        continue
                    raw_fields = [_cell_text(value) for value in row[: len(RAW_HEADERS)]]
                    try:
                        sequence = int(_compact(raw_fields[0]))
                    except ValueError:
                        continue

                    tx_time = _parse_time(raw_fields[1])
                    amount = money_to_decimal(_compact(raw_fields[3]))
                    balance = money_to_decimal(_compact(raw_fields[4]))
                    if tx_time is None or amount is None or balance is None:
                        continue

                    merchant_name, source_fields, source_labels = _parse_remark_fields(raw_fields[8])
                    standard_values = {
                        "source_sequence": _compact(raw_fields[0]),
                        "counterparty_account": _compact(raw_fields[5]),
                        "counterparty_name": _standard_text(raw_fields[6]),
                        "summary": _standard_text(raw_fields[7]),
                        "remark": _standard_text(raw_fields[8]),
                        "merchant_name": merchant_name,
                    }
                    field_sources = {
                        name: f"raw_headers[{index}]:{RAW_HEADERS[index]}"
                        for name, index in (
                            ("source_sequence", 0),
                            ("counterparty_account", 5),
                            ("counterparty_name", 6),
                            ("summary", 7),
                            ("remark", 8),
                        )
                        if standard_values[name]
                    }
                    if merchant_name:
                        merchant_label = "商户名称及地址" if "merchant_name_and_address_raw" in source_fields else "商户"
                        field_sources["merchant_name"] = f"raw_headers[8]:{RAW_HEADERS[8]}#{merchant_label}"
                    for field_name, label in source_labels.items():
                        field_sources[field_name] = f"raw_headers[8]:{RAW_HEADERS[8]}#{label}"

                    transaction = Transaction(
                        transaction_time=tx_time,
                        income=amount.quantize(CENT) if amount > ZERO else ZERO,
                        expense=(-amount).quantize(CENT) if amount < ZERO else ZERO,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=sequence,
                        raw_time=raw_fields[1],
                        raw_amount=raw_fields[3],
                        raw_balance=raw_fields[4],
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=RAW_HEADERS,
                        counterparty_account=standard_values["counterparty_account"],
                        counterparty_name=standard_values["counterparty_name"],
                        summary=standard_values["summary"],
                        remark=standard_values["remark"],
                        merchant_name=standard_values["merchant_name"],
                        field_sources=field_sources,
                        field_confidence={name: 1.0 for name in field_sources},
                        source_sequence=standard_values["source_sequence"],
                        source_fields=source_fields,
                    )
                    transaction.merge_key = "|".join(
                        [raw_fields[0], raw_fields[1], raw_fields[3], raw_fields[4]]
                    )
                    transactions.append(transaction)
    return TransactionList(transactions, metadata)
