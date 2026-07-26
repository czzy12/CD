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


if __name__ == "__main__":
    unittest.main()
