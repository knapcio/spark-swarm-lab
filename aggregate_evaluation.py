#!/usr/bin/env python3
"""Aggregate complete evaluation cohorts; resample tasks, retaining all seeds."""
import argparse
import csv
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import statistics

TIMES = (5, 10, 30, 60, 120, 180)
COLORS = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9", "#000000")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quantile(values, q):
    values = sorted(values)
    if not values: return None
    position = (len(values) - 1) * q
    index = int(position)
    return values[index] + (values[min(index + 1, len(values) - 1)] - values[index]) * (position - index)


def cluster_ci(task_means, repetitions=5000, seed=20261115):
    """Percentile CI of equally weighted task means; all seed outcomes stay together."""
    values, rng = list(task_means), random.Random(seed)
    if not values or repetitions < 1: raise ValueError("nonempty tasks and positive bootstrap repetitions required")
    samples = [sum(rng.choice(values) for _ in values) / len(values) for _ in range(repetitions)]
    return quantile(samples, .025), quantile(samples, .975)


def known_server(row):
    return row.get("server_cost_known") is True and all(
        type(row.get("server_" + key)) in (int, float) and math.isfinite(row["server_" + key])
        and row["server_" + key] >= row.get(key, 0) for key in ("prompt_tokens", "completion_tokens"))


def ledger_record(path, meta, ledger):
    entries = {entry["name"]: entry for entry in ledger}
    if len(entries) != len(ledger): raise ValueError("duplicate ledger cohort names")
    identity, manifest_hash = path.name, None
    if identity not in entries:
        for name in ("export-manifest.json", "manifest.json"):
            manifest = path / name
            if manifest.exists():
                identity = Path(json.loads(manifest.read_bytes()).get("source_directory", "")).name
                manifest_hash = sha(manifest)
                if identity in entries: break
    entry = entries.get(identity)
    if entry is None: raise ValueError("input cohort has no matching ledger entry")
    annotation = entry.get("review_annotation", {}).get("primary_aggregation", "")
    if (entry.get("valid_for_aggregation") is False or annotation is False
            or str(annotation).strip().lower().startswith(("excluded", "invalid"))):
        raise ValueError("ledger excludes this cohort from primary aggregation")
    if (entry.get("domain") != meta.get("domain", "arithmetic") or entry.get("seed") != meta.get("seed")
            or entry.get("returncode") != 0 or entry.get("incomplete") is not False
            or entry.get("source_changed") is not False or not entry.get("completed_utc")
            or entry.get("completed_cases") != meta.get("completed_cases")
            or entry.get("source_revision") != meta.get("git_revision")):
        raise ValueError("ledger must confirm completed, unchanged matching cohort")
    return dict(entry=entry, identity_manifest_sha256=manifest_hash)


