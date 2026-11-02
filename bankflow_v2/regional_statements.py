"""Explicit text-layer layouts from the November 2026 problem batch.

Amounts are read from their printed columns. Balance links only order rows;
they never replace amounts or discard unmatched transactions.
"""
import re
import hashlib
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pdfplumber

from .models import Transaction


ZERO = Decimal("0.00")
DATE = re.compile(r"20\d{2}[-./]?\d{2}[-./]?\d{2}")
TIME = re.compile(r"\d{2}:\d{2}:\d{2}")
MINTAI_CONFIRMED_SOURCE = "d8a72bd0417049e910915796293a378b0e93caa117d28dd7805378b469dd92fe"


def _compact(value):
    return re.sub(r"\s+", "", str(value or ""))


def _money(raw, blank=False):
    text = _compact(raw).replace(",", "").replace("￥", "").replace("¥", "")
    if blank and text in {"", "--", "-"}:
        return ZERO
    if not re.fullmatch(r"[+-]?\d+(?:\.\d{1,2})?", text):
        raise ValueError("金额列不是明确数值，请人工核对原页")
    return Decimal(text).quantize(Decimal("0.01"))


def _datetime(raw):
    date = DATE.search(raw)
    if date is None:
        return None
    digits = re.sub(r"\D", "", date.group())
    try:
        value = datetime.strptime(digits, "%Y%m%d")
        clock = TIME.search(raw)
        return datetime.combine(value.date(), datetime.strptime(clock.group(), "%H:%M:%S").time()) if clock else value
    except ValueError:
        return None


def order_statement_rows(rows, newest_first=False):
    """Keep source provenance while ordering equal-time rows by exact links."""
    groups = defaultdict(list)
    for tx in reversed(rows) if newest_first else rows:
        tx.source_page_no = getattr(tx, "source_page_no", tx.page_no)
        tx.source_row_no = getattr(tx, "source_row_no", tx.row_no)
        groups[tx.transaction_time.date()].append(tx)
    ordered = []
    previous = None
    for stamp in sorted(groups):
        source = groups[stamp]
        edges = defaultdict(list)
        degree = defaultdict(int)
        for tx in reversed(source):
            before = tx.balance - tx.amount
            edges[before].append(tx)
            degree[before] += 1
            degree[tx.balance] -= 1
        start = previous if previous in edges else next((b for b,n in degree.items() if n == 1), source[0].balance-source[0].amount)
        vertices, trail, result = [start], [], []
        while vertices:
            available = edges[vertices[-1]]
            if available:
                tx = available.pop()
                vertices.append(tx.balance)
                trail.append(tx)
            else:
                vertices.pop()
                if trail:
                    result.append(trail.pop())
        result.reverse()
        if len(result) != len(source) or any(a.balance + b.amount != b.balance for a,b in zip(result,result[1:])):
            # Unprovable/disconnected rows remain present and fail normal checks.
            result = source
        ordered.extend(result)
        previous = result[-1].balance
    for index, tx in enumerate(ordered, 1):
        tx.statement_order = index
    return ordered


def _account(rows, text):
    account = re.search(r"(?:账\(卡\)号|账/卡号|卡号/账号|账号|账\s*号)\s*[:：]\s*([\d *-]+)", text)
    name = re.search(r"(?:账户名称|客户名称|户名)\s*[:：]\s*(\S+)", text)
    for tx in rows:
        tx.account_no = _compact(account.group(1)) if account else ""
        tx.account_name = name.group(1) if name else ""
    return rows


def _check_totals(rows, text, patterns):
    """Compare independently printed statement totals, without correcting rows."""
    if not rows:
        raise ValueError("未提取到交易，请人工核对版式")
    compact = _compact(text)
    actual = {
        "count": len(rows), "income_count": sum(tx.income != 0 for tx in rows),
        "expense_count": sum(tx.expense != 0 for tx in rows),
        "income": sum((tx.income for tx in rows), ZERO),
        "expense": sum((tx.expense for tx in rows), ZERO),
    }
    for field, pattern in patterns.items():
        match = re.search(pattern, compact)
        if match:
            expected = Decimal(match.group(1).replace(",", ""))
            if actual[field] != expected:
                rows[0].issues.append(f"打印{field}合计不一致：识别{actual[field]}，打印{expected}")
                rows[0].status = "review"
    return rows


def _table_rows(path, bank, headers, date_col, income_col, expense_col, balance_col):
    rows, texts = [], []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            texts.append(page.extract_text() or "")
            for table in page.extract_tables():
                for row_no, row in enumerate(table, 1):
                    if len(row) != len(headers):
                        continue
                    fields = [_compact(cell) for cell in row]
                    raw_time = fields[date_col]
                    stamp = _datetime(raw_time)
                    if stamp is None:
                        continue
                    income = _money(fields[income_col], blank=True)
                    expense = _money(fields[expense_col], blank=True)
                    tx = Transaction(stamp, income, expense, _money(fields[balance_col]), bank,
                                     page_no, row_no, raw_time, f"{fields[income_col]}|{fields[expense_col]}",
                                     fields[balance_col], " | ".join(str(x or "") for x in row),
                                     [str(x or "") for x in row], headers)
                    rows.append(tx)
    text = "\n".join(texts)
    return _account(order_statement_rows(rows), text), text


