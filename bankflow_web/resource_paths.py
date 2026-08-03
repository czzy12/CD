"""Resolve bundled and source-tree frontend resources."""

from __future__ import annotations

import sys
from pathlib import Path


def application_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def frontend_index() -> Path:
    return application_root() / "web_frontend" / "dist" / "index.html"
