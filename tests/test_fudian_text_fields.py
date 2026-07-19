import unittest
from datetime import date, datetime
from unittest.mock import patch

from bankflow_v2.fudian import extract_fudian
from bankflow_v2.models import TransactionList, get_statement_metadata


class _Page:
    def __init__(self, text, table):
        self.text = text
        self.table = table

    def extract_text(self):
        return self.text

    def extract_tables(self):
        return [self.table]


class _Pdf:
    def __init__(self, page):
        self.pages = [page]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class FudianTextFieldTests(unittest.TestCase):
    def test_extracts_confirmed_transaction_and_statement_fields(self):
        first_page_text = "\n".join(
            [
                "富滇交易明细 - 文件1 第 1 页 / 共 16 页",
                "富滇银行交易流水(Fudian Bank Transaction Details)",
                "20251107--20260506",
                "户名(Account Name):赵云飞 币种(Currency):人民币",
                "银行账号（Bank Accout):6214150000010393543 验证码(Verification Code):secret 申请时间(Print Time):2026/05/07 09:16",
            ]
        )
        table = [
            [
                "序号\nSerial\nNumber",
                "交易日期\nTrading Date",
                "货币\nCurrency",
                "交易金额\nTrading\nAmount",
                "账户余额\nAccount\nBalance",
                "对方账号\nCounterparty Account",
                "对方户名\nCounterparty Name",
                "摘要描述\nTrading\nDescription",
                "备注 Remark",
            ],
            [
                "7",
                "2025-11-09\n20:10:00",
                "CNY",
                "-21.6",
                "8725.19",
                "",
                "",
                "协议支付",
                "商户代码 ：84258407399\n0001,商户名称\n及地址：微信支\n付,二级商户信息\n ：1000107301",
            ],
            [
                "8",
                "2025-11-10\n12:00:00",
                "CNY",
                "100.00",
                "8825.19",
                "24*****33",
                "甲公\n司",
                "网络支付",
                "财付通公司快捷支付，商户：扫码付款，商品：午餐，车牌：云A12345",
            ],
            [
                "9",
                "2025-11-11\n08:00:00",
                "CNY",
                "-10.00",
                "8815.19",
                "622848*********0177",
                "乙某",
                "个人行外转出",
                "附言：借款",
            ],
        ]

        with patch("bankflow_v2.fudian.pdfplumber.open", return_value=_Pdf(_Page(first_page_text, table))):
            transactions = extract_fudian("unused.pdf")

        self.assertIsInstance(transactions, TransactionList)
        self.assertEqual(len(transactions), 3)
        composite, merchant, postscript = transactions
        self.assertEqual(composite.source_sequence, "7")
        self.assertEqual(composite.summary, "协议支付")
        self.assertEqual(composite.remark, "商户代码 ：84258407399 0001,商户名称及地址：微信支付,二级商户信息 ：1000107301")
        self.assertEqual(composite.merchant_name, "微信支付")
        self.assertEqual(composite.source_fields["merchant_code"], "842584073990001")
        self.assertEqual(composite.source_fields["merchant_name_and_address_raw"], "微信支付")
        self.assertEqual(composite.source_fields["secondary_merchant_info"], "1000107301")
        self.assertEqual(merchant.counterparty_account, "24*****33")
        self.assertEqual(merchant.counterparty_name, "甲公司")
        self.assertEqual(merchant.merchant_name, "扫码付款")
        self.assertEqual(merchant.source_fields["remark_details"], {"商品": "午餐", "车牌": "云A12345", "原文前缀": "财付通公司快捷支付"})
        self.assertEqual(postscript.source_fields["postscript"], "借款")
        self.assertEqual(merchant.field_sources["counterparty_account"], "raw_headers[5]:对方账号 / Counterparty Account")
        self.assertEqual(composite.field_confidence["merchant_code"], 1.0)
        self.assertFalse(hasattr(composite, "currency"))
        self.assertEqual(composite.raw_fields[2], "CNY")

        metadata = get_statement_metadata(transactions)
        self.assertEqual(metadata.account_name, "赵云飞")
        self.assertEqual(metadata.account_number, "6214150000010393543")
        self.assertEqual(metadata.statement_period_start, date(2025, 11, 7))
        self.assertEqual(metadata.statement_period_end, date(2026, 5, 6))
        self.assertEqual(metadata.generated_at, datetime(2026, 5, 7, 9, 16))
        self.assertEqual(metadata.source_part_label, "文件1")
        self.assertEqual(metadata.page_total, 16)
        self.assertNotIn("currency", metadata.raw_fields)
        self.assertNotIn("account_currency", metadata.raw_fields)
        self.assertNotIn("verification_code", metadata.raw_fields)
        self.assertFalse(hasattr(metadata, "account_currency"))
        self.assertFalse(hasattr(metadata, "verification_code"))


if __name__ == "__main__":
    unittest.main()
