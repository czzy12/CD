from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.pipeline import extract_transactions
from bankflow_v2.summary import summarize


def main() -> None:
    root = Path(r"D:\Codex data\CD_assets\PDF流水\打包测试")
    files = sorted(root.glob("*工商银行历史明细*.pdf"))
    print(f"ICBC files: {len(files)}")
    ignored = 0
    passed = 0
    review = 0
    failed = 0
    for pdf_path in files:
        try:
            detection = detect_bank_type(str(pdf_path))
            if not detection.bank_id:
                ignored += 1
                print(f"{pdf_path.name}\tIGNORED\t{detection.reason}")
                continue

            bank_id = detection.bank_id if detection else "icbc"
            rows = extract_transactions(str(pdf_path), bank_id)
            summary = summarize(rows, pdf_path.name)
            if summary.issues:
                review += 1
            else:
                passed += 1
            print(
                f"{pdf_path.name}\t"
                f"bank={bank_id}\t"
                f"rows={len(rows)}\t"
                f"in={summary.income_count}/{summary.income_sum}\t"
                f"out={summary.expense_count}/{summary.expense_sum}\t"
                f"issues={len(summary.issues)}"
            )
            for issue in summary.issues[:3]:
                print(f"  ISSUE\t{issue.time}\t{issue.message}\tamount={issue.raw_amount}\tbalance={issue.raw_balance}")
        except Exception as exc:
            failed += 1
            print(f"{pdf_path.name}\tERROR\t{type(exc).__name__}: {exc}")
    print(f"SUMMARY\tpassed={passed}\treview={review}\tignored={ignored}\tfailed={failed}")


if __name__ == "__main__":
    main()
