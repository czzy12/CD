import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import StatementMetadata, Transaction, TransactionList


BANK_NAME = "华夏银行"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
RAW_HEADERS = ["记账日期", "摘要", "交易金额", "余额", "交易机构", "对方姓名", "对方卡/账号", "对方开户行", "附言"]
COLUMN_LEFTS = (35.0, 75.0, 125.0, 180.0, 218.0, 265.0, 340.0, 415.0, 480.0)
KNOWN_HEADER_TITLES = (
    "记账日期",
    "摘要",
    "交易金额",
    "余额",
    "交易机构",
    "对方姓名",
    "对方卡/账号",
    "对方开户行",
    "附言",
)


def _parse_money(text: str) -> Decimal | None:
    try:
        return Decimal(str(text).replace(",", "")).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _normalize_reverse_printed(rows: list[Transaction]) -> list[Transaction]:
    if len(rows) < 2:
        return rows

    reverse_printed = rows[0].transaction_time.date() > rows[-1].transaction_time.date()
    rows = sorted(rows, key=lambda tx: (tx.transaction_time.date(), -tx.row_no if reverse_printed else tx.row_no))
    for index, tx in enumerate(rows, start=1):
        tx.transaction_time = tx.transaction_time + timedelta(seconds=index)
        tx.raw_time = tx.transaction_time.strftime("%Y-%m-%d %H:%M:%S")
    return rows


def _normalize_header_title(value: str) -> str:
    return value.replace("/", "").replace(" ", "")


def _detect_column_lefts(words: list[dict]) -> list[float] | None:
    """Detect column x origins from the Chinese header row (6 or 9 columns)."""
    date_words = [
        word for word in words if str(word["text"]) == "记账日期"
    ]
    if not date_words:
        return None
    top = float(date_words[0]["top"])
    header_words = [
        word for word in words
        if abs(float(word["top"]) - top) < 3.0
        and any("\u4e00" <= char <= "\u9fff" for char in str(word["text"]))
    ]
    if not header_words:
        return None
    clusters: list[list[dict]] = []
    for word in sorted(header_words, key=lambda item: float(item["x0"])):
        if clusters and float(word["x0"]) - float(clusters[-1][-1]["x0"]) < 25.0:
            clusters[-1].append(word)
        else:
            clusters.append([word])
    matched: list[tuple[str, float]] = []
    known = {
        _normalize_header_title(title): title
        for title in KNOWN_HEADER_TITLES
    }
    for cluster in clusters:
        text = "".join(str(word["text"]) for word in cluster)
        normalized = _normalize_header_title(text)
        title = known.get(normalized)
        if title is not None:
            matched.append((title, min(float(word["x0"]) for word in cluster)))
    if not matched or "记账日期" not in {title for title, _ in matched}:
        return None
    return [x0 for _, x0 in sorted(matched, key=lambda item: item[1])]


def _table_column_lefts(page) -> list[float] | None:
    """Read column x boundaries from the extracted table geometry."""
    try:
        tables = page.find_tables()
    except Exception:
        return None
    for table in tables:
        if not table.rows:
            continue
        cells = [cell for cell in table.rows[0].cells if cell]
        if len(cells) >= 5:
            return [float(cell[0]) for cell in cells]
    return None


def _column_index(x0: float, lefts: list[float] | None = None) -> int | None:
    boundaries = lefts or list(COLUMN_LEFTS)
    for index in range(len(boundaries) - 1, -1, -1):
        if x0 >= boundaries[index] - 2.0 and (
            index + 1 >= len(boundaries) or x0 < boundaries[index + 1]
        ):
            return index
    return None


def _join_words(words: list[dict]) -> str:
    lines: dict[float, list[dict]] = {}
    for word in words:
        lines.setdefault(round(float(word["top"]), 1), []).append(word)
    return "\n".join(
        " ".join(str(word["text"]) for word in sorted(lines[top], key=lambda item: float(item["x0"])))
        for top in sorted(lines)
    ).strip()


