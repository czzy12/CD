import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


BANK_NAME = "中国光大银行个人"
CORP_BANK_NAME = "中国光大银行对公"
CENT = Decimal("0.01")
ZERO = Decimal("0.00")

CORP_ROW_RE = re.compile(
    r"^(?P<seq>\d+)\s+"
    r"(?P<date>20\d{6})\s+"
    r"(?P<time>\d{6})\s+"
    r"(?P<direction>借方|贷方)\s+"
    r"(?P<amount>\d[\d,]*\.\d{2})\s+"
    r"(?P<balance>\d[\d,]*\.\d{2})(?:\s+(?P<rest>.*))?$"
)


def _clean_cell(value) -> str:
    return str(value or "").replace("\n", " ").strip()


def _compact(value) -> str:
    return _clean_cell(value).replace(" ", "")


def _money(value) -> Decimal | None:
    return money_to_decimal(_clean_cell(value))


def _parse_personal_date(raw: str) -> datetime | None:
    try:
        return datetime.strptime(_clean_cell(raw), "%Y-%m-%d")
    except ValueError:
        return None


def _parse_corp_time(raw_date: str, raw_time: str) -> datetime | None:
    try:
        return datetime.strptime(f"{raw_date} {raw_time}", "%Y%m%d %H%M%S")
    except ValueError:
        return None


def _is_personal_table(table: list[list]) -> bool:
    if not table:
        return False
    header = "".join(_compact(cell) for cell in table[0])
    return (
        "TransDate" in header
        and "TransAmtDr" in header
        and "TransAmtCr" in header
        and "AccountBalance" in header
    )


def extract_everbright(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for table in page.extract_tables():
                if not _is_personal_table(table):
                    continue

                headers = [_clean_cell(cell) for cell in table[0]]
                for row in table[1:]:
                    fields = [_clean_cell(cell) for cell in row]
                    if len(fields) < 4:
                        continue

                    tx_time = _parse_personal_date(fields[0])
                    expense = _money(fields[1]) or ZERO
                    income = _money(fields[2]) or ZERO
                    balance = _money(fields[3])
                    if tx_time is None or balance is None or (income == ZERO and expense == ZERO):
                        continue

                    issues: list[str] = []
                    if income > ZERO and expense > ZERO:
                        issues.append("存入金额和支出金额同时有值")

                    sequence += 1
                    tx = Transaction(
                        transaction_time=tx_time,
                        income=income.quantize(CENT),
                        expense=expense.quantize(CENT),
                        balance=balance.quantize(CENT),
                        bank=BANK_NAME,
                        page_no=1,
                        row_no=-sequence,
                        raw_time=fields[0],
                        raw_amount=f"支出:{fields[1]} 存入:{fields[2]}",
                        raw_balance=fields[3],
                        raw_text=" | ".join(fields),
                        raw_fields=fields,
                        raw_headers=headers,
                        status="ok" if not issues else "review",
                        issues=issues,
                    )
                    tx.merge_key = "|".join([fields[0], fields[1], fields[2], fields[3], str(page_index), str(sequence)])
                    transactions.append(tx)

    return transactions


def extract_everbright_corp(pdf_path: str) -> list[Transaction]:
    transactions: list[Transaction] = []
    sequence = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            for line_no, raw_line in enumerate((page.extract_text() or "").splitlines(), start=1):
                line = " ".join(raw_line.strip().split())
                match = CORP_ROW_RE.match(line)
                if not match:
                    continue

                tx_time = _parse_corp_time(match.group("date"), match.group("time"))
                amount = _money(match.group("amount"))
                balance = _money(match.group("balance"))
                if tx_time is None or amount is None or balance is None:
                    continue

                direction = match.group("direction")
                income = amount if direction == "贷方" else ZERO
                expense = amount if direction == "借方" else ZERO

                sequence += 1
                tx = Transaction(
                    transaction_time=tx_time,
                    income=income.quantize(CENT),
                    expense=expense.quantize(CENT),
                    balance=balance.quantize(CENT),
                    bank=CORP_BANK_NAME,
                    page_no=1,
                    row_no=-sequence,
                    raw_time=f"{match.group('date')} {match.group('time')}",
                    raw_amount=f"{direction}:{match.group('amount')}",
                    raw_balance=match.group("balance"),
                    raw_text=line,
                    raw_fields=[
                        match.group("seq"),
                        match.group("date"),
                        match.group("time"),
                        direction,
                        match.group("amount"),
                        match.group("balance"),
                        match.group("rest") or "",
                    ],
                    raw_headers=["序号", "交易日期", "时间", "借/贷", "交易金额", "账户余额", "其余字段"],
                )
                tx.merge_key = "|".join([match.group("seq"), match.group("date"), match.group("time"), str(page_index)])
                transactions.append(tx)

    return transactions
