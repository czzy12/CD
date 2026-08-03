from __future__ import annotations

import platform
import unittest
from unittest.mock import patch

from bankflow_webview2.runtime_check import RuntimeStatus, check_webview2_runtime


class WebView2RuntimeCheckTests(unittest.TestCase):
    def test_current_windows_runtime_has_stable_status(self):
        result = check_webview2_runtime()
        self.assertIn(result.status, set(RuntimeStatus))
        self.assertGreaterEqual(result.elapsed_ms, 0)
        self.assertTrue(result.python_architecture.endswith("-bit"))
        if result.status is RuntimeStatus.AVAILABLE:
            self.assertRegex(result.version or "", r"^\d+(?:\.\d+)+$")
            self.assertIn(result.runtime_architecture, {"x86", "x64", "arm64"})

    def test_non_windows_is_missing_without_initialization(self):
        with patch.object(platform, "system", return_value="Linux"):
            result = check_webview2_runtime()
        self.assertEqual(result.status, RuntimeStatus.MISSING)
        self.assertIn("不是 Windows", result.message)


if __name__ == "__main__":
    unittest.main()
