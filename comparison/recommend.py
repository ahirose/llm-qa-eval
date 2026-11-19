"""Evaluate model and retrieval combinations and write a recommendation."""
import argparse
from datetime import datetime, timezone
import uuid
import hashlib
import json
import tomllib
from pathlib import Path

from comparison.runner import matrix_profiles, run_eval


def choose(summaries, profiles):
    eligible = [name for name, item in summaries.items() if item["coverage"] == 1]
    if not eligible:
        return None
    return min(eligible, key=lambda name: (
        -summaries[name]["passed"],
        profiles[name]["retrieval"]["mode"] != "none",
        summaries[name]["mean_answer_ms"],
        name,
    ))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/mock.toml"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--rag", nargs="+", default=["none", "external"])
    parser.add_argument("--logs", type=Path, default=Path("comparison/runs"))
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--log-content", action="store_true")
    args = parser.parse_args()
    args.command = "compare"
    created = datetime.now(timezone.utc)
    filename = f"recommended-{created:%Y%m%d-%H%M%S}-{created.microsecond // 1000:03d}Z-{uuid.uuid4().hex[:8]}.json"
    if args.output is None:
        args.output = Path("answering/configs") / filename
    if args.output.exists():
        parser.error("Recommendation output already exists. Choose a new path")
    if args.output.resolve() in {args.dataset.resolve(), args.config.resolve()}:
        parser.error("--output must differ from the dataset and configuration files")

    raw = args.config.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    config = tomllib.loads(raw.decode("utf-8-sig"))
    profiles = matrix_profiles(parser, args, config)
    summaries, log_path = run_eval(args, profiles, config, args.config.resolve().parent, digest)
    winner = choose(summaries, profiles)
    selection = None
    if winner:
        model, rag = winner.split("/")
        selection = {"model": model, "rag": rag, "metrics": summaries[winner]}
    result = {"version": 1, "config_sha256": digest, "evaluation_log": str(log_path.resolve()),
              "selection": selection, "created_at": created.isoformat(),
              "config_path": str(args.config.resolve()),
              "profile": profiles[winner] if winner else None}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    archive = log_path.parent / filename
    if archive.resolve() != args.output.resolve():
        with archive.open("x", encoding="utf-8") as output:
            output.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    if selection:
        print(f"Recommended: {winner} ({selection['metrics']['pass_rate']:.1%} pass rate)")
    else:
        print("No recommendation: no combination completed evaluation for every case.")
    print(f"Recommendation file: {args.output}")
    return int(winner is None or any(item["errors"] for item in summaries.values()))


if __name__ == "__main__":
    raise SystemExit(main())
