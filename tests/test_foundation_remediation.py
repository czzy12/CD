import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

from bankflow_v2.ccb_corp import extract_ccb_corp
from bankflow_v2.huaxia import extract_huaxia
from bankflow_v2.icbc_corp import extract_icbc_corp
from bankflow_v2.models import TransactionList
from bankflow_v2.psbc import extract_psbc
from bankflow_v2.result_export import build_bankflow_result


class _Row:
    def __init__(self, cells):
        self.cells = cells


class _Table:
    def __init__(self, rows):
        self.rows = rows


class _Page:
    def __init__(self, tables=None, text="", words=None, table_boxes=None):
        self._tables = tables or []
        self._text = text
        self._words = words or []
        self._table_boxes = table_boxes

    def extract_tables(self):
        return self._tables

    def extract_text(self):
        return self._text

    def extract_words(self, **_kwargs):
        return self._words

    def find_tables(self):
        if self._table_boxes is None:
            return []
        return [
            _Table(
                [
                    _Row([tuple(cell) for cell in row])
                    for row in self._table_boxes
                ]
            )
        ]


class _Pdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


SIX_COLUMN_BOXES = [
    [(37.5, 196.0, 94.23, 221.0), (94.23, 196.0, 221.86, 221.0),
     (221.86, 196.0, 297.5, 221.0), (297.5, 196.0, 363.68, 221.0),
     (363.68, 196.0, 429.86, 221.0), (429.86, 196.0, 557.5, 221.0)],
]
NINE_COLUMN_BOXES = [
    [(37.5, 196.0, 75.32, 221.0), (75.32, 196.0, 122.59, 221.0),
     (122.59, 196.0, 169.86, 221.0), (169.86, 196.0, 217.14, 221.0),
     (217.14, 196.0, 264.41, 221.0), (264.41, 196.0, 340.05, 221.0),
     (340.05, 196.0, 415.68, 221.0), (415.68, 196.0, 472.41, 221.0),
     (472.41, 196.0, 557.5, 221.0)],
]


def _six_column_words():
    words = [
        {"text": "记账日期", "x0": 51.9, "top": 202.3},
        {"text": "摘要", "x0": 151.1, "top": 202.3},
        {"text": "交易金额", "x0": 245.7, "top": 202.3},
        {"text": "余额", "x0": 323.6, "top": 202.3},
        {"text": "交易机构", "x0": 382.8, "top": 202.3},
        {"text": "附言", "x0": 486.7, "top": 202.3},
        {"text": "2025-05-18", "x0": 52.5, "top": 231.2},
        {"text": "人行跨行收款", "x0": 96.2, "top": 231.2},
        {"text": "100.00", "x0": 280.2, "top": 231.2},
        {"text": "5279.63", "x0": 343.6, "top": 231.2},
        {"text": "华夏银行股份有限公司", "x0": 365.7, "top": 235.7},
        {"text": "成都武侯支行", "x0": 365.7, "top": 248.7},
        {"text": "2025-05-20", "x0": 52.5, "top": 253.2},
        {"text": "柜台扣收贷款本息", "x0": 96.2, "top": 253.2},
        {"text": "-5019.79", "x0": 275.2, "top": 253.2},
        {"text": "259.84", "x0": 346.4, "top": 253.2},
        {"text": "华夏银行股份有限公司", "x0": 365.7, "top": 257.7},
        {"text": "成都分行贷款业务组", "x0": 365.7, "top": 270.7},
        {"text": "货款", "x0": 487.7, "top": 253.2},
    ]
    return words


