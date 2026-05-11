"""
日期解析器 — 多格式兼容，抗乱码干扰
返回 (datetime, format_name) 或 (None, 原始值)
"""
import re
from datetime import datetime


def _strip_garbage(text: str) -> str:
    """去除PDF提取中的乱码：只保留日期时间相关字符"""
    text = text.replace("\n", "")
    # 只保留数字、日期分隔符、时间分隔符、空格
    text = re.sub(r"[^\d\-/.\s:]", "", text)
    # 多个空格合并
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_date(raw: str) -> tuple:
    """
    尝试解析日期字符串，返回 (datetime对象, 格式名) 或 (None, 原始值)
    使用 search 而非 match，允许前缀乱码
    """
    if not raw:
        return None, raw

    text = str(raw).strip()
    if not text:
        return None, raw

    # 清洗乱码
    cleaned = _strip_garbage(text)
    if not cleaned:
        return None, raw

    # ---- datetime 带分隔符优先 ----
    # YYYY-MM-DD HH:MM:SS 或 YYYY/MM/DD HH:MM:SS (space between date and time)
    dt_space = re.search(
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})\s+(\d{1,2}):(\d{2}):(\d{2})",
        cleaned
    )
    if dt_space:
        try:
            y, m, d, hh, mm, ss = dt_space.groups()
            return datetime(int(y), int(m), int(d), int(hh), int(mm), int(ss)), "datetime"
        except ValueError:
            pass

    # YYYY-MM-DDHH:MM:SS (乱码吞掉了空格)
    dt_nospace = re.search(
        r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})(\d{2}):(\d{2}):(\d{2})",
        cleaned
    )
    if dt_nospace:
        try:
            y, m, d, hh, mm, ss = dt_nospace.groups()
            return datetime(int(y), int(m), int(d), int(hh), int(mm), int(ss)), "datetime"
        except ValueError:
            pass

    # ---- 纯日期 ----
    # YYYY-MM-DD
    iso = re.search(r"(\d{4})-(\d{2})-(\d{2})", cleaned)
    if iso:
        try:
            y, m, d = iso.groups()
            return datetime(int(y), int(m), int(d)), "iso_date"
        except ValueError:
            pass

    # YYYY/MM/DD
    slash = re.search(r"(\d{4})/(\d{2})/(\d{2})", cleaned)
    if slash:
        try:
            y, m, d = slash.groups()
            return datetime(int(y), int(m), int(d)), "slash_date"
        except ValueError:
            pass

    # YYYY.MM.DD
    dot = re.search(r"(\d{4})\.(\d{2})\.(\d{2})", cleaned)
    if dot:
        try:
            y, m, d = dot.groups()
            return datetime(int(y), int(m), int(d)), "dot_date"
        except ValueError:
            pass

    # ---- 紧凑格式 ----
    # YYYYMMDD (8位数字)
    compact8 = re.search(r"(\d{8})", cleaned)
    if compact8:
        try:
            return datetime.strptime(compact8.group(1), "%Y%m%d"), "compact8"
        except ValueError:
            pass

    # YYMMDD (6位数字)
    compact6 = re.search(r"(\d{6})", cleaned)
    if compact6:
        try:
            return datetime.strptime(compact6.group(1), "%y%m%d"), "compact6"
        except ValueError:
            pass

    return None, raw


def format_date(dt: datetime) -> str:
    """datetime -> 'YYYY-MM-DD'"""
    return dt.strftime("%Y-%m-%d")


def format_month(dt: datetime) -> str:
    """datetime -> 'YYYY-MM'"""
    return dt.strftime("%Y-%m")
