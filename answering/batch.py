"""Answer a CSV question list using a saved recommendation."""
import argparse
import csv
import hashlib
import json
import tomllib
from pathlib import Path
from types import SimpleNamespace

from common.pipeline import answer
from comparison.runner import matrix_profiles
from common.tabular import read_records, csv_row


def load_questions(path):
    rows = []
    ids = set()
    for index, case in enumerate(read_records(path.read_bytes()), 1):
        if not isinstance(case, dict) or any(
            not isinstance(case.get(key), str) or not case[key].strip()
            for key in ("id", "question")
        ):
            raise ValueError(f"Line {index} must have nonempty id and question strings")
        if case["id"] in ids:
            raise ValueError(f"Duplicate question ID on line {index}")
        ids.add(case["id"])
        rows.append(case)
    if not rows:
        raise ValueError("Question list is empty")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/mock.toml"))
    parser.add_argument("--recommendation", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = args.config.read_bytes()
    recommendation = json.loads(args.recommendation.read_text(encoding="utf-8-sig"))
    selection = recommendation.get("selection")
    if recommendation.get("version") != 1 or not selection:
        parser.error("The recommendation file has no usable selection")
    if recommendation.get("config_sha256") != hashlib.sha256(raw).hexdigest():
        parser.error("Use the configuration from the recommendation run or run recommend.py again")
    config = tomllib.loads(raw.decode("utf-8-sig"))
    root = args.config.resolve().parent
    model, rag = selection["model"], selection["rag"]
    selectors = SimpleNamespace(models=[model], rag=[rag])
    profile = matrix_profiles(parser, selectors, config)[f"{model}/{rag}"]

    try:
        questions = load_questions(args.questions)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    errors = 0
    try:
        output = args.output.open("x", encoding="utf-8-sig" if args.output.suffix.lower() == ".csv"
                                  else "utf-8", newline="")
    except FileExistsError:
        parser.error("The output file already exists. Specify a new --output path")
    with output:
        writer = None
        if args.output.suffix.lower() == ".csv":
            writer = csv.DictWriter(output, fieldnames=[
                "id", "question", "answer", "model_profile", "model", "rag", "usage", "error_type"])
            writer.writeheader()
        for case in questions:
            question = case["question"]
            row = {"id": case["id"], "question": question, "model_profile": model, "rag": rag}
            try:
                reply, _ = answer(profile, question, root)
                row.update(answer=reply.text, model=reply.model, usage=reply.usage)
            except Exception as exc:
                row.update(answer=None, error_type=type(exc).__name__)
                errors += 1
            if writer:
                writer.writerow(csv_row(row))
                output.flush()
            else:
                print(json.dumps(row, ensure_ascii=False), file=output, flush=True)
    print(f"Answered {len(questions) - errors}/{len(questions)} questions. Output: {args.output}")
    return int(errors > 0)


if __name__ == "__main__":
    raise SystemExit(main())
