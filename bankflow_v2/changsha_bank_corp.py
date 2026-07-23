import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "长沙银行对公"
ZERO = Decimal("0.00")
CENT = Decimal("0.01")
RAW_HEADERS = ["交易日期", "交易金额", "账户余额", "摘要/备注", "编号"]
COLUMNS = {
    "date": (20, 85),
    "amount": (105, 190),
    "balance": (220, 295),
    "memo": (330, 455),
    "number": (455, 570),
}


def _compact(text: object) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _money(text: str) -> Decimal | None:
    try:
        return Decimal(text.replace(",", "")).quantize(CENT)
    except (InvalidOperation, ValueError):
        return None


def _parse_date(text: str, sequence: int) -> datetime | None:
    if not re.fullmatch(r"20\d{6}", text):
        return None
    try:
        parsed = datetime.strptime(text, "%Y%m%d")
    except ValueError:
        return None
    return parsed.replace(microsecond=sequence)


def _column_text(words: list[dict], column: str, top: float, bottom: float) -> str:
    x0, x1 = COLUMNS[column]
    selected = [
        word
        for word in words
        if x0 <= float(word["x0"]) <= x1 and top <= float(word["top"]) < bottom
    ]
    return " ".join(word["text"] for word in sorted(selected, key=lambda item: (float(item["top"]), float(item["x0"]))))


def _date_anchors(words: list[dict]) -> list[tuple[float, str]]:
    anchors: list[tuple[float, str]] = []
    for word in words:
        text = word.get("text", "")
        if (
            re.fullmatch(r"20\d{6}", text)
            and COLUMNS["date"][0] <= float(word["x0"]) <= COLUMNS["date"][1]
            and float(word["top"]) > 150
        ):
            anchors.append((float(word["top"]), text))
    return sorted(anchors)


def _is_target_statement(text: str) -> bool:
    compact = _compact(text)
    return (
        "单位账户明细对账单" in compact
        and "账户名称" in compact
        and "客户账号" in compact
        and "账单期初余额" in compact
        and "账单期末余额" in compact
        and "交易日期交易金额账户余额摘要/备注编号" in compact
    )


def _header_balances(text: str) -> tuple[Decimal | None, Decimal | None]:
    match = re.search(r"账单期初余额[:：]\s*([\d,.]+)\s+账单期末余额[:：]\s*([\d,.]+)", text)
    if not match:
        return None, None
    return _money(match.group(1)), _money(match.group(2))


def _footer_totals(text: str) -> tuple[Decimal | None, Decimal | None]:
    match = re.search(r"收入合计[:：]\s*([\d,.]+)\s+支出合计[:：]\s*([\d,.]+)", text)
    if not match:
        return None, None
    return _money(match.group(1)), _money(match.group(2))


def _footer_count(text: str) -> int | None:
    matches = re.findall(r"第\d+页，共\d+页/第(\d+)笔，共(\d+)笔", text)
    if not matches:
        return None
    return int(matches[-1][1])


def _add_statement_issues(
    transactions: list[Transaction],
    expected_count: int | None,
    expected_income: Decimal | None,
    expected_expense: Decimal | None,
    expected_opening: Decimal | None,
    expected_closing: Decimal | None,
) -> None:
    if not transactions:
        return
    issues: list[str] = []
    income = sum((tx.income for tx in transactions), ZERO).quantize(CENT)
    expense = sum((tx.expense for tx in transactions), ZERO).quantize(CENT)
    opening = (transactions[0].balance - transactions[0].income + transactions[0].expense).quantize(CENT)
    closing = transactions[-1].balance.quantize(CENT)

    if expected_count is not None and len(transactions) != expected_count:
        issues.append(f"交易笔数与页脚不一致: 解析 {len(transactions)} / 页脚 {expected_count}")
    if expected_income is not None and income != expected_income:
        issues.append(f"收入合计与页脚不一致: 解析 {income:.2f} / 页脚 {expected_income:.2f}")
    if expected_expense is not None and expense != expected_expense:
        issues.append(f"支出合计与页脚不一致: 解析 {expense:.2f} / 页脚 {expected_expense:.2f}")
    if expected_opening is not None and opening != expected_opening:
        issues.append(f"期初余额与页眉不一致: 解析 {opening:.2f} / 页眉 {expected_opening:.2f}")
    if expected_closing is not None and closing != expected_closing:
        issues.append(f"期末余额与页眉不一致: 解析 {closing:.2f} / 页眉 {expected_closing:.2f}")

    if issues:
        first = transactions[0]
        first.status = "review"
        first.issues.extend(issues)


def extract_changsha_bank_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    expected_count: int | None = None
    expected_income: Decimal | None = None
    expected_expense: Decimal | None = None
    expected_opening: Decimal | None = None
    expected_closing: Decimal | None = None
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return transactions
        first_text = pdf.pages[0].extract_text() or ""
        if not _is_target_statement(first_text):
            return transactions
        expected_opening, expected_closing = _header_balances(first_text)

        for page_no, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            footer_income, footer_expense = _footer_totals(page_text)
            if footer_income is not None:
                expected_income = footer_income
                expected_expense = footer_expense
            footer_count = _footer_count(page_text)
            if footer_count is not None:
                expected_count = footer_count

            words = page.extract_words()
            anchors = _date_anchors(words)
            for index, (top, raw_date) in enumerate(anchors):
                next_top = anchors[index + 1][0] if index + 1 < len(anchors) else 735
                band_top = max(150, top - 5)
                band_bottom = next_top - 1
                raw_amount = _column_text(words, "amount", band_top, band_bottom)
                raw_balance = _column_text(words, "balance", band_top, band_bottom)
                memo = _column_text(words, "memo", band_top, band_bottom)
                number = _column_text(words, "number", band_top, band_bottom)

                sequence += 1
                tx_time = _parse_date(raw_date, sequence)
                amount = _money(raw_amount)
                balance = _money(raw_balance)
                if tx_time is None or amount is None or balance is None:
                    continue

                raw_fields = [raw_date, raw_amount, raw_balance, memo, number]
                source_fields = {"summary_remark_raw": memo} if memo else {}
                transaction = Transaction(
                    transaction_time=tx_time,
                    income=amount if amount > ZERO else ZERO,
                    expense=-amount if amount < ZERO else ZERO,
                    balance=balance,
                    bank=BANK_NAME,
                    page_no=page_no,
                    row_no=sequence,
                    raw_time=f"{raw_date} 00:00:00",
                    raw_amount=raw_amount,
                    raw_balance=raw_balance,
                    raw_text=" | ".join(raw_fields),
                    raw_fields=raw_fields,
                    raw_headers=RAW_HEADERS,
                    source_fields=source_fields,
                    field_sources={"summary_remark_raw": "raw_headers[3]:摘要/备注"} if memo else {},
                    field_confidence={"summary_remark_raw": 1.0} if memo else {},
                )
                transaction.merge_key = "|".join([str(sequence), raw_date, raw_amount, raw_balance, number])
                transactions.append(transaction)

    _add_statement_issues(
        transactions,
        expected_count,
        expected_income,
        expected_expense,
        expected_opening,
        expected_closing,
    )
    return transactions
