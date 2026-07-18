import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bankflow_v2.income_proof_export import unique_accounts
from bankflow_v2.models import Transaction
from gui_v2 import dedupe_transactions, parse_account_name, parse_account_no


def transaction(source_file: str, account_no: str) -> Transaction:
    tx = Transaction(
        transaction_time=datetime(2026, 1, 2, 3, 4, 5),
        income=Decimal("100.00"),
        expense=Decimal("0.00"),
        balance=None,
        bank="微信流水",
        row_no=1,
        raw_amount="100.00",
        raw_balance="",
    )
    tx.source_file = source_file
    tx.account_no = account_no
    tx.balance_optional = True
    return tx


class MultiAccountMergeTests(unittest.TestCase):
    def test_extracts_wechat_owner_and_id(self):
        text = "兹证明：乔建国（居民身份证：已隐藏），在其微信号：Q071484中的交易明细信息如下："
        self.assertEqual(parse_account_name(text), "乔建国")
        self.assertEqual(parse_account_no(text), "Q071484")

    def test_keeps_identical_transactions_from_different_wechat_accounts(self):
        rows, issues = dedupe_transactions(
            [transaction("微信流水_0.pdf", "wechat_a"), transaction("微信流水_1.pdf", "wechat_b")]
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(issues, [])

    def test_dedupes_overlapping_exports_of_the_same_wechat_account(self):
        rows, issues = dedupe_transactions(
            [transaction("微信流水_0.pdf", "wechat_a"), transaction("微信流水_1.pdf", "wechat_a")]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(issues), 1)

    def test_income_proof_keeps_two_wechat_accounts(self):
        results = [
            SimpleNamespace(
                path=Path("微信流水_0.pdf"),
                bank_id="wechat",
                bank_label="微信流水",
                bank_confidence=98,
                bank_reason="微信证明",
                account_no="wechat_a",
                account_name="甲",
            ),
            SimpleNamespace(
                path=Path("微信流水_1.pdf"),
                bank_id="wechat",
                bank_label="微信流水",
                bank_confidence=98,
                bank_reason="微信证明",
                account_no="wechat_b",
                account_name="乙",
            ),
        ]
        accounts = unique_accounts(results)
        self.assertEqual([account["account_no"] for account in accounts], ["wechat_a", "wechat_b"])


if __name__ == "__main__":
    unittest.main()
