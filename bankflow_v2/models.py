import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


ZERO = Decimal("0.00")


STANDARD_TEXT_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "source_sequence": (
        "序号",
    ),
    "counterparty_name": (
        "对方户名",
        "对方账户名称",
        "对方账户名",
        "对手户名",
        "对手名称",
        "交易对方",
        "对方名称",
        "收(付)方名称",
        "收付方名称",
        "交易对手名称",
        "counterparty name",
    ),
    "counterparty_account": (
        "对方账号",
        "对方帐号",
        "对方账户",
        "对方卡号/账号",
        "对方卡号账号",
        "对手账号",
        "交易对方账号",
        "收(付)方账号",
        "收付方账号",
        "counterparty account",
    ),
    "counterparty_bank": (
        "对方开户行",
        "对方行名",
        "对手行名",
        "对方银行",
        "对方开户行名",
        "对方行名称",
        "counterparty bank",
    ),
    "summary": (
        "摘要",
        "交易摘要",
        "摘要信息",
        "摘要描述",
        "交易描述",
        "summary",
    ),
    "remark": (
        "备注",
        "附言",
        "remark",
    ),
    "purpose": (
        "用途",
        "交易用途",
        "purpose",
    ),
    "transaction_type": (
        "交易类型",
        "业务类型",
        "交易名称",
        "transaction type",
    ),
    "transaction_direction": (
        "收/支/其他",
        "收支或其他",
        "收/支",
        "收支",
        "收入/支出",
        "收支状态",
        "交易方向",
        "借贷标志",
        "借贷状态",
        "借/贷",
        "借贷",
    ),
    "transaction_method": (
        "交易方式",
    ),
    "payment_method": (
        "收/付款方式",
        "收付款方式",
        "付款方式",
    ),
    "product_description": (
        "商品说明",
    ),
    "merchant_name": (
        "商户名称",
        "商家名称",
        "merchant name",
    ),
    "merchant_category": (
        "商户类别",
        "商户分类",
        "merchant category",
    ),
    "merchant_location": (
        "商户地点",
        "merchant location",
    ),
}


def normalize_text_header(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s:/\\|_\-()（）\[\]【】]+", "", text)


NORMALIZED_TEXT_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    field_name: tuple(normalize_text_header(alias) for alias in aliases)
    for field_name, aliases in STANDARD_TEXT_HEADER_ALIASES.items()
}


SOURCE_FIELD_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "core_transaction_id": ("核心流水号",),
    "transaction_reference": ("交易流水号", "流水号"),
    "transaction_voucher_id": ("交易凭证号",),
    "voucher_number": ("凭证号码",),
    "voucher_type": ("凭证种类",),
    "posting_date": ("记账日期", "记账日"),
    "accounting_date": ("会计日期",),
    "detail_marker": ("明细标注",),
    "transaction_description": ("交易描述",),
    "transaction_branch": ("交易网点", "网点"),
    "record_source": ("来源",),
    "global_routing_number": ("全局路由号",),
    "card_number": ("卡号",),
}


NORMALIZED_SOURCE_FIELD_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    field_name: tuple(normalize_text_header(alias) for alias in aliases)
    for field_name, aliases in SOURCE_FIELD_HEADER_ALIASES.items()
}


def map_standard_text_fields(
    raw_headers: list[str] | tuple[str, ...] | None,
    raw_fields: list[str] | tuple[str, ...] | None,
) -> dict[str, tuple[str, str]]:
    """Map exact header synonyms to non-empty standard text values."""
    headers = list(raw_headers or [])
    fields = list(raw_fields or [])
    header_indices: dict[str, list[int]] = {}
    for index, header in enumerate(headers):
        header_indices.setdefault(normalize_text_header(header), []).append(index)
    mapped: dict[str, tuple[str, str]] = {}

    for field_name, aliases in NORMALIZED_TEXT_HEADER_ALIASES.items():
        for alias in aliases:
            for index in header_indices.get(alias, []):
                if index >= len(fields):
                    continue
                value = re.sub(r"\s+", " ", str(fields[index] or "")).strip()
                if not value:
                    continue
                mapped[field_name] = (value, f"raw_headers[{index}]:{headers[index]}")
                break
            if field_name in mapped:
                break

    return mapped


