import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("report", Path(__file__).with_name("Report-ExpandedBenchmark.py"))
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class EvaluationMetricsTests(unittest.TestCase):
    def test_empty_labels_are_unjudged(self):
        self.assertIsNone(report.rank_metrics(["a"], []))

    def test_duplicate_results_cannot_inflate_ndcg(self):
        result = report.rank_metrics(["a", "a"], {"a"}, 10)
        self.assertEqual(result["ndcg"], 1)
        self.assertEqual(result["labeled_positive_at_10"], .1)

    def test_rank_and_empty_result_denominators(self):
        self.assertEqual(report.rank_metrics(["b", "a"], {"a"})["mrr"], .5)
        self.assertEqual(report.rank_metrics([], {"a"})["ndcg"], 0)

    def test_normalization(self):
        self.assertEqual(report.norm(" ＰＯＣＫＹ- 바 "), "pocky바")

    def test_unknown_must_not_be_presented_as_verified(self):
        row = {"result_mode": "VERIFIED", "items": [{"barcode": "1", "safety": "UNKNOWN", "diet": "PASS", "verificationRequired": True}]}
        self.assertIn("unverified_presented_as_safe", report.presentation_errors(row))

    def test_fallback_needs_warning_and_action(self):
        row = {"result_mode": "VERIFICATION_REQUIRED", "items": [{"barcode": "1", "safety": "UNKNOWN", "diet": "PASS", "verificationRequired": True, "warnings": ["check"], "requiredActions": []}]}
        self.assertIn("missing_verification_guidance", report.presentation_errors(row))
        row["items"][0]["requiredActions"] = ["check label"]
        self.assertEqual(report.presentation_errors(row), [])


if __name__ == "__main__":
    unittest.main()
