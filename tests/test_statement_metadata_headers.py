import unittest
from unittest.mock import patch

from bankflow_v2.abc import _statement_metadata as abc_metadata
from bankflow_v2.abc import extract_abc
from bankflow_v2.icbc import _statement_metadata as icbc_metadata
from bankflow_v2.icbc import extract_icbc
from bankflow_v2.models import TransactionList, get_statement_metadata


class _Page:
    def __init__(self, tables=None, text=""):
        self._tables = tables or []
        self._text = text

    def extract_tables(self):
        return self._tables

    def extract_text(self):
        return self._text


class _Pdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class StatementMetadataHeaderTests(unittest.TestCase):
    def test_abc_maps_one_labeled_name_and_full_account(self):
        metadata = abc_metadata("户名：张鑫 账户：6222 0000-0000 1234 567 币种：人民币")

        self.assertEqual(metadata.account_name, "张鑫")
        self.assertEqual(metadata.account_number, "6222000000001234567")
        self.assertEqual(metadata.raw_fields["账户"], "6222 0000-0000 1234 567")
        self.assertEqual(metadata.field_sources["account_number"], "page=1:document_header:账户")
        self.assertEqual(metadata.field_confidence["account_name"], 1.0)
        self.assertEqual(metadata.field_confidence["account_number"], 1.0)

    def test_icbc_maps_one_labeled_name_and_full_card(self):
        metadata = icbc_metadata("卡号 6222 0000-0000 1234 567 户名：姚志国 起止日期：2025-03-16")

        self.assertEqual(metadata.account_name, "姚志国")
        self.assertEqual(metadata.account_number, "6222000000001234567")
        self.assertEqual(metadata.raw_fields["卡号"], "6222 0000-0000 1234 567")
        self.assertEqual(metadata.field_sources["account_number"], "page=1:document_header:卡号")
        self.assertEqual(metadata.field_confidence["account_name"], 1.0)
        self.assertEqual(metadata.field_confidence["account_number"], 1.0)

    def test_rejects_masked_invalid_or_multiple_header_accounts(self):
        for extractor, text in (
            (abc_metadata, "户名：张鑫 账户：6222****1234"),
            (abc_metadata, "户名：张鑫 账户：12345678901"),
            (abc_metadata, "户名：张鑫 账户：6222000000001234567 账户：6222000000001234568"),
            (icbc_metadata, "户名：姚志国 卡号：6222****1234"),
            (icbc_metadata, "户名：姚志国 卡号：12345678901"),
            (icbc_metadata, "户名：姚志国 卡号：6222000000001234567 卡号：6222000000001234568"),
        ):
            with self.subTest(text=text):
                metadata = extractor(text)
                self.assertEqual(metadata.account_name, "")
                self.assertEqual(metadata.account_number, "")
                self.assertEqual(metadata.field_confidence, {})

    def test_extractors_attach_metadata_without_changing_transaction_lists(self):
        abc_table = [["交易日期", "交易发生额", "账户余额", "对方账号", "对方户名", "摘要", "备注"], [
            "20260101", "100.00", "100.00", "", "", "转账", "",
        ]]
        icbc_table = [["header"] * 13, [
            "2026-01-01 10:20:30", "本方账号", "活期", "7", "人民币", "钞", "转账", "北京",
            "+100.00", "100.00", "甲公司", "对方账号", "网银",
        ]]
        with patch(
            "bankflow_v2.abc.pdfplumber.open",
            return_value=_Pdf([_Page([abc_table], "户名：张鑫 账户：6222000000001234567")]),
        ):
            abc_transactions = extract_abc("sample.pdf")
        with patch(
            "bankflow_v2.icbc.pdfplumber.open",
            return_value=_Pdf([_Page([icbc_table], "卡号 6222000000001234567 户名：姚志国")]),
        ):
            icbc_transactions = extract_icbc("sample.pdf")

        self.assertIsInstance(abc_transactions, TransactionList)
        self.assertIsInstance(icbc_transactions, TransactionList)
        self.assertEqual(len(abc_transactions), 1)
        self.assertEqual(len(icbc_transactions), 1)
        self.assertEqual(abc_transactions[0].income, 100)
        self.assertEqual(icbc_transactions[0].income, 100)
        self.assertEqual(get_statement_metadata(abc_transactions).account_name, "张鑫")
        self.assertEqual(get_statement_metadata(icbc_transactions).account_name, "姚志国")


if __name__ == "__main__":
    unittest.main()
