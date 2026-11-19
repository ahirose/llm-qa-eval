import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from comparison.judge import judge
from comparison.statistics import compare
from comparison.runner import load_cases
from comparison.recommend import choose
from common.sources import retrieve

ROOT = Path(__file__).resolve().parents[1]


class HarnessTests(unittest.TestCase):
    def test_timestamped_recommendation_and_archive(self):
        from unittest.mock import patch
        from comparison.recommend import main

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / "configs", root / "configs")
            shutil.copytree(ROOT / "common/data", root / "common/data")
            dataset = ROOT / "comparison/data/cases.jsonl"
            original = Path.cwd()
            try:
                os.chdir(root)
                with patch("sys.argv", ["recommend", "--dataset", str(dataset),
                                        "--models", "mock_a"]):
                    self.assertEqual(main(), 0)
                (selected,) = (root / "answering/configs").glob("recommended-*.json")
                record = json.loads(selected.read_text(encoding="utf-8"))
                self.assertIn("+00:00", record["created_at"])
                archive = Path(record["evaluation_log"]).parent / selected.name
                self.assertEqual(archive.read_bytes(), selected.read_bytes())
                self.assertEqual(record["profile"]["retrieval"]["mode"], "fixture-search")
            finally:
                os.chdir(original)

    def test_paired_statistics_use_question_level_changes(self):
        before = {str(i): {"passed": i < 70} for i in range(100)}
        after = {str(i): {"passed": i < 65 or 70 <= i < 95} for i in range(100)}
        result = compare(before, after, draws=2000, seed=42, margin=3)
        self.assertEqual(result["pair_counts"], {"both_pass": 65, "improved": 25,
                                               "worsened": 5, "both_fail": 5})
        self.assertEqual(result["difference_pp"], 20)
        self.assertAlmostEqual(result["mcnemar_exact_two_sided_p"], 0.0003249142318964)
        low, high = result["bootstrap"]["ci95_pp"]
        self.assertLess(0, low)
        self.assertLess(low, 20)
        self.assertGreater(high, 20)
        self.assertEqual(result["noninferiority"]["status"], "met")

    def test_grouped_log_and_incomplete_pairs(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "cases.jsonl"
            cases = [json.loads(line) for line in (ROOT / "comparison/data" / dataset.name).read_text(
                encoding="utf-8").splitlines()]
            dataset.write_text("\n".join(json.dumps(dict(case, group="same-policy"))
                                         for case in cases), encoding="utf-8")
            _, _, rows = self.evaluate(dataset, ["baseline", "direct"])
            log = next((dataset.parent / "runs").glob("*.jsonl"))
            command = [sys.executable, "compare_stats.py", "--log", str(log),
                       "--baseline", "baseline", "--candidate", "direct", "--margin-pp", "3"]
            result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, encoding="utf-8")
            report = json.loads(result.stdout)
            self.assertEqual(report["bootstrap"]["unit"], "group")
            self.assertEqual(report["bootstrap"]["units"], 1)
            self.assertIsNone(report["mcnemar_exact_two_sided_p"])
            self.assertEqual(report["noninferiority"]["status"], "inconclusive")
            del rows[1]["passed"]
            rows[1]["error_stage"] = "judge"
            log.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            result = subprocess.run(command, cwd=ROOT, check=True, capture_output=True, encoding="utf-8")
            report = json.loads(result.stdout)
            self.assertEqual(report["paired_graded"], 9)
            self.assertEqual(report["baseline"]["judge_errors"], 1)
            self.assertIsNone(report["bootstrap"]["ci95_pp"])

    def test_recommendation_requires_complete_coverage_and_breaks_score_ties(self):
        profiles = {"incomplete": {"retrieval": {"mode": "external-search"}},
                    "search": {"retrieval": {"mode": "external-search"}},
                    "baseline": {"retrieval": {"mode": "none"}}}
        summaries = {"incomplete": {"coverage": 0.5, "passed": 2, "mean_answer_ms": 1},
                     "search": {"coverage": 1, "passed": 1, "mean_answer_ms": 1},
                     "baseline": {"coverage": 1, "passed": 1, "mean_answer_ms": 2}}
        self.assertEqual(choose(summaries, profiles), "baseline")
        self.assertIsNone(choose({"incomplete": summaries["incomplete"]}, profiles))

    def test_recommendation_runs_batch_without_references(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            recommendation = logs / "recommendation.json"
            output = logs / "answers.jsonl"
            for script, args in (
                ("recommend.py", ["--dataset", "comparison/data/cases.jsonl", "--models", "mock_a", "mock_b",
                                  "--logs", str(logs), "--output", str(recommendation)]),
                ("answer_batch.py", ["--recommendation", str(recommendation),
                                     "--questions", "answering/data/questions.jsonl", "--output", str(output)]),
            ):
                result = subprocess.run([sys.executable, script, *args], cwd=ROOT,
                                        capture_output=True, encoding="utf-8")
                self.assertEqual(result.returncode, 0, result.stderr)
            selection = json.loads(recommendation.read_text(encoding="utf-8"))["selection"]
            answers = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(selection["rag"], "external")
        cases = load_cases((ROOT / "comparison/data/cases.jsonl").read_bytes())
        self.assertEqual(len(answers), 10)
        self.assertEqual([(row["id"], row["question"], row["answer"]) for row in answers],
                         [(case["id"], case["question"], case["reference"]) for case in cases])
        self.assertTrue(all(row["model_profile"] == selection["model"] for row in answers))

    def evaluate(self, dataset, profiles):
        logs = dataset.parent / "runs"
        result = subprocess.run(
            [sys.executable, "harness.py", "eval", "--dataset", str(dataset),
             "--logs", str(logs), "--profiles", *profiles],
            cwd=ROOT, capture_output=True, encoding="utf-8",
        )
        summary = json.loads(result.stdout)
        rows = [json.loads(line) for line in Path(summary["log"]).read_text(
            encoding="utf-8").splitlines()]
        return result, summary["profiles"], rows

    def test_all_fixture_profiles(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "cases.jsonl"
            dataset.write_bytes((ROOT / "comparison/data" / dataset.name).read_bytes())
            result, summary, rows = self.evaluate(dataset, ["baseline", "direct", "search", "tool"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([profile["passed"] for profile in summary.values()], [0, 10, 10, 10])
        for row in rows[1:-1]:
            self.assertNotIn("answer", row)
            self.assertNotIn("reason", row)
            self.assertNotIn("question", row)

    def test_compare_runs_every_model_and_rag_combination(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            result = subprocess.run(
                [sys.executable, "harness.py", "compare", "--dataset", "comparison/data/cases.jsonl",
                 "--logs", str(logs), "--models", "mock_a", "mock_b", "--rag", "none", "external"],
                cwd=ROOT, capture_output=True, encoding="utf-8",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Pass rate", result.stdout)
            self.assertIn("Mean answer ms", result.stdout)
            (log,) = logs.glob("*.jsonl")
            rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        profiles = rows[-1]["profiles"]
        self.assertEqual(list(profiles), ["mock_a/none", "mock_a/external",
                                         "mock_b/none", "mock_b/external"])
        self.assertEqual([item["passed"] for item in profiles.values()], [0, 10, 0, 10])
        self.assertTrue(all(item["coverage"] == 1 for item in profiles.values()))
        self.assertEqual({row["model"] for row in rows if row["type"] == "case"},
                         {"fixture-a", "fixture-b"})

    def test_error_is_counted_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "cases.jsonl"
            dataset.write_bytes((ROOT / "comparison/data" / dataset.name).read_bytes())
            logs = Path(directory) / "runs"
            config = Path(directory) / "config.toml"
            config.write_text((ROOT / "configs/mock.toml").read_text(encoding="utf-8"), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "harness.py", "--config", str(config), "eval",
                 "--dataset", str(dataset), "--logs", str(logs), "--profiles", "direct", "baseline"],
                cwd=ROOT, capture_output=True, encoding="utf-8",
            )
        self.assertEqual(result.returncode, 1)
        profiles = json.loads(result.stdout)["profiles"]
        self.assertEqual(profiles["direct"]["errors"], 10)
        self.assertIsNone(profiles["direct"]["pass_rate"])
        self.assertEqual(profiles["baseline"]["failed"], 10)

    def test_external_search_contract_without_network(self):
        response = Mock()
        response.json.return_value = {"results": [{"id": "abc", "text": "evidence"}]}
        httpx = SimpleNamespace(post=Mock(return_value=response))
        config = {"mode": "external-search", "url_env": "TEST_SEARCH_URL",
                  "token_env": "TEST_SEARCH_TOKEN", "top_k": 1}
        with patch.dict(sys.modules, {"httpx": httpx}), patch.dict(
                "os.environ", {"TEST_SEARCH_URL": "https://search.invalid/query",
                               "TEST_SEARCH_TOKEN": "fixture"}):
            files, evidence = retrieve(config, "question", ROOT)
        self.assertEqual(files, [])
        self.assertEqual(evidence, [{"id": "abc", "text": "evidence"}])
        httpx.post.assert_called_once_with("https://search.invalid/query",
                                         headers={"Authorization": "Bearer fixture"}, timeout=30,
                                         json={"query": "question", "top_k": 1})

    def test_invalid_judge_json_is_an_error(self):
        with patch("comparison.judge.generate", return_value=SimpleNamespace(
                text='{"pass":"true","reason":"reason"}')):
            with self.assertRaises(ValueError):
                judge({"provider": "openai"}, {"question": "q", "reference": "r"}, "answer")

    def test_duplicate_ids_terminate_before_evaluation(self):
        raw = (ROOT / "comparison/data/cases.jsonl").read_bytes()
        with self.assertRaisesRegex(ValueError, "unique"):
            load_cases(raw + b"\n" + raw)


if __name__ == "__main__":
    unittest.main()
