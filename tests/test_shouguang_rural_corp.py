import unittest
from unittest.mock import patch

from bankflow_v2.jinan_rural_corp import extract_shouguang_rural_corp


class _Pdf:
    def __init__(self, rows):
        self.pages = [_Page(rows)]

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class _Page:
    def __init__(self, rows):
        self._rows = rows

    def extract_tables(self):
        return [self._rows]


class ShouguangRuralCorpTests(unittest.TestCase):
    def test_extracts_shared_rural_corp_layout_with_shouguang_label(self):
        rows = [["2025-09-05", "+30000.00", None, "36363.30", None, "跨行实时汇入", None, None, "王文明 6214855360350918"]]

        with patch("bankflow_v2.jinan_rural_corp.pdfplumber.open", return_value=_Pdf(rows)):
            transactions = extract_shouguang_rural_corp("statement.pdf")

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].bank, "寿光农村商业银行对公")
        self.assertEqual(str(transactions[0].income), "30000.00")
        self.assertEqual(str(transactions[0].balance), "36363.30")


if __name__ == "__main__":
    unittest.main()
