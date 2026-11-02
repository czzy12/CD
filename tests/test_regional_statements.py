import os
import unittest
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from bankflow_v2.auto_detect import detect_bank_type
from bankflow_v2.models import Transaction
from bankflow_v2.psbc import extract_psbc
from bankflow_v2.ccb_corp import extract_ccb_corp
from bankflow_v2.regional_statements import (
    _money, order_statement_rows, _apply_confirmed_mintai_repair,
    MINTAI_CONFIRMED_SOURCE,
)
from bankflow_v2.summary import summarize
from tools.regression import run_case


def tx(amount, balance, hour=0, row=1):
    amount = Decimal(amount)
    return Transaction(datetime(2026, 11, 1, hour), max(amount, Decimal(0)),
                       max(-amount, Decimal(0)), Decimal(balance), page_no=2,
                       row_no=row, raw_time=f'2026-11-01 {hour:02}:00:00',
                       raw_amount=str(amount), raw_balance=balance)


class RegionalStatementTests(unittest.TestCase):
    def test_cycle_is_kept_and_exit_is_taken_after_all_rows(self):
        items = [tx('-10', '90', row=1), tx('-5', '85', row=2),
                 tx('10', '100', row=3), tx('-10', '90', row=4)]
        result = order_statement_rows(items)
        self.assertEqual(len(result), 4)
        self.assertEqual(summarize(result).issues, [])
        self.assertEqual(sum(x.expense for x in result), Decimal('25'))
        self.assertEqual([x.page_no for x in items], [2]*4)
        self.assertEqual({x.source_row_no for x in items}, {1, 2, 3, 4})

    def test_posting_order_preserves_non_monotone_original_clock(self):
        items = [tx('10', '110', hour=23), tx('-5', '105', hour=7)]
        result = order_statement_rows(items)
        self.assertEqual(summarize(result).issues, [])
        self.assertEqual(items[0].raw_time, '2026-11-01 23:00:00')
        self.assertEqual(items[0].transaction_time.hour, 23)

    def test_disconnected_source_is_not_changed_to_force_closure(self):
        items = [tx('10', '110'), tx('-5', '300', row=2)]
        before = [(x.income, x.expense, x.balance, x.raw_amount) for x in items]
        result = order_statement_rows(items)
        self.assertEqual(before, [(x.income, x.expense, x.balance, x.raw_amount) for x in items])
        self.assertGreater(len(summarize(result).issues), 0)

    def test_strict_money_does_not_guess_contaminated_value(self):
        for value in ['', '100.00J', '100.00 200.00']:
            with self.assertRaises(ValueError):
                _money(value)
        self.assertEqual(_money('￥-1,000.00'), Decimal('-1000'))

    def test_psbc_thirteen_columns_wrap_dates_and_signed_reversal(self):
        header = ['交易日期', '交易时间', '记账日期', '支出金额', '收入金额', '余额',
                  '对方账号', '对方户名', '对方行名', '用途', '附言', '摘要', '全局路由号']
        page = MagicMock()
        page.extract_text.return_value = '中国邮政储蓄银行账户交易明细'
        page.extract_tables.return_value = [[header,
            ['2026-11-0\n1', '10:00:00', '2026-11-0\n1', '10.00', '0.00', '90.00'] + ['']*7,
            ['2026-11-0\n1', '10:01:00', '2026-11-0\n1', '-10.00', '0.00', '100.00'] + ['']*7]]
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = [page]
        with patch('bankflow_v2.psbc.pdfplumber.open', return_value=pdf):
            rows = extract_psbc('synthetic.pdf')
        result = summarize(rows)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].transaction_time.hour, 10)
        self.assertEqual(result.expense_sum, Decimal('0.00'))
        self.assertEqual(result.expense_count, 2)
        self.assertEqual(result.issues, [])

    def test_specific_issuers_precede_counterparty_keyword_matches(self):
        samples = [
            ('tianjin_corp', '天津银行对公交易明细清单 借方发生额 贷方发生额 中国工商银行'),
            ('yongxing_rural', '湖南永兴农村商业银行股份有限公司交易明细 交易时间交易金额账户余额对方账号对方户名摘要备注 兴业银行'),
            ('psbc', '中国邮政储蓄银行账户交易明细 支出金额收入金额余额 中国工商银行'),
        ]
        for expected, text in samples:
            with patch('bankflow_v2.auto_detect._looks_like_icbc_corp_ocr_layout', return_value=False), patch('bankflow_v2.auto_detect._image_only_reason', return_value=None), patch('bankflow_v2.auto_detect._sample_text', return_value=text):
                self.assertEqual(detect_bank_type('synthetic.pdf').bank_id, expected)

    def test_ccb_account_comes_from_its_wrapped_account_column(self):
        page = MagicMock()
        page.extract_tables.return_value = [[
            ['1234567890\n123456789', '20261101\n10:00:00', '0.00', '10.00', '100.00'] + ['']*12,
        ]]
        pdf = MagicMock()
        pdf.__enter__.return_value.pages = [page]
        with patch('bankflow_v2.ccb_corp.pdfplumber.open', return_value=pdf):
            rows = extract_ccb_corp('synthetic.pdf')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].account_no, '1234567890123456789')

    def test_encrypted_regression_requires_runtime_secret(self):
        with patch('pathlib.Path.exists', return_value=True), patch.dict(os.environ, {}, clear=True):
            result = run_case({'name':'encrypted', 'path':'synthetic.pdf',
                               'password_env':'BANKFLOW_REGRESSION_TEST_PASSWORD'}, True)
        self.assertEqual(result.status, 'SKIP')
        self.assertIn('runtime password required', result.detail)

    def test_confirmed_repair_is_bound_to_exact_source_and_retains_originals(self):
        items = [tx('-2', '5329.42'), tx('39.82', '15967.17', row=6), tx('-25','5304.42',row=7)]
        current = items[1]
        current.raw_time = '20260817'
        current.source_page_no, current.source_row_no = 6, 6
        untouched = _apply_confirmed_mintai_repair(items, 'another-source')
        self.assertEqual(untouched[1].income, Decimal('39.82'))
        result = _apply_confirmed_mintai_repair(items, MINTAI_CONFIRMED_SOURCE)
        self.assertEqual(current.raw_amount, '39.82')
        self.assertEqual(current.raw_balance, '15967.17')
        self.assertEqual(current.balance, Decimal('15967.17'))
        self.assertNotIn(current, result)
        self.assertEqual(result[0].manual_confirmation['action'], 'exclude')
        self.assertEqual(len(result), 2)
        self.assertEqual(len(summarize(result).issues), 1)
        self.assertEqual(summarize(result).issues[0].level, '低风险')
        self.assertIn('已人工确认剔除', summarize(result).issues[0].message)
        self.assertEqual(summarize(result).count, 2)


if __name__ == '__main__':
    unittest.main()
