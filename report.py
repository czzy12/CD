"""
报表生成模块
- 按月汇总
- 按交易类型汇总
- 总体统计（含收入-支出余额）
- 输出Excel
"""

import pandas as pd
from pathlib import Path


def build_monthly_summary(df: pd.DataFrame) -> pd.DataFrame:
    """按月汇总"""
    if df.empty:
        return pd.DataFrame()
    monthly = df.groupby("月份").agg(
        笔数=("金额", "count"),
        收入总额=("收入金额", "sum"),
        支出总额=("支出金额", "sum"),
        净流入=("金额", "sum"),
    ).round(2)
    return monthly


def build_type_summary(df: pd.DataFrame) -> pd.DataFrame:
    """按交易类型汇总"""
    if df.empty:
        return pd.DataFrame()
    ts = df.groupby("交易类型").agg(
        笔数=("金额", "count"),
        收入总额=("收入金额", "sum"),
        支出总额=("支出金额", "sum"),
    ).round(2).sort_values("笔数", ascending=False)
    return ts


def build_overall_summary(df: pd.DataFrame) -> dict:
    """总体统计"""
    return {
        "总笔数": len(df),
        "收入笔数": int((df["收支方向"] == "收入").sum()),
        "收入合计": round(df["收入金额"].sum(), 2),
        "支出笔数": int((df["收支方向"] == "支出").sum()),
        "支出合计": round(df["支出金额"].sum(), 2),
        "净流入": round(df["金额"].sum(), 2),
        "余额(收入-支出)": round(df["收入金额"].sum() - df["支出金额"].sum(), 2),
        "时间范围": f"{df['日期'].min()} ~ {df['日期'].max()}" if not df.empty else "",
    }


def export_excel(df: pd.DataFrame, output_path: str, bank_name: str = ""):
    """导出Excel报表，含明细+汇总"""
    monthly = build_monthly_summary(df)
    type_summ = build_type_summary(df)
    overall = build_overall_summary(df)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Sheet 1: 原始明细
        detail_cols = ["日期", "交易类型", "金额", "收支方向", "收入金额", "支出金额", "对方名称"]
        df[detail_cols].to_excel(writer, sheet_name="原始明细", index=False)

        # Sheet 2: 按月汇总
        monthly.to_excel(writer, sheet_name="按月汇总")

        # Sheet 3: 按类型汇总
        type_summ.to_excel(writer, sheet_name="按类型汇总")

        # Sheet 4: 总体统计
        overall_df = pd.DataFrame([
            {"项目": "银行", "值": bank_name},
            {"项目": "时间范围", "值": overall["时间范围"]},
            {"项目": "总笔数", "值": overall["总笔数"]},
            {"项目": "收入笔数", "值": overall["收入笔数"]},
            {"项目": "收入合计", "值": overall["收入合计"]},
            {"项目": "支出笔数", "值": overall["支出笔数"]},
            {"项目": "支出合计", "值": overall["支出合计"]},
            {"项目": "净流入", "值": overall["净流入"]},
            {"项目": "余额(收入-支出)", "值": overall["余额(收入-支出)"]},
        ])
        overall_df.to_excel(writer, sheet_name="总体统计", index=False)

    return output_path


def print_summary(df: pd.DataFrame, bank_name: str = ""):
    """控制台打印汇总结果"""
    print(f"\n{'='*60}")
    print(f"  {bank_name} 流水分析")
    print(f"{'='*60}")

    monthly = build_monthly_summary(df)
    type_summ = build_type_summary(df)
    overall = build_overall_summary(df)

    print("\n【原始明细】共 {} 笔".format(len(df)))
    print(df[["日期", "交易类型", "金额", "收支方向"]].to_string(index=False))

    print(f"\n【按月汇总】")
    print(monthly.to_string())

    print(f"\n【按类型汇总】")
    print(type_summ.to_string())

    print(f"\n【总体统计】")
    for k, v in overall.items():
        print(f"  {k}: {v}")