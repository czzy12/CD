"""Independent launcher for the WebView2 integration spike."""

from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path

from bankflow_webview2.app import StartupError, run_app


def _show_error(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "流水核查工作台", 0x10)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--smoke-close-after-ready", type=float)
    parser.add_argument("--qa-case", action="append", type=Path, default=[])
    parser.add_argument("--qa-output", type=Path)
    args = parser.parse_args()
    if args.qa_case:
        if args.qa_output is None:
            parser.error("--qa-output is required with --qa-case")
        from bankflow_webview2.real_case_qa import run_real_case_qa

        return run_real_case_qa(args.qa_case, args.qa_output)
    try:
        metrics = run_app(debug=args.debug, smoke_close_after_ready=args.smoke_close_after_ready)
        if args.smoke_close_after_ready is not None:
            print(json.dumps(metrics, ensure_ascii=False, sort_keys=True))
    except StartupError as exc:
        _show_error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
