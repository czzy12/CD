"""Launch the isolated Web desktop integration slice."""

from __future__ import annotations

import argparse
import logging
import sys

from PyQt6.QtWidgets import QApplication

from bankflow_web.app import WebSpikeWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="流水核查 Web 集成切片")
    parser.add_argument("--dev-url", help="仅开发模式允许的 127.0.0.1 Vite 地址")
    args = parser.parse_args(argv)
    if args.dev_url and not args.dev_url.startswith("http://127.0.0.1"):
        parser.error("--dev-url 仅允许 http://127.0.0.1 地址")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    app = QApplication(sys.argv[:1])
    app.setApplicationName("BankFlowWebSpike")
    window = WebSpikeWindow(dev_url=args.dev_url)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
