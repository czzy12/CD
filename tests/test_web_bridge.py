from __future__ import annotations

import json
import unittest

from bankflow_web.bridge import WebBridge
from bankflow_web.case_session import CaseSession


class WebBridgeTests(unittest.TestCase):
    def setUp(self):
        self.bridge = WebBridge(CaseSession())

    def test_no_case_is_stable_envelope(self):
        value = json.loads(self.bridge.get_case_header())
        self.assertFalse(value["ok"])
        self.assertEqual(value["error"]["code"], "NO_CASE")
        self.assertIn("request_id", value["meta"])

    def test_invalid_arguments_do_not_leak_python_traceback(self):
        value = json.loads(self.bridge.list_purchase_transactions(0, 50, "{}"))
        encoded = json.dumps(value, ensure_ascii=False)
        self.assertEqual(value["error"]["code"], "NO_CASE")
        self.assertNotIn("Traceback", encoded)
        self.assertNotIn("ApplicationError", encoded)

    def test_bad_filter_json_returns_invalid_argument(self):
        value = json.loads(self.bridge.list_purchase_transactions(1, 50, "{"))
        self.assertEqual(value["error"]["code"], "INVALID_ARGUMENT")


if __name__ == "__main__":
    unittest.main()
