from __future__ import annotations

import json
import unittest

from bankflow_web.contracts import ApplicationError
from bankflow_webview2.bridge_adapter import PyWebviewBridgeAdapter


class PyWebviewBridgeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.bridge = PyWebviewBridgeAdapter()

    def test_success_envelope_is_directly_serializable(self):
        value = self.bridge.invoke(lambda: {"pong": True})
        self.assertTrue(value["ok"])
        self.assertEqual(value["data"], {"pong": True})
        self.assertIn("request_id", value["meta"])
        json.dumps(value, ensure_ascii=False)

    def test_application_error_is_stable(self):
        def fail():
            raise ApplicationError("NO_CASE")

        value = self.bridge.invoke(fail)
        self.assertFalse(value["ok"])
        self.assertEqual(value["error"]["code"], "NO_CASE")

    def test_unknown_error_does_not_leak_traceback(self):
        def fail():
            raise RuntimeError("private detail")

        value = self.bridge.invoke(fail)
        encoded = json.dumps(value, ensure_ascii=False)
        self.assertEqual(value["error"]["code"], "INTERNAL_ERROR")
        self.assertNotIn("Traceback", encoded)
        self.assertNotIn("private detail", encoded)


if __name__ == "__main__":
    unittest.main()
