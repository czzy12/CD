import unittest

from bankflow_v2.cmb_corp import ROW_RE


class CmbCorpTests(unittest.TestCase):
    def test_statement_row_accepts_space_between_date_and_business_type(self):
        line = "20260103 网银费用 网银支付-跨行-异地手续费 -177.59 2,471,689.47 网上电子汇划收入"

        match = ROW_RE.match(line)

        self.assertIsNotNone(match)
        self.assertEqual(match.group("date"), "20260103")
        self.assertEqual(match.group("business_type"), "网银费用")
        self.assertEqual(match.group("amount"), "-177.59")
        self.assertEqual(match.group("balance"), "2,471,689.47")

    def test_statement_row_still_accepts_joined_date_and_business_type(self):
        line = "20260103网银费用 网银支付-跨行-异地手续费 -177.59 2,471,689.47 网上电子汇划收入"

        match = ROW_RE.match(line)

        self.assertIsNotNone(match)
        self.assertEqual(match.group("business_type"), "网银费用")

    def test_statement_row_accepts_empty_description(self):
        line = "20260103 网银费用 -20.35 2,471,428.56 网上电子汇划收入"

        match = ROW_RE.match(line)

        self.assertIsNotNone(match)
        self.assertEqual(match.group("body"), None)
        self.assertEqual(match.group("amount"), "-20.35")


if __name__ == "__main__":
    unittest.main()
