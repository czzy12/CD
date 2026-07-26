import unittest
from unittest.mock import patch

from bankflow_v2.abc import extract_abc
from bankflow_v2.boc import extract_boc
from bankflow_v2.boc_corp import extract_boc_corp
from bankflow_v2.bocom import extract_bocom
from bankflow_v2.cmbc import extract_cmbc
from bankflow_v2.icbc_corp import extract_icbc_corp


class _Page:
    def __init__(self, tables=None, text="", words=None, height=800):
        self._tables = tables or []
        self._text = text
        self._words = words or []
        self.height = height

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


class FieldConfirmationBatchTenTests(unittest.TestCase):
    def test_abc_keeps_counterparty_and_channel_as_source_fields_and_cleans_postscript(self):
        text = "20250518 141715 微信支付 -920.00 6630.51 淘宝平台 W076739606 电子商务 NA2025051830155328535028410311003淘宝平台"
        with patch("bankflow_v2.abc.pdfplumber.open", return_value=_Pdf([_Page(text=text)])):
            tx = extract_abc("sample.pdf")[0]

        self.assertEqual(tx.counterparty_name, "")
        self.assertEqual(tx.source_fields["counterparty_info_raw"], "淘宝平台")
        self.assertEqual(tx.transaction_method, "电子商务")
        self.assertEqual(tx.remark, "淘宝平台")

    def test_boc_keeps_channel_and_non_placeholder_branch_as_source_fields(self):
        table = [[
            ["记账日期", "记账时间", "币别", "金额", "余额", "交易名称", "渠道", "网点名称", "附言", "对方账户名", "对方卡号/账号", "对方开户行"],
            ["2026-04-27", "17:22:56", "人民币", "14,835.60", "61,132.06", "工资", "柜台", "中国银行曲靖市分行营业部", "农民工工资专用账户", "云南鑫衢矿业有限公司", "137303327501", "中国银行曲靖市分行营业部"],
        ]]
        with patch("bankflow_v2.boc.pdfplumber.open", return_value=_Pdf([_Page(tables=table)])):
            tx = extract_boc("sample.pdf")[0]

        self.assertEqual(tx.transaction_method, "柜台")
        self.assertEqual(tx.source_fields["branch_name"], "中国银行曲靖市分行营业部")
        self.assertEqual(tx.remark, "农民工工资专用账户")

    def test_boc_corp_keeps_text_only_voucher_detail_reference_and_continued_note(self):
        text = "\n".join([
            "| 1 |251101|251101|小额普通| |BEPS103303324714 2025110106006073/还款 | | 200,000.00| 202,638.49|08860/9880809/163433684|江苏瑞宁威电气设备有限公司|",
            "| | | | | | | | | | |/中国农业银行股份有限公司 |",
        ])
        with patch("bankflow_v2.boc_corp.pdfplumber.open", return_value=_Pdf([_Page(text=text)])):
            tx = extract_boc_corp("sample.pdf")[0]

        self.assertEqual(tx.summary, "还款")
        self.assertEqual(tx.source_fields["operator_reference"], "08860/9880809/163433684")
        self.assertEqual(tx.remark, "")
        self.assertEqual(tx.source_fields["counterparty_info_raw"], "江苏瑞宁威电气设备有限公司/中国农业银行股份有限公司")

    def test_bocom_keeps_confirmed_location_code_out_of_counterparty_account(self):
        table = [[
            ["1", "2025-06-04", "13:55:29", "工资转存", "贷 Cr", "1,594.00", "1,594.01", "03404600040028454", "上海市闵行区财政局", "批处理", "代发工资"],
        ]]
        with patch("bankflow_v2.bocom.pdfplumber.open", return_value=_Pdf([_Page(tables=table)])):
            tx = extract_bocom("sample.pdf")[0]

        self.assertEqual(tx.counterparty_account, "")
        self.assertEqual(tx.counterparty_name, "上海市闵行区财政局")
        self.assertEqual(tx.source_fields["transaction_location"], "03404600040028454")

    def test_icbc_corp_maps_account_and_retains_bank_code_and_receipt_customization(self):
        table = [[
            ["凭证号", "对方账号", "交易时间", "借贷标志", "对方单位", "对方行号", "用途", "摘要", "附言", "回单个性化信息", "发生额", "余额"],
            ["000000000", "773175862334", "2026-03-30 14:48:49", "借", "深圳市宝安区沙井建诚精密机械配件行", "104584079053", "货款", "货款", "", "附言: 指令编号:HQP928041592841 提交人", "2,720.00", "533,799.24"],
        ]]
        with patch("bankflow_v2.icbc_corp.pdfplumber.open", return_value=_Pdf([_Page(tables=table)])):
            tx = extract_icbc_corp("sample.pdf")[0]

        self.assertEqual(tx.counterparty_account, "773175862334")
        self.assertEqual(tx.field_sources["counterparty_account"], "raw_headers[1]:对方账号")
        self.assertEqual(tx.source_fields["counterparty_bank_code"], "104584079053")
        self.assertEqual(tx.source_fields["receipt_customization"], "附言: 指令编号:HQP928041592841 提交人")

    def test_cmbc_personal_ignores_transfer_flag_and_keeps_only_name_side_of_slash(self):
        words = [
            {"text": "2025/11/23", "x0": 97, "top": 106},
            {"text": "16:38:39", "x0": 136, "top": 106},
            {"text": "财付通-快捷支付-polo", "x0": 174, "top": 106},
            {"text": "-129.00", "x0": 348, "top": 106},
            {"text": "2,888.56", "x0": 416, "top": 106},
            {"text": "转账", "x0": 449, "top": 106},
            {"text": "跨行支付", "x0": 483, "top": 106},
            {"text": "0001", "x0": 534, "top": 106},
            {"text": "polo/548582230", "x0": 569, "top": 106},
            {"text": "财付通", "x0": 696, "top": 106},
        ]
        with patch("bankflow_v2.cmbc.pdfplumber.open", return_value=_Pdf([_Page(text="个人账户对账单", words=words)])):
            tx = extract_cmbc("sample.pdf")[0]

        self.assertEqual(tx.counterparty_name, "polo")
        self.assertEqual(tx.counterparty_account, "")
        self.assertNotIn("现转标志", tx.source_fields)
        self.assertEqual(tx.source_fields["counterparty_name_account_raw"], "polo/548582230")


if __name__ == "__main__":
    unittest.main()
