import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import real_chain_acceptance_report as report_tool  # noqa: E402


class RealChainAcceptanceReportTests(unittest.TestCase):
    def _artifact(
        self,
        root: Path,
        *,
        task_id: str,
        slot_id: str,
        domain: str,
        route: str,
        title: str,
        body: str,
        score: float = 73.0,
    ) -> None:
        path = root / task_id / f"{slot_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "status": "ready",
            "task_id": task_id,
            "slot_id": slot_id,
            "domain": domain,
            "generation_route": route,
            "title": title,
            "body": body,
            "score": score,
            "blocking": False,
            "quality_issues": [],
            "source_context": "- 已核验事实：测试事实\n- 价格/人均：人均88元\n- 营业时间：10:00-22:00",
        }, ensure_ascii=False), encoding="utf-8")

    def test_build_report_passes_complete_artifact_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "vtest_acceptance"
            body_base = "这是一篇可交付正文，事实清楚，信息完整，适合直接发布。点赞收藏。#测试 #小红书 #内容"
            for idx, domain in enumerate(sorted(report_tool.REQUIRED_DOMAINS), 1):
                self._artifact(
                    artifact_dir,
                    task_id=f"task_{idx}",
                    slot_id="generate_initial",
                    domain=domain,
                    route="generate",
                    title=f"{domain}测试标题88元",
                    body=body_base + str(idx),
                    score=73 + idx / 10,
                )
            for suffix in ("a", "b", "c"):
                self._artifact(
                    artifact_dir,
                    task_id="diagnosis_task",
                    slot_id=f"diagnosis_plan_{suffix}",
                    domain="美食",
                    route="analyze",
                    title=f"美食诊断标题{suffix}88元",
                    body=body_base + suffix,
                    score=74.0,
                )
            (artifact_dir / "run_report_20260628T000000Z.json").write_text(json.dumps({
                "created_at": "2026-06-28T00:00:00+00:00",
                "result_count": 9,
                "by_status": {"ready": 9},
                "score_summary": {"blocked_count": 0, "count": 9, "mean": 73.5, "min": 73.1},
                "failures": [],
            }), encoding="utf-8")
            shadow_report = Path(tmp) / "shadow.json"
            shadow_report.write_text(json.dumps({
                "created_at": "2026-06-28T00:00:00+00:00",
                "summary": {"shadow_ready_rate": 1.0, "hard_block_count": 0},
                "by_artifact_set": {
                    "vtest_acceptance": {
                        "count": 9,
                        "shadow_ready_rate": 1.0,
                        "hard_block_count": 0,
                        "avg_v04_score": 73.5,
                        "v04_score_ge_72_count": 9,
                    }
                },
            }), encoding="utf-8")

            report = report_tool.build_report(artifact_dir, shadow_report)
            out = Path(tmp) / "report.md"
            report_tool.write_markdown(report, out)
            markdown = out.read_text(encoding="utf-8")

            self.assertTrue(report["gates"]["passed"], report["gates"])
            self.assertEqual(report["artifact_summary"]["blocking_count"], 0)
            self.assertEqual(report["artifact_summary"]["title_issues_after_sanitize_count"], 0)
            self.assertIn("RQS-07 Real Chain Acceptance Report", markdown)
            self.assertIn("Historical Generated Variants Context", markdown)

    def test_gate_fails_when_required_domain_is_missing(self):
        artifact_summary = {
            "blocking_count": 0,
            "failure_count": 0,
            "score_lt_60_count": 0,
            "title_issues_after_sanitize_count": 0,
            "by_domain": {"美食": {}},
            "diagnosis_integrity": [{"body_distinct": True}],
        }
        run_summary = {"failure_count": 0, "blocked_count": 0}
        gates = report_tool.evaluate_gates(artifact_summary, run_summary, {"available": False})

        self.assertFalse(gates["passed"])
        self.assertIn("all_required_domains_present", gates["failed_checks"])


if __name__ == "__main__":
    unittest.main()
