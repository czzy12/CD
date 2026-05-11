"""
银行流水PDF批量处理 v2
用法:
    python main.py file1.pdf                          # 默认最近6个月，输出Word
    python main.py file1.pdf --date-range "2025-11~2026-04"
    python main.py file1.pdf --date-range all          # 全部数据
    python main.py file1.pdf --format excel            # 输出Excel
    python main.py *.pdf
"""
import sys
import os
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.pipeline import process_pdf
from output.aggregator import build_balance_text, build_summary_rows, build_verify_text

OUTPUT_DIR = Path(__file__).parent / "output"


def main():
    parser = argparse.ArgumentParser(description="银行流水PDF批量处理 v2")
    parser.add_argument("pdfs", nargs="+", help="PDF文件路径")
    parser.add_argument("--date-range", "-d", default=None,
                        help='日期范围: "2025-11~2026-04" / "all"(全部)')
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)

    success = 0
    failed = []

    for pdf_path in args.pdfs:
        pdf_path = str(pdf_path)
        if not os.path.isfile(pdf_path):
            print(f"  [跳过] 文件不存在: {pdf_path}")
            continue
        if not pdf_path.lower().endswith(".pdf"):
            print(f"  [跳过] 非PDF: {pdf_path}")
            continue

        try:
            print(f"\n{'='*60}")
            print(f"  处理: {os.path.basename(pdf_path)}")
            print(f"{'='*60}")

            result = process_pdf(pdf_path, date_range_str=args.date_range)
            df = result["df"]

            if df.empty:
                print(f"  [警告] 未提取到流水数据")
                failed.append(pdf_path)
                continue

            # 控制台摘要
            balance_text = build_balance_text(df)
            verify_text = build_verify_text(df)
            print(f"\n  银行: {result['bank_name']}")
            print(f"  收入 {balance_text}")
            if verify_text:
                print(f"  {verify_text}")
            print(f"  总笔数: {len(df)}")
            if result["issues"]:
                for issue in result["issues"][:5]:
                    print(f"    {issue}")
            # 月度汇总表
            rows = build_summary_rows(df)
            if rows:
                print(f"  {'月份':<10} {'收入笔数':>6} {'收入':>14} {'支出笔数':>6} {'支出':>14}")
                for r in rows:
                    print(f"  {r[0]:<10} {r[1]:>6} {r[2]:>14.2f} {r[3]:>6} {r[4]:>14.2f}")

            success += 1

        except Exception as e:
            print(f"  [错误] {e}")
            import traceback
            traceback.print_exc()
            failed.append(pdf_path)

    print(f"\n{'='*60}")
    print(f"  处理完成: 成功 {success} 份, 失败 {len(failed)} 份")
    if failed:
        for f in failed:
            print(f"    失败: {f}")
    print(f"  输出目录: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
