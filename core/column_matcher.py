"""
列匹配器 — 根据表头关键词自动匹配语义列
"""
import re


# 语义角色 → 候选关键词列表
ROLE_KEYWORDS = {
    "date": ["交易日期", "记账日期", "日期", "Date", "交易时间"],
    "time": ["交易时间", "时间"],
    "amount": ["交易金额", "金额", "发生额", "交易额"],
    "amount_income": ["收入金额", "贷方金额", "进账金额", "收入", "贷方"],
    "amount_expense": ["支出金额", "借方金额", "出账金额", "支出", "借方"],
    "direction": ["收支方向", "借贷标志", "进出标志", "方向", "借贷"],
    "counterparty": ["对方名称", "对方户名", "交易对手", "对方", "收款人", "付款人", "户名"],
    "counterparty_account": ["对方账号", "对方账户", "对方帐号"],
    "type": ["摘要", "交易类型", "用途", "备注", "交易摘要"],
    "balance": ["余额", "账户余额", "当前余额"],
    "account": ["账号", "账户", "卡号"],
    "currency": ["币种", "货币"],
}


def clean_cell(text) -> str:
    """清洗单元格文本用于匹配"""
    if text is None:
        return ""
    s = str(text).replace("\n", "").strip()
    # 去除混杂的单个字母/数字（乱码特征）
    s = re.sub(r'\b[A-Z0-9]\b', '', s)
    return s.strip()


def match_columns(header_row: list) -> dict:
    """
    根据表头行匹配语义列
    返回 ColumnMatchResult:
    {
        "resolved": {"date": 0, "amount": 8, ...},
        "unmatched_roles": ["counterparty_account", ...],
        "confidence": 0.85,
        "header_row": [...]
    }
    """
    resolved = {}
    unmatched = []
    total_roles = 0
    matched_roles = 0

    for role, keywords in ROLE_KEYWORDS.items():
        total_roles += 1
        found = False
        for idx, cell in enumerate(header_row):
            cleaned = clean_cell(cell)
            if not cleaned:
                continue
            for kw in keywords:
                if kw in cleaned:
                    resolved[role] = idx
                    matched_roles += 1
                    found = True
                    break
            if found:
                break
        if not found:
            unmatched.append(role)

    # 如果没有找到 amount 但找到了 amount_income 和 amount_expense
    # 则不标记 amount 为缺失（使用 separate_columns 模式）
    if "amount" in unmatched and "amount_income" in resolved and "amount_expense" in resolved:
        unmatched.remove("amount")

    confidence = matched_roles / max(total_roles, 1)

    return {
        "resolved": resolved,
        "unmatched_roles": unmatched,
        "confidence": round(confidence, 2),
    }


def find_header_row(rows: list, min_match_score: int = 2) -> int:
    """
    在多行中查找表头行
    返回表头行索引，找不到返回 -1
    """
    best_score = 0
    best_idx = -1

    for idx, row in enumerate(rows[:10]):  # 只在前10行中查找
        if not row:
            continue
        score = 0
        for cell in row:
            cleaned = clean_cell(cell)
            if not cleaned:
                continue
            for keywords in ROLE_KEYWORDS.values():
                for kw in keywords:
                    if kw in cleaned:
                        score += 1
                        break
        if score > best_score:
            best_score = score
            best_idx = idx

    if best_score >= min_match_score:
        return best_idx
    return -1
