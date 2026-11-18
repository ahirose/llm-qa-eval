"""Evaluate model and retrieval combinations and write a recommendation."""
import argparse
import hashlib
import json
import tomllib
from pathlib import Path

from harness import matrix_profiles, run_eval


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
    parser.add_argument("--config", type=Path, default=Path("mock.toml"))
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--rag", nargs="+", default=["none", "external"])
    parser.add_argument("--logs", type=Path, default=Path("runs"))
    parser.add_argument("--output", type=Path, default=Path("runs/recommendation.json"))
    parser.add_argument("--log-content", action="store_true")
    args = parser.parse_args()
    args.command = "compare"
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
              "selection": selection}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if selection:
        print(f"Recommended: {winner} ({selection['metrics']['pass_rate']:.1%} pass rate)")
    else:
        print("No recommendation: no combination completed evaluation for every case.")
    print(f"Recommendation file: {args.output}")
    return int(winner is None or any(item["errors"] for item in summaries.values()))


if __name__ == "__main__":
    raise SystemExit(main())
