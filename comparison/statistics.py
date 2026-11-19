"""Analyze two profiles from the same completed evaluation JSONL."""
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import random
from common.tabular import read_records, write_csv


def read_csv_pairs(path, baseline, candidate):
    rows = read_records(path.read_bytes())
    profiles = {baseline: {}, candidate: {}}
    metadata = set()
    for row in rows:
        if row.get("profile") not in profiles:
            continue
        metadata.add((row["dataset_sha256"], int(row["case_count"])))
        passed = row["passed"].lower()
        if passed not in {"true", "false", ""}:
            raise ValueError("CSV passed values must be True, False or empty")
        if passed:
            row["passed"] = passed == "true"
        else:
            row.pop("passed")
        profile = profiles[row["profile"]]
        if row["id"] in profile:
            raise ValueError("Duplicate case ID in CSV profile")
        profile[row["id"]] = row
    if len(metadata) != 1:
        raise ValueError("CSV must contain one evaluation dataset")
    digest, count = metadata.pop()
    before, after = profiles[baseline], profiles[candidate]
    if not before or before.keys() != after.keys() or len(before) != count:
        raise ValueError("Both profiles must have the same complete set of case records")
    if any(row.get("group") != after[key].get("group") for key, row in before.items()):
        raise ValueError("Group mismatch between CSV profiles")
    return {"dataset_sha256": digest}, before, after


def read_pairs(path, baseline, candidate):
    if path.suffix.lower() == ".csv":
        return read_csv_pairs(path, baseline, candidate)
    profiles = {baseline: {}, candidate: {}}
    with path.open(encoding="utf-8-sig") as source:
        rows = (json.loads(line) for line in source if line.strip())
        run = next(rows, {})
        if run.get("type") != "run":
            raise ValueError("Expected the evaluation run header")
        last = run
        for row in rows:
            last = row
            name = row.get("profile")
            if row.get("type") != "case" or name not in profiles:
                continue
            case_id = row["id"]
            if case_id in profiles[name]:
                raise ValueError(f"Duplicate case ID in profile {name}: {case_id}")
            profiles[name][case_id] = row
    if last.get("type") != "summary":
        raise ValueError("Evaluation did not finish writing its summary")
    before, after = profiles[baseline], profiles[candidate]
    if not before or before.keys() != after.keys() or len(before) != run.get("case_count"):
        raise ValueError("Both profiles must have the same complete set of case records")
    for case_id, row in before.items():
        if row.get("group") != after[case_id].get("group"):
            raise ValueError(f"Group mismatch for case {case_id}")
    return run, before, after


def exact_mcnemar(improved, worsened):
    discordant = improved + worsened
    tail = sum(math.comb(discordant, k) for k in range(min(improved, worsened) + 1))
    return min(1.0, (2 * tail) / (2 ** discordant))


def bootstrap_interval(units, draws, seed):
    # Each unit stores its net change and its number of paired questions.
    if len(units) < 2 or len({delta / count for delta, count in units}) < 2:
        return None
    rng = random.Random(seed)
    estimates = []
    for _ in range(draws):
        sample = rng.choices(units, k=len(units))
        estimates.append(sum(delta for delta, _ in sample) /
                         sum(count for _, count in sample))
    estimates.sort()

    def percentile(p):
        index = p * (draws - 1)
        lower, upper = math.floor(index), math.ceil(index)
        return estimates[lower] + (index - lower) * (estimates[upper] - estimates[lower])

    low, high = percentile(0.025), percentile(0.975)
    return [100 * low, 100 * high] if low < high else None


def summarize_profile(rows):
    graded = [row["passed"] for row in rows.values() if type(row.get("passed")) is bool]
    return {"passed": sum(graded), "graded": len(graded),
            "answer_errors": sum(row.get("error_stage") == "answer" for row in rows.values()),
            "judge_errors": sum(row.get("error_stage") == "judge" for row in rows.values())}


def compare(before, after, draws, seed, margin):
    counts = {"both_pass": 0, "improved": 0, "worsened": 0, "both_fail": 0}
    units = defaultdict(lambda: [0, 0])
    clustered = any(row.get("group") is not None for row in before.values())
    for case_id, row in before.items():
        first, second = row.get("passed"), after[case_id].get("passed")
        if type(first) is not bool or type(second) is not bool:
            continue
        counts[{(True, True): "both_pass", (False, True): "improved",
                (True, False): "worsened", (False, False): "both_fail"}[first, second]] += 1
        group = row.get("group")
        key = ("group", group) if group is not None else ("case", case_id)
        units[key][0] += int(second) - int(first)
        units[key][1] += 1

    paired = sum(counts.values())
    complete = paired == len(before)
    net = counts["improved"] - counts["worsened"]
    interval = bootstrap_interval(list(units.values()), draws, seed) if complete else None
    warnings = []
    if not complete:
        warnings.append("Incomplete grading. Paired point estimates use graded pairs only.")
    elif interval is None:
        warnings.append("The bootstrap could not estimate a non-degenerate interval.")
    result = {
        "total_questions": len(before), "paired_graded": paired,
        "excluded_ungraded_pairs": len(before) - paired, "pair_counts": counts,
        "baseline": summarize_profile(before), "candidate": summarize_profile(after),
        "baseline_paired_pass_pct": 100 * (counts["both_pass"] + counts["worsened"]) / paired if paired else None,
        "candidate_paired_pass_pct": 100 * (counts["both_pass"] + counts["improved"]) / paired if paired else None,
        "difference_pp": 100 * net / paired if paired else None,
        "bootstrap": {"unit": "group" if clustered else "question", "units": len(units),
                      "resamples": draws, "seed": seed, "ci95_pp": interval},
        "mcnemar_exact_two_sided_p": (
            exact_mcnemar(counts["improved"], counts["worsened"])
            if complete and not clustered else None
        ),
        "warnings": warnings,
    }
    if margin is not None:
        result["noninferiority"] = {
            "margin_pp": margin,
            "status": "inconclusive" if interval is None else
                      "met" if interval[0] > -margin else "not_demonstrated",
        }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--resamples", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--margin-pp", type=float)
    parser.add_argument("--output", type=Path, help="Save the statistical report as CSV")
    args = parser.parse_args()
    if args.baseline == args.candidate:
        parser.error("Choose two different profiles")
    if args.resamples < 1000:
        parser.error("--resamples must be at least 1000")
    if args.margin_pp is not None and not 0 < args.margin_pp <= 100:
        parser.error("--margin-pp must be positive and at most 100")
    try:
        run, before, after = read_pairs(args.log, args.baseline, args.candidate)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    result = compare(before, after, args.resamples, args.seed, args.margin_pp)
    report = {"baseline_profile": args.baseline, "candidate_profile": args.candidate,
              "dataset_sha256": run.get("dataset_sha256"), **result}
    if args.output:
        flattened = {}

        def flatten(values, prefix=""):
            for key, value in values.items():
                name = prefix + key
                if isinstance(value, dict):
                    flatten(value, name + "_")
                else:
                    flattened[name] = value

        flatten(report)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        write_csv(args.output, [flattened], list(flattened))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
