#!/usr/bin/env python3
"""Finite task/arm pilot: dry-run by default; --run sends requests via harness.py."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
ARMS = {
    "direct_off": ("direct", 1, False), "direct_thinking": ("direct", 1, True),
    "solo_steps_off": ("independent", 1, False), "solo_steps_thinking": ("independent", 1, True),
    "independent8": ("independent", 8, False),
    "independent_rounds8": ("independent_rounds", 8, False),
    "democracy8": ("democracy", 8, False), "shared8": ("shared", 8, False),
}
FIELDS = ["task_id", "split", "arm", "seed", "endpoint", "solved", "observed_solved",
          "successful_paths", "calls", "completed_calls", "unfinished_calls", "prompt_tokens",
          "completion_tokens", "charged_completion_tokens", "missing_prompt_usage",
          "missing_completion_usage", "wall_seconds", "status", "stop_reason", "deadline",
          "budget_denials", "infrastructure_failures", "response_errors", "length_finishes",
          "returncode", "controller_error", "malformed_lines", "events"]


def hashes():
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ("run_benchmark.py", "harness.py", "direct_solver.py",
                         "shared_search.py", "runtime.json", "make_tasks.py")}


def metrics(records, deadline=False):
    requests = [r for r in records if r.get("type") == "request_end"]
    ends = [r for r in records if r.get("type") == "run_end"]
    puzzles = [r for r in records if r.get("type") == "puzzle_end"]
    end = ends[-1] if ends else {}
    observed = bool(end.get("solved") or any(p.get("solved") for p in puzzles))
    outcomes = [o for p in puzzles for o in p.get("outcomes", [])]
    paths = sum(bool(o.get("solved")) for o in outcomes) if outcomes else sum(
        bool(r.get("solved")) for r in records if r.get("type") == "reward" and r.get("agent_id") is not None)
    calls = sum(r.get("type") == "request_start" for r in records)
    return dict(solved=observed and not deadline, observed_solved=observed, successful_paths=paths,
                calls=calls, completed_calls=len(requests), unfinished_calls=calls - len(requests),
                prompt_tokens=sum(r.get("usage", {}).get("prompt_tokens", 0) for r in requests),
                completion_tokens=sum(r.get("usage", {}).get("completion_tokens", 0) for r in requests),
                charged_completion_tokens=sum(r.get("completion_tokens_charged", 0) for r in requests),
                missing_prompt_usage=sum("prompt_tokens" not in r.get("usage", {}) for r in requests),
                missing_completion_usage=sum("completion_tokens" not in r.get("usage", {}) for r in requests),
                status="deadline" if deadline else end.get("status", "missing_run_end"),
                stop_reason="controller_180_second_deadline" if deadline else next(
                    (r.get("reason") for r in reversed(records) if r.get("type") == "halt"),
                    "solved" if observed else end.get("error", end.get("status", "missing_run_end"))),
                deadline=deadline, budget_denials=sum(r.get("type") == "budget_exhausted" for r in records),
                infrastructure_failures=end.get("infrastructure_failures"),
                response_errors=sum(bool(r.get("error")) for r in requests),
                length_finishes=sum(r.get("finish_reason") == "length" for r in requests))


def execute(case):
    start = time.monotonic()
    deadline, error, returncode = False, None, None
    with Path(case["stdout"]).open("x") as stdout, Path(case["stderr"]).open("x") as stderr:
        try:
            process = subprocess.Popen(case["command"], cwd=HERE, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
            try:
                returncode = process.wait(timeout=180)
            except subprocess.TimeoutExpired:
                deadline = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                returncode = process.wait()
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
    records, malformed = [], 0
    trace = Path(case["events"])
    if trace.exists():
        for line in trace.read_text(errors="replace").splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1
    row = {k: case[k] for k in ("task_id", "split", "arm", "seed", "endpoint", "events")}
    row.update(metrics(records, deadline), wall_seconds=round(time.monotonic() - start, 6),
               returncode=returncode, controller_error=error, malformed_lines=malformed)
    if not deadline and (error or returncode != 0):
        row.update(solved=False, status="controller_error" if error else "process_error")
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Public tasks.json; never reference-witnesses.json")
    parser.add_argument("--split", choices=("development", "evaluation"), required=True)
    parser.add_argument("--arms", action="append", help="Repeat or comma-separate arm names; default all eight")
    parser.add_argument("--endpoint", action="append", help="Repeat; default four local /v1 tunnels")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, help="New output directory; never overwrite")
    parser.add_argument("--run", action="store_true", help="Execute; otherwise print plan without writing files")
    args = parser.parse_args(argv)
    raw = args.dataset.read_bytes()
    dataset = json.loads(raw)
    if dataset.get("protocol") != "synthetic-countdown-v1" or "witnesses" in dataset:
        parser.error("expected public synthetic-countdown-v1 tasks.json, without witnesses")
    tasks = [t for t in dataset["tasks"] if t["split"] == args.split]
    if len(dataset["tasks"]) != 32 or any(sum(t["split"] == split for t in dataset["tasks"]) != count
                                         for split, count in (("development", 8), ("evaluation", 24))):
        parser.error("dataset must contain 8 development and 24 evaluation tasks")
    if len({t["id"] for t in tasks}) != len(tasks) or any(
            not re.fullmatch(r"[A-Za-z0-9_-]+", t["id"]) or len(t["numbers"]) not in (4, 6)
            or any(type(n) is not int or n <= 0 for n in t["numbers"]) or type(t["target"]) is not int for t in tasks):
        parser.error("invalid public task schema")
    arms = [a.strip() for part in args.arms for a in part.split(",")] if args.arms else list(ARMS)
    if not arms or len(set(arms)) != len(arms) or any(a not in ARMS for a in arms):
        parser.error("arms must be unique names from " + ", ".join(ARMS))
    endpoints = args.endpoint or [f"http://127.0.0.1:{p}/v1" for p in range(18081, 18085)]
    if not 1 <= args.jobs <= min(4, len(endpoints)) or len(set(endpoints)) != len(endpoints):
        parser.error("jobs must be 1–4, with one distinct endpoint per job slot")
    started_utc = datetime.now(timezone.utc).isoformat()
    directory = (args.output or HERE / "runs" / ("benchmark-" + args.split + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))).resolve()
    if args.run and directory.exists():
        parser.error("output directory already exists")
    cases = []
    for index, task in enumerate(tasks):
        order = arms[index % len(arms):] + arms[:index % len(arms)]
        for arm in order:
            method, agents, thinking = ARMS[arm]
            name = f"{task['id']}-{arm}-s{args.seed}"
            trace = directory / (name + ".jsonl")
            slot = index % args.jobs
            command = [sys.executable, str(HERE / "harness.py"), "--method", method,
                       "--puzzle", ",".join(map(str, task["numbers"])) + ":" + str(task["target"]),
                       "--model", "nemotron-lightning", "--agents", str(agents),
                       "--per-endpoint-concurrency", "25", "--rounds", "5", "--max-tokens", "4096" if thinking else "192",
                       "--max-calls", "128", "--max-completion-tokens", "32768", "--timeout", "90",
                       "--seed", str(args.seed), "--events", str(trace), "--endpoint", endpoints[slot]]
            if thinking:
                command.append("--thinking")
            if arm == "democracy8":
                command.append("--accept-verified-solution")
            cases.append(dict(task_id=task["id"], split=args.split, arm=arm, seed=args.seed, slot=slot,
                              endpoint=endpoints[slot], events=str(trace), command=command,
                              stdout=str(directory / (name + ".stdout.log")), stderr=str(directory / (name + ".stderr.log"))))
    metadata = dict(schema_version=1, mode="run" if args.run else "dry_run", started_utc=started_utc,
                    dataset=str(args.dataset.resolve()), dataset_sha256=hashlib.sha256(raw).hexdigest(),
                    dataset_protocol=dataset["protocol"], split=args.split, arms=arms, seed=args.seed,
                    jobs=args.jobs, source_hashes=hashes(), runtime=json.loads((HERE / "runtime.json").read_text()),
                    runtime_evidence="Configuration snapshot, not a live serving probe", temperature=0.8,
                    scheduling="Fixed endpoint per persistent slot; each task's rotated arms run sequentially on its assigned slot",
                    scope="Latency/quality calibration with four job slots; NOT a saturated fleet-throughput measurement",
                    budget="128 calls/32768 completion tokens per case; prompt usage measured, no input-token cap",
                    partial_trace_accounting="Deadline runs are unsolved; observed usage excludes any unfinished server requests",
                    controller_deadline_seconds=180, output=str(directory), cases=cases)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True)
    metadata["git_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
    if not args.run:
        print(json.dumps(metadata, indent=2))
        return 0
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    results, lock = [], threading.Lock()
    def worker(slot):
        for case in (c for c in cases if c["slot"] == slot):
            row = execute(case)
            with lock:
                results.append(row)
                (directory / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
                with (directory / "summary.csv").open("w", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows(results)
                print(f"{len(results)}/{len(cases)} {case['task_id']} {case['arm']} {row['status']} solved={int(row['solved'])} calls={row['calls']} wall={row['wall_seconds']:.2f}s", flush=True)
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(worker, range(args.jobs)))
    metadata.update(batch_wall_seconds=time.monotonic() - start, completed_cases=len(results),
                    completed_utc=datetime.now(timezone.utc).isoformat(), final_source_hashes=hashes())
    metadata["source_changed_during_run"] = metadata["source_hashes"] != metadata["final_source_hashes"]
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return int(any(r["controller_error"] or (r["returncode"] != 0 and not r["deadline"]) for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
