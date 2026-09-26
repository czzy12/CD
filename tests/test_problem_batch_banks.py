import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from bankflow_v2.fuxin_corp import extract_fuxin_corp
from bankflow_v2.gansu import extract_gansu
from bankflow_v2.mengshang_corp import extract_mengshang_corp
from bankflow_v2.shanxi_rural_corp import extract_shanxi_rural_corp
from bankflow_v2.sichuan_rural import extract_sichuan_rural
from bankflow_v2.summary import summarize


def fake_pdf(rows):
    page = MagicMock()
    page.extract_tables.return_value = [[*rows]]
    pdf = MagicMock()
    pdf.__enter__.return_value.pages = [page]
    return pdf


class ProblemBatchBankTests(unittest.TestCase):
    def test_sichuan_rural_excludes_proven_reversal_pair(self):
        rows = [
            ["20260513", "16:53:38", "人民币", "-100.00", "10.00", "甲", "1", "银行", "转出", "", "20260513"],
            ["20260513", "16:53:41", "人民币", "100.00", "110.00", "甲", "1", "无", "跨行转出-抹账", "抹账", "20260513"],
            ["20260513", "17:00:00", "人民币", "10.00", "120.00", "乙", "2", "银行", "转入", "", "20260513"],
        ]
        with patch("bankflow_v2.sichuan_rural.pdfplumber.open", return_value=fake_pdf(rows)):
            summary = summarize(extract_sichuan_rural("sample.pdf"))
        self.assertEqual(summary.count, 1)
        self.assertEqual(summary.income_sum, Decimal("10.00"))
        self.assertEqual(summary.issues, [])

    def test_fuxin_same_second_reverse_source_order(self):
        rows = [
            ["20260410", "09:26:30", "人民币", "15.00", "0.00", "299985.00"],
            ["20260410", "09:26:30", "人民币", "300000.00", "0.00", "300000.00"],
            ["20260410", "09:00:00", "人民币", "0.00", "600000.00", "600000.00"],
        ]
        with patch("bankflow_v2.fuxin_corp.pdfplumber.open", return_value=fake_pdf(rows)):
            self.assertEqual(summarize(extract_fuxin_corp("sample.pdf")).issues, [])

    def test_shanxi_negative_expense_is_reversal_income(self):
        rows = [["2026-03-30\n12:02:09", "1", "0.00", "-200.00", "300.00"]]
        with patch("bankflow_v2.shanxi_rural_corp.pdfplumber.open", return_value=fake_pdf(rows)):
            tx = extract_shanxi_rural_corp("sample.pdf")[0]
        self.assertEqual(tx.income, Decimal("200.00"))
        self.assertEqual(tx.expense, Decimal("0.00"))

    def test_gansu_watermark_and_same_second(self):
        rows = [
            ["甘\n2026-08-26 16:53:02", "3.50", "741.80", "x", "y", "支出"],
            ["2026-08-26 16:53:02", "2,000.00", "745.30", "x", "y", "支出"],
            ["2026-08-26 15:00:00", "1.00", "2,745.30", "x", "y", "收入"],
        ]
        with patch("bankflow_v2.gansu.pdfplumber.open", return_value=fake_pdf(rows)):
            self.assertEqual(summarize(extract_gansu("sample.pdf")).issues, [])

    def test_mengshang_restores_account_from_detail_column(self):
        rows = [["60004477\n9", "20260105\n11:39:38", "1.00", "0.00", "9.00"]]
        with patch("bankflow_v2.ccb_corp.pdfplumber.open", return_value=fake_pdf(rows)):
            tx = extract_mengshang_corp("sample.pdf")[0]
        self.assertEqual(tx.account_no, "600044779")


if __name__ == "__main__":
    unittest.main()
