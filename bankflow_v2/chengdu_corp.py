import re
from datetime import datetime
from decimal import Decimal

import pdfplumber

from .models import Transaction
from .number_parser import money_to_decimal


HEADERS = ["交易参考号", "交易日期", "收入", "支出", "余额", "对方账号", "对方户名", "对方行名", "用途"]
TOTAL_RE = re.compile(r"汇总笔数\s*[:：]\s*(\d+)\s+收入总计\s*[:：]\s*([\d,.]+)\s+支出总计\s*[:：]\s*([\d,.]+)")


def extract_chengdu_corp(pdf_path: str) -> list[Transaction]:
    transactions = []
    printed_totals = None
    account_no = account_name = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page_no, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            if page_no == 1:
                printed_totals = TOTAL_RE.search(text)
                account = re.search(r"账号\s*[:：]\s*(\d+)", text)
                name = re.search(r"户名\s*[:：]\s*(.*)", text)
                account_no = account.group(1) if account else ""
                account_name = name.group(1).strip() if name else ""
                # The name can wrap onto a separate line below the account.
                tail = re.search(r"时间区间[^\n]*\n([^\n]+)\n汇总笔数", text)
                if tail:
                    account_name += tail.group(1).strip()
            for table in page.extract_tables():
                for row in table:
                    if len(row) != 9:
                        continue
                    fields = [str(value or "").replace("\n", "").strip() for value in row]
                    try:
                        tx_time = datetime.strptime(fields[1], "%Y-%m-%d")
                    except ValueError:
                        continue
                    income = money_to_decimal(fields[2]) or Decimal("0.00")
                    expense = money_to_decimal(fields[3]) or Decimal("0.00")
                    balance = money_to_decimal(fields[4])
                    tx = Transaction(
                        tx_time, income, expense, balance, bank="成都银行",
                        page_no=page_no, raw_time=fields[1], raw_amount=f"{fields[2]}|{fields[3]}",
                        raw_balance=fields[4], raw_text=" | ".join(fields),
                        raw_fields=fields, raw_headers=HEADERS,
                    )
                    tx.account_no = account_no
                    tx.account_name = account_name
                    transactions.append(tx)
    # The PDF is newest-first, including the order of multiple rows on a day.
    transactions.reverse()
    for row_no, tx in enumerate(transactions, start=1):
        tx.page_no = 0
        tx.row_no = row_no
    if printed_totals and transactions:
        expected = (int(printed_totals.group(1)), money_to_decimal(printed_totals.group(2)), money_to_decimal(printed_totals.group(3)))
        actual = (len(transactions), sum((tx.income for tx in transactions), Decimal("0.00")), sum((tx.expense for tx in transactions), Decimal("0.00")))
        if actual != expected:
            transactions[0].issues.append(f"明细与打印合计不一致: 实际 {actual}, 打印 {expected}")
            transactions[0].status = "review"
    return transactions
