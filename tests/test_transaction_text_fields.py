import unittest
from datetime import datetime
from decimal import Decimal

from bankflow_v2.models import Transaction, map_standard_text_fields
from bankflow_v2.summary import summarize


class TransactionTextFieldTests(unittest.TestCase):
    def test_maps_exact_header_synonyms(self):
        headers = [
            "对方账户名称",
            "对方卡号/账号",
            "对方开户行",
            "摘要信息",
            "附言",
            "交易用途",
            "业务类型",
            "商户名称",
            "商户类别",
            "交易地点",
        ]
        fields = ["甲公司", "62220001", "示例银行", "转账", "加急", "货款", "网银转账", "乙商户", "零售", "上海"]

        transaction = Transaction(datetime(2026, 7, 18), raw_headers=headers, raw_fields=fields)

        self.assertEqual(transaction.counterparty_name, "甲公司")
        self.assertEqual(transaction.counterparty_account, "62220001")
        self.assertEqual(transaction.counterparty_bank, "示例银行")
        self.assertEqual(transaction.summary, "转账")
        self.assertEqual(transaction.remark, "加急")
        self.assertEqual(transaction.purpose, "货款")
        self.assertEqual(transaction.transaction_type, "网银转账")
        self.assertEqual(transaction.merchant_name, "乙商户")
        self.assertEqual(transaction.merchant_category, "零售")
        self.assertEqual(transaction.merchant_location, "上海")
        self.assertEqual(transaction.field_sources["counterparty_name"], "raw_headers[0]:对方账户名称")
        self.assertEqual(transaction.field_confidence["counterparty_name"], 1.0)

    def test_explicit_fields_and_metadata_are_not_overwritten(self):
        transaction = Transaction(
            datetime(2026, 7, 18),
            raw_headers=["对方户名", "摘要"],
            raw_fields=["自动对手", "自动摘要"],
            counterparty_name="显式对手",
            summary="显式摘要",
            field_sources={"summary": "parser:explicit"},
            field_confidence={"summary": 0.8},
        )

        self.assertEqual(transaction.counterparty_name, "显式对手")
        self.assertEqual(transaction.summary, "显式摘要")
        self.assertNotIn("counterparty_name", transaction.field_sources)
        self.assertEqual(transaction.field_sources["summary"], "parser:explicit")
        self.assertEqual(transaction.field_confidence["summary"], 0.8)

    def test_missing_or_ambiguous_fields_remain_empty(self):
        transaction = Transaction(
            datetime(2026, 7, 18),
            raw_text="对方户名可能是甲公司",
            raw_headers=["摘要/备注", "对方账号/户名", "对方户名"],
            raw_fields=["混合内容", "混合对手", ""],
        )

        self.assertEqual(transaction.counterparty_name, "")
        self.assertEqual(transaction.counterparty_account, "")
        self.assertEqual(transaction.summary, "")
        self.assertEqual(transaction.remark, "")
        self.assertEqual(transaction.field_sources, {})
        self.assertEqual(transaction.field_confidence, {})
        self.assertEqual(transaction.manual_review, {})

    def test_mapping_tool_ignores_missing_columns(self):
        self.assertEqual(map_standard_text_fields(["对方户名"], []), {})

    def test_standard_text_fields_do_not_change_numeric_summary(self):
        plain = [
            Transaction(datetime(2026, 7, 1), income=Decimal("100.00"), balance=Decimal("110.00")),
            Transaction(datetime(2026, 7, 2), expense=Decimal("40.00"), balance=Decimal("70.00")),
        ]
        enriched = [
            Transaction(
                datetime(2026, 7, 1),
                income=Decimal("100.00"),
                balance=Decimal("110.00"),
                raw_headers=["对方户名", "摘要"],
                raw_fields=["甲公司", "收款"],
            ),
            Transaction(
                datetime(2026, 7, 2),
                expense=Decimal("40.00"),
                balance=Decimal("70.00"),
                counterparty_name="乙公司",
                summary="付款",
            ),
        ]

        plain_summary = summarize(plain)
        enriched_summary = summarize(enriched)
        for name in (
            "count",
            "income_count",
            "income_sum",
            "expense_count",
            "expense_sum",
            "net",
            "opening_balance",
            "closing_balance",
        ):
            self.assertEqual(getattr(enriched_summary, name), getattr(plain_summary, name))
        self.assertEqual(enriched_summary.issues, plain_summary.issues)


if __name__ == "__main__":
    unittest.main()
