import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber

from .models import Transaction


BANK_NAME = "农村信用社"
HEBEI_RURAL_BANK_NAME = "河北省农村信用社联合社"
RURAL_COMMERCIAL_BANK_NAME = "农村商业银行个人"
MONEY_RE = re.compile(r"[\d,]+\.\d{2}")
CENT = Decimal("0.01")
HEBEI_HISTORY_HEADERS = ["序号", "交易日期", "交易金额", "金额", "对方户名", "对方账号", "摘要", "网点", "来源"]
LINE_ROW_RE = re.compile(
    r"^\s*(?P<seq>\d+)\s+"
    r"(?P<summary>.+?)\s+人民币元\s+钞\s+"
    r"(?P<date>20\d{6})\s+"
    r"(?P<amount>-?\d[\d,]*\.\d{2})\s+"
    r"(?P<balance>\d[\d,]*\.\d{2})"
    r"(?:\s+(?P<tail>.*))?$"
)
HEADER_TOTAL_RE = re.compile(
    r"总收入:([\d,.]+)\s+总收入笔数：(\d+)\s+总支出：(-?[\d,.]+)\s+总支出笔数：(\d+)"
)
FOOTER_PAGE_RE = re.compile(r"当前页：(\d+)\s+总页数：(\d+)")


def _cell(row: list[str], index: int) -> str:
    if index >= len(row) or row[index] is None:
        return ""
    return str(row[index]).strip()


def _compact(text: object) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _cell_line(text: object) -> str:
    return " ".join(str(text or "").split())


def _money(text: str) -> Decimal | None:
    match = MONEY_RE.search(text or "")
    if not match:
        return None
    return Decimal(match.group(0).replace(",", "")).quantize(Decimal("0.01"))


def _signed_money(text: str) -> Decimal:
    return Decimal(text.replace(",", "")).quantize(CENT)


