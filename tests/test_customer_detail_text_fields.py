import unittest
from unittest.mock import patch

from bankflow_v2.customer_detail_corp import extract_customer_detail_corp


class _Page:
    def extract_text(self):
        return "\n".join(
            [
                "对公客户账户明细",
                "20260101 -12.00 100.00 62220001甲公司 支付货款",
                "补充备注",
            ]
        )


class _Pdf:
    pages = [_Page()]

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class CustomerDetailTextFieldTests(unittest.TestCase):
    def test_keeps_unsplit_body_out_of_counterparty_name(self):
        with patch("bankflow_v2.customer_detail_corp.pdfplumber.open", return_value=_Pdf()):
            transactions = extract_customer_detail_corp("unused.pdf")

        self.assertEqual(len(transactions), 1)
        transaction = transactions[0]
        self.assertEqual(transaction.counterparty_account, "62220001")
        self.assertEqual(transaction.counterparty_name, "")
        self.assertEqual(transaction.raw_headers[-1], "未拆分交易文本")
        self.assertEqual(transaction.source_fields["unparsed_transaction_text"], "甲公司 支付货款 补充备注")
        self.assertEqual(
            transaction.field_sources["unparsed_transaction_text"],
            "raw_headers[4]:未拆分交易文本",
        )


if __name__ == "__main__":
    unittest.main()