def extract_tianjin_corp(path):
    headers = ["序号", "交易日期", "交易时间", "借方发生额", "贷方发生额", "余额", "对方账号", "对方户名", "对方账户开户行", "凭证种类", "凭证号码", "摘要", "附言"]
    rows, _ = _table_rows(path, "天津银行对公", headers, 2, 4, 3, 5)
    if not rows:
        raise ValueError("天津银行对公明细为空，请人工核对")
    return rows


def extract_abc_history(path):
    headers = ["交易时间", "收入金额", "支出金额", "账户余额", "对方账号", "对方户名", "对方开户行", "摘要"]
    rows, text = _table_rows(path, "中国农业银行", headers, 0, 1, 2, 3)
    return _check_totals(rows, text, {"income_count": r"总收入笔数(\d+)", "expense_count": r"总支出笔数(\d+)", "income": r"总收入金额([\d,.]+)", "expense": r"总支出金额([\d,.]+)"})


def extract_ordos(path):
    headers = ["交易时间", "收入(元)", "支出(元)", "余额(元)", "币种", "对方账号", "对方户名", "备注"]
    rows, text = _table_rows(path, "鄂尔多斯银行个人", headers, 0, 1, 2, 3)
    return _check_totals(rows, text, {"count": r"共(\d+)条", "income_count": r"总收入笔数[:：](\d+)", "expense_count": r"总支出笔数[:：](\d+)", "income": r"总收入金额[:：]([\d,.]+)", "expense": r"总支出金额[:：]([\d,.]+)"})


def _column_text(words, left, right, top, bottom):
    selected = [w for w in words if left <= (w["x0"] + w["x1"]) / 2 < right and top <= w["top"] < bottom]
    lines = []
    for word in sorted(selected, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0] - word["top"]) < 2:
            lines[-1][1].append(word)
        else:
            lines.append((word["top"], [word]))
    return "\n".join("".join(w["text"] for w in sorted(line, key=lambda w:w["x0"])) for _, line in lines)


def _coordinate_rows(path, bank, boundaries, headers, date_col, amount_col=None, balance_col=None, income_col=None, expense_col=None, newest_first=False):
    rows, texts = [], []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            texts.append(page.extract_text() or "")
            words = page.extract_words(x_tolerance=2, y_tolerance=2)
            cells = page.chars
            left, right = boundaries[date_col:date_col+2]
            heading_tops = [w["top"] for w in words if w["text"] == headers[date_col]]
            start = min(heading_tops) + 8 if heading_tops else 0
            anchors = [w for w in words if w["top"] > start and left <= w["x0"] < right and DATE.match(w["text"]) and _datetime(w["text"]) is not None]
            anchors.sort(key=lambda w:w["top"])
            for row_no, anchor in enumerate(anchors, 1):
                top = anchor["top"] - 2
                bottom = anchors[row_no]["top"] - 2 if row_no < len(anchors) else page.height
                fields = [_column_text(cells, a, b, top, bottom) for a,b in zip(boundaries,boundaries[1:])]
                for col in {amount_col, balance_col, income_col, expense_col} - {None}:
                    fields[col] = _column_text(cells, boundaries[col], boundaries[col+1], top, min(bottom, anchor["top"] + 7))
                fields[date_col] = _column_text(cells, left, right, top, min(bottom, anchor["top"] + 18))
                # Header dates can be closer than 18pt to the first data row.
                # The date always comes from this anchor, never from a following row.
                raw_time = anchor["text"]
                clock = TIME.search(fields[date_col])
                if clock:
                    raw_time = DATE.match(raw_time).group() + " " + clock.group()
                stamp = _datetime(raw_time)
                if stamp is None:
                    raise ValueError("交易日期列无法读取，请核对原页")
                if amount_col is None:
                    income, expense = _money(fields[income_col], True), _money(fields[expense_col], True)
                    raw_amount = fields[income_col] + "|" + fields[expense_col]
                else:
                    amount = _money(fields[amount_col])
                    income, expense = max(amount,ZERO), max(-amount,ZERO)
                    raw_amount = fields[amount_col]
                tx = Transaction(stamp, income, expense, _money(fields[balance_col]), bank,
                                 page_no, row_no, raw_time, raw_amount, fields[balance_col],
                                 " | ".join(fields), fields, headers)
                rows.append(tx)
    text = "\n".join(texts)
    if not rows:
        raise ValueError("此版式未提取到交易，请人工核对")
    return _account(order_statement_rows(rows, newest_first), text), text


