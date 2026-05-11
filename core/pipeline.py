"""
流水线编排 — 检测银行 → 列匹配 → 提取数据 → 时间过滤
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd


def _add_months(dt: datetime, months: int) -> datetime:
    """简易月份加减"""
    y, m = dt.year, dt.month
    m += months
    y += (m - 1) // 12
    m = ((m - 1) % 12) + 1
    return datetime(y, m, dt.day, dt.hour, dt.minute, dt.second)


def _last_day_of_month(dt: datetime) -> datetime:
    """当月最后一天"""
    next_month = _add_months(datetime(dt.year, dt.month, 1), 1)
    return next_month - timedelta(days=1)

from .extractor import TransactionExtractor


def detect_bank(pdf_path: str, config_dir: str = None) -> tuple:
    """
    扫描PDF文本，匹配银行关键词
    返回 (config_dict, bank_id)
    """
    if config_dir is None:
        config_dir = Path(__file__).parent.parent / "configs"

    import pdfplumber

    # 收集所有页面文本
    with pdfplumber.open(pdf_path) as pdf:
        all_text = ""
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_text += text + "\n"

    # 加载配置并打分
    scores = {}
    configs = {}
    for f in Path(config_dir).glob("*.json"):
        if f.name.startswith("_"):
            continue
        cfg = json.loads(f.read_text(encoding="utf-8"))
        configs[f.stem] = cfg
        # 用关键词长度加权：长关键词更特异，避免短词误匹配
        matched_kws = [kw for kw in cfg.get("detection_keywords", [])
                       if kw.lower() in all_text.lower()]
        score = sum(len(kw) for kw in matched_kws)
        if score > 0:
            scores[f.stem] = score

    if not scores:
        return None, None

    best = max(scores, key=scores.get)
    return configs[best], best


def get_default_date_range() -> tuple:
    """默认最近6个自然月"""
    today = datetime.now()
    end = _last_day_of_month(today)
    start = _add_months(datetime(today.year, today.month, 1), -5)
    return start, end


def parse_date_range(range_str: str) -> tuple:
    """
    解析日期范围字符串
    支持格式: "2025-11~2026-04" "25年11月-26年4月" "2511-2604"
    """
    import re

    # 匹配 YYYY-MM~YYYY-MM
    m = re.match(r"(\d{4})-(\d{2})[~\-](\d{4})-(\d{2})", range_str)
    if m:
        y1, m1, y2, m2 = m.groups()
        return (
            datetime(int(y1), int(m1), 1),
            _last_day_of_month(datetime(int(y2), int(m2), 1)),
        )

    # 匹配 "25年11月-26年4月"
    m = re.match(r"(\d{2})年(\d{1,2})月[~\-](\d{2})年(\d{1,2})月", range_str)
    if m:
        y1, m1, y2, m2 = m.groups()
        y1 = 2000 + int(y1) if int(y1) < 100 else int(y1)
        y2 = 2000 + int(y2) if int(y2) < 100 else int(y2)
        return (
            datetime(y1, int(m1), 1),
            _last_day_of_month(datetime(y2, int(m2), 1)),
        )

    # 匹配 "2511-2604" (6位年月)
    m = re.match(r"(\d{4})[~\-](\d{4})", range_str)
    if m:
        y1, m1 = int(m.group(1)[:2]), int(m.group(1)[2:])
        y2, m2 = int(m.group(2)[:2]), int(m.group(2)[2:])
        y1 = 2000 + y1 if y1 < 100 else y1
        y2 = 2000 + y2 if y2 < 100 else y2
        return (
            datetime(y1, m1, 1),
            _last_day_of_month(datetime(y2, m2, 1)),
        )

    return None


def filter_by_date_range(df: pd.DataFrame, start: datetime, end: datetime) -> pd.DataFrame:
    """按日期范围筛选，未识别日期的行保留"""
    if df.empty:
        return df
    dated = df[df["日期"].notna()].copy()
    undated = df[df["日期"].isna()].copy()

    if not dated.empty:
        dated["_date_dt"] = pd.to_datetime(dated["日期"])
        mask = (dated["_date_dt"] >= start) & (dated["_date_dt"] <= end)
        dated = dated[mask].drop(columns=["_date_dt"])

    return pd.concat([dated, undated], ignore_index=True)


def process_pdf(pdf_path: str, date_range_str: str = None, config_dir: str = None) -> dict:
    """
    一站式处理
    返回 PipelineResult:
    {
        "df": DataFrame,
        "bank_name": str,
        "bank_id": str,
        "unrecognized_count": int,
        "issues": list,
    }
    """
    if config_dir is None:
        config_dir = Path(__file__).parent.parent / "configs"

    # 1. 检测银行
    cfg, bank_id = detect_bank(pdf_path, config_dir)
    if cfg is None:
        raise ValueError(f"无法识别该PDF的银行格式: {pdf_path}\n"
                         f"请确认 configs/ 下有对应银行的配置文件")

    # 2. 提取数据
    extractor = TransactionExtractor(cfg)
    df = extractor.extract(pdf_path)

    if df.empty:
        return {
            "df": df,
            "bank_name": cfg.get("name", bank_id),
            "bank_id": bank_id,
            "unrecognized_count": 0,
            "issues": ["未提取到任何流水数据"],
        }

    # 3. 统计未识别行
    unrecognized = df[df["_unrecognized"] == True]
    issues = []
    if len(unrecognized) > 0:
        issues.append(f"{len(unrecognized)} 笔交易存在未识别字段")
        for _, row in unrecognized.iterrows():
            issues.append(f"  - {row.get('原始日期', '?')}: {row.get('_issues', [])}")

    # 4. 时间范围过滤
    if date_range_str and date_range_str.lower() == "all":
        date_range = None
    elif date_range_str:
        date_range = parse_date_range(date_range_str)
    else:
        date_range = get_default_date_range()

    if date_range and not df.empty:
        df = filter_by_date_range(df, date_range[0], date_range[1])

    return {
        "df": df,
        "bank_name": cfg.get("name", bank_id),
        "bank_id": bank_id,
        "unrecognized_count": len(unrecognized),
        "issues": issues,
        "date_range": (
            date_range[0].strftime("%Y-%m"),
            date_range[1].strftime("%Y-%m"),
        ) if date_range else None,
    }
