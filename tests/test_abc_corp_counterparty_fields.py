import unittest
from unittest.mock import patch

from bankflow_v2.abc_corp import extract_abc_corp
from bankflow_v2.ccb import _statement_metadata as ccb_statement_metadata


class _Page:
    width = 595
    height = 842

    def __init__(self, text="", tables=None, words=None, lines=None):
        self._text = text
        self._tables = tables or []
        self._words = words or []
        self.lines = lines or []

    def extract_text(self):
        return self._text

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


def _word(text, x0, top, x1=None):
    return {"text": text, "x0": x0, "x1": x1 or x0 + 20, "top": top, "size": 9}


class AbcCorpCounterpartyFieldTests(unittest.TestCase):
    def test_maps_nine_column_history_table_counterparty_fields(self):
        header = [
            "交易时间",
            "收入金额",
            "支出金额",
            "账户余额",
            "对方账号",
            "对方户名",
            "对方开户行",
            "摘要",
            "交易用途",
        ]
        row = [
            "2026-01-01 10:20:30",
            "100.00",
            "",
            "1000.00",
            "6222\n0000 0000 1234",
            "甲公司",
            "中国农业银行",
            "转账",
            "货款",
        ]
        page = _Page(tables=[[header, row]])
        with patch("bankflow_v2.abc_corp.pdfplumber.open", return_value=_Pdf([page])):
            transaction = extract_abc_corp("sample.pdf")[0]

        self.assertEqual(transaction.counterparty_account, "6222 0000 0000 1234")
        self.assertEqual(transaction.counterparty_name, "甲公司")
        self.assertEqual(transaction.counterparty_bank, "中国农业银行")
        self.assertEqual(transaction.summary, "转账")
        self.assertEqual(transaction.purpose, "货款")
        self.assertEqual(transaction.field_confidence["counterparty_account"], 1.0)

    def test_maps_only_fixed_independent_coordinate_columns(self):
        words = [
            _word("2026-01-", 20, 100),
            _word("02", 40, 112),
            _word("10:20:30", 30, 124),
            _word("100.00", 80, 124),
            _word("1100.00", 190, 124),
            _word("6222000000001234", 245, 124),
            _word("甲公司", 300, 124),
            _word("中国农业银行", 360, 124),
            _word("货款", 430, 124),
        ]
        page = _Page(words=words)
        with patch("bankflow_v2.abc_corp.pdfplumber.open", return_value=_Pdf([page])):
            transaction = extract_abc_corp("sample.pdf")[0]

        self.assertEqual(transaction.counterparty_account, "6222000000001234")
        self.assertEqual(transaction.counterparty_name, "甲公司")
        self.assertEqual(transaction.counterparty_bank, "中国农业银行")
        self.assertEqual(transaction.purpose, "货款")

    def test_maps_lined_independent_columns_before_mixed_text_fallback(self):
        headers = [
            "交易时间",
            "收入金额",
            "支出金额",
            "账户余额",
            "对方账号",
            "对方户名",
            "对方开户行",
            "交易用途",
        ]
        words = [
            *[
                _word(header, 20 + index * 70, 60, 52 + index * 70)
                for index, header in enumerate(headers)
            ],
            _word("2026-01-02", 20, 80),
            _word("10:20:30", 20, 90),
            _word("100.00", 100, 85),
            _word("1100.00", 240, 85),
            _word("6222000000001234", 300, 80),
            _word("甲公司", 370, 80),
            _word("中国农业银行", 440, 80),
            _word("货款", 520, 80),
        ]
        lines = [
            {"top": top, "width": 60, "height": 0}
            for top in (74, 104)
            for _ in range(8)
        ]
        page = _Page(words=words, lines=lines)
        with patch("bankflow_v2.abc_corp.pdfplumber.open", return_value=_Pdf([page])):
            transaction = extract_abc_corp("sample.pdf")[0]

        self.assertEqual(transaction.counterparty_account, "6222000000001234")
        self.assertEqual(transaction.counterparty_name, "甲公司")
        self.assertEqual(transaction.counterparty_bank, "中国农业银行")
        self.assertEqual(transaction.purpose, "货款")

    def test_ccb_header_metadata_does_not_change_mixed_counterparty_rule(self):
        metadata = ccb_statement_metadata(
            "卡号/账号:6217000480002792404 客户名称:韩鹏飞 "
            "币别:人民币元 钞汇:钞 起止日期:20250121-20260121"
        )

        self.assertEqual(metadata.account_name, "韩鹏飞")
        self.assertEqual(metadata.account_number, "6217000480002792404")
        self.assertEqual(str(metadata.statement_period_start), "2025-01-21")
        self.assertEqual(str(metadata.statement_period_end), "2026-01-21")


if __name__ == "__main__":
    unittest.main()