def map_source_fields(
    raw_headers: list[str] | tuple[str, ...] | None,
    raw_fields: list[str] | tuple[str, ...] | None,
) -> dict[str, tuple[str, str]]:
    """Map exact evidence-field headers without inferring from unstructured text."""
    headers = list(raw_headers or [])
    fields = list(raw_fields or [])
    header_indices: dict[str, list[int]] = {}
    for index, header in enumerate(headers):
        header_indices.setdefault(normalize_text_header(header), []).append(index)
    mapped: dict[str, tuple[str, str]] = {}

    for field_name, aliases in NORMALIZED_SOURCE_FIELD_HEADER_ALIASES.items():
        for alias in aliases:
            for index in header_indices.get(alias, []):
                if index >= len(fields):
                    continue
                value = re.sub(r"\s+", " ", str(fields[index] or "")).strip()
                if not value:
                    continue
                mapped[field_name] = (value, f"raw_headers[{index}]:{headers[index]}")
                break
            if field_name in mapped:
                break

    return mapped


@dataclass
class Transaction:
    transaction_time: datetime
    income: Decimal = ZERO
    expense: Decimal = ZERO
    balance: Decimal | None = None
    bank: str = ""
    page_no: int = 0
    row_no: int = 0
    raw_time: str = ""
    raw_amount: str = ""
    raw_balance: str = ""
    raw_text: str = ""
    raw_fields: list[str] = field(default_factory=list)
    raw_headers: list[str] = field(default_factory=list)
    status: str = "ok"
    issues: list[str] = field(default_factory=list)
    counterparty_name: str = ""
    counterparty_account: str = ""
    counterparty_bank: str = ""
    summary: str = ""
    remark: str = ""
    purpose: str = ""
    transaction_type: str = ""
    transaction_direction: str = ""
    transaction_method: str = ""
    payment_method: str = ""
    product_description: str = ""
    merchant_name: str = ""
    merchant_category: str = ""
    merchant_location: str = ""
    field_sources: dict[str, str] = field(default_factory=dict)
    field_confidence: dict[str, float] = field(default_factory=dict)
    manual_review: dict[str, str] = field(default_factory=dict)
    source_sequence: str = ""
    source_fields: dict[str, object] = field(default_factory=dict)
    source_file: str = ""
    source_file_id: str = ""
    evidence_locator: str = ""
    transaction_id: str = ""

    def __post_init__(self) -> None:
        mapped_fields = map_standard_text_fields(self.raw_headers, self.raw_fields)
        for field_name, (value, source) in mapped_fields.items():
            if getattr(self, field_name):
                continue
            setattr(self, field_name, value)
            self.field_sources.setdefault(field_name, source)
            self.field_confidence.setdefault(field_name, 1.0)

        mapped_source_fields = map_source_fields(self.raw_headers, self.raw_fields)
        for field_name, (value, source) in mapped_source_fields.items():
            self.source_fields.setdefault(field_name, value)
            self.field_sources.setdefault(field_name, source)
            self.field_confidence.setdefault(field_name, 1.0)

    @property
    def amount(self) -> Decimal:
        return self.income - self.expense


@dataclass
class StatementMetadata:
    account_name: str = ""
    account_number: str = ""
    statement_period_start: date | None = None
    statement_period_end: date | None = None
    generated_at: datetime | None = None
    source_part_label: str = ""
    page_total: int | None = None
    raw_fields: dict[str, str] = field(default_factory=dict)
    field_sources: dict[str, str] = field(default_factory=dict)
    field_confidence: dict[str, float] = field(default_factory=dict)
    manual_review: dict[str, str] = field(default_factory=dict)


class TransactionList(list[Transaction]):
    """List-compatible parser result with file-level statement metadata."""

    def __init__(
        self,
        transactions: list[Transaction] | tuple[Transaction, ...] | None = None,
        metadata: StatementMetadata | None = None,
    ) -> None:
        super().__init__(transactions or [])
        self.metadata = metadata or StatementMetadata()


def get_statement_metadata(transactions: object) -> StatementMetadata:
    metadata = getattr(transactions, "metadata", None)
    return metadata if isinstance(metadata, StatementMetadata) else StatementMetadata()
