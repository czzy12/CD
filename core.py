"""
银行流水PDF核心提取引擎
- 自动识别银行
- 按配置提取表格数据
- 标准化输出
"""

import json
import re
import os
from pathlib import Path
import pdfplumber
import pandas as pd


class BankDetector:
    """根据PDF内容自动识别银行"""

    def __init__(self, config_dir):
        self.configs = {}
        for f in Path(config_dir).glob("*.json"):
            if f.name.startswith("_"):
                continue
            cfg = json.loads(f.read_text(encoding="utf-8"))
            self.configs[f.stem] = cfg

    def detect(self, pdf_path: str):
        """扫描PDF首页，匹配银行关键词，返回(config, bank_id)"""
        with pdfplumber.open(pdf_path) as pdf:
            if not pdf.pages:
                return None, None
            first_page_text = pdf.pages[0].extract_text() or ""

        # 按关键词匹配，取匹配数最多的银行
        scores = {}
        for bank_id, cfg in self.configs.items():
            score = sum(
                1 for kw in cfg.get("detection_keywords", [])
                if kw.lower() in first_page_text.lower()
            )
            if score > 0:
                scores[bank_id] = score

        if not scores:
            return None, None

        best = max(scores, key=scores.get)
        return self.configs[best], best


class TransactionExtractor:
    """根据银行配置提取流水数据"""

    def __init__(self, config: dict):
        self.cfg = config
        self.col_map = config["column_mapping"]
        self.date_col = self.col_map["date"]
        self.amount_col = self.col_map["amount"]
        self.type_col = self.col_map.get("type", -1)
        self.cp_col = self.col_map.get("counterparty", -1)
        self.date_fmt = config.get("date_format", "%Y%m%d")
        self.skip_kw = config.get("skip_keywords", [])
        self.header_kw = config.get("header_markers", [])
        self.income_method = config.get("income_method", "sign")

    def extract(self, pdf_path: str) -> pd.DataFrame:
        rows = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                rows += self._process_page(page)
        return self._to_dataframe(rows)

    def _process_page(self, page) -> list:
        """处理单页，返回标准化行列表"""
        results = []
        tables = page.extract_tables()

        for table in tables:
            for row in table:
                if not row or len(row) <= max(self.date_col, self.amount_col):
                    continue
                parsed = self._parse_row(row)
                if parsed:
                    results.append(parsed)
        return results

    def _parse_row(self, row: list) -> dict | None:
        """解析单行数据"""
        # 提取并清洗日期
        date_raw = str(row[self.date_col] or "").strip().replace("\n", "")
        if not date_raw:
            return None

        # 跳过表头
        if self._is_header(date_raw):
            return None

        # 提取日期数字
        date_match = re.match(r'(\d{6,8})', date_raw)
        if not date_match:
            return None
        date_str = date_match.group(1)

        # 解析日期
        date = self._parse_date(date_str)
        if date is None:
            return None

        # 提取金额
        amount = self._parse_amount(row[self.amount_col])
        if amount is None:
            return None

        # 交易类型
        txn_type = self._clean_text(row[self.type_col]) if self.type_col >= 0 and len(row) > self.type_col else ""

        # 对方名称
        counterparty = self._clean_text(row[self.cp_col]) if self.cp_col >= 0 and len(row) > self.cp_col else ""

        # 收支方向
        direction = self._get_direction(amount)

        return {
            "日期": date.strftime("%Y-%m-%d"),
            "月份": date.strftime("%Y-%m"),
            "交易类型": txn_type,
            "金额": amount,
            "收支方向": direction,
            "收入金额": amount if amount > 0 else 0,
            "支出金额": abs(amount) if amount < 0 else 0,
            "对方名称": counterparty,
            "原始日期": date_str,
        }

    def _is_header(self, date_val: str) -> bool:
        return any(kw in date_val for kw in self.skip_kw)

    def _parse_date(self, date_str: str):
        """兼容多种日期格式"""
        formats = [self.date_fmt, "%Y%m%d", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"]
        for fmt in formats:
            try:
                return pd.to_datetime(date_str, format=fmt)
            except (ValueError, TypeError):
                continue
        # 最后尝试自动推断
        try:
            return pd.to_datetime(date_str)
        except:
            return None

    def _parse_amount(self, raw) -> float | None:
        """提取金额，兼容逗号分隔、换行等"""
        if raw is None:
            return None
        text = str(raw).strip().replace("\n", "").replace(",", "").replace(" ", "")
        try:
            return float(text)
        except ValueError:
            return None

    def _clean_text(self, raw) -> str:
        """清洗文本单元格"""
        if raw is None:
            return ""
        return str(raw).replace("\n", "").strip()

    def _get_direction(self, amount: float) -> str:
        if self.income_method == "sign":
            rules = self.cfg.get("income_rules", {})
            pos = rules.get("positive_is", "收入")
            neg = rules.get("negative_is", "支出")
            return pos if amount > 0 else neg
        return ""

    def _to_dataframe(self, rows: list) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df = df.sort_values("日期").reset_index(drop=True)
        return df


def process_pdf(pdf_path: str, config_dir: str = None) -> tuple:
    """
    一站式处理：检测银行 → 提取数据 → 返回DataFrame

    返回: (df, bank_name, bank_id)
    """
    if config_dir is None:
        config_dir = Path(__file__).parent / "configs"

    detector = BankDetector(config_dir)

    cfg, bank_id = detector.detect(pdf_path)
    if cfg is None:
        raise ValueError(f"无法识别该PDF的银行格式: {pdf_path}")

    extractor = TransactionExtractor(cfg)
    df = extractor.extract(pdf_path)

    return df, cfg["name"], bank_id