def load_cohorts(paths, domain, labels=None, expected_tasks=None, expected_seeds=3, ledger=None):
    rows, cohorts, seen, datasets = [], [], set(), set()
    labels = labels or {}
    for path in map(Path, paths):
        meta_path, summary_path = path / "metadata.json", path / "summary.json"
        meta = json.loads(meta_path.read_bytes())
        validity = ledger_record(path, meta, ledger) if ledger is not None else None
        summary = json.loads(summary_path.read_bytes())
        if meta.get("split") != "evaluation" or meta.get("domain", "arithmetic") != domain:
            raise ValueError("all inputs must be evaluation of the requested domain")
        if not meta.get("source_hashes") or meta.get("source_changed_during_run") is not False or meta.get("final_source_hashes") != meta["source_hashes"]:
            raise ValueError("captured unchanged-source verification required")
        planned = [(c["task_id"], c["arm"], c["seed"]) for c in meta["cases"]]
        actual = [(r["task_id"], r["arm"], r["seed"]) for r in summary]
        if (not planned or len(set(planned)) != len(planned) or len(set(actual)) != len(actual)
                or set(actual) != set(planned) or meta.get("completed_cases") != len(planned)
                or meta.get("incomplete") or meta.get("missing_cases") or meta.get("slot_failures")
                or not meta.get("completed_utc") or meta.get("batch_wall_seconds") is None):
            raise ValueError("complete, unique planned cases and final queue measurement required")
        if not meta.get("dataset_sha256"): raise ValueError("dataset SHA required")
        datasets.add(meta["dataset_sha256"])
        cohort = str(path.resolve()); label = labels.get(cohort, "")
        cohorts.append(dict(directory=cohort, label=label, metadata_sha256=sha(meta_path), summary_sha256=sha(summary_path),
                            source_commit=meta.get("git_revision"), source_hashes=meta["source_hashes"],
                            final_source_hashes=meta["final_source_hashes"], runtime=meta.get("runtime"),
                            configuration={k: meta.get(k) for k in ("budget", "temperature", "controller_deadline_seconds", "scheduling", "scope", "stop_on_solution", "server_metrics", "code_format", "selection_policy")},
                            mixed_arm_queue_wall_seconds=meta["batch_wall_seconds"]))
        if validity is not None: cohorts[-1]["ledger_verification"] = validity
        for original in summary:
            row = dict(original)
            if row.get("split") != "evaluation" or type(row.get("solved")) is not bool:
                raise ValueError("summary evaluation split and boolean solved required")
            for key in ("calls", "prompt_tokens", "completion_tokens", "wall_seconds"):
                if type(row.get(key)) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0:
                    raise ValueError("finite nonnegative usage/wall required")
            row["original_arm"], row["cohort"] = row["arm"], cohort
            row["arm"] = label + "/" + row["arm"] if label else row["arm"]
            key = row["task_id"], row["arm"], row["seed"]
            if key in seen: raise ValueError("duplicate task/arm/seed across cohorts; explicitly label distinct protocol variants")
            seen.add(key); rows.append(row)
    if len(datasets) != 1: raise ValueError("different datasets cannot be pooled")
    tasks, seeds = {r["task_id"] for r in rows}, {r["seed"] for r in rows}
    if (expected_tasks is not None and len(tasks) != expected_tasks) or len(seeds) != expected_seeds:
        raise ValueError("unexpected distinct task or seed count")
    expected = set(itertools.product(tasks, seeds))
    for arm in {r["arm"] for r in rows}:
        if {(r["task_id"], r["seed"]) for r in rows if r["arm"] == arm} != expected:
            raise ValueError("each arm must cover the same complete task-by-seed grid")
    return rows, cohorts, next(iter(datasets))


