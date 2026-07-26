import unittest
from unittest.mock import patch

from bankflow_v2.ccb import extract_ccb
from bankflow_v2.cib import extract_cib
from bankflow_v2.citic import extract_citic
from bankflow_v2.cmb import extract_cmb
from bankflow_v2.cmbc_corp import extract_cmbc_corp
from bankflow_v2.huaxia import extract_huaxia
from bankflow_v2.icbc import extract_icbc
from bankflow_v2.pingan import extract_pingan
from bankflow_v2.spdb import extract_spdb, extract_spdb_corp


class _Page:
    def __init__(self, tables=None, text="", words=None):
        self._tables = tables or []
        self._text = text
        self._words = words or []

    def extract_tables(self):
        return self._tables

    def extract_text(self):
        return self._text

    def extract_words(self, **_kwargs):
        return self._words


class _Pdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class ConfirmedBankFieldParserTests(unittest.TestCase):
    def test_icbc_preserves_confirmed_fields_and_excludes_accounts(self):
        table = [["header"] * 13, [
            "2026-01-01 10:20:30", "本方账号", "活期", "7", "人民币", "钞", "转账", "北京",
            "+100.00", "100.00", "甲公司", "对方账号", "网银",
        ]]
        with patch("bankflow_v2.icbc.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            tx = extract_icbc("sample.pdf")[0]

        self.assertEqual(tx.summary, "转账")
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.counterparty_account, "")
        self.assertEqual(tx.source_sequence, "7")
        self.assertEqual(tx.source_fields, {"storage_type": "活期", "transaction_channel": "网银"})

    def test_ccb_only_splits_unique_slash_and_keeps_combined_location_remark(self):
        table = [["header"] * 7, ["1", "消费", "20260101", "-20.00", "80.00", "网点，附言", "6222/甲公司"]]
        with patch("bankflow_v2.ccb.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            tx = extract_ccb("sample.pdf")[0]

        self.assertEqual(tx.summary, "消费")
        self.assertEqual(tx.remark, "网点，附言")
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.counterparty_account, "")
        self.assertEqual(tx.source_fields["transaction_location"], "网点，附言")
        self.assertEqual(tx.source_fields["counterparty_account_name_raw"], "6222/甲公司")

    def test_ccb_maps_only_full_numeric_account_before_unique_slash(self):
        table = [["header"] * 7, [
            "1", "电子汇出", "20260101", "-20.00", "80.00", "转账", "6217004530016072148/甲公司",
        ], [
            "2", "消费", "20260102", "-10.00", "70.00", "消费", "4******9202/乙商户",
        ], [
            "3", "转账", "20260103", "-5.00", "65.00", "转账", "6217004530016072148/",
        ]]
        with patch("bankflow_v2.ccb.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            full_account, masked_account, missing_name = extract_ccb("sample.pdf")

        self.assertEqual(full_account.counterparty_account, "6217004530016072148")
        self.assertEqual(full_account.counterparty_name, "甲公司")
        self.assertEqual(full_account.field_confidence["counterparty_account"], 1.0)
        self.assertEqual(
            full_account.source_fields["counterparty_account_name_raw"],
            "6217004530016072148/甲公司",
        )
        self.assertEqual(masked_account.counterparty_account, "")
        self.assertEqual(masked_account.counterparty_name, "乙商户")
        self.assertEqual(missing_name.counterparty_account, "")
        self.assertEqual(missing_name.counterparty_name, "")

    def test_cib_maps_nine_confirmed_columns_without_splitting_mixed_counterparty(self):
        table = [["header"] * 9, [
            "2026-01-01 10:00:00", "20260101", "汇款", "支", "-20.00", "80.00", "货款", "甲公司", "6222/示例银行",
        ]]
        with patch("bankflow_v2.cib.pdfplumber.open", return_value=_Pdf([_Page([table], "")])):
            tx = extract_cib("sample.pdf")[0]

        self.assertEqual(tx.summary, "汇款")
        self.assertEqual(tx.transaction_direction, "支")
        self.assertEqual(tx.purpose, "货款")
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.counterparty_account, "")
        self.assertEqual(tx.source_fields["counterparty_account_bank_raw"], "6222/示例银行")

    def test_cmbc_corp_splits_only_unique_slash_boundary(self):
        text = "\n".join([
            "2026/01/01 货款 网银凭证 00000001 20.00 0.00 80.00 123456789012 甲公司/6222 示例银行",
            "10:20:30 34567890123 总行",
        ])
        with patch("bankflow_v2.cmbc_corp.pdfplumber.open", return_value=_Pdf([_Page(text=text)])):
            tx = extract_cmbc_corp("sample.pdf")[0]

        self.assertEqual(tx.summary, "货款")
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.counterparty_account, "6222")
        self.assertEqual(tx.counterparty_bank, "示例银行 总行")
        self.assertEqual(tx.source_fields["voucher_type"], "网银凭证")
        self.assertEqual(tx.source_fields["voucher_number"], "00000001")
        self.assertEqual(tx.source_fields["transaction_reference"], "12345678901234567890123")

    def test_pingan_preserves_counterparty_info_without_splitting(self):
        table = [["header"] * 8, ["1", "2026-01-01", "-20.00", "80.00", "平安银行", "快捷支付", "财付通", "示例银行-甲公司-6222"]]
        with patch("bankflow_v2.pingan.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            tx = extract_pingan("sample.pdf")[0]

        self.assertEqual(tx.summary, "快捷支付")
        self.assertEqual(tx.remark, "财付通")
        self.assertEqual(tx.counterparty_name, "")
        self.assertEqual(tx.source_fields["transaction_location"], "平安银行")
        self.assertEqual(tx.source_fields["counterparty_info_raw"], "示例银行-甲公司-6222")

    def test_spdb_personal_excludes_account_and_empty_summary_columns(self):
        table = [["header"] * 9, ["20260101", "102030", "本方账号", "工资", "100.00", "100.00", "甲公司", "对手账号", "****"]]
        with patch("bankflow_v2.spdb.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            tx = extract_spdb("sample.pdf")[0]

        self.assertEqual(tx.transaction_type, "工资")
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.counterparty_account, "")
        self.assertEqual(tx.summary, "")

    def test_spdb_corp_maps_confirmed_fields_and_keeps_abstract_code(self):
        table = [["header"] * 9, [None] * 9, [
            "2026/01/01", "TX1", "20.00", "", "80.00", "示例银行", "甲公司", "电子渠道转账", "货款",
        ]]
        with patch("bankflow_v2.spdb.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            tx = extract_spdb_corp("sample.pdf")[0]

        self.assertEqual(tx.counterparty_bank, "示例银行")
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.remark, "货款")
        self.assertEqual(tx.transaction_type, "电子渠道转账")
        self.assertEqual(tx.source_fields["abstract_code"], "电子渠道转账")
        self.assertEqual(tx.source_fields["transaction_reference"], "TX1")

    def test_citic_splits_fixed_tail_columns_and_keeps_statement_metadata(self):
        text = "\n".join([
            "户名：王杰 证件类型：居民身份证 证件号码：已排除",
            "账号：62170001 时间段：20250101-20251231 开立日期：2026-01-01",
            "查询最低限额：0 币种：全部",
            "20250101 RMB 100.00 RMB 100.00 转账 6222 甲公司",
        ])
        with patch("bankflow_v2.citic.pdfplumber.open", return_value=_Pdf([_Page(text=text)])):
            rows = extract_citic("sample.pdf")
        tx = rows[0]

        self.assertEqual(tx.summary, "转账")
        self.assertEqual(tx.counterparty_account, "6222")
        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.source_fields["currency_raw"], "RMB")
        self.assertEqual(rows.metadata.account_name, "王杰")
        self.assertEqual(rows.metadata.account_number, "62170001")
        self.assertEqual(rows.metadata.raw_fields["开户日期"], "2026-01-01")

    def test_cmb_splits_summary_and_terminal_counterparty_account(self):
        text = "2025-01-01 CNY 100.00 100.00 汇入汇款 甲公司 华北分公司 6222"
        with patch("bankflow_v2.cmb.pdfplumber.open", return_value=_Pdf([_Page(text=text)])):
            tx = extract_cmb("sample.pdf")[0]

        self.assertEqual(tx.summary, "汇入汇款")
        self.assertEqual(tx.counterparty_name, "甲公司 华北分公司")
        self.assertEqual(tx.counterparty_account, "6222")
        self.assertEqual(tx.source_fields["counterparty_info_raw"], "甲公司 华北分公司 6222")

    def test_huaxia_uses_fixed_coordinate_columns_for_confirmed_fields(self):
        words = [
            {"text": "2025-01-01", "x0": 43.0, "top": 230.0},
            {"text": "手机银行转账", "x0": 77.0, "top": 230.0},
            {"text": "-20.00", "x0": 145.0, "top": 230.0},
            {"text": "80.00", "x0": 195.0, "top": 230.0},
            {"text": "华夏银行营业部", "x0": 220.0, "top": 230.0},
            {"text": "甲公司", "x0": 266.0, "top": 230.0},
            {"text": "6222", "x0": 342.0, "top": 230.0},
            {"text": "示例银行", "x0": 418.0, "top": 230.0},
            {"text": "货款", "x0": 482.0, "top": 230.0},
        ]
        with patch("bankflow_v2.huaxia.pdfplumber.open", return_value=_Pdf([_Page(words=words)])):
            tx = extract_huaxia("sample.pdf")[0]

        self.assertEqual(tx.summary, "手机银行转账")
        self.assertEqual(tx.remark, "货款")
        self.assertEqual(tx.counterparty_bank, "")
        self.assertEqual(tx.source_fields["transaction_institution"], "华夏银行营业部")


if __name__ == "__main__":
    unittest.main()
