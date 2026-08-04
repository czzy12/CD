"""Formal source launcher for the WebView2 review workbench."""

from __future__ import annotations

import argparse
import ctypes
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
        return run_real_case_qa(args.qa_case, args.qa_output, title="流水核查工作台")
    try:
        metrics = run_app(
            debug=args.debug,
            smoke_close_after_ready=args.smoke_close_after_ready,
            title="流水核查工作台",
            runtime_tag="cd-bankflow-webview2-workbench",
        )
        if args.smoke_close_after_ready is not None:
            print(metrics)
    except StartupError as exc:
        _show_error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
