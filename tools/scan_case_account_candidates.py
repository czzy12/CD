"""Create a read-only, pending-confirmation account candidate manifest for one case folder."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bankflow_v2.case_accounts import scan_case_account_candidates, write_case_manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描案例目录中的待人工确认账户候选")
    parser.add_argument("case_folder", help="只扫描该案例目录；文件夹不代表账户归属")
    parser.add_argument("output", help="输出候选清单 JSON")
    parser.add_argument("--file-timeout", type=float, default=30.0, help="单个 PDF 的超时秒数")
    args = parser.parse_args()

    manifest = scan_case_account_candidates(args.case_folder, args.file_timeout)
    output = write_case_manifest(manifest, Path(args.output))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