def extract_guangxi_rural(path):
    headers = ["序号", "交易时间", "对方户名", "对方账号", "对方行名", "币种", "收入/支出金额", "账户余额", "用途", "摘要", "附言", "备注"]
    rows,text = _coordinate_rows(path,"广西农商联合银行个人",[20,50,104,190,280,360,400,475,548,620,685,746,815],headers,1,6,7)
    for previous, current in zip(rows, rows[1:]):
        if ("冲正" in current.raw_fields[9] and previous.expense > ZERO
                and current.income == previous.expense
                and current.balance == previous.balance + previous.expense):
            # The statement includes a debit reversal in signed expense totals.
            # Preserve both transactions and the original signed amount text.
            current.expense, current.income = -current.income, ZERO
            current.signed_expense_reversal = True
        current.preserve_signed_columns = True
    rows[0].preserve_signed_columns = True
    return _check_totals(rows,text,{"income_count":r"收入笔数[:：](\d+)","expense_count":r"支出笔数[:：](\d+)","income":r"收入合计[:：]([\d,.]+)","expense":r"支出合计[:：]([\d,.]+)"})


def extract_hengfeng(path):
    headers = ["记账日期", "货币", "交易金额", "联机余额", "交易摘要", "对手信息"]
    rows,_ = _coordinate_rows(path,"恒丰银行个人",[65,125,165,230,300,420,545],headers,0,2,3,newest_first=True)
    return rows


def extract_tiantai_rural(path):
    headers = ["交易日期", "币种", "交易摘要", "交易金额", "账户余额", "对方账号", "对方户名", "对方行", "交易渠道", "备注"]
    rows,_ = _coordinate_rows(path,"浙江天台农村商业银行个人",[35,75,100,140,180,215,280,385,465,500,560],headers,0,3,4)
    return rows


def extract_mintai(path):
    headers = ["交易日期", "收入金额", "支出金额", "余额", "对方户名", "对方账号", "交易摘要"]
    rows,_ = _coordinate_rows(path,"浙江民泰商业银行个人",[0,48,103,157,213,392,470,556],headers,0,balance_col=3,income_col=1,expense_col=2,newest_first=True)
    return _apply_confirmed_mintai_repair(rows, hashlib.sha256(Path(path).read_bytes()).hexdigest())


def _apply_confirmed_mintai_repair(rows, source_sha256):
    """One explicit user confirmation; never a general amount/closure rule."""
    if source_sha256 != MINTAI_CONFIRMED_SOURCE:
        return rows
    matches = [i for i,tx in enumerate(rows) if tx.raw_time == "20260817"
               and tx.income == Decimal("39.82") and tx.balance == Decimal("15967.17")
               and tx.source_page_no == 6 and tx.source_row_no == 6]
    if len(matches) != 1 or not 0 < matches[0] < len(rows)-1:
        raise ValueError("已确认源文件的修正定位不一致，请人工核对")
    index = matches[0]
    previous, current, following = rows[index-1:index+2]
    if previous.balance != Decimal("5329.42") or following.expense != Decimal("25.00") or following.balance != Decimal("5304.42"):
        raise ValueError("已确认修正的相邻余额依据变化，请人工核对")
    previous.manual_confirmation = {
        "id": "mintai-source-row-20261102", "confirmed_on": "2026-11-02",
        "action": "exclude",
        "source_sha256": source_sha256, "source_page": 6, "source_row": 6,
        "raw_date": current.raw_time, "original_income": "39.82",
        "original_balance": "15967.17", "confirmed_net": "0.00",
        "basis": "用户确认剔除此源文件异常行，不计收入、支出及有效笔数；原始PDF不修改。",
    }
    return order_statement_rows(rows[:index] + rows[index+1:])


def extract_yongxing_rural(path):
    headers = ["交易时间", "交易金额", "账户余额", "对方账号", "对方户名", "摘要", "备注"]
    rows,_ = _coordinate_rows(path,"湖南永兴农村商业银行个人",[40,122,195,248,335,425,480,570],headers,0,1,2,newest_first=True)
    return rows


def extract_mengshang(path):
    headers = ["序号", "摘要", "币别", "钞汇", "交易日期", "交易金额", "账户余额", "交易地点/附言", "对方账号与户名"]
    rows,_ = _coordinate_rows(path,"蒙商银行个人",[20,70,198,250,268,330,412,473,675,835],headers,4,5,6)
    return rows


def extract_qingdao_rural_corp(path):
    headers = ["记账日期", "交易金额", "账户余额", "交易摘要", "交易对手信息"]
    rows,_ = _coordinate_rows(path,"青岛农村商业银行对公",[45,125,195,265,350,555],headers,0,1,2)
    return rows
