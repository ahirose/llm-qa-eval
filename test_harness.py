import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from evaluation import judge
from harness import load_cases
from sources import retrieve

ROOT = Path(__file__).resolve().parent


class HarnessTests(unittest.TestCase):
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
            dataset.write_bytes((ROOT / dataset.name).read_bytes())
            result, summary, rows = self.evaluate(dataset, ["baseline", "direct", "search", "tool"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([profile["passed"] for profile in summary.values()], [0, 2, 2, 2])
        for row in rows[1:-1]:
            self.assertNotIn("answer", row)
            self.assertNotIn("reason", row)
            self.assertNotIn("question", row)

    def test_compare_runs_every_model_and_rag_combination(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory)
            result = subprocess.run(
                [sys.executable, "harness.py", "compare", "--dataset", "cases.jsonl",
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
        self.assertEqual([item["passed"] for item in profiles.values()], [0, 2, 0, 2])
        self.assertTrue(all(item["coverage"] == 1 for item in profiles.values()))
        self.assertEqual({row["model"] for row in rows if row["type"] == "case"},
                         {"fixture-a", "fixture-b"})

    def test_error_is_counted_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = Path(directory) / "cases.jsonl"
            dataset.write_bytes((ROOT / dataset.name).read_bytes())
            logs = Path(directory) / "runs"
            config = Path(directory) / "config.toml"
            config.write_text((ROOT / "mock.toml").read_text(encoding="utf-8"), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "harness.py", "--config", str(config), "eval",
                 "--dataset", str(dataset), "--logs", str(logs), "--profiles", "direct", "baseline"],
                cwd=ROOT, capture_output=True, encoding="utf-8",
            )
        self.assertEqual(result.returncode, 1)
        profiles = json.loads(result.stdout)["profiles"]
        self.assertEqual(profiles["direct"]["errors"], 2)
        self.assertIsNone(profiles["direct"]["pass_rate"])
        self.assertEqual(profiles["baseline"]["failed"], 2)

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
        with patch("evaluation.generate", return_value=SimpleNamespace(
                text='{"pass":"true","reason":"reason"}')):
            with self.assertRaises(ValueError):
                judge({"provider": "openai"}, {"question": "q", "reference": "r"}, "answer")

    def test_duplicate_ids_terminate_before_evaluation(self):
        raw = (ROOT / "cases.jsonl").read_bytes()
        with self.assertRaisesRegex(ValueError, "unique"):
            load_cases(raw + b"\n" + raw)


if __name__ == "__main__":
    unittest.main()
