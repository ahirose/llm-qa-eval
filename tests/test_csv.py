import csv
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from common.tabular import read_records
from comparison.statistics import read_pairs


ROOT = Path(__file__).resolve().parents[1]


class CsvTests(unittest.TestCase):
    def test_csv_quotes_newlines_and_validation(self):
        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=["id", "question", "reference", "group"])
        writer.writeheader()
        writer.writerow({"id": "001", "question": '日本語,"確認"\n次の行',
                         "reference": "回答\n詳細", "group": ""})
        rows = read_records(stream.getvalue().encode("utf-8-sig"))
        self.assertEqual(rows, [{"id": "001", "question": '日本語,"確認"\n次の行',
                                 "reference": "回答\n詳細"}])
        for text in ("id,id\na,b\n", "id,question\na,b,c\n", "id,question\na\n"):
            with self.assertRaises(ValueError):
                read_records(text.encode())

    def test_csv_recommend_answer_and_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recommendation = root / "recommended.json"
            answers = root / "answers.csv"

            def run(*args):
                return subprocess.run([sys.executable, "-m", *args], cwd=ROOT,
                                      check=True, capture_output=True, encoding="utf-8")

            run("comparison.recommend", "--dataset", "comparison/data/cases.csv",
                "--models", "mock_a", "mock_b", "--logs", str(root),
                "--output", str(recommendation))
            record = json.loads(recommendation.read_text(encoding="utf-8"))
            log = Path(record["evaluation_log"])
            results = log.with_name(log.stem + "-results.csv")
            summary = log.with_name(log.stem + "-summary.csv")
            with results.open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 40)
            self.assertTrue(all(row["question"] for row in rows))
            self.assertTrue(all(row["answer"] and row["reason"] for row in rows))
            self.assertEqual(read_pairs(log, "mock_a/none", "mock_a/external")[1]["incident-contact"]["passed"],
                             read_pairs(results, "mock_a/none", "mock_a/external")[1]["incident-contact"]["passed"])
            report = root / "statistics.csv"
            run("comparison.statistics", "--log", str(results), "--baseline", "mock_a/none",
                "--candidate", "mock_a/external", "--output", str(report))
            run("answering.batch", "--recommendation", str(recommendation),
                "--questions", "answering/data/questions.csv", "--output", str(answers))
            for path in (results, summary, answers, report):
                self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with answers.open(encoding="utf-8-sig", newline="") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 10)
            self.assertTrue(all(row["answer"] and not row["error_type"] for row in rows))


if __name__ == "__main__":
    unittest.main()
