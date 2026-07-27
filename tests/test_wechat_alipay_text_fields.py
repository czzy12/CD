import unittest
from unittest.mock import patch

from bankflow_v2.alipay import extract_alipay
from bankflow_v2.wechat import _parse_table, _wechat_identity_metadata


class _Page:
    def __init__(self, table, text=""):
        self.table = table
        self.text = text

    def extract_tables(self):
        return [self.table]

    def extract_text(self):
        return self.text


class _Pdf:
    def __init__(self, table):
        self.pages = [_Page(table)]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class WechatAlipayTextFieldTests(unittest.TestCase):
    def test_wechat_identity_metadata_requires_explicit_complete_triplet(self):
        metadata = _wechat_identity_metadata(
            "兹证明：张三（居民身份证：110101199001011234），在其微信号：zhangsan_01中的交易明细信息如下："
        )

        self.assertEqual(metadata.account_name, "张三")
        self.assertEqual(metadata.account_number, "")
        self.assertEqual(metadata.raw_fields["payment_account_type"], "wechat_account")
        self.assertEqual(metadata.raw_fields["identity_number"], "110101199001011234")
        self.assertEqual(metadata.field_sources["payment_account_id"], "page=1:wechat_proof_header")
        self.assertEqual(metadata.field_confidence["identity_owner_name"], 1.0)

    def test_wechat_identity_metadata_rejects_masked_or_ambiguous_triplet(self):
        masked = _wechat_identity_metadata(
            "兹证明：张三（居民身份证：110101********1234），在其微信号：zhangsan_01中的交易明细信息如下："
        )
        ambiguous = _wechat_identity_metadata(
            "兹证明：张三（居民身份证：110101199001011234），在其微信号：zhangsan_01中。"
            "微信号：zhangsan_02"
        )

        self.assertEqual(masked.raw_fields, {})
        self.assertEqual(ambiguous.raw_fields, {})

    def test_wechat_maps_confirmed_fields_and_keeps_orders_raw(self):
        table = [
            ["交易单号", "交易时间", "交易类型", "收/支/其他", "交易方式", "金额(元)", "交易对方", "商户单号"],
            ["wx-expense", "2026-05-15 17:16:19", "商户消费", "支出", "储蓄卡(3894)", "5000.00", "甲公司\n销售部", "merchant-1"],
            ["wx-income", "2026-05-14 15:03:08", "转账", "收入", "/", "1500.00", "乙某", "/"],
            ["wx-other", "2026-05-13 12:00:00", "充值", "其他", "", "20.00", "", "merchant-3"],
        ]

        transactions = _parse_table(table, 1)

        self.assertEqual(len(transactions), 3)
        expense, income, other = transactions
        self.assertEqual(expense.transaction_type, "商户消费")
        self.assertEqual(expense.transaction_direction, "支出")
        self.assertEqual(expense.transaction_method, "储蓄卡(3894)")
        self.assertEqual(expense.counterparty_name, "甲公司 销售部")
        self.assertEqual(expense.field_sources["transaction_method"], "raw_headers[4]:交易方式")
        self.assertEqual(income.transaction_direction, "收入")
        self.assertEqual(other.transaction_direction, "其他")
        self.assertEqual(other.transaction_method, "")
        self.assertEqual(other.counterparty_name, "")
        self.assertTrue(other.neutral)
        self.assertEqual(expense.raw_fields[0], "wx-expense")
        self.assertEqual(expense.raw_fields[7], "merchant-1")
        self.assertFalse(hasattr(expense, "transaction_order_no"))
        self.assertFalse(hasattr(expense, "merchant_order_no"))

    def test_alipay_maps_confirmed_fields_and_keeps_orders_raw(self):
        table = [
            ["收/支", "交易对方", "商品说明", "收/付款方式", "金额", "交易订单号", "商家订单号", "交易时间"],
            ["支出", "甲商户", "商品甲\n分期", "花呗", "106.40", "ali-expense", "merchant-1", "2026-06-25 22:07:28"],
            ["收入", "乙某", "收钱码收款", "", "100000.00", "ali-income", "merchant-2", "2026-06-25 18:50:08"],
            ["不计收支", "丙公司", "押金解冻", "", "0.00", "ali-neutral", "", "2026-06-20 22:58:49"],
        ]

        with patch("bankflow_v2.alipay.pdfplumber.open", return_value=_Pdf(table)):
            transactions = extract_alipay("unused.pdf")

        self.assertEqual(len(transactions), 3)
        expense, income, neutral = transactions
        self.assertEqual(expense.transaction_direction, "支出")
        self.assertEqual(expense.counterparty_name, "甲商户")
        self.assertEqual(expense.product_description, "商品甲 分期")
        self.assertEqual(expense.payment_method, "花呗")
        self.assertEqual(expense.field_sources["payment_method"], "raw_headers[3]:收/付款方式")
        self.assertEqual(income.transaction_direction, "收入")
        self.assertEqual(income.payment_method, "")
        self.assertEqual(neutral.transaction_direction, "不计收支")
        self.assertTrue(neutral.neutral)
        self.assertEqual(expense.raw_fields[5], "ali-expense")
        self.assertEqual(expense.raw_fields[6], "merchant-1")
        self.assertFalse(hasattr(expense, "transaction_order_no"))
        self.assertFalse(hasattr(expense, "merchant_order_no"))


if __name__ == "__main__":
    unittest.main()
