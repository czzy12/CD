import unittest
from unittest.mock import patch

from bankflow_v2.city_commercial import extract_foshan_rural, extract_jiujiang, extract_nanjing_corp, extract_ningbo
from bankflow_v2.luzhou import extract_luzhou
from bankflow_v2.shanghai import extract_shanghai
from bankflow_v2.shengjing import extract_shengjing
from bankflow_v2.xingtai import extract_xingtai


class _Page:
    def __init__(self, *, tables=None, words=None):
        self._tables = tables or []
        self._words = words or []

    def extract_tables(self):
        return self._tables

    def extract_words(self, **_kwargs):
        return self._words


class _Pdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _words(headers, values):
    positions = [10 + 80 * index for index in range(len(headers))]
    return [
        *[{"text": header, "x0": x0, "top": 10} for header, x0 in zip(headers, positions)],
        *[{"text": value, "x0": x0, "top": 30} for value, x0 in zip(values, positions)],
    ]


class FieldConfirmationBatchEightTests(unittest.TestCase):
    def test_foshan_excludes_confirmed_columns_and_maps_remaining_headers(self):
        headers = ["流水号", "记账日期", "交易日期", "收入/支出", "余额", "对方账号", "对方户名", "对方行名", "交易类型", "摘要", "附言"]
        row = ["001", "2026-01-02", "2026-01-02", "-20.00", "80.00", "6222", "甲公司", "示例银行", "转账", "货款", "无需保留"]
        with patch("bankflow_v2.city_commercial.pdfplumber.open", return_value=_Pdf([_Page(tables=[[headers, row]])])):
            tx = extract_foshan_rural("sample.pdf")[0]
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.summary, "货款")
        self.assertNotIn("流水号", tx.raw_headers)
        self.assertNotIn("记账日期", tx.raw_headers)
        self.assertNotIn("附言", tx.raw_headers)

    def test_jiujiang_preserves_currency_and_summary_without_currency_prompt_logic(self):
        headers = ["记账日期", "货币", "交易金额", "联机余额", "交易摘要", "对手信息"]
        with patch("bankflow_v2.city_commercial.pdfplumber.open", return_value=_Pdf([_Page(words=_words(headers, ["20260102", "CNY", "20.00", "80.00", "转账", "甲公司"]))])):
            tx = extract_jiujiang("sample.pdf")[0]
        self.assertEqual(tx.summary, "转账")
        self.assertEqual(tx.source_fields["counterparty_info_raw"], "甲公司")
        self.assertIn("货币", tx.raw_headers)

    def test_luzhou_maps_transaction_channel_to_transaction_method(self):
        headers = ["序号", "交易时间", "币种", "交易金额", "账户余额", "对方账号", "对方户名", "交易类型", "摘要", "交易渠道"]
        row = ["1", "2026-01-02\n10:20:30", "人民币", "-20.00", "80.00", "6222", "甲公司", "转账", "货款", "手机银行"]
        with patch("bankflow_v2.luzhou.pdfplumber.open", return_value=_Pdf([_Page(tables=[[headers, row]])])):
            tx = extract_luzhou("sample.pdf")[0]
        self.assertEqual(tx.transaction_method, "手机银行")
        self.assertEqual(tx.field_sources["transaction_method"], "raw_headers[9]:交易渠道")

    def test_nanjing_excludes_sequence_and_reference_while_mapping_fields(self):
        headers = ["序号", "交易日期", "收入", "支出", "账户余额", "对方账号", "对方户名", "对方行名", "摘要", "附言", "流水号"]
        row = ["1", "2026-01-02 10:20:30", "", "20.00", "80.00", "6222", "甲公司", "示例银行", "转账", "货款", "TX1"]
        with patch("bankflow_v2.city_commercial.pdfplumber.open", return_value=_Pdf([_Page(tables=[[headers, row]])])):
            tx = extract_nanjing_corp("sample.pdf")[0]
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.remark, "货款")
        self.assertNotIn("序号", tx.raw_headers)
        self.assertNotIn("流水号", tx.raw_headers)

    def test_ningbo_excludes_currency_and_operator(self):
        headers = ["日期", "摘要", "币种", "交易金额", "余额", "交易柜员"]
        with patch("bankflow_v2.city_commercial.pdfplumber.open", return_value=_Pdf([_Page(words=_words(headers, ["2026-01-02", "工资", "人民币", "20.00", "80.00", "001"]))])):
            tx = extract_ningbo("sample.pdf")[0]
        self.assertEqual(tx.summary, "工资")
        self.assertNotIn("币种", tx.raw_headers)
        self.assertNotIn("交易柜员", tx.raw_headers)

    def test_shanghai_excludes_branch_and_keeps_channel_as_source_evidence(self):
        headers = ["记账日期", "交易摘要", "币种", "交易金额", "期末金额", "交易网点", "对方户名", "交易渠道"]
        values = ["20260102", "网联付款", "CNY", "-20.00", "80.00", "上海银行支行", "甲公司", "网络支付清算"]
        with patch("bankflow_v2.shanghai.pdfplumber.open", return_value=_Pdf([_Page(words=_words(headers, values))])):
            tx = extract_shanghai("sample.pdf")[0]
        self.assertEqual(tx.summary, "网联付款")
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.transaction_method, "")
        self.assertEqual(tx.source_fields["transaction_channel_raw"], "网络支付清算")
        self.assertNotIn("交易网点", tx.raw_headers)

    def test_shengjing_excludes_currency_and_preserves_counterparty_evidence(self):
        headers = ["记账日期", "货币", "交易金额", "账户余额", "交易摘要", "对手信息", "附言"]
        values = ["20260102", "人民币", "20.00", "80.00", "工资", "甲公司", "批量代发"]
        with patch("bankflow_v2.shengjing.pdfplumber.open", return_value=_Pdf([_Page(words=_words(headers, values))])):
            tx = extract_shengjing("sample.pdf")[0]
        self.assertEqual(tx.summary, "工资")
        self.assertEqual(tx.remark, "批量代发")
        self.assertEqual(tx.source_fields["counterparty_info_raw"], "甲公司")
        self.assertNotIn("货币", tx.raw_headers)

    def test_xingtai_maps_counterparty_account_and_excludes_channel(self):
        headers = ["交易时间", "收入/支出", "交易金额（元）", "余额（元）", "对方账号", "对方账户名称", "交易户名", "交易账号", "交易渠道", "交易摘要"]
        row = ["2026-01-02\n10:20:30", "收入", "20.00", "80.00", "6222", "甲公司", "本方公司", "1111", "企业网银", "货款"]
        with patch("bankflow_v2.xingtai.pdfplumber.open", return_value=_Pdf([_Page(tables=[[headers, row]])])):
            tx = extract_xingtai("sample.pdf")[0]
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.summary, "货款")
        self.assertEqual(tx.source_fields["transaction_account_name_raw"], "本方公司")
        self.assertIn("对方账号", tx.raw_headers)
        self.assertNotIn("交易账号", tx.raw_headers)
        self.assertNotIn("交易渠道", tx.raw_headers)


if __name__ == "__main__":
    unittest.main()
