"""
交易提取器 — 组合日期/金额/列匹配，逐行提取并标记未识别项
"""
import pandas as pd
import pdfplumber

from .date_parser import parse_date, format_date, format_month
from .amount_parser import (
    parse_sign_mode,
    parse_separate_mode,
    parse_direction_mode,
    parse_debit_credit_mode,
)
from .column_matcher import match_columns, find_header_row


class TransactionExtractor:
    """根据银行配置提取流水数据"""

    def __init__(self, config: dict):
        self.cfg = config
        self.amount_mode = config.get("amount_mode", "sign")
        self.amount_rules = config.get("amount_rules", {})
        self.direction_map = self.amount_rules.get("direction_mapping", {})
        self.skip_kw = config.get("skip_keywords", [])
        self._cached_col_match = None  # 跨页复用列匹配

    def extract(self, pdf_path: str) -> pd.DataFrame:
        rows = []
        self._cached_col_match = None
        self._cached_text_resolved = None  # 文本模式的列映射缓存
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                page_rows = self._process_page(page)
                if not page_rows:
                    # 表格提取为空，尝试文本解析
                    page_rows = self._process_page_text(page)
                rows += page_rows
        return self._to_dataframe(rows)

    def _process_page_text(self, page) -> list:
        """文本行解析回退：用于无表格结构的PDF"""
        text_regex = self.cfg.get("text_line_regex")
        if not text_regex:
            return []

        import re
        text = page.extract_text()
        if not text:
            return []

        results = []
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        # 行配对模式：每两行合并（日期在首行，时间在次行）
        if self.cfg.get("text_line_pair"):
            paired = []
            i = 0
            while i < len(lines):
                if re.match(r'\d{4}/\d{2}/\d{2}', lines[i]) and i + 1 < len(lines):
                    paired.append(lines[i] + " " + lines[i + 1])
                    i += 2
                else:
                    paired.append(lines[i])
                    i += 1
            lines = paired

        for line in lines:
            line = line.strip()
            if not line:
                continue
            if self._is_skip_row([line]):
                continue

            m = re.search(text_regex, line)
            if not m:
                continue

            groups = m.groupdict()

            # 验证行不含乱码：日期前缀必须干净
            date_raw = groups.get("date", "")
            time_raw = groups.get("time", "")
            date_time_prefix = f"{date_raw} {time_raw}".strip() if time_raw else date_raw
            valid_prefix = (
                re.match(r'^\d{8}\s+\d{6}$', date_time_prefix) or
                re.match(r'^\d{8}$', date_time_prefix) or
                re.match(r'^\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2}$', date_time_prefix) or
                re.match(r'^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}$', date_time_prefix) or
                re.match(r'^\d{4}/\d{2}/\d{2}$', date_time_prefix)     # 时间可能在行尾(配对模式)
            )
            if not valid_prefix:
                continue

            from .date_parser import parse_date, format_date, format_month
            date_dt, date_fmt = parse_date(date_raw)
            issues = []
            if date_dt is None:
                issues.append(f"日期无法解析: '{date_raw}'")

            # 解析金额
            from .amount_parser import parse_sign_mode, parse_separate_mode
            if self.amount_mode == "separate_columns":
                debit_raw = groups.get("amount_debit", "")
                credit_raw = groups.get("amount_credit", "")
                amount_raw = f"debit={debit_raw} credit={credit_raw}"
                # 根据配置决定借方/贷方对应收入还是支出
                debit_is = self.amount_rules.get("debit_is", "支出")
                if debit_is == "收入":
                    amount_result = parse_separate_mode(debit_raw, credit_raw)
                else:
                    amount_result = parse_separate_mode(credit_raw, debit_raw)
            else:
                amount_raw = groups.get("amount", "")
                amount_result = parse_sign_mode(amount_raw)
            if amount_result is None:
                issues.append(f"金额无法解析")

            # 对方名称
            counterparty = groups.get("counterparty", "").strip()

            # 交易类型
            txn_type = groups.get("type", "").strip()

            result = {
                "日期": format_date(date_dt) if date_dt else None,
                "月份": format_month(date_dt) if date_dt else None,
                "交易类型": txn_type,
                "对方名称": counterparty,
                "账号": "",
                "原始日期": date_raw,
                "原始金额": amount_raw,
                "_time": time_raw or "",
                "_balance": None,
                "_bal_reliable": False,
                "_unrecognized": len(issues) > 0,
                "_issues": issues,
            }

            if amount_result:
                result.update({
                    "金额": amount_result["金额"],
                    "收支方向": amount_result["收支方向"],
                    "收入金额": amount_result["收入金额"],
                    "支出金额": amount_result["支出金额"],
                    "金额模式": amount_result["金额模式"],
                })
            else:
                result.update({
                    "金额": None, "收支方向": None,
                    "收入金额": 0.0, "支出金额": 0.0, "金额模式": None,
                })

            results.append(result)

        return results

    def _process_page(self, page) -> list:
        results = []
        tables = page.extract_tables()

        for table in tables:
            if not table or len(table) < 2:
                continue

            # 查找表头行
            header_idx = find_header_row(table)
            col_match = None
            data_start = 0

            if header_idx >= 0:
                # 找到了表头，尝试匹配列
                header_row = table[header_idx]
                col_match = match_columns(header_row)

                # 如果第一轮匹配效果差，尝试合并表头两行
                if col_match["confidence"] < 0.3 and header_idx + 1 < len(table):
                    merged_header = []
                    for i in range(len(header_row)):
                        part1 = str(header_row[i] or "") if i < len(header_row) else ""
                        part2 = str(table[header_idx + 1][i] or "") if i < len(table[header_idx + 1]) else ""
                        merged_header.append(part1 + part2)
                    col_match = match_columns(merged_header)

                if col_match["confidence"] >= 0.2:
                    self._cached_col_match = col_match  # 缓存有效的列匹配
                data_start = header_idx + 1

            elif self._cached_col_match is not None:
                # 本页没有表头，复用之前缓存的列匹配
                col_match = self._cached_col_match
                data_start = 0

            else:
                # 既没找到表头也没有缓存，尝试用第一行
                col_match = match_columns(table[0])
                data_start = 1 if col_match["confidence"] >= 0.2 else 0

            if col_match is None or col_match["confidence"] < 0.15:
                continue

            resolved = col_match["resolved"]
            parse_func, col_args = self._get_parse_strategy(resolved)

            for row in table[data_start:]:
                if not row or self._is_skip_row(row):
                    continue
                parsed = self._parse_row(row, resolved, col_args, parse_func, col_match)
                if parsed:
                    results.append(parsed)

        return results

    def _get_parse_strategy(self, resolved: dict) -> tuple:
        """根据已解析的列和配置，确定金额解析策略"""
        mode = self.amount_mode
        col_args = {}

        if mode == "sign":
            # 需要 amount 列
            if "amount" in resolved:
                col_args["amount_col"] = resolved["amount"]
            elif "amount_income" in resolved:
                col_args["amount_col"] = resolved["amount_income"]
            elif "amount_expense" in resolved:
                col_args["amount_col"] = resolved["amount_expense"]
            else:
                col_args["amount_col"] = -1
            return "sign", col_args

        elif mode == "separate_columns":
            col_args["income_col"] = resolved.get("amount_income", -1)
            col_args["expense_col"] = resolved.get("amount_expense", -1)
            return "separate_columns", col_args

        elif mode == "direction_column":
            col_args["amount_col"] = resolved.get("amount", -1)
            col_args["direction_col"] = resolved.get("direction", -1)
            return "direction_column", col_args

        elif mode == "debit_credit":
            col_args["amount_col"] = resolved.get("amount", -1)
            col_args["dc_col"] = resolved.get("direction", -1)
            return "debit_credit", col_args

        # 默认 sign
        col_args["amount_col"] = resolved.get("amount", 0)
        return "sign", col_args

    def _parse_row(self, row: list, resolved: dict, col_args: dict,
                   parse_strategy: str, col_match: dict) -> dict | None:
        """解析单行数据"""
        issues = []

        # --- 日期 ---
        date_col = resolved.get("date", 0)
        date_raw = self._safe_get(row, date_col)
        date_dt, date_fmt = parse_date(date_raw)

        if date_dt is None:
            issues.append(f"日期无法解析: '{date_raw}'")

        # --- 金额 ---
        amount_result = None
        if parse_strategy == "sign":
            amt_col = col_args.get("amount_col", -1)
            if amt_col >= 0 and amt_col < len(row):
                amount_result = parse_sign_mode(row[amt_col])
            else:
                issues.append("金额列未找到")

        elif parse_strategy == "separate_columns":
            inc_col = col_args.get("income_col", -1)
            exp_col = col_args.get("expense_col", -1)
            inc_raw = self._safe_get(row, inc_col)
            exp_raw = self._safe_get(row, exp_col)
            amount_result = parse_separate_mode(inc_raw, exp_raw)

        elif parse_strategy == "direction_column":
            amt_col = col_args.get("amount_col", -1)
            dir_col = col_args.get("direction_col", -1)
            amt_raw = self._safe_get(row, amt_col)
            dir_raw = self._safe_get(row, dir_col)
            amount_result = parse_direction_mode(amt_raw, dir_raw, self.direction_map)

        elif parse_strategy == "debit_credit":
            amt_col = col_args.get("amount_col", -1)
            dc_col = col_args.get("dc_col", -1)
            amt_raw = self._safe_get(row, amt_col)
            dc_raw = self._safe_get(row, dc_col)
            amount_result = parse_debit_credit_mode(amt_raw, dc_raw, self.direction_map)

        if amount_result is None:
            issues.append("金额无法解析")

        # --- 对方名称 ---
        cp_col = resolved.get("counterparty", -1)
        counterparty = self._safe_get(row, cp_col)

        # --- 交易类型 ---
        type_col = resolved.get("type", -1)
        txn_type = self._safe_get(row, type_col)

        # --- 余额 ---
        bal_col = resolved.get("balance", -1)
        balance_raw = self._safe_get(row, bal_col)
        balance_val, balance_reliable = self._parse_balance(balance_raw)

        # --- 账号 ---
        acct_col = resolved.get("account", -1)
        account = self._safe_get(row, acct_col)

        # 组装结果
        result = {
            "日期": format_date(date_dt) if date_dt else None,
            "月份": format_month(date_dt) if date_dt else None,
            "交易类型": txn_type,
            "对方名称": counterparty,
            "账号": account,
            "原始日期": str(date_raw).replace("\n", "").strip() if date_raw else "",
            "原始金额": str(self._safe_get(row, col_args.get("amount_col", col_args.get("income_col", 0)))).replace("\n", "").strip(),
            "_balance": balance_val,
            "_bal_reliable": balance_reliable,
            "_unrecognized": len(issues) > 0,
            "_issues": issues,
        }

        if amount_result:
            result.update({
                "金额": amount_result["金额"],
                "收支方向": amount_result["收支方向"],
                "收入金额": amount_result["收入金额"],
                "支出金额": amount_result["支出金额"],
                "金额模式": amount_result["金额模式"],
            })
        else:
            result.update({
                "金额": None,
                "收支方向": None,
                "收入金额": 0.0,
                "支出金额": 0.0,
                "金额模式": None,
            })

        return result

    def _safe_get(self, row: list, idx: int) -> str:
        if idx < 0 or idx >= len(row):
            return ""
        val = row[idx]
        if val is None:
            return ""
        return str(val).replace("\n", "").strip()

    def _parse_balance(self, raw: str):
        """解析余额，返回 (value, is_reliable)"""
        import re
        if not raw:
            return None, False
        text = raw.strip().replace("\n", "")
        # 检查是否干净: 可选逗号 + 数字 + 小数点 + 两位
        clean_match = re.match(r'^[\d,]+\.\d{2}$', text)
        if clean_match:
            try:
                return float(text.replace(",", "")), True
            except ValueError:
                pass
        # 不干净但尝试提取
        text2 = text.replace(",", "").replace("，", "").replace(" ", "")
        matches = re.findall(r'\d+\.\d{2}', text2)
        if matches:
            try:
                return float(matches[-1]), False  # 不可靠
            except ValueError:
                pass
        return None, False

    def _is_skip_row(self, row: list) -> bool:
        """判断是否应跳过的行（合计、小计等）"""
        row_text = " ".join(str(c or "") for c in row)
        for kw in self.skip_kw:
            if kw in row_text:
                return True
        return False

    def _to_dataframe(self, rows: list) -> pd.DataFrame:
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        # 按日期+时间排序
        if "_time" in df.columns and not df["_time"].isna().all():
            df["_sort_key"] = df["日期"].fillna("") + df["_time"].fillna("")
            dated = df[df["日期"].notna()].sort_values("_sort_key")
            undated = df[df["日期"].isna()]
            df = pd.concat([dated, undated], ignore_index=True)
            df = df.drop(columns=["_sort_key"])
        else:
            dated = df[df["日期"].notna()].sort_values("日期")
            undated = df[df["日期"].isna()]
            df = pd.concat([dated, undated], ignore_index=True)
        # 余额交叉验证修正
        df = self._validate_with_balance(df)
        return df

    def _validate_with_balance(self, df: pd.DataFrame) -> pd.DataFrame:
        """用余额变动修正乱码粘合导致的金额错误（仅当前后余额均可解析且修正量合理时）"""
        if "_balance" not in df.columns or df.empty:
            return df

        for i in range(1, len(df)):
            prev_bal = df.at[i - 1, "_balance"]
            curr_bal = df.at[i, "_balance"]
            prev_rel = df.at[i - 1, "_bal_reliable"]
            curr_rel = df.at[i, "_bal_reliable"]
            parsed_amt = df.at[i, "金额"]

            # 需要当前余额可解析（不必clean），上笔余额最好clean
            if pd.isna(prev_bal) or pd.isna(curr_bal) or pd.isna(parsed_amt):
                continue
            if not curr_rel and not prev_rel:
                continue

            bal_change = round(curr_bal - prev_bal, 2)

            if abs(parsed_amt - bal_change) < 0.02:
                continue

            # 只修复合乎逻辑的：修正后的值应和原解析值量级接近（0.05x ~ 20x）
            if parsed_amt != 0:
                ratio = abs(bal_change / parsed_amt)
                if ratio < 0.05 or ratio > 20:
                    continue

            correct_amt = bal_change
            direction = "收入" if correct_amt >= 0 else "支出"

            df.at[i, "金额"] = correct_amt
            df.at[i, "收支方向"] = direction
            df.at[i, "收入金额"] = correct_amt if correct_amt >= 0 else 0.0
            df.at[i, "支出金额"] = abs(correct_amt) if correct_amt < 0 else 0.0
            df.at[i, "_unrecognized"] = True
            issues = df.at[i, "_issues"] if isinstance(df.at[i, "_issues"], list) else []
            issues.append(f"金额已用余额修正: {parsed_amt} -> {correct_amt}")
            df.at[i, "_issues"] = issues

        df = df.drop(columns=["_bal_reliable"])
        return df