def _nine_column_words():
    words = [
        {"text": "记账日期", "x0": 43.0, "top": 202.3},
        {"text": "摘要", "x0": 77.0, "top": 202.3},
        {"text": "交易金额", "x0": 125.0, "top": 202.3},
        {"text": "余额", "x0": 180.0, "top": 202.3},
        {"text": "交易机构", "x0": 218.0, "top": 202.3},
        {"text": "对方姓名", "x0": 265.0, "top": 202.3},
        {"text": "对方卡/账号", "x0": 340.0, "top": 202.3},
        {"text": "对方开户行", "x0": 415.0, "top": 202.3},
        {"text": "附言", "x0": 480.0, "top": 202.3},
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
    return words


class HuaxiaSixColumnTests(unittest.TestCase):
    def test_six_column_layout_maps_columns_and_records_raw_evidence(self):
        page = _Page(
            text="户名：张三 账号：113530******24084",
            words=_six_column_words(),
            table_boxes=SIX_COLUMN_BOXES,
        )
        with patch("bankflow_v2.huaxia.pdfplumber.open", return_value=_Pdf([page])):
            rows = extract_huaxia("sample.pdf")

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertEqual(first.summary, "人行跨行收款")
        self.assertEqual(first.income, Decimal("100.00"))
        self.assertEqual(first.expense, Decimal("0.00"))
        self.assertEqual(first.balance, Decimal("5279.63"))
        self.assertTrue(first.raw_fields)
        self.assertTrue(first.raw_headers)
        self.assertIn("人行跨行收款", first.raw_text)
        self.assertEqual(rows.metadata.account_name, "张三")
        self.assertEqual(rows.metadata.account_number, "")
        self.assertEqual(rows.metadata.raw_fields["masked_account_number"], "113530******24084")
        self.assertEqual(rows.diagnostics["parsed_transaction_count"], 2)
        self.assertEqual(rows.diagnostics["unparsed_row_count"], 0)

        second = rows[1]
        self.assertEqual(second.income, Decimal("0.00"))
        self.assertEqual(second.expense, Decimal("5019.79"))
        self.assertEqual(second.remark, "货款")

    def test_nine_column_layout_still_parses_with_table_boundaries(self):
        page = _Page(
            text="户名：李四 账号：6222000012345678",
            words=_nine_column_words(),
            table_boxes=NINE_COLUMN_BOXES,
        )
        with patch("bankflow_v2.huaxia.pdfplumber.open", return_value=_Pdf([page])):
            rows = extract_huaxia("sample.pdf")

        self.assertEqual(len(rows), 1)
        tx = rows[0]
        self.assertEqual(tx.summary, "手机银行转账")
        self.assertEqual(tx.remark, "货款")
        self.assertEqual(tx.expense, Decimal("20.00"))
        self.assertEqual(tx.balance, Decimal("80.00"))
        self.assertEqual(rows.metadata.account_number, "6222000012345678")
        self.assertEqual(rows.diagnostics["parsed_transaction_count"], 1)

    def test_unparsed_rows_are_visible_in_diagnostics(self):
        words = _six_column_words()
        words.append({"text": "2025-05-21", "x0": 52.5, "top": 275.0})
        page = _Page(text="户名：张三", words=words, table_boxes=SIX_COLUMN_BOXES)
        with patch("bankflow_v2.huaxia.pdfplumber.open", return_value=_Pdf([page])):
            rows = extract_huaxia("sample.pdf")
        self.assertEqual(rows.diagnostics["unparsed_row_count"], 1)
        self.assertEqual(rows.diagnostics["skipped_row_count"], 1)


class IcbcCorpSignedDirectionTests(unittest.TestCase):
    def test_format_b_negative_debit_is_income_and_keeps_raw_evidence(self):
        table = [
            ["交易时间", "借方发生额", "贷方发生额", "余额", "借/贷", "对方账号", "对方户名"],
            ["20260213 11:05:01", "-150,000.00", "", "1,524,544.76", "借", "62220000", "甲公司"],
        ]
        with patch("bankflow_v2.icbc_corp.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            rows = extract_icbc_corp("sample.pdf")

        self.assertEqual(len(rows), 1)
        tx = rows[0]
        self.assertEqual(tx.income, Decimal("150000.00"))
        self.assertEqual(tx.expense, Decimal("0.00"))
        self.assertTrue(tx.raw_fields)
        self.assertTrue(tx.raw_headers)
        self.assertIn("-150,000.00", tx.raw_text)
        self.assertEqual(rows.diagnostics["parsed_transaction_count"], 1)
        self.assertEqual(rows.diagnostics["unparsed_row_count"], 0)

    def test_format_b_negative_credit_is_expense(self):
        table = [
            ["交易时间", "借方发生额", "贷方发生额", "余额", "借/贷", "对方账号", "对方户名"],
            ["20260213 11:05:01", "", "-100.00", "80.00", "贷", "62220000", "甲公司"],
        ]
        with patch("bankflow_v2.icbc_corp.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            tx = extract_icbc_corp("sample.pdf")[0]
        self.assertEqual(tx.income, Decimal("0.00"))
        self.assertEqual(tx.expense, Decimal("100.00"))


class CorpRawEvidenceTests(unittest.TestCase):
    def test_ccb_corp_active_download_path_keeps_raw_fields(self):
        table = [
            ["交易时间", "借方发生额", "贷方发生额", "余额", "摘要", "对方户名"],
            ["1", "2026010109:00:00", "100.00", "", "200.00", "转账", "甲公司"],
        ]
        with patch("bankflow_v2.ccb_corp.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            rows = extract_ccb_corp("sample.pdf")
        tx = rows[0]
        self.assertTrue(tx.raw_fields)
        self.assertTrue(tx.raw_headers)
        self.assertTrue(tx.raw_text)
        self.assertIn("转账", tx.raw_text)
        self.assertEqual(rows.diagnostics["parsed_transaction_count"], 1)

    def test_psbc_history_path_keeps_raw_fields(self):
        table = [
            ["交易时间", "摘要", "收入金额", "支出金额", "余额", "金额", "对方户名"],
            ["2026-01-01 10:00:00", "转账", "", "100.00", "200.00", "-100.00", "甲公司"],
        ]
        with patch("bankflow_v2.psbc.pdfplumber.open", return_value=_Pdf([_Page([table])])):
            rows = extract_psbc("sample.pdf")
        tx = rows[0]
        self.assertTrue(tx.raw_fields)
        self.assertTrue(tx.raw_headers)
        self.assertTrue(tx.raw_text)
        self.assertEqual(rows.diagnostics["parsed_transaction_count"], 1)


class DiagnosticsAndMetadataContractTests(unittest.TestCase):
    def test_source_diagnostics_are_preserved_in_source_files(self):
        result = build_bankflow_result(
            [],
            ai_config={},
            source_diagnostics=[
                {
                    "source_file": "statement.pdf",
                    "status": "included",
                    "source_row_count": 10,
                    "parsed_transaction_count": 9,
                    "skipped_row_count": 1,
                    "unparsed_row_count": 1,
                    "ignored_non_transaction_row_count": 2,
                    "metadata_owner_available": True,
                    "metadata_account_available": False,
                    "metadata_period_available": False,
                }
            ],
        )
        record = result["source_files"][0]
        self.assertEqual(record["source_row_count"], 10)
        self.assertEqual(record["parsed_transaction_count"], 9)
        self.assertEqual(record["unparsed_row_count"], 1)
        self.assertEqual(record["metadata_owner_available"], True)
        self.assertEqual(record["metadata_account_available"], False)

    def test_statement_metadata_has_explicit_availability_flags(self):
        result = build_bankflow_result([], ai_config={})
        metadata = result["statement_metadata"]
        self.assertIn("account_name_available", metadata)
        self.assertIn("account_number_available", metadata)
        self.assertIn("statement_period_available", metadata)

    def test_transaction_list_carries_diagnostics(self):
        rows = TransactionList([], diagnostics={"unparsed_row_count": 3})
        self.assertEqual(rows.diagnostics["unparsed_row_count"], 3)


if __name__ == "__main__":
    unittest.main()