def _time(text: str) -> datetime | None:
    try:
        return datetime.strptime(text.strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _date_time(raw_date: str, sequence: int) -> datetime:
    parsed = datetime.strptime(raw_date, "%Y%m%d")
    return parsed.replace(microsecond=max(0, 999999 - sequence))


def _date(raw_date: str) -> datetime:
    return datetime.strptime(raw_date, "%Y%m%d")


def _rural_commercial_bank_name(text: str) -> str:
    match = re.search(r"([\u4e00-\u9fa5]{2,20}农村商业银行)", text)
    if match:
        return f"{match.group(1)}个人"
    return RURAL_COMMERCIAL_BANK_NAME


def _extract_line_statement(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    header_totals: tuple[Decimal, int, Decimal, int] | None = None
    max_current_page = 0
    footer_total_pages = 0
    bank_name = RURAL_COMMERCIAL_BANK_NAME

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if bank_name == RURAL_COMMERCIAL_BANK_NAME:
                bank_name = _rural_commercial_bank_name(text)
            if header_totals is None:
                header_match = HEADER_TOTAL_RE.search(text)
                if header_match:
                    header_totals = (
                        _signed_money(header_match.group(1)),
                        int(header_match.group(2)),
                        _signed_money(header_match.group(3)),
                        int(header_match.group(4)),
                    )
            footer_match = FOOTER_PAGE_RE.search(text)
            if footer_match:
                max_current_page = max(max_current_page, int(footer_match.group(1)))
                footer_total_pages = max(footer_total_pages, int(footer_match.group(2)))

            for line_no, raw_line in enumerate(text.splitlines(), start=1):
                match = LINE_ROW_RE.match(raw_line.strip())
                if not match:
                    continue

                sequence = int(match.group("seq"))
                amount = _signed_money(match.group("amount"))
                balance = _signed_money(match.group("balance"))
                raw_tail = match.group("tail") or ""
                raw_fields = [
                    match.group("seq"),
                    match.group("summary"),
                    "人民币元",
                    "钞",
                    match.group("date"),
                    match.group("amount"),
                    match.group("balance"),
                    raw_tail,
                ]
                tx = Transaction(
                    transaction_time=_date_time(match.group("date"), sequence),
                    income=amount if amount > 0 else Decimal("0.00"),
                    expense=-amount if amount < 0 else Decimal("0.00"),
                    balance=balance,
                    bank=bank_name,
                    page_no=page_no,
                    row_no=sequence,
                    raw_time=f"{match.group('date')} 00:00:00",
                    raw_amount=match.group("amount"),
                    raw_balance=match.group("balance"),
                    raw_text=raw_line.strip(),
                    raw_fields=raw_fields,
                    raw_headers=["序号", "摘要", "币别", "钞汇", "交易日期", "交易金额", "账户余额", "交易地点/附言 对方账号与户名"],
                )
                tx.merge_key = "|".join([match.group("seq"), match.group("date"), match.group("amount"), match.group("balance")])
                rows.append(tx)

    if rows:
        _add_line_statement_issues(rows, header_totals, max_current_page, footer_total_pages)
    return rows


def _add_line_statement_issues(
    rows: list[Transaction],
    header_totals: tuple[Decimal, int, Decimal, int] | None,
    current_pages: int,
    total_pages: int,
) -> None:
    issues: list[str] = []
    if total_pages and current_pages and current_pages < total_pages:
        issues.append(f"PDF页数不完整: 当前文件 {current_pages} 页 / 页脚总页数 {total_pages} 页")

    if header_totals is not None:
        expected_income, expected_income_count, expected_expense_signed, expected_expense_count = header_totals
        income = sum((tx.income for tx in rows), Decimal("0.00")).quantize(CENT)
        expense = sum((tx.expense for tx in rows), Decimal("0.00")).quantize(CENT)
        income_count = sum(1 for tx in rows if tx.income > 0)
        expense_count = sum(1 for tx in rows if tx.expense > 0)
        expected_expense = (-expected_expense_signed).quantize(CENT)

        if income_count != expected_income_count:
            issues.append(f"收入笔数与页眉不一致: 解析 {income_count} / 页眉 {expected_income_count}")
        if expense_count != expected_expense_count:
            issues.append(f"支出笔数与页眉不一致: 解析 {expense_count} / 页眉 {expected_expense_count}")
        if income != expected_income:
            issues.append(f"收入合计与页眉不一致: 解析 {income:.2f} / 页眉 {expected_income:.2f}")
        if expense != expected_expense:
            issues.append(f"支出合计与页眉不一致: 解析 {expense:.2f} / 页眉 {expected_expense:.2f}")

    if issues:
        first = rows[0]
        first.status = "review"
        first.issues.extend(issues)


def _is_hebei_history_header(row: list[str]) -> bool:
    return [_compact(value) for value in row[: len(HEBEI_HISTORY_HEADERS)]] == HEBEI_HISTORY_HEADERS


def _extract_hebei_history_statement(pdf_path: str) -> list[Transaction]:
    rows: list[Transaction] = []
    header_total: int | None = None

    with pdfplumber.open(pdf_path) as pdf:
        if not pdf.pages:
            return rows

        first_text = _compact(pdf.pages[0].extract_text() or "")
        if "河北省农村信用社联合社账户历史明细清单" not in first_text:
            return rows
        total_match = re.search(r"总条数[:：](\d+)", first_text)
        if total_match:
            header_total = int(total_match.group(1))

        saw_header = False
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not table:
                    continue
                for row in table:
                    if len(row) < len(HEBEI_HISTORY_HEADERS):
                        continue
                    if _is_hebei_history_header(row):
                        saw_header = True
                        continue

                    raw_fields = [_cell_line(value) for value in row[: len(HEBEI_HISTORY_HEADERS)]]
                    sequence_text = _compact(raw_fields[0])
                    raw_date = _compact(raw_fields[1])
                    raw_amount = _compact(raw_fields[2]).replace(",", "")
                    raw_balance = _compact(raw_fields[3]).replace(",", "")
                    if not sequence_text.isdigit() or not re.fullmatch(r"20\d{6}", raw_date):
                        continue
                    try:
                        signed_amount = Decimal(raw_amount).quantize(CENT)
                        balance = Decimal(raw_balance).quantize(CENT)
                    except (InvalidOperation, ValueError):
                        continue

                    tx = Transaction(
                        transaction_time=_date(raw_date),
                        income=signed_amount if signed_amount > 0 else Decimal("0.00"),
                        expense=-signed_amount if signed_amount < 0 else Decimal("0.00"),
                        balance=balance,
                        bank=HEBEI_RURAL_BANK_NAME,
                        page_no=page_no,
                        row_no=int(sequence_text),
                        raw_time=f"{raw_date} 00:00:00",
                        raw_amount=raw_fields[2],
                        raw_balance=raw_fields[3],
                        raw_text=" | ".join(raw_fields),
                        raw_fields=raw_fields,
                        raw_headers=HEBEI_HISTORY_HEADERS,
                        source_fields={
                            field_name: raw_fields[index]
                            for field_name, index in (("transaction_branch", 7), ("record_source", 8))
                            if raw_fields[index]
                        },
                        field_sources={
                            field_name: f"raw_headers[{index}]:{HEBEI_HISTORY_HEADERS[index]}"
                            for field_name, index in (("transaction_branch", 7), ("record_source", 8))
                            if raw_fields[index]
                        },
                        field_confidence={
                            field_name: 1.0
                            for field_name, index in (("transaction_branch", 7), ("record_source", 8))
                            if raw_fields[index]
                        },
                    )
                    tx.merge_key = "|".join([sequence_text, raw_date, raw_fields[2], raw_fields[3]])
                    rows.append(tx)

    if not rows or not saw_header:
        return []

    _order_hebei_history_rows(rows, header_total)
    return rows


def _order_hebei_history_rows(rows: list[Transaction], header_total: int | None) -> None:
    issues: list[str] = []
    sequences = sorted(tx.row_no for tx in rows)
    if sequences != list(range(1, len(rows) + 1)):
        issues.append("序号不连续")
    if header_total is not None and len(rows) != header_total:
        issues.append(f"交易笔数与页眉不一致: 解析 {len(rows)} / 页眉 {header_total}")

    newest_first = sorted(rows, key=lambda tx: tx.row_no)
    oldest = newest_first[-1]
    previous_balance = (oldest.balance - oldest.income + oldest.expense).quantize(CENT)

    groups: dict[object, list[Transaction]] = defaultdict(list)
    for tx in rows:
        groups[tx.transaction_time.date()].append(tx)

    chain_order = 0
    unresolved = False
    for date_key in sorted(groups):
        remaining = groups[date_key][:]
        while remaining:
            matches = [
                tx
                for tx in remaining
                if (previous_balance + tx.income - tx.expense).quantize(CENT) == tx.balance
            ]
            if not matches:
                unresolved = True
                for tx in sorted(remaining, key=lambda item: item.row_no, reverse=True):
                    tx.transaction_time = tx.transaction_time.replace(microsecond=chain_order)
                    chain_order += 1
                break

            tx = sorted(matches, key=lambda item: item.row_no, reverse=True)[0]
            remaining.remove(tx)
            tx.transaction_time = tx.transaction_time.replace(microsecond=chain_order)
            chain_order += 1
            previous_balance = tx.balance

    if unresolved:
        issues.append("同日交易无法完全按余额链恢复顺序")
    if issues:
        first = newest_first[0]
        first.status = "review"
        first.issues.extend(issues)


def extract_rural_credit(pdf_path: str) -> list[Transaction]:
    hebei_history_rows = _extract_hebei_history_statement(pdf_path)
    if hebei_history_rows:
        return hebei_history_rows

    line_rows = _extract_line_statement(pdf_path)
    if line_rows:
        return line_rows

    rows: list[Transaction] = []
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                for row in table:
                    if len(row) < 6 or _cell(row, 1) == "交易日期":
                        continue

                    tx_time = _time(_cell(row, 1))
                    amount = _money(_cell(row, 4))
                    balance = _money(_cell(row, 5))
                    direction = _cell(row, 3)
                    if tx_time is None or amount is None or balance is None:
                        continue
                    if direction not in ("收入", "支出"):
                        continue

                    sequence += 1
                    # The PDF is printed newest-first. Microseconds make rows
                    # with the same second sort back into balance-chain order.
                    sort_time = tx_time.replace(microsecond=max(0, 999999 - sequence))
                    income = amount if direction == "收入" else Decimal("0.00")
                    expense = amount if direction == "支出" else Decimal("0.00")
                    tx = Transaction(
                        transaction_time=sort_time,
                        income=income,
                        expense=expense,
                        balance=balance,
                        bank=BANK_NAME,
                        page_no=page_no,
                        row_no=sequence,
                        raw_time=_cell(row, 1),
                        raw_amount=_cell(row, 4),
                        raw_balance=_cell(row, 5),
                        raw_text=" ".join(_cell(row, index) for index in range(min(len(row), 11))),
                        raw_fields=[_cell(row, index) for index in range(len(row))],
                        raw_headers=["交易流水号", "交易日期", "交易网点", "收入/支出", "交易金额", "实时余额", "交易渠道", "对方户名", "对方账号", "对方行名称", "备注"],
                    )
                    tx.merge_key = "|".join([_cell(row, 0), _cell(row, 1), direction, _cell(row, 4), _cell(row, 5), str(page_no), str(sequence)])
                    rows.append(tx)

    return rows
