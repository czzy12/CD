from __future__ import annotations

import os
import unittest
from pathlib import Path


class WebShellSmokeTests(unittest.TestCase):
    def test_built_frontend_exists_and_contains_no_mock_case(self):
        root = Path(__file__).resolve().parents[1]
        index = root / "web_frontend" / "dist" / "index.html"
        self.assertTrue(index.exists())
        assets = "".join(path.read_text(encoding="utf-8", errors="ignore") for path in (root / "web_frontend" / "dist" / "assets").glob("*.js"))
        self.assertIn("未连接桌面后端", assets)
        self.assertNotIn("BF-001", assets)
        self.assertNotIn("布局演示案例", assets)

    def test_network_policy_allows_only_local_schemes_by_default(self):
        source = (Path(__file__).resolve().parents[1] / "bankflow_web" / "network_policy.py").read_text(encoding="utf-8")
        self.assertIn('{"file", "qrc", "data", "blob", "about"}', source)
        self.assertIn("info.block(True)", source)

    @unittest.skipUnless(os.environ.get("BANKFLOW_RUN_WEBENGINE_SMOKE") == "1", "set BANKFLOW_RUN_WEBENGINE_SMOKE=1 for offscreen WebEngine")
    def test_offscreen_window_constructs(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtWidgets import QApplication
        from bankflow_web.app import WebSpikeWindow
        app = QApplication.instance() or QApplication([])
        window = WebSpikeWindow()
        self.assertIn("Web集成切片", window.windowTitle())
        window.close()
        app.processEvents()


if __name__ == "__main__":
    unittest.main()