def report_for(rows, cohorts, dataset, domain, repetitions=5000, seed=20261115):
    tasks, arms = sorted({r["task_id"] for r in rows}), sorted({r["arm"] for r in rows})
    aggregates, means, curves = [], {}, []
    for arm in arms:
        selected = [r for r in rows if r["arm"] == arm]; n = len(selected)
        means[arm] = [statistics.mean(r["solved"] for r in selected if r["task_id"] == task) for task in tasks]
        low, high = cluster_ci(means[arm], repetitions, seed)
        proofs = [r["time_to_verified_solution_seconds"] for r in selected if r["solved"]
                  and type(r.get("time_to_verified_solution_seconds")) in (int, float)
                  and math.isfinite(r["time_to_verified_solution_seconds"]) and r["time_to_verified_solution_seconds"] >= 0]
        known = [r for r in selected if known_server(r)]
        item = dict(arm=arm, tasks=len(tasks), cases=n, solved=sum(r["solved"] for r in selected),
                    accuracy=statistics.mean(means[arm]), cluster95_low=low, cluster95_high=high,
                    median_occupied_case_wall_seconds=statistics.median(r["wall_seconds"] for r in selected),
                    p95_occupied_case_wall_seconds=quantile([r["wall_seconds"] for r in selected], .95),
                    solved_only_first_proof_n=len(proofs), solved_only_median_first_proof_seconds=statistics.median(proofs) if proofs else None,
                    solved_only_p95_first_proof_seconds=quantile(proofs, .95), missing_solved_proof_times=sum(r["solved"] for r in selected)-len(proofs))
        for key in ("calls", "prompt_tokens", "completion_tokens", "unfinished_calls", "length_finishes", "budget_denials", "missing_prompt_usage", "missing_completion_usage"):
            item[key] = sum(r.get(key, 0) or 0 for r in selected)
        item.update(client_cost_is_lower_bound=any(r.get("deadline") or r.get("unfinished_calls") or r.get("missing_prompt_usage") or r.get("missing_completion_usage") for r in selected),
                    deadline_cases=sum(bool(r.get("deadline")) for r in selected),
                    infrastructure_failures=sum(r.get("infrastructure_failures") or 0 for r in selected),
                    missing_infrastructure_counts=sum(r.get("infrastructure_failures") is None for r in selected),
                    controller_error_cases=sum(bool(r.get("controller_error")) for r in selected),
                    unexpected_process_error_cases=sum(r.get("returncode") not in (None, 0) and not r.get("controller_stop") for r in selected),
                    server_cost_known_cases=len(known), server_cost_unknown_cases=n-len(known),
                    server_counter_floor_failures=sum(r.get("server_cost_known") is True and not known_server(r) for r in selected),
                    server_prompt_tokens_known=sum(r["server_prompt_tokens"] for r in known) if known else None,
                    server_completion_tokens_known=sum(r["server_completion_tokens"] for r in known) if known else None,
                    source_variants=sorted({r["cohort"] for r in selected}))
        if domain == "coding":
            item.update(feedback_pass_cases=sum(r.get("feedback_final_status") == "passed" for r in selected),
                        final_holdout_pass_cases=sum(r.get("holdout_status") == "passed" for r in selected))
        aggregates.append(item)
        for seconds in TIMES:
            curves.append(dict(arm=arm, seconds=seconds, solved_by_time=sum(t <= seconds for t in proofs),
                               cases=n, fraction=sum(t <= seconds for t in proofs)/n,
                               missing_solved_proof_times=item["missing_solved_proof_times"]))
    lookup = {(r["task_id"], r["seed"], r["arm"]): r for r in rows}
    paired_cases = [dict(task_id=task, seed=seed, **{arm: lookup[task, seed, arm]["solved"] for arm in arms})
                    for task, seed in sorted({(r["task_id"], r["seed"]) for r in rows})]
    paired = []
    for a, b in itertools.combinations(arms, 2):
        differences = [x-y for x, y in zip(means[a], means[b])]
        low, high = cluster_ci(differences, repetitions, seed)
        paired.append(dict(arm_a=a, arm_b=b, direction="a_minus_b", tasks=len(tasks),
                           matched_task_seed_pairs=sum(r["arm"] == a for r in rows),
                           accuracy_delta=statistics.mean(differences), cluster95_low=low, cluster95_high=high))
    return dict(schema_version=1, domain=domain, split="evaluation", dataset_sha256=dataset, tasks=len(tasks),
                seeds=sorted({r["seed"] for r in rows}), source_cohorts=cohorts,
                script_sha256=sha(Path(__file__)), bootstrap=dict(unit="task cluster, all seeds retained", repetitions=repetitions, seed=seed, interval="percentile 95%"),
                scope="Fixed synthetic task distribution; repeated seeds are not independent tasks; no winner or fleet-throughput inference.",
                notes=["Accuracy is the equally weighted mean of per-task seed success rates.",
                       "Paired deltas match task/seed and use task-cluster bootstrap; trajectories need not be identical.",
                       "Pairwise intervals are pointwise, unadjusted for multiple comparisons; no automatic winner labels.",
                       "Known server totals are subtotals over known cases only; unknowns remain null, never zero.",
                       "Client tokens with unfinished/missing usage or deadlines are lower bounds, not GPU-equivalent cost.",
                       "Time-success denominators include every case; missing proof timestamps make curves lower bounds.",
                       "Occupied case wall includes controller/metrics/drain overhead; first-proof latency is solved-only.",
                       "Mixed-arm queue wall is recorded separately per cohort, never per-arm fleet throughput."],
                arms=aggregates, paired_cases=paired_cases, paired_deltas=paired, success_by_time=curves)


def csv_out(path, rows):
    with path.open("x", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=list(rows[0])); writer.writeheader()
        writer.writerows({k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in row.items()} for row in rows)


