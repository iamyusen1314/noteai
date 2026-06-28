import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "model"))

from export_labeling_batch import export_batch  # noqa: E402
from ingest_golden_annotations import ingest_golden_annotations  # noqa: E402
from ingest_preference_annotations import ingest_preference_annotations  # noqa: E402
from v04_training_data_health import build_health_report  # noqa: E402


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


class LabelingPipelineToolTests(unittest.TestCase):
    def test_export_labeling_batch_balances_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            queue = tmp_path / "queue.jsonl"
            rows = []
            for i, domain in enumerate(["美食", "美食", "旅行", "旅行", "旅行"], 1):
                rows.append({
                    "annotation_id": f"a{i}",
                    "human_label_status": "needs_label",
                    "priority": "high",
                    "domain": domain,
                    "title": f"标题{i}",
                    "body": f"正文{i}",
                })
            _write_jsonl(queue, rows)
            args = argparse.Namespace(
                kind="golden",
                queue=str(queue),
                output_dir=str(tmp_path / "batches"),
                batch_id="b1",
                max_rows=10,
                per_domain=1,
                domains="",
                priorities="high",
                exclude_ids_from="",
            )
            report = export_batch(args)
            self.assertEqual(report["rows"], 2)
            self.assertEqual(report["by_domain"], {"旅行": 1, "美食": 1})

    def test_export_labeling_batch_excludes_prior_reviewed_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            queue = tmp_path / "queue.jsonl"
            reviewed = tmp_path / "reviewed.jsonl"
            _write_jsonl(queue, [
                {"annotation_id": "a1", "human_label_status": "needs_label", "priority": "high", "domain": "美食", "title": "标题1", "body": "正文1"},
                {"annotation_id": "a2", "human_label_status": "needs_label", "priority": "high", "domain": "美食", "title": "标题2", "body": "正文2"},
            ])
            _write_jsonl(reviewed, [
                {"annotation_id": "a1", "review_decision": "", "domain": "美食"},
            ])
            args = argparse.Namespace(
                kind="golden",
                queue=str(queue),
                output_dir=str(tmp_path / "batches"),
                batch_id="b2",
                max_rows=10,
                per_domain=0,
                domains="美食",
                priorities="high",
                exclude_ids_from=str(reviewed),
            )
            report = export_batch(args)
            rows = [
                json.loads(line)
                for line in Path(report["outputs"]["jsonl"]).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(report["rows"], 1)
            self.assertEqual(report["selection"]["excluded_id_count"], 1)
            self.assertEqual(rows[0]["annotation_id"], "a2")

    def test_export_labeling_batch_maps_research_sports_to_product_fitness(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            queue = tmp_path / "queue.jsonl"
            _write_jsonl(queue, [
                {
                    "annotation_id": "sport1",
                    "human_label_status": "needs_label",
                    "priority": "high",
                    "domain": "运动",
                    "title": "居家训练",
                    "body": "深蹲和臀桥各3组，适合新手。",
                },
                {
                    "annotation_id": "food1",
                    "human_label_status": "needs_label",
                    "priority": "high",
                    "domain": "美食",
                    "title": "粤菜探店",
                    "body": "招牌小青龙值得试。",
                },
            ])
            args = argparse.Namespace(
                kind="golden",
                queue=str(queue),
                output_dir=str(tmp_path / "batches"),
                batch_id="fitness",
                max_rows=10,
                per_domain=0,
                domains="健身",
                priorities="high",
                exclude_ids_from="",
            )
            report = export_batch(args)
            rows = [
                json.loads(line)
                for line in Path(report["outputs"]["jsonl"]).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            self.assertEqual(report["rows"], 1)
            self.assertEqual(report["by_domain"], {"健身": 1})
            self.assertEqual(rows[0]["annotation_id"], "sport1")
            self.assertEqual(rows[0]["domain"], "健身")

    def test_ingest_golden_skips_locked_seed_and_imports_completed(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            seed = tmp_path / "seed.json"
            inp = tmp_path / "ann.jsonl"
            out = tmp_path / "merged.json"
            report = tmp_path / "report.json"
            seed.write_text(json.dumps({"version": "golden-labels-v0.1", "items": [{"id": "seed", "content_source": {"type": "inline", "file": "", "domain": "美食", "title": "seed", "body": "seed"}, "labels": {"human_quality_score": 80, "delivery_ready": True, "naturalness_label": 80, "fact_status": "safe", "ai_smell_level": 1, "failure_tags": []}}]}, ensure_ascii=False), encoding="utf-8")
            _write_jsonl(inp, [
                {"annotation_id": "locked", "human_label_status": "locked_seed", "title": "x", "body": "y", "domain": "美食", "human_quality_score": 80, "delivery_ready": "true", "naturalness_label": 80, "fact_status": "safe", "ai_smell_level": 1},
                {"annotation_id": "done", "human_label_status": "completed", "title": "小青龙很稳", "body": "招牌小青龙，人均98元，点赞收藏。", "domain": "美食", "human_quality_score": 82, "delivery_ready": "true", "naturalness_label": 78, "fact_status": "verified", "ai_smell_level": 2, "failure_tags": "delivery_ready"},
                {"annotation_id": "todo", "human_label_status": "needs_label", "title": "todo", "body": "todo", "domain": "美食"},
            ])
            result = ingest_golden_annotations(input_path=inp, seed_path=seed, output_path=out, report_path=report)
            doc = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(result["imported_count"], 1)
            self.assertEqual(result["skipped_locked_seed"], 1)
            self.assertEqual(len(doc["items"]), 2)

    def test_ingest_preference_exports_labeled_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            inp = tmp_path / "pref.jsonl"
            out_jsonl = tmp_path / "labeled.jsonl"
            out_json = tmp_path / "labels.json"
            report = tmp_path / "report.json"
            base = {
                "pair_id": "p1",
                "label_status": "needs_label",
                "task_id": "t",
                "domain": "美食",
                "variant_a_id": "a",
                "variant_a_title": "A标题",
                "variant_a_body": "A正文",
                "variant_b_id": "b",
                "variant_b_title": "B标题",
                "variant_b_body": "B正文",
                "winner": "A",
                "preference_margin": "2",
                "reason_tags": "title_hook|naturalness",
                "rationale": "A更自然",
            }
            _write_jsonl(inp, [base, {**base, "pair_id": "p2", "winner": ""}])
            result = ingest_preference_annotations(input_path=inp, output_jsonl=out_jsonl, output_json=out_json, report_path=report)
            rows = [json.loads(line) for line in out_jsonl.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertEqual(result["labeled_count"], 1)
            self.assertEqual(rows[0]["winner"], "A")
            self.assertEqual(rows[0]["preference_margin"], 2)

    def test_health_report_detects_single_class_preference(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            golden = tmp_path / "golden.json"
            pref = tmp_path / "pref.jsonl"
            golden.write_text(json.dumps({
                "version": "golden-labels-v0.1",
                "items": [
                    {"id": "g1", "content_source": {"type": "inline", "file": "", "domain": "美食", "title": "好标题", "body": "招牌小青龙，人均98元，点赞收藏。"}, "labels": {"human_quality_score": 82, "delivery_ready": True, "naturalness_label": 80, "fact_status": "safe", "ai_smell_level": 1, "failure_tags": []}},
                    {"id": "g2", "content_source": {"type": "inline", "file": "", "domain": "美食", "title": "坏", "body": "好吃"}, "labels": {"human_quality_score": 20, "delivery_ready": False, "naturalness_label": 20, "fact_status": "unknown", "ai_smell_level": 5, "failure_tags": ["too_short"]}},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            _write_jsonl(pref, [{
                "pair_id": "p1", "task_id": "t", "domain": "美食", "winner": "B", "preference_margin": 2,
                "variant_a_id": "a", "variant_a_title": "A", "variant_a_body": "A正文",
                "variant_b_id": "b", "variant_b_title": "B", "variant_b_body": "B正文",
            }])
            args = argparse.Namespace(
                golden_labels=str(golden),
                preference_queue=str(pref),
                min_golden_candidate=300,
                min_preference_candidate=1000,
                min_golden_production=1000,
                min_preference_production=3000,
            )
            report = build_health_report(args)
            self.assertIn("preference_winner_single_class_or_empty", report["issues"])
            self.assertEqual(report["decision"], "blocked_need_labels")

    def test_health_report_counts_research_sports_as_product_fitness(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            golden = tmp_path / "golden.json"
            pref = tmp_path / "pref.jsonl"
            golden.write_text(json.dumps({
                "version": "golden-labels-v0.1",
                "items": [
                    {"id": "g1", "content_source": {"type": "inline", "file": "", "domain": "运动", "title": "新手练臀", "body": "臀桥3组，注意膝盖和腰。"}, "labels": {"human_quality_score": 82, "delivery_ready": True, "naturalness_label": 80, "fact_status": "safe", "ai_smell_level": 1, "failure_tags": []}},
                    {"id": "g2", "content_source": {"type": "inline", "file": "", "domain": "运动", "title": "练臀误区", "body": "动作太少。"}, "labels": {"human_quality_score": 20, "delivery_ready": False, "naturalness_label": 20, "fact_status": "unknown", "ai_smell_level": 5, "failure_tags": ["too_short"]}},
                ],
            }, ensure_ascii=False), encoding="utf-8")
            _write_jsonl(pref, [
                {
                    "pair_id": "p1", "task_id": "t", "domain": "运动", "winner": "B", "preference_margin": 2,
                    "variant_a_id": "a", "variant_a_title": "A", "variant_a_body": "A正文",
                    "variant_b_id": "b", "variant_b_title": "B", "variant_b_body": "B正文",
                },
                {
                    "pair_id": "p2", "task_id": "t", "domain": "健身", "winner": "A", "preference_margin": 2,
                    "variant_a_id": "a2", "variant_a_title": "A2", "variant_a_body": "A2正文",
                    "variant_b_id": "b2", "variant_b_title": "B2", "variant_b_body": "B2正文",
                },
            ])
            args = argparse.Namespace(
                golden_labels=str(golden),
                preference_queue=str(pref),
                min_golden_candidate=300,
                min_preference_candidate=1000,
                min_golden_production=1000,
                min_preference_production=3000,
            )
            report = build_health_report(args)
            self.assertEqual(report["counts"]["golden_by_domain"].get("健身"), 2)
            self.assertEqual(report["counts"]["preference_by_domain"].get("健身"), 2)
            self.assertEqual(report["gaps_by_domain"]["健身"]["golden_labeled"], 2)
            self.assertEqual(report["gaps_by_domain"]["健身"]["preference_pairs_labeled"], 2)


if __name__ == "__main__":
    unittest.main()
