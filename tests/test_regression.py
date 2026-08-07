import unittest

from tools.regression import run_case


class RegressionTests(unittest.TestCase):
    def test_skips_explicitly_deferred_case_without_reading_sample(self):
        result = run_case(
            {
                "name": "待后续确认样本",
                "skip_reason": "暂缓待后续专项确认",
            }
        )

        self.assertEqual(result.status, "SKIP")
        self.assertEqual(result.detail, "暂缓待后续专项确认")
        self.assertEqual(result.failures, [])

    def test_missing_file_is_skip_with_allow_missing_and_flag(self):
        result = run_case(
            {
                "name": "缺失样本",
                "path": r"D:\definitely\missing\sample.pdf",
            },
            allow_missing=True,
        )

        self.assertEqual(result.status, "SKIP")
        self.assertTrue(result.missing)
        self.assertEqual(result.failures, [])

    def test_missing_file_is_fail_without_allow_missing(self):
        result = run_case(
            {
                "name": "缺失样本",
                "path": r"D:\definitely\missing\sample.pdf",
            },
            allow_missing=False,
        )

        self.assertEqual(result.status, "FAIL")
        self.assertFalse(result.missing)
        self.assertEqual(len(result.failures), 1)


if __name__ == "__main__":
    unittest.main()
