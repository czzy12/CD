import unittest
from decimal import Decimal
from unittest.mock import patch

from bankflow_v2.abc_corp import _statement_metadata as abc_metadata
from bankflow_v2.ccb_corp import _statement_metadata as ccb_metadata
from bankflow_v2.changsha_bank_corp import extract_changsha_bank_corp
from bankflow_v2.cmb_corp import extract_cmb_corp
from bankflow_v2.customer_detail_corp import extract_customer_detail_corp
from bankflow_v2.hebei_bazhou import extract_bazhou_shunfeng_corp, extract_hebei_personal
from bankflow_v2.icbc_corp import extract_icbc_corp


class _Pdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _TextPage:
    def __init__(self, text):
        self._text = text

    def extract_text(self, *args, **kwargs):
        return self._text


class _TablePage(_TextPage):
    def __init__(self, text, tables):
        super().__init__(text)
        self._tables = tables

    def extract_tables(self):
        return self._tables


class _WordPage(_TextPage):
    height = 800

    def __init__(self, text, words):
        super().__init__(text)
        self._words = words

    def extract_words(self, *args, **kwargs):
        return self._words


def _word(text, x0, top):
    return {"text": text, "x0": x0, "top": top}


class NextConfirmedBankFieldParserTests(unittest.TestCase):
    def test_changsha_keeps_summary_remark_as_one_source_field(self):
        page = _WordPage(
            "单位账户明细对账单 账户名称 客户账号 账单期初余额 账单期末余额 交易日期交易金额账户余额摘要/备注编号",
            [
                _word("20260101", 20, 160),
                _word("-20.00", 110, 160),
                _word("80.00", 225, 160),
                _word("转账/货款", 330, 160),
                _word("123", 456, 160),
            ],
        )
        with patch("bankflow_v2.changsha_bank_corp.pdfplumber.open", return_value=_Pdf([page])):
            tx = extract_changsha_bank_corp("sample.pdf")[0]

        self.assertEqual(tx.source_fields["summary_remark_raw"], "转账/货款")
        self.assertEqual(tx.summary, "")
        self.assertEqual(tx.remark, "")

    def test_cmb_corp_excludes_numeric_bill_number_and_keeps_description(self):
        page = _TextPage("\n".join([
            "20260101对公转账出 7134836497 -20.00 80.00甲公司",
            "20260102网银费用 网上企业银行服务费 -5.00 75.00乙公司",
        ]))
        with patch("bankflow_v2.cmb_corp.pdfplumber.open", return_value=_Pdf([page])):
            transactions = extract_cmb_corp("sample.pdf")

        self.assertEqual(transactions[0].summary, "")
        self.assertEqual(transactions[1].summary, "网上企业银行服务费")
        self.assertEqual(transactions[1].field_sources["summary"], "raw_headers[2]:票据号/摘要")

    def test_hebei_personal_keeps_counterparty_account_only_as_raw_evidence(self):
        text = "20260101 贷 20.00 120.00 6222 甲公司 001 转账 备注"
        with patch("bankflow_v2.hebei_bazhou._extract_text", return_value=text):
            tx = extract_hebei_personal("sample.pdf")[0]

        self.assertEqual(tx.counterparty_account, "")
        self.assertEqual(tx.source_fields["counterparty_account_raw"], "6222")
        self.assertEqual(tx.counterparty_name, "甲公司")

    def test_bazhou_table_maps_confirmed_columns_and_excludes_account(self):
        table = [
            ["交易日期", "对方账户", "对方户名", "对方开户行名", "汇出金额", "汇入金额", "余额", "摘要", "用途"],
            ["2026-01-01", "6222", "甲公司", "示例银行", "20.00", "", "80.00", "转账", "货款"],
        ]
        page = _TablePage("", [table])
        with patch("bankflow_v2.hebei_bazhou.pdfplumber.open", return_value=_Pdf([page])):
            tx = extract_bazhou_shunfeng_corp("sample.pdf")[0]

        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.counterparty_bank, "示例银行")
        self.assertEqual(tx.summary, "转账")
        self.assertEqual(tx.purpose, "货款")
        self.assertEqual(tx.counterparty_account, "")
        self.assertEqual(tx.source_fields["counterparty_account_raw"], "6222")

    def test_customer_detail_keeps_remark_whole_and_excludes_counterparty_account(self):
        page = _WordPage("", [
            _word("20260101", 46, 182),
            _word("-20.00", 89, 182),
            _word("80.00", 147, 182),
            _word("6222", 208, 182),
            _word("甲公司", 285, 182),
            _word("网银转账", 361, 182),
            _word("普通汇兑;附言:货款;", 408, 182),
        ])
        with patch("bankflow_v2.customer_detail_corp.pdfplumber.open", return_value=_Pdf([page])):
            tx = extract_customer_detail_corp("sample.pdf")[0]

        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.summary, "网银转账")
        self.assertEqual(tx.remark, "普通汇兑;附言:货款;")
        self.assertEqual(tx.counterparty_account, "")
        self.assertEqual(tx.source_fields["counterparty_account_raw"], "6222")

    def test_icbc_account_detail_maps_only_confirmed_fields(self):
        header = ["凭证号", "对方账号", "交易时间", "借贷标志", "对方单位", "对方行号", "用途", "摘要", "附言", "回单个性化信息", "发生额", "余额"]
        row = ["1", "6222", "2026-01-01 10:00:00", "借", "甲公司", "", "货款", "转账", "", "补充摘要", "20.00", "80.00"]
        page = _TablePage("", [[header, row]])
        with patch("bankflow_v2.icbc_corp.pdfplumber.open", return_value=_Pdf([page])):
            tx = extract_icbc_corp("sample.pdf")[0]

        self.assertEqual(tx.counterparty_name, "甲公司")
        self.assertEqual(tx.summary, "转账")
        self.assertEqual(tx.purpose, "货款")
        self.assertEqual(tx.counterparty_account, "")
        self.assertNotIn("card_number", tx.source_fields)

    def test_abc_corp_extracts_confirmed_file_metadata(self):
        text = "账号:14-321 户名:甲公司 币种:人民币 起止日期: 2025年05月14日 - 2025年11月14日"
        with patch("bankflow_v2.abc_corp.pdfplumber.open", return_value=_Pdf([_TextPage(text)])):
            metadata = abc_metadata("sample.pdf")

        self.assertEqual(metadata.account_name, "甲公司")
        self.assertEqual(metadata.account_number, "14-321")
        self.assertEqual(str(metadata.statement_period_start), "2025-05-14")
        self.assertEqual(str(metadata.statement_period_end), "2025-11-14")

    def test_ccb_corp_extracts_confirmed_file_metadata(self):
        text = "账号：510501 账户名称：甲公司 日期：20260118-20260319 第1页"
        with patch("bankflow_v2.ccb_corp.pdfplumber.open", return_value=_Pdf([_TextPage(text)])):
            metadata = ccb_metadata("sample.pdf")

        self.assertEqual(metadata.account_name, "甲公司")
        self.assertEqual(metadata.account_number, "510501")
        self.assertEqual(str(metadata.statement_period_start), "2026-01-18")
        self.assertEqual(str(metadata.statement_period_end), "2026-03-19")


if __name__ == "__main__":
    unittest.main()
