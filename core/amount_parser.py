"""
金额解析器 — 四种模式
- sign: 单列正负号
- separate_columns: 收入/支出分列
- direction_column: 金额列 + 方向文字列
- debit_credit: 金额列 + 借贷标志列(可配置借/贷方向)
"""
import re


def clean_number(raw) -> str:
    """
    清洗金额文本：优先提取带符号+小数的真实金额，抗乱码前缀。
    策略：乱码通常在前面，真实金额在后面，所以从右优先匹配。
    """
    if raw is None:
        return ""
    text = str(raw).replace("\n", "").replace(",", "").replace("，", "").replace(" ", "")

    # 找所有可能的金额模式
    # 1. 带符号 + 小数点 + 两位小数（如 +900.00 / -38.94）
    signed_decimals = re.findall(r'[+-]\d+\.\d{2}', text)
    if signed_decimals:
        return signed_decimals[-1]  # 取最后一个（最靠右，乱码通常在左）

    # 2. 无符号小数点（如 900.00）
    decimals = re.findall(r'\d+\.\d{2}', text)
    if decimals:
        return decimals[-1]

    # 3. 带符号整数
    signed_ints = re.findall(r'[+-]\d+', text)
    if signed_ints:
        return signed_ints[-1]

    # 4. 普通数字（取最长的）
    numbers = re.findall(r'\d+', text)
    if numbers:
        return max(numbers, key=len)

    return text


def parse_sign_mode(amount_raw) -> dict | None:
    """
    sign 模式：单列 + 正负号
    正 = 收入，负 = 支出
    """
    text = clean_number(amount_raw)
    if not text:
        return None
    try:
        val = float(text)
    except ValueError:
        return None

    return {
        "金额": val,
        "收支方向": "收入" if val >= 0 else "支出",
        "收入金额": val if val >= 0 else 0.0,
        "支出金额": abs(val) if val < 0 else 0.0,
        "金额模式": "sign",
    }


def parse_separate_mode(income_raw, expense_raw) -> dict | None:
    """
    separate_columns 模式：收入列 + 支出列分开
    """
    inc_text = clean_number(income_raw)
    exp_text = clean_number(expense_raw)

    inc_val = None
    exp_val = None
    try:
        inc_val = float(inc_text) if inc_text else 0.0
    except ValueError:
        pass
    try:
        exp_val = float(exp_text) if exp_text else 0.0
    except ValueError:
        pass

    if inc_val is None and exp_val is None:
        return None

    inc_val = inc_val or 0.0
    exp_val = exp_val or 0.0

    if inc_val > 0:
        direction = "收入"
        amount = inc_val
    elif exp_val > 0:
        direction = "支出"
        amount = -exp_val
    else:
        direction = "收入"
        amount = 0.0

    return {
        "金额": amount,
        "收支方向": direction,
        "收入金额": inc_val,
        "支出金额": exp_val,
        "金额模式": "separate_columns",
    }


def parse_direction_mode(amount_raw, direction_raw, direction_map: dict) -> dict | None:
    """
    direction_column 模式：金额列(正数) + 方向文字列
    direction_map: {"进": "收入", "出": "支出", "借": "支出", "贷": "收入", ...}
    """
    text = clean_number(amount_raw)
    if not text:
        return None
    try:
        val = float(text)
    except ValueError:
        return None

    # 金额应为正数（取绝对值）
    val = abs(val)

    # 解析方向文字
    dir_text = str(direction_raw).strip().replace("\n", "") if direction_raw else ""
    direction = None
    for keyword, meaning in direction_map.items():
        if keyword in dir_text:
            direction = meaning
            break

    if direction is None:
        return None

    if direction == "收入":
        return {
            "金额": val,
            "收支方向": "收入",
            "收入金额": val,
            "支出金额": 0.0,
            "金额模式": "direction_column",
        }
    else:
        return {
            "金额": -val,
            "收支方向": "支出",
            "收入金额": 0.0,
            "支出金额": val,
            "金额模式": "direction_column",
        }


def parse_debit_credit_mode(amount_raw, dc_raw, dc_map: dict) -> dict | None:
    """
    debit_credit 模式：金额列(正数) + 借贷标志列
    dc_map 在配置中定义，如 {"借": "支出", "贷": "收入"} 或反过来
    """
    text = clean_number(amount_raw)
    if not text:
        return None
    try:
        val = float(text)
    except ValueError:
        return None

    val = abs(val)

    dc_text = str(dc_raw).strip().replace("\n", "") if dc_raw else ""
    direction = None
    for keyword, meaning in dc_map.items():
        if keyword in dc_text:
            direction = meaning
            break

    if direction is None:
        return None

    if direction == "收入":
        return {
            "金额": val,
            "收支方向": "收入",
            "收入金额": val,
            "支出金额": 0.0,
            "金额模式": "debit_credit",
        }
    else:
        return {
            "金额": -val,
            "收支方向": "支出",
            "收入金额": 0.0,
            "支出金额": val,
            "金额模式": "debit_credit",
        }
