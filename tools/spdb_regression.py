from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.summary import summarize


def main() -> None:
    root = Path(r"D:\Codex data\CD_assets\PDF流水\打包测试")
    files = sorted(root.glob("*浦发*.pdf"))
    print(f"SPDB files: {len(files)}")
    for pdf_path in files:
        try:
            detection = detect_bank_type(str(pdf_path))
            if not detection.bank_id:
                print(f"{pdf_path.name}\tUNRECOGNIZED\t{detection.reason}")
                continue
            rows = extract_transactions(str(pdf_path), detection.bank_id)
            summary = summarize(rows, pdf_path.name)
            print(
                f"{pdf_path.name}\t"
                f"bank={detection.bank_id}\t"
                f"rows={len(rows)}\t"
                f"in={summary.income_count}/{summary.income_sum}\t"
                f"out={summary.expense_count}/{summary.expense_sum}\t"
                f"open={summary.opening_balance}\t"
                f"close={summary.closing_balance}\t"
                f"issues={len(summary.issues)}"
            )
            for issue in summary.issues[:5]:
                print(f"  ISSUE\t{issue.time}\t{issue.message}\tamount={issue.raw_amount}\tbalance={issue.raw_balance}")
        except Exception as exc:
            print(f"{pdf_path.name}\tERROR\t{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
