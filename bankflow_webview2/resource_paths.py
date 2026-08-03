"""Resolve and inline the local Vite production build for offline WebView2."""

from __future__ import annotations

import re
import sys
from pathlib import Path

from .security_policy import CONTENT_SECURITY_POLICY, FRONTEND_GUARD_SCRIPT


def application_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[1]


def frontend_dist() -> Path:
    return application_root() / "web_frontend" / "dist"


def build_offline_frontend_html() -> str:
    dist = frontend_dist()
    index = dist / "index.html"
    if not index.is_file():
        raise FileNotFoundError("缺少 web_frontend/dist/index.html，请先执行 npm run build。")
    html = index.read_text(encoding="utf-8")

    def inline_stylesheet(match: re.Match[str]) -> str:
        relative = match.group("path").lstrip("./")
        css = (dist / relative).read_text(encoding="utf-8")
        return f"<style>{css}</style>"

    def inline_module(match: re.Match[str]) -> str:
        relative = match.group("path").lstrip("./")
        script = (dist / relative).read_text(encoding="utf-8")
        return f"<script type=\"module\">{script}</script>"

    html = re.sub(
        r'<link\s+rel="stylesheet"\s+crossorigin\s+href="(?P<path>[^\"]+)"\s*/?>',
        inline_stylesheet,
        html,
    )
    html = re.sub(
        r'<script\s+type="module"\s+crossorigin\s+src="(?P<path>[^\"]+)"></script>',
        inline_module,
        html,
    )
    csp = f'<meta http-equiv="Content-Security-Policy" content="{CONTENT_SECURITY_POLICY}">'
    html = html.replace("<head>", f"<head>{csp}{FRONTEND_GUARD_SCRIPT}", 1)
    if re.search(r'<(?:script|link)[^>]+(?:src|href)="(?:https?:)?//', html, re.IGNORECASE):
        raise ValueError("前端构建包含外部资源引用。")
    return html
