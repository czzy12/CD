import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from bankflow_v2.models import Transaction
from bankflow_v2.psbc import _restore_same_time_order, extract_psbc
from bankflow_v2.summary import summarize


class PsbcTests(unittest.TestCase):
    def test_newest_first_ties_across_pages(self):
        def row(time, amount, balance):
            return [time, '0001', '活期', '人民币元', '钞', amount, balance]

        pages = [MagicMock(), MagicMock()]
        pages[0].extract_tables.return_value = [[
            row('2026-06-22 09:58:05', '305.06', '468754.70'),
            row('2026-06-22 07:06:40', '-637.22', '468449.64'),
        ]]
        pages[1].extract_tables.return_value = [[
            row('2026-06-22 07:06:40', '-637.22', '469086.86'),
            row('2026-06-21 12:00:00', '100.00', '469724.08'),
        ]]
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = pages
        with patch('bankflow_v2.psbc.pdfplumber.open', return_value=pdf):
            transactions = extract_psbc('sample.pdf')
        summary = summarize(transactions)
        self.assertEqual(summary.count, 4)
        self.assertEqual(summary.income_sum, Decimal('405.06'))
        self.assertEqual(summary.expense_sum, Decimal('1274.44'))
        self.assertEqual(summary.issues, [])
        self.assertEqual(transactions[1].raw_time, '2026-06-22 07:06:40')

    def test_forward_and_unproven_ties_are_unchanged(self):
        for balances in [('90', '80'), ('90', '71')]:
            items = [Transaction(datetime(2026, 6, 22, 7, 6, 40),
                                 expense=Decimal('10'), balance=Decimal(balance))
                     for balance in balances]
            _restore_same_time_order(items)
            self.assertEqual([tx.transaction_time.microsecond for tx in items], [0, 0])


if __name__ == '__main__':
    unittest.main()