def plots(report, output):
    try: import matplotlib
    except ImportError as exc: raise SystemExit("--plot requires the optional requirements-plot.txt environment") from exc
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"svg.fonttype": "none", "axes.spines.top": False, "axes.spines.right": False})
    title = "Evaluation " + report["domain"] + " — fixed task scope"
    def save(fig, name):
        fig.text(.02, .01, "Task-cluster bootstrap; all seeds retained. Client-cost * = lower bound. No fleet-throughput inference.", fontsize=8)
        fig.tight_layout(rect=(0, .05, 1, 1))
        for ext in ("svg", "png"): fig.savefig(output / (name + "." + ext), dpi=200)
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, max(4, len(report["arms"])*.4)))
    for i, row in enumerate(report["arms"]):
        ax.errorbar(row["accuracy"]*100, i, xerr=[[100*(row["accuracy"]-row["cluster95_low"])], [100*(row["cluster95_high"]-row["accuracy"])]], fmt="o", color=COLORS[i%len(COLORS)], capsize=3)
    ax.set(yticks=range(len(report["arms"])), yticklabels=[r["arm"] for r in report["arms"]], xlabel="Task/seed accuracy (%) with task-cluster 95% CI", title=title, xlim=(-2,102)); ax.invert_yaxis()
    save(fig, "accuracy-cluster95")
    fig, ax = plt.subplots(figsize=(12,6))
    for i, row in enumerate(report["arms"]):
        points = [p for p in report["success_by_time"] if p["arm"] == row["arm"]]
        ax.plot([p["seconds"] for p in points], [100*p["fraction"] for p in points], marker="o", color=COLORS[i%len(COLORS)], label=row["arm"])
    ax.set(xlabel="Seconds to first verified proof", ylabel="Solved by time / all cases (%)", ylim=(-2,102), title=title); ax.legend(bbox_to_anchor=(1.02,1), loc="upper left", fontsize=8)
    save(fig, "success-by-time")
    fig, ax = plt.subplots(figsize=(12,6))
    for i, row in enumerate(report["arms"]):
        ax.scatter(row["completion_tokens"]/row["cases"], row["accuracy"]*100, color=COLORS[i%len(COLORS)], marker=("o","s","^","D","P","X","v")[i%7], label=row["arm"] + (" *" if row["client_cost_is_lower_bound"] else ""))
    ax.set(xlabel="Mean client completion tokens / case (* lower bound)", ylabel="Task/seed accuracy (%)", ylim=(-2,102), title=title); ax.legend(bbox_to_anchor=(1.02,1), loc="upper left", fontsize=8)
    save(fig, "success-vs-client-output-cost")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("benchmarks", nargs="+", type=Path)
    parser.add_argument("--domain", choices=("arithmetic", "coding"), required=True)
    parser.add_argument("--output", type=Path, required=True, help="New derived-output directory")
    parser.add_argument("--cohort-label", action="append", default=[], metavar="DIR=LABEL", help="Separate a supplementary protocol under LABEL/arm")
    parser.add_argument("--ledger", type=Path, help="Require completed, non-excluded entries in this cohort ledger")
    parser.add_argument("--bootstrap", type=int, default=5000)
    parser.add_argument("--bootstrap-seed", type=int, default=20261115)
    parser.add_argument("--expected-tasks", type=int, help="Defaults: arithmetic24, coding18")
    parser.add_argument("--expected-seeds", type=int, default=3)
    parser.add_argument("--plot", action="store_true")
    args = parser.parse_args(argv)
    try:
        labels = {str(Path(k).resolve()): v for k, v in (text.rsplit("=",1) for text in args.cohort_label)}
        if any(not v for v in labels.values()) or not set(labels) <= {str(p.resolve()) for p in args.benchmarks}: raise ValueError("labels must name an input directory and nonempty variant")
        ledger = json.loads(args.ledger.read_bytes()) if args.ledger else None
        if ledger is not None and not isinstance(ledger, list): raise ValueError("ledger must be a list of cohort entries")
        rows, cohorts, dataset = load_cohorts(args.benchmarks, args.domain, labels, args.expected_tasks or (24 if args.domain == "arithmetic" else 18), args.expected_seeds, ledger)
        report = report_for(rows, cohorts, dataset, args.domain, args.bootstrap, args.bootstrap_seed)
        report["ledger_source"] = dict(path=str(args.ledger.resolve()), sha256=sha(args.ledger)) if args.ledger else None
    except (ValueError, KeyError, TypeError) as exc: parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "analysis.json").write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    for name, key in (("summary", "arms"), ("paired-cases", "paired_cases"), ("paired-deltas", "paired_deltas"), ("success-by-time", "success_by_time")):
        if report[key]: csv_out(args.output / (name+".csv"), report[key])
    if args.plot: plots(report, args.output)
    print(f"{args.domain} evaluation: {len(rows)} cases, {report['tasks']} task clusters; outputs {args.output}")


if __name__ == "__main__": main()
