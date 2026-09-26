import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from bankflow_v2.excel_input import _extract_sheet, _parse_datetime
from bankflow_v2.models import Transaction
from bankflow_v2.income_proof_export import account_from_result
from bankflow_v2.summary import summarize
from gui_v2 import FileResult, SUPPORTED_INPUTS, Worker, infer_flow_type, parse_account_name


class LegacyExcelTests(unittest.TestCase):
    def test_parses_compact_legacy_excel_date(self):
        self.assertEqual(_parse_datetime("20260301"), datetime(2026, 3, 1))

    def test_extracts_corporate_legacy_excel_layout(self):
        rows = [
            ("", "", "账户交易明细", "", ""),
            ("账户", "0710725011015200022669", "长春市岭昇汽车服务贸易有限公司", "", ""),
            ("交易流水号", "交易日期", "借方发生额", "贷方发生额", "余额"),
            ("08929691", "20260301", "0.00", "31900.00", "1389830.20"),
        ]

        transactions = _extract_sheet(rows, 1)

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].bank, "公户Excel导入")
        self.assertEqual(str(transactions[0].income), "31900.00")
        self.assertEqual(str(transactions[0].balance), "1389830.20")

    def test_extracts_account_name_and_supports_xls(self):
        text = "账户 0710725011015200022669 长春市岭昇汽车服务贸易有限公司"

        self.assertEqual(parse_account_name(text), "长春市岭昇汽车服务贸易有限公司")
        self.assertIn(".xls", SUPPORTED_INPUTS)
        self.assertEqual(infer_flow_type("excel", "长春市岭昇汽车服务贸易有限公司"), "对公")

    def test_extracts_sichuan_rural_credit_with_separate_date_and_time(self):
        rows = [
            ("四川农信账户交易明细", "", "", "", "", ""),
            ("户名: 宜宾市长宁县乡土食品有限公司", "", "", "", "", ""),
            ("交易日期", "交易时间", "收入/支出", "收入金额", "支出金额", "账户余额"),
            ("2026/01/01", "11:26:11", "收入", "9,000.00", "", "11,464.15"),
        ]

        transactions = _extract_sheet(rows, 1)

        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].transaction_time, datetime(2026, 1, 1, 11, 26, 11))
        self.assertEqual(transactions[0].bank, "四川农信公户")
        self.assertEqual(transactions[0].income, Decimal("9000.00"))
        self.assertEqual(transactions[0].balance, Decimal("11464.15"))

    def test_merges_excel_files_for_same_account(self):
        def result(name: str, when: datetime, income: str, balance: str) -> FileResult:
            tx = Transaction(when, Decimal(income), Decimal("0.00"), Decimal(balance), "四川农信公户")
            tx.account_no = "61950120000005599"
            return FileResult(
                Path(name), "excel", "四川农信公户", 100, "Excel文件导入",
                summarize([]), [tx], "正常", "", "宜宾市长宁县乡土食品有限公司", "61950120000005599",
            )

        results = Worker._merge_excel_account_statements([
            result("1月.xls", datetime(2026, 1, 1), "100.00", "1100.00"),
            result("2月.xls", datetime(2026, 2, 1), "200.00", "1300.00"),
        ])

        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0].transactions), 2)
        self.assertIn("2个分表合并", results[0].path.name)

    def test_extracts_boc_corporate_online_banking_export(self):
        rows = [
            ("查询账号[ Inquirer account number ]", "118588982892", "", "", "", "", "", "", "", "", "", "", "", ""),
            ("总笔数[ Total number ]", "2", "", "", "", "", "", "", "", "", "", "", "", ""),
            ("借方发生总额[ Total Debit Amount of Payments ]", "100.00", "", "", "", "", "", "", "", "", "", "", "", ""),
            ("贷方发生总额[ Total Credit Amount of Payments ]", "60.00", "", "", "", "", "", "", "", "", "", "", "", ""),
            (
                "交易类型[ Transaction Type ]", "业务类型[ Business type ]", "付款人开户行号[ Account holding bank number of payer ]",
                "付款人开户行名[ Payer account bank ]", "付款人账号[ Debit Account No. ]", "付款人名称[ Payer's Name ]",
                "收款人开户行行号[ Account holding bank number of beneficiary ]", "收款人开户行名[ Beneficiary account bank ]",
                "收款人账号[ Payee's Account Number ]", "收款人名称[ Payee's Name ]", "交易日期[ Transaction Date ]",
                "交易时间[ Transaction time ]", "交易货币[ Trade Currency ]", "交易金额[ Trade Amount ]",
            ),
            ("往账", "网上支付", "15459", "中国银行", "118588982892", "四川雄美顺国际物流有限公司", "1", "他行", "9", "甲", "20260801", "04:00:12", "CNY", -100.0),
            ("来账", "小额普通", "1", "他行", "8", "乙", "15459", "中国银行", "118588982892", "四川雄美顺国际物流有限公司", "20260802", "10:00:00", "CNY", 60.0),
        ]

        transactions = _extract_sheet(rows, 1)
        summary = summarize(transactions)

        self.assertEqual(summary.count, 2)
        self.assertEqual(summary.income_sum, Decimal("60.00"))
        self.assertEqual(summary.expense_sum, Decimal("100.00"))
        self.assertEqual(summary.issues, [])
        self.assertEqual(transactions[0].account_no, "118588982892")
        self.assertEqual(transactions[0].account_name, "四川雄美顺国际物流有限公司")
        self.assertTrue(transactions[0].balance_optional)

        result = FileResult(
            Path("中国银行对公.xls"), "excel", "中国银行对公Excel导入", 100, "Excel文件导入",
            summary, transactions, "正常", "", transactions[0].account_name, transactions[0].account_no,
        )
        account = account_from_result(result)
        self.assertEqual(account["bank"], "中国")
        self.assertEqual(account["account_no_source"], "excel_auto")
        self.assertFalse(account["bank_review_required"])


if __name__ == "__main__":
    unittest.main()
