import unittest

from tools.sse_latency_report import latency_stats, summarize_records


class SSELatencyReportTests(unittest.TestCase):
    def test_nearest_rank_p50_p95_and_small_sample_disclosure(self):
        stats = latency_stats(list(range(1, 21)))
        self.assertEqual(stats["sample_count"], 20)
        self.assertEqual(stats["p50_ms"], 10)
        self.assertEqual(stats["p95_ms"], 19)
        self.assertFalse(stats["p95_reliable"])
        self.assertEqual(stats["p95_reliability"], "insufficient_sample")

    def test_one_hundred_samples_can_mark_p95_reliable(self):
        stats = latency_stats(list(range(1, 101)))
        self.assertEqual(stats["sample_count"], 100)
        self.assertEqual(stats["p50_ms"], 50)
        self.assertEqual(stats["p95_ms"], 95)
        self.assertTrue(stats["p95_reliable"])
        self.assertEqual(stats["p95_reliability"], "reliable")

        report = summarize_records([
            {"operation": "generate", "outcome": "success", "elapsed_ms": value}
            for value in range(1, 101)
        ])
        self.assertFalse(report["overall"]["p95_reliable"])
        self.assertEqual(report["overall"]["p95_reliability"], "heterogeneous_not_sla")
        self.assertTrue(report["groups"][0]["p95_reliable"])

    def test_report_groups_only_sanitized_latency_dimensions(self):
        report = summarize_records([
            {"operation": "analyze", "outcome": "success", "elapsed_ms": 1200, "prompt": "must-not-output"},
            {"operation": "analyze", "outcome": "success", "elapsed_ms": 1800},
            {"operation": "chat", "outcome": "error", "elapsed_ms": 900},
            {"operation": "generate", "outcome": "success", "elapsed_ms": -1},
            {"operation": "用户正文-不可作为维度", "outcome": "success", "elapsed_ms": 100},
            {"operation": "chat", "outcome": "secret-cookie-value", "elapsed_ms": 100},
        ])
        self.assertEqual(report["overall"]["sample_count"], 3)
        self.assertEqual(report["rejected_count"], 3)
        self.assertEqual(len(report["groups"]), 2)
        self.assertNotIn("must-not-output", str(report))
        self.assertNotIn("用户正文-不可作为维度", str(report))
        self.assertNotIn("secret-cookie-value", str(report))


if __name__ == "__main__":
    unittest.main()
