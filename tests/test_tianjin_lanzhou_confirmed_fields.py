import unittest
from decimal import Decimal
from unittest.mock import patch

from bankflow_v2.city_commercial import extract_lanzhou
from bankflow_v2.tianjin_rural_corp import extract_tianjin_rural


class _Page:
    def __init__(self, tables=None):
        self._tables = tables or []

    def extract_tables(self):
        return self._tables


class _Pdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class TianjinLanzhouConfirmedFieldTests(unittest.TestCase):
    def test_tianjin_rural_maps_counterparty_account_and_keeps_confirmed_headers(self):
        row = {
            "交易日期": "20260513",
            "交易时间": "19:05:40",
            "交易摘要": "快捷支付",
            "交易金额": "-34.80",
            "当前余额": "8600.83",
            "交易附言": "附言编号",
            "对手户名": "北京三快在线科技有限公司",
            "对手账号": "20881418178444930156",
            "交易渠道": "农信银系统",
        }
        with patch("bankflow_v2.tianjin_rural_corp.pdfplumber.open", return_value=_Pdf([_Page()])):
            with patch("bankflow_v2.tianjin_rural_corp.extract_coordinate_rows", return_value=[row]):
                tx = extract_tianjin_rural("sample.pdf")[0]

        self.assertEqual(tx.expense, Decimal("34.80"))
        self.assertEqual(tx.summary, "快捷支付")
        self.assertEqual(tx.counterparty_name, "北京三快在线科技有限公司")
        self.assertNotIn("交易附言", tx.raw_headers)
        self.assertIn("对手账号", tx.raw_headers)
        self.assertEqual(tx.counterparty_account, "20881418178444930156")
        self.assertEqual(tx.source_fields["transaction_channel_raw"], "农信银系统")

    def test_lanzhou_excludes_sequence_and_maps_counterparty_account(self):
        headers = ["序号", "交易日期", "收/支金额", "余额", "对方户名", "对方帐号", "对方行名", "现转标识", "交易渠道", "交易摘要"]
        row = ["1", "2026-01-02", "-20.00", "80.00", "甲公司", "6222", "乙银行", "转账", "网银", "货款"]
        with patch("bankflow_v2.city_commercial.pdfplumber.open", return_value=_Pdf([_Page(tables=[[headers, row]])])):
            tx = extract_lanzhou("sample.pdf")[0]

        self.assertEqual(tx.expense, Decimal("20.00"))
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.counterparty_bank, "乙银行")
        self.assertEqual(tx.summary, "货款")
        self.assertNotIn("序号", tx.raw_headers)
        self.assertIn("对方帐号", tx.raw_headers)
        self.assertEqual(tx.counterparty_account, "6222")
        self.assertIn("现转标识", tx.raw_headers)
        self.assertIn("交易渠道", tx.raw_headers)


if __name__ == "__main__":
    unittest.main()
