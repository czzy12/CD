from __future__ import annotations

import os
import unittest
from pathlib import Path

from bankflow_webview2.resource_paths import build_offline_frontend_html
from bankflow_webview2.security_policy import CONTENT_SECURITY_POLICY


ROOT = Path(__file__).resolve().parents[1]


class WebView2ShellSmokeTests(unittest.TestCase):
    def test_shell_forces_edgechromium_and_has_no_mshtml_fallback(self):
        source = (ROOT / "bankflow_webview2" / "app.py").read_text(encoding="utf-8")
        self.assertIn('gui="edgechromium"', source)
        self.assertIn('renderer != "edgechromium"', source)
        self.assertNotIn('gui="mshtml"', source)

    def test_built_frontend_is_inlined_and_offline(self):
        html = build_offline_frontend_html()
        self.assertIn("connect-src 'none'", CONTENT_SECURITY_POLICY)
        self.assertIn("External network is disabled", html)
        self.assertNotIn('<script type="module" crossorigin src=', html)
        self.assertNotIn('<link rel="stylesheet" crossorigin href=', html)
        self.assertNotIn("BF-001", html)

    def test_frontend_defaults_to_pywebview_adapter(self):
        source = (ROOT / "web_frontend" / "src" / "bridge" / "desktopBridge.ts").read_text(encoding="utf-8")
        self.assertIn("new PyWebviewBridgeAdapter", source)
        self.assertIn('get("bridge") === "qwebchannel"', source)
        self.assertIn("pywebview API unavailable", source)

    @unittest.skipUnless(os.environ.get("BANKFLOW_RUN_WEBVIEW2_SMOKE") == "1", "set BANKFLOW_RUN_WEBVIEW2_SMOKE=1 for visible shell smoke")
    def test_visible_shell_connects_and_closes(self):
        from bankflow_webview2.app import run_app

        run_app(smoke_close_after_ready=0.2)


if __name__ == "__main__":
    unittest.main()
