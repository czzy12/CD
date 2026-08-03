from __future__ import annotations

import unittest

from bankflow_web.contracts import CaseHeaderDTO, TransactionListItemDTO, to_dict


class WebContractTests(unittest.TestCase):
    def test_case_header_has_only_stable_summary_fields(self):
        value = to_dict(CaseHeaderDTO("fixture", "2026-01-01", "2026-01-02", 1, 2, "已完成", "证据完整", "1.16"))
        self.assertEqual(value["schema_version"], "1.16")
        self.assertNotIn("standard_result", value)
        self.assertNotIn("absolute_path", value)

    def test_list_item_excludes_full_transaction_and_sensitive_identifiers(self):
        value = to_dict(TransactionListItemDTO("tx:1", "2026-01-01", "支出", "100.00", "公司", "订金", "现有观察", "sample.pdf", "订金/定金", "direct"))
        self.assertNotIn("original_transactions", value)
        self.assertNotIn("raw_fields", value)
        self.assertNotIn("account_number", value)
        self.assertNotIn("source_path", value)


if __name__ == "__main__":
    unittest.main()