def _extract_page_rows(page) -> tuple[list[list[str]], list[float]]:
    words = page.extract_words(use_text_flow=False, keep_blank_chars=False)
    lefts = _table_column_lefts(page) or _detect_column_lefts(words)
    if lefts is None:
        lefts = list(COLUMN_LEFTS)
    if len(lefts) >= 9:
        column_semantics = (0, 1, 2, 3, 4, 5, 6, 7, 8)
    else:
        column_semantics = (0, 1, 2, 3, 4, 8)
    date_left = lefts[0]
    date_right = lefts[1] if len(lefts) > 1 else date_left + 25.0
    anchors = sorted(
        (
            word for word in words
            if date_left - 5.0 <= float(word["x0"]) < date_right
            and DATE_RE.fullmatch(str(word["text"]))
        ),
        key=lambda word: float(word["top"]),
    )
    rows: list[list[str]] = []
    for index, anchor in enumerate(anchors):
        top = float(anchor["top"])
        previous_gap = top - float(anchors[index - 1]["top"]) if index else None
        next_gap = float(anchors[index + 1]["top"]) - top if index + 1 < len(anchors) else None
        start = top - ((previous_gap if previous_gap is not None else next_gap or 24.0) / 2)
        end = top + ((next_gap if next_gap is not None else previous_gap or 24.0) / 2)
        columns: list[list[dict]] = [[] for _ in RAW_HEADERS]
        for word in words:
            word_top = float(word["top"])
            if not (start <= word_top < end):
                continue
            column = _column_index(float(word["x0"]), lefts)
            if column is not None and column < len(column_semantics):
                columns[column_semantics[column]].append(word)
        rows.append([_join_words(column_words) for column_words in columns])
    return rows, lefts


def extract_huaxia(pdf_path: str) -> TransactionList:
    rows: list[Transaction] = []
    diagnostics = {
        "source_row_count": 0,
        "parsed_transaction_count": 0,
        "skipped_row_count": 0,
        "unparsed_row_count": 0,
        "ignored_non_transaction_row_count": 0,
        "review_row_count": 0,
        "unsupported_row_count": 0,
    }
    metadata = StatementMetadata()
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            if page_no == 1:
                first_text = page.extract_text() or ""
                match = re.search(r"户名[:：]\s*([^\s（(，,：:]+)", first_text)
                if match:
                    metadata.account_name = match.group(1).strip()
                    metadata.field_sources["account_name"] = "document_header:户名"
                    metadata.field_confidence["account_name"] = 1.0
                account_match = re.search(r"账号[:：]\s*([0-9*]+)", first_text)
                if account_match:
                    account_raw = account_match.group(1).strip()
                    if "*" not in account_raw:
                        metadata.account_number = account_raw
                        metadata.field_sources["account_number"] = "document_header:账号"
                        metadata.field_confidence["account_number"] = 1.0
                    else:
                        metadata.raw_fields["masked_account_number"] = account_raw
                        metadata.field_sources["masked_account_number"] = "document_header:账号"
                        metadata.field_confidence["masked_account_number"] = 1.0
            page_rows, _lefts = _extract_page_rows(page)
            diagnostics["source_row_count"] += len(page_rows)
            for raw_fields in page_rows:
                if len(raw_fields) != len(RAW_HEADERS):
                    diagnostics["skipped_row_count"] += 1
                    diagnostics["unparsed_row_count"] += 1
                    continue
                amount = _parse_money(raw_fields[2])
                balance = _parse_money(raw_fields[3])
                if amount is None or balance is None:
                    diagnostics["skipped_row_count"] += 1
                    diagnostics["unparsed_row_count"] += 1
                    continue
                try:
                    tx_time = datetime.strptime(raw_fields[0], "%Y-%m-%d")
                except ValueError:
                    diagnostics["skipped_row_count"] += 1
                    diagnostics["unparsed_row_count"] += 1
                    continue

                row_no = len(rows) + 1
                transaction_institution = raw_fields[4]
                source_fields = (
                    {"transaction_institution": transaction_institution}
                    if transaction_institution
                    else {}
                )
                tx = Transaction(
                    transaction_time=tx_time,
                    income=amount if amount >= ZERO else ZERO,
                    expense=-amount if amount < ZERO else ZERO,
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=row_no,
                    raw_time=raw_fields[0],
                    raw_amount=raw_fields[2],
                    raw_balance=raw_fields[3],
                    raw_text=" | ".join(raw_fields),
                    raw_fields=raw_fields,
                    raw_headers=RAW_HEADERS,
                    source_fields=source_fields,
                    field_sources=(
                        {"transaction_institution": "raw_headers[4]:交易机构"}
                        if transaction_institution
                        else {}
                    ),
                    field_confidence=(
                        {"transaction_institution": 1.0}
                        if transaction_institution
                        else {}
                    ),
                )
                tx.counterparty_bank = ""
                tx.field_sources.pop("counterparty_bank", None)
                tx.field_confidence.pop("counterparty_bank", None)
                tx.merge_key = "|".join([raw_fields[0], raw_fields[2], raw_fields[3], str(page_no), str(row_no)])
                rows.append(tx)
                diagnostics["parsed_transaction_count"] += 1
                if tx.status == "review":
                    diagnostics["review_row_count"] += 1

    rows = _normalize_reverse_printed(rows)
    diagnostics["parsed_transaction_count"] = len(rows)
    return TransactionList(rows, metadata=metadata, diagnostics=diagnostics)
