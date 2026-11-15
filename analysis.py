#!/usr/bin/env python3
"""Analyze one development OR evaluation benchmark; optional matplotlib artifacts."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics

LABELS = {"direct_off": "Direct (thinking off)", "direct_thinking": "Direct (thinking on)",
          "solo_steps_off": "Iterative solo (off)", "solo_steps_thinking": "Iterative solo (on)",
          "independent8": "Independent 8", "independent_rounds8": "Independent rounds 8",
          "democracy8": "Democracy + guard 8", "shared8": "Shared memory 8",
          "direct_thinking_8k": "Direct (thinking on, 8k cap)",
          "solo_steps_thinking_8k": "Iterative solo (on, 8k cap)",
          "solo_iterative": "Iterative solo", "ensemble2_thinking_8k": "Full-plan ensemble 2 (on, 8k cap)",
          "ensemble4_thinking_8k": "Full-plan ensemble 4 (on, 8k cap)",
          **{f"{family}{n}": f"{label} {n}" for n in (32, 100)
             for family, label in (("independent", "Independent"), ("democracy", "Democracy + guard"), ("shared", "Shared memory"))},
          **{f"cascade{n}": f"Cascade {n} then direct (on, 8k cap)" for n in (8, 32, 100)}}
COLORS = ["#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000", "#777777", "#882255"]


def valid_server_cost(row):
    return row.get("server_cost_known") is True and all(
        type(row.get("server_" + field)) in (int, float) and math.isfinite(row["server_" + field])
        and row["server_" + field] >= row.get(field, 0)
        for field in ("prompt_tokens", "completion_tokens"))


def outcome(row):
    if row is None:
        return "missing"
    if row.get("deadline"):
        return "solved_with_deadline" if row["solved"] else "deadline"
    if row.get("controller_error") or (row.get("returncode") != 0 and not row.get("controller_stop")):
        return "error"
    return "solved_early" if row["solved"] and row.get("controller_stop") else "solved" if row["solved"] else "not_solved"


def wilson(successes, n):
    if not n:
        return None, None
    z = 1.959963984540054
    p, denominator = successes / n, 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * q
    i = int(position)
    return values[i] + (values[min(i + 1, len(values) - 1)] - values[i]) * (position - i)


def aggregate(arm, rows, planned):
    n, successes = len(rows), sum(bool(r["solved"]) for r in rows)
    lo, hi = wilson(successes, n)
    walls = [r["wall_seconds"] for r in rows]
    result = dict(arm=arm, label=LABELS.get(arm, arm), observed_cases=n, planned_cases=planned,
                  solved=successes, success_rate=successes / n if n else None,
                  wilson95_low=lo, wilson95_high=hi,
                  median_case_wall_seconds=statistics.median(walls) if walls else None,
                  p95_case_wall_seconds=percentile(walls, .95), sum_case_wall_seconds=sum(walls))
    for field in ("successful_paths", "calls", "completed_calls", "unfinished_calls", "prompt_tokens", "completion_tokens",
                  "charged_completion_tokens", "budget_denials", "response_errors", "length_finishes",
                  "missing_prompt_usage", "missing_completion_usage", "malformed_lines"):
        result[field] = sum(r.get(field, 0) or 0 for r in rows)
    result.update(deadline_cases=sum(bool(r.get("deadline")) for r in rows),
                  infrastructure_failures=sum(r.get("infrastructure_failures") or 0 for r in rows),
                  cases_missing_infrastructure_count=sum(r.get("infrastructure_failures") is None for r in rows),
                  controller_error_cases=sum(bool(r.get("controller_error")) for r in rows),
                  mean_recorded_completion_tokens_per_case=result["completion_tokens"] / n if n else None)
    result["observed_cost_is_lower_bound"] = bool(n < planned or result["deadline_cases"] or result["unfinished_calls"]
        or result["missing_prompt_usage"] or result["missing_completion_usage"])
    known = [r for r in rows if valid_server_cost(r)]
    result.update(server_cost_known_cases=len(known), server_cost_unknown_cases=n - len(known),
                  server_counter_floor_failures=sum(r.get("server_cost_known") is True and not valid_server_cost(r) for r in rows),
                  server_prompt_tokens_known=sum(r["server_prompt_tokens"] for r in known) if known else None,
                  server_completion_tokens_known=sum(r["server_completion_tokens"] for r in known) if known else None,
                  success_early_cases=sum(r.get("status") == "success_early" for r in rows),
                  solved_with_deadline_cases=sum(bool(r.get("deadline") and r["solved"]) for r in rows),
                  unexpected_process_error_cases=sum(r.get("returncode") != 0 and not r.get("controller_stop") for r in rows))
    if any("holdout_status" in r for r in rows):
        result.update(feedback_pass_cases=sum(r.get("feedback_final_status") == "passed" for r in rows),
                      final_holdout_pass_cases=sum(r.get("holdout_status") == "passed" for r in rows))
        for field in ("feedback_eval_count", "holdout_eval_count", "holdout_passed", "holdout_total", "grader_errors", "grader_infrastructure_errors"):
            result[field] = sum(r.get(field, 0) for r in rows)
    return result


def write_csv(path, rows, fields):
    with path.open("x", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def plots(report, directory):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise SystemExit("--plot needs matplotlib in the selected Python environment; no global installation was attempted") from exc
    plt.rcParams.update({"font.size": 10, "svg.fonttype": "none", "axes.spines.top": False,
                         "axes.spines.right": False, "figure.facecolor": "white"})
    rows = [r for r in report["arms"] if r["observed_cases"]]
    if not rows:
        return
    title = report["split"].capitalize() + " " + report.get("domain", "arithmetic") + (" — PROVISIONAL" if report["provisional"] else "")
    if report.get("title_note"): title += " — " + report["title_note"]
    footer = "Fixed synthetic tasks; Wilson intervals are descriptive. Same tasks do not imply identical sampled trajectories."
    def save(fig, name):
        fig.text(.02, .015, footer, fontsize=8)
        fig.tight_layout(rect=(0, .06, 1, 1))
        for extension in ("svg", "png"):
            fig.savefig(directory / f"{name}.{extension}", dpi=200)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(11, 5.6))
    for i, row in enumerate(rows):
        value = row["success_rate"] * 100
        ax.errorbar(value, i, xerr=[[value - 100 * row["wilson95_low"]],
                    [100 * row["wilson95_high"] - value]], fmt="o", color=COLORS[i % len(COLORS)], capsize=4)
        ax.text(102, i, f"{row['solved']}/{row['observed_cases']}", va="center")
    ax.set(yticks=range(len(rows)), yticklabels=[r["label"] for r in rows], xlim=(-2, 112),
           xlabel="Solved tasks (%) with Wilson 95% interval", title=title + (" — final holdout task success" if report.get("domain") == "coding" else " — task success"))
    ax.invert_yaxis(); ax.grid(axis="x", alpha=.25)
    save(fig, "accuracy-wilson95")
    fig, ax = plt.subplots(figsize=(11, 6.2))
    markers = ["o", "s", "^", "D", "P", "X", "v", "h", "*"]
    for i, row in enumerate(rows):
        x, y = row["mean_recorded_completion_tokens_per_case"], row["success_rate"] * 100
        ax.scatter(x, y, s=75, color=COLORS[i % len(COLORS)], marker=markers[i % len(markers)],
                   edgecolor="black", linewidth=.5,
                   label=row["label"] + (" *" if row["observed_cost_is_lower_bound"] else ""))
    ax.set(xlabel="Mean recorded completion tokens per task (* = cost lower bound)",
           ylabel="Solved tasks (%)", ylim=(-3, 105), title=title + " — success and output-token cost")
    ax.legend(loc="upper left", bbox_to_anchor=(1.02, 1), frameon=False, fontsize=9)
    ax.margins(x=.08); ax.grid(alpha=.25)
    save(fig, "success-vs-completion-cost")
    fig, ax = plt.subplots(figsize=(11, 5.6))
    for i, row in enumerate(rows):
        median, tail = row["median_case_wall_seconds"], row["p95_case_wall_seconds"]
        ax.plot([median, tail], [i, i], color=COLORS[i % len(COLORS)], linewidth=2)
        ax.scatter(median, i, color=COLORS[i % len(COLORS)], marker="o", s=55)
        ax.scatter(tail, i, color=COLORS[i % len(COLORS)], marker="|", s=130)
    ax.set(yticks=range(len(rows)), yticklabels=[r["label"] for r in rows],
           xlabel="Actual case wall seconds: circle = median, tick = empirical p95",
           title=title + " — per-case latency (not fleet throughput)")
    ax.invert_yaxis(); ax.grid(axis="x", alpha=.25)
    save(fig, "case-latency")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmark", type=Path)
    parser.add_argument("--output", type=Path, help="New derived-output directory; default BENCHMARK/analysis")
    parser.add_argument("--allow-partial", action="store_true", help="Explicitly label incomplete/unverified runs provisional")
    parser.add_argument("--plot", action="store_true", help="Write three standalone SVG and PNG figures")
    parser.add_argument("--title-note", default="", help="Explicit interim scope shown on every figure")
    args = parser.parse_args(argv)
    meta_raw = (args.benchmark / "metadata.json").read_bytes()
    summary_raw = (args.benchmark / "summary.json").read_bytes()
    meta, rows = json.loads(meta_raw), json.loads(summary_raw)
    if meta["split"] not in ("development", "evaluation"):
        parser.error("one development or evaluation split is required; mixed splits are forbidden")
    if meta.get("source_changed_during_run") or (meta.get("final_source_hashes") is not None
            and meta["source_hashes"] != meta["final_source_hashes"]):
        parser.error("benchmark sources changed during execution; refusing comparison")
    planned = {(c["task_id"], c["arm"], c["seed"]) for c in meta["cases"]}
    seen = [(r["task_id"], r["arm"], r["seed"]) for r in rows]
    if len(planned) != len(meta["cases"]) or len(set(seen)) != len(seen) or not set(seen) <= planned:
        parser.error("duplicate or unplanned task/arm/seed rows")
    if any(r["split"] != meta["split"] for r in rows):
        parser.error("summary split differs from metadata")
    reasons = []
    if len(rows) != len(planned) or meta.get("completed_cases") != len(planned):
        reasons.append("Not all planned cases completed")
    if meta.get("final_source_hashes") != meta.get("source_hashes") or meta.get("source_changed_during_run") is not False:
        reasons.append("Final unchanged-source verification unavailable")
    if meta.get("batch_wall_seconds") is None:
        reasons.append("Final whole-queue wall measurement unavailable")
    if reasons and not args.allow_partial:
        parser.error("; ".join(reasons) + "; use --allow-partial only for a provisional report")
    arms = [aggregate(a, [r for r in rows if r["arm"] == a], sum(c["arm"] == a for c in meta["cases"]))
            for a in meta["arms"]]
    if meta.get("domain") == "coding":
        for arm in arms:
            if arm["arm"] == "democracy8": arm["label"] = "Democracy 8"
    pairs = []
    for task, seed in sorted({(c["task_id"], c["seed"]) for c in meta["cases"]}):
        pair = dict(task_id=task, split=meta["split"], seed=seed)
        for arm in meta["arms"]:
            match = next((r for r in rows if (r["task_id"], r["seed"], r["arm"]) == (task, seed, arm)), None)
            pair[arm] = outcome(match)
        pairs.append(pair)
    report = dict(schema_version=1, benchmark=str(args.benchmark.resolve()), split=meta["split"], domain=meta.get("domain", "arithmetic"),
                  provisional=bool(reasons), provisional_reasons=reasons, seed=meta["seed"], title_note=args.title_note,
                  dataset_sha256=meta["dataset_sha256"], source_commit=meta.get("git_revision"),
                  source_hashes=meta["source_hashes"], final_source_hashes=meta.get("final_source_hashes"),
                  metadata_sha256=hashlib.sha256(meta_raw).hexdigest(), summary_sha256=hashlib.sha256(summary_raw).hexdigest(),
                  analysis_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  scope=meta["scope"], scheduling=meta["scheduling"], runtime=meta["runtime"],
                  whole_mixed_arm_queue_wall_seconds=meta.get("batch_wall_seconds"),
                  observed_cost_is_lower_bound=any(a["observed_cost_is_lower_bound"] for a in arms),
                  arms=arms, paired_task_results=pairs,
                  notes=["Development and evaluation are analyzed separately; do not infer a held-out winner from development.",
                         "Wilson intervals describe observed binary task outcomes; tasks form a small synthetic construction sample.",
                         "p95 uses linear interpolation between ordered observed case times; it is not a confidence interval.",
                         "Sum of case wall seconds is NOT fleet wall time. Mixed-arm queue wall time is NOT per-arm throughput.",
                         "Input/output token counts are observed API usage, not equal GPU cost; output-cost plots omit input cost.",
                         "Deadline/incomplete-usage costs are lower bounds; reported successes preserve the runner's deadline rule.",
                         "Expected negative exit codes after controller stops are not process/infrastructure failures.",
                         "Server counter sums include only explicitly known deltas that cover completed client usage; unknowns remain null.",
                         "Paired table matches task/seed, not identical sampled trajectories. No paired causal effect is claimed."])
    directory = args.output or args.benchmark / "analysis"
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    write_csv(directory / "summary.csv", arms, list(arms[0]))
    write_csv(directory / "paired-results.csv", pairs, ["task_id", "split", "seed", *meta["arms"]])
    if args.plot:
        plots(report, directory)
    print(("PROVISIONAL " if reasons else "") + meta["split"] + f": {len(rows)}/{len(planned)} cases")
    for a in arms:
        interval = "n/a" if not a["observed_cases"] else f"{100*a['wilson95_low']:.1f}–{100*a['wilson95_high']:.1f}%"
        print(f"{a['label']}: {a['solved']}/{a['observed_cases']} Wilson95 {interval}; calls={a['calls']} completion={a['completion_tokens']} deadlines={a['deadline_cases']}")
    print(f"Artifacts: {directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
