#!/usr/bin/env python3
"""Offline finite-batch throughput summaries; admission selection uses development only."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import random
import statistics


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values) - 1) * fraction
    lower = int(position)
    return values[lower] + (values[min(lower + 1, len(values) - 1)] - values[lower]) * (position - lower)


def success_ci(clusters, repetitions=2000):
    """Resample whole tasks, retaining all their seeds; not a queue-rate interval."""
    means = [sum(values) / len(values) for values in clusters.values()]
    if len(means) < 2 or repetitions < 1:
        return None
    rng = random.Random(20261115)
    samples = [statistics.mean(rng.choices(means, k=len(means))) for _ in range(repetitions)]
    return [quantile(samples, .025), quantile(samples, .975)]


def transport_error(event):
    if event.get("type") != "request_end" or not event.get("error"):
        return False
    message = str(event["error"])
    return message.startswith(("HTTPError:", "URLError:", "TimeoutError:", "ConnectionError:", "OSError:",
                               "ConnectionResetError:", "RemoteDisconnected:", "IncompleteRead:", "SSLError:")) or (
        event.get("response") is None and event.get("finish_reason") != "length")


def case_infrastructure_clear(row, directory):
    if row.get("infrastructure_failures") not in (0, None):
        return False
    if row.get("infrastructure_failures") == 0:
        return True
    # Controlled stopping can pre-empt run_end. Inspect available completed calls;
    # unfinished calls/usage stay unknown, rather than becoming zero-cost success.
    if row.get("controller_stop") is not True:
        return False
    trace = directory / Path(row.get("events", "missing-trace")).name
    if not trace.is_file():
        return False
    records = []
    for line in trace.read_text().splitlines():
        try:
            records.append(json.loads(line))
        except ValueError:
            return False
    return bool(records) and not any(transport_error(event) or event.get("infrastructure_error") is True
                                    or event.get("kind") in ("infrastructure", "client_infrastructure") for event in records)


def load_cohort(directory, repetitions=2000):
    directory = Path(directory).resolve()
    metadata, cohort, rows = [json.loads((directory / filename).read_text())
                              for filename in ("metadata.json", "cohort.json", "summary.json")]
    require(metadata.get("mode") == "run" and metadata.get("status") == "complete", "cohort is not a completed run")
    require(metadata.get("incomplete") is False and metadata.get("source_changed_during_run") is False,
            "incomplete or source-changed cohort")
    require(bool(metadata.get("source_hashes")) and metadata["source_hashes"] == metadata.get("final_source_hashes"),
            "source hashes missing or changed")
    require(cohort.get("fully_drained") is True and cohort.get("throughput_scope_valid") is True,
            "queue scope invalid or endpoint not drained")
    require(cohort.get("controller_errors") == 0 and cohort.get("known_infrastructure_failures") == 0,
            "controller or infrastructure errors invalidate the cohort")
    require(metadata.get("split") in ("development", "evaluation"), "unknown data split")
    for key in ("arm", "split", "seeds", "unique_tasks", "attempts", "completed_cases"):
        require(metadata.get(key) == cohort.get(key), "metadata/cohort mismatch: " + key)
    count = metadata.get("attempts")
    require(type(count) is int and count > 0 and len(rows) == count == metadata.get("completed_cases")
            and len(metadata.get("cases", [])) == count, "attempts are incomplete")
    wall = cohort.get("batch_wall_seconds")
    require(type(wall) in (int, float) and math.isfinite(wall) and wall > 0
            and wall == metadata.get("batch_wall_seconds"), "invalid actual batch wall")
    seeds = metadata.get("seeds", [])
    require(bool(seeds) and len(seeds) == len(set(seeds)), "invalid seed list")
    identities = [(row.get("task_id"), row.get("seed")) for row in rows]
    tasks = {task for task, _ in identities}
    require(None not in tasks and len(tasks) == metadata.get("unique_tasks") and len(set(identities)) == count
            and set(identities) == {(task, seed) for task in tasks for seed in seeds}, "task/seed matrix mismatch")
    require(set(identities) == {(case.get("task_id"), case.get("seed")) for case in metadata["cases"]},
            "scheduled and observed task/seed identities differ")
    require(all(row.get("arm") == metadata["arm"] and row.get("split") == metadata["split"]
                and type(row.get("solved")) is bool and not row.get("controller_error")
                and case_infrastructure_clear(row, directory)
                and (row.get("returncode") == 0 or row.get("controller_stop") is True) for row in rows),
            "invalid case outcome or infrastructure failure")
    solved = sum(row["solved"] for row in rows)
    require(solved == cohort.get("verified_successes"), "verified-success count mismatch")
    require(math.isclose(cohort.get("successes_per_minute", -1), solved * 60 / wall, rel_tol=1e-9, abs_tol=1e-9),
            "rate does not use actual batch wall")
    nodes = metadata.get("nodes", [])
    require(len(nodes) == 4 and len({node.get("endpoint") for node in nodes}) == 4
            and all(node.get("idle_after") is True for node in nodes), "four-node drain evidence missing")
    known = cohort.get("server_cost_known") is True
    costs = {}
    for key in ("prompt_tokens", "completion_tokens"):
        field = "server_" + key
        covered = all(node.get("server_cost_known") is True and type(node.get(field)) in (int, float)
                      and math.isfinite(node[field]) and node[field] >= node.get("completed_client_floor", {}).get(key, 0)
                      for node in nodes)
        if known:
            require(covered and cohort.get(field) == sum(node[field] for node in nodes), "global server cost lacks complete coverage")
        costs[field] = cohort[field] if known else None
    clusters = {task: [int(row["solved"]) for row in rows if row["task_id"] == task] for task in sorted(tasks)}
    result = dict(cohort=directory.name, path=str(directory), split=metadata["split"], arm=metadata["arm"],
                  jobs_per_node=metadata["jobs_per_node"], source_revision=metadata.get("git_revision"),
                  dataset_sha256=metadata.get("dataset_sha256"), source_hashes=metadata["source_hashes"],
                  attempts=count, unique_tasks=len(tasks), seeds=seeds, verified_successes=solved,
                  infrastructure_count_known_cases=sum(row.get("infrastructure_failures") is not None for row in rows),
                  infrastructure_count_unknown_cases=sum(row.get("infrastructure_failures") is None for row in rows),
                  unfinished_client_calls=sum(row.get("unfinished_calls", 0) for row in rows),
                  successes_per_minute=solved * 60 / wall, batch_wall_seconds=wall,
                  server_cost_known=known, **costs, task_cluster_success_fraction_ci95=success_ci(clusters, repetitions),
                  rate_uncertainty="No rate CI: one finite queue wall observation; task bootstrap covers success fraction only.",
                  input_sha256={name: sha(directory / name) for name in ("metadata.json", "cohort.json", "summary.json")})
    for field in ("queue_wait_seconds", "service_wall_seconds", "total_latency_seconds", "end_to_end_first_proof_seconds"):
        values = [row[field] for row in rows if type(row.get(field)) in (int, float) and math.isfinite(row[field])]
        result[field] = dict(observed=len(values), median=statistics.median(values) if values else None, p95=quantile(values, .95))
    return result


def select_development(rows, arms=None, jobs=(1, 2, 4, 8)):
    require(bool(rows) and all(row["split"] == "development" for row in rows), "selection accepts development inputs ONLY")
    arms = list(arms) if arms is not None else sorted({row["arm"] for row in rows})
    require(len(arms) == len(set(arms)) and set(arms) == {row["arm"] for row in rows}, "selection arm set differs from frozen plan")
    require(len({row["dataset_sha256"] for row in rows}) == 1 and len({tuple(row["seeds"]) for row in rows}) == 1,
            "development cohorts use different data or seeds")
    selections = []
    for arm in arms:
        candidates = [row for row in rows if row["arm"] == arm]
        require(len(candidates) == len(jobs) and {row["jobs_per_node"] for row in candidates} == set(jobs), "missing or duplicate development grid point: " + arm)
        maximum = max(row["successes_per_minute"] for row in candidates)
        winner = min((row for row in candidates if row["successes_per_minute"] >= maximum * .99), key=lambda row: row["jobs_per_node"])
        selections.append(dict(arm=arm, jobs_per_node=winner["jobs_per_node"], development_rate=winner["successes_per_minute"],
                               development_max_rate=maximum, chosen_cohort=winner["cohort"],
                               inputs=[dict(cohort=row["cohort"], input_sha256=row["input_sha256"]) for row in candidates]))
    return dict(selection_split="development", rule="Maximum verified/min; within 1% of maximum choose smaller jobs/node",
                dataset_sha256=rows[0]["dataset_sha256"], selections=selections)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cohorts", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New output directory")
    parser.add_argument("--select-development", action="store_true")
    parser.add_argument("--arms", help="Required complete arm set for selection, comma-separated")
    parser.add_argument("--bootstrap", type=int, default=2000)
    args = parser.parse_args(argv)
    rows = [load_cohort(path, args.bootstrap) for path in args.cohorts]
    require(len({row["path"] for row in rows}) == len(rows), "duplicate input cohort")
    selection = select_development(rows, args.arms.split(",") if args.arms else None) if args.select_development else None
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "summary.json").write_text(json.dumps(dict(scope="Finite four-node queue batches including final drain; repeated seeds clustered by task", cohorts=rows), indent=2) + "\n")
    table = []
    for row in rows:
        flat = {key: row[key] for key in ("cohort", "split", "arm", "jobs_per_node", "unique_tasks", "attempts", "verified_successes", "successes_per_minute", "batch_wall_seconds", "server_cost_known", "server_prompt_tokens", "server_completion_tokens")}
        for field in ("queue_wait_seconds", "service_wall_seconds", "total_latency_seconds", "end_to_end_first_proof_seconds"):
            for metric in ("median", "p95"):
                flat[field + "_" + metric] = row[field][metric]
        table.append(flat)
    with (args.output / "summary.csv").open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(table[0])); writer.writeheader(); writer.writerows(table)
    if selection:
        (args.output / "selection.json").write_text(json.dumps(selection, indent=2) + "\n")
    print(json.dumps(dict(output=str(args.output), cohorts=len(rows), development_selection=selection is not None)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
