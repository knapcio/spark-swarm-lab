#!/usr/bin/env python3
"""Paired coding-policy pilot; default dry-run. --run uses existing bounded executor."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from run_benchmark import execute, FIELDS, read_trace
from sandbox_code import RUNNER

HERE = Path(__file__).resolve().parent
ARMS = {"direct_off": ("direct", 1, 1, False), "solo_iterative": ("iterative", 1, 3, False),
        "direct_thinking": ("direct", 1, 1, True),
        **{f"{method}{n}": (method, n, 3, False) for n in (8, 32, 100)
           for method in ("independent", "shared", "democracy")}}
EXTRA_FIELDS = ["grader_host", "method", "agents", "rounds", "thinking", "code_format", "feedback_final_status",
                "feedback_final_passed", "feedback_final_total", "holdout_status", "holdout_passed",
                "holdout_total", "feedback_eval_count", "holdout_eval_count", "grader_eval_count",
                "grader_errors", "grader_infrastructure_errors", "selection_basis"]
SOURCE_FILES = ("run_coding_benchmark.py", "run_benchmark.py", "coding_harness.py", "sandbox_code.py",
                "harness.py", "coding_tasks.py", "runtime.json")


def source_hashes():
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in SOURCE_FILES}


def coding_metrics(case, row):
    records, _ = read_trace(Path(case["events"]))
    evaluations = [r for r in records if r.get("type") == "evaluation_end"]
    selected = next((r for r in reversed(records) if r.get("type") == "candidate_selected"), {})
    final = next((r for r in reversed(records) if r.get("type") in ("selection_complete", "run_end") and "holdout" in r), {})
    candidate = final.get("candidate_id", selected.get("candidate_id"))
    report = lambda phase: next((r.get("report", {}) for r in reversed(evaluations)
                                if r.get("phase") == phase and r.get("candidate_id") == candidate), {})
    feedback = final.get("feedback") or report("feedback")
    holdout = final.get("holdout") or report("holdout")
    row.update({k: case[k] for k in ("grader_host", "method", "agents", "rounds", "thinking", "code_format")})
    row.update(feedback_final_status=feedback.get("status"), feedback_final_passed=feedback.get("passed"),
               feedback_final_total=feedback.get("total"), holdout_status=holdout.get("status"),
               holdout_passed=holdout.get("passed"), holdout_total=holdout.get("total"),
               feedback_eval_count=sum(r.get("phase") == "feedback" for r in evaluations),
               holdout_eval_count=sum(r.get("phase") == "holdout" for r in evaluations),
               grader_eval_count=len(evaluations),
               grader_errors=sum(bool(r.get("infrastructure_error")) or r.get("report", {}).get("status") in ("error", "timeout") for r in evaluations),
               grader_infrastructure_errors=sum(bool(r.get("infrastructure_error")) for r in evaluations),
               selection_basis=final.get("selection_basis", selected.get("selection_basis")))
    if row.get("infrastructure_failures") is None and "infrastructure_failures" in final:
        row["infrastructure_failures"] = final["infrastructure_failures"]
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Public coding tasks.json")
    parser.add_argument("--tests", type=Path, required=True, help="Private feedback/holdout JSON; never sent in full to model")
    parser.add_argument("--split", choices=("development", "evaluation", "dev", "eval"), required=True)
    parser.add_argument("--arms", action="append", help="Repeat or comma-separate; default direct_off,solo_iterative,independent8,shared8,democracy8")
    parser.add_argument("--endpoint", action="append")
    parser.add_argument("--host", action="append", help="Repeat grader SSH hosts, paired by endpoint position")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--code-format", choices=("json", "python"), default="json")
    parser.add_argument("--output", type=Path, help="New directory; refuses overwrite")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    split = {"dev": "development", "eval": "evaluation"}.get(args.split, args.split)
    public_raw, private_raw = args.dataset.read_bytes(), args.tests.read_bytes()
    public, private = json.loads(public_raw), json.loads(private_raw)
    if public.get("protocol") != "original-python-functions-v1" or private.get("protocol") != public.get("protocol") or "references" in public:
        parser.error("expected matching public coding corpus and separate private reference JSON")
    tasks = [t for t in public.get("tasks", []) if t.get("split") == split]
    if len(public["tasks"]) != 24 or any(sum(t.get("split") == s for t in public["tasks"]) != n
                                         for s, n in (("development", 6), ("evaluation", 18))):
        parser.error("corpus requires 6 development and 18 evaluation tasks")
    if len({t["id"] for t in public["tasks"]}) != 24 or any(not re.fullmatch(r"[A-Za-z0-9_-]+", t["id"])
          or not t.get("function_name", "").isidentifier() or len(t.get("examples", [])) != 2 for t in public["tasks"]):
        parser.error("invalid public task schema")
    for task in tasks:
        reference = private.get("references", {}).get(task["id"], {})
        if any(len(reference.get(phase, [])) < 3 for phase in ("feedback_tests", "holdout_tests")):
            parser.error("every selected task needs separate feedback/holdout partitions with >=3 cases")
    arms = [a.strip() for part in args.arms for a in part.split(",")] if args.arms else [
        "direct_off", "solo_iterative", "independent8", "shared8", "democracy8"]
    if not arms or len(set(arms)) != len(arms) or any(a not in ARMS for a in arms):
        parser.error("unique arms required from: " + ", ".join(ARMS))
    endpoints = args.endpoint or [f"http://127.0.0.1:{p}/v1" for p in range(18081, 18085)]
    hosts = args.host or [f"Spark_0{i}" for i in range(1, 5)]
    if len(endpoints) != len(hosts) or len(set(endpoints)) != len(endpoints) or len(set(hosts)) != len(hosts) or not 1 <= args.jobs <= min(4, len(endpoints)):
        parser.error("use 1–4 jobs and distinct one-to-one endpoint/host pairs")
    for endpoint, host in zip(endpoints, hosts):
        url = urlsplit(endpoint)
        if url.scheme not in ("http", "https") or not url.netloc or url.username or url.password or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*(?:@[A-Za-z0-9][A-Za-z0-9_.-]*)?", host):
            parser.error("invalid credential-free HTTP endpoint or SSH host")
    directory = (args.output or HERE / "runs" / ("coding-" + split + "-" + datetime.now().strftime("%Y%m%d-%H%M%S-%f"))).resolve()
    if directory.exists():
        parser.error("output directory already exists")
    cases = []
    for index, task in enumerate(tasks):
        order = arms[index % len(arms):] + arms[:index % len(arms)]
        slot = index % args.jobs
        for arm in order:
            method, agents, rounds, thinking = ARMS[arm]
            name = f"{task['id']}-{arm}-s{args.seed}"
            trace = directory / (name + ".jsonl")
            command = [sys.executable, str(HERE / "coding_harness.py"), "--tasks", str(args.dataset.resolve()),
                       "--tests", str(args.tests.resolve()), "--task-id", task["id"], "--method", method,
                       "--agents", str(agents), "--rounds", str(rounds), "--endpoint", endpoints[slot],
                       "--host", hosts[slot], "--events", str(trace), "--max-tokens", "8192" if thinking else "1024",
                       "--max-calls", "1024", "--maxcompletion", "131072", "--seed", str(args.seed),
                       "--thinking", "on" if thinking else "off", "--code-format", args.code_format]
            cases.append(dict(task_id=task["id"], split=split, arm=arm, seed=args.seed, slot=slot,
                              endpoint=endpoints[slot], grader_host=hosts[slot], method=method, agents=agents,
                              rounds=rounds, thinking=thinking, code_format=args.code_format, events=str(trace), command=command,
                              stop_on_solution=True, server_metrics=True,
                              stdout=str(directory / (name + ".stdout.log")), stderr=str(directory / (name + ".stderr.log"))))
    metadata = dict(schema_version=1, domain="coding", mode="run" if args.run else "dry_run",
                    started_utc=datetime.now(timezone.utc).isoformat(), split=split, arms=arms, seed=args.seed, code_format=args.code_format,
                    dataset=str(args.dataset.resolve()), dataset_sha256=hashlib.sha256(public_raw).hexdigest(),
                    tests=str(args.tests.resolve()), tests_sha256=hashlib.sha256(private_raw).hexdigest(),
                    dataset_protocol=public["protocol"], jobs=args.jobs,
                    source_hashes=source_hashes(), sandbox_runner_sha256=hashlib.sha256(RUNNER.encode()).hexdigest(),
                    runtime=json.loads((HERE / "runtime.json").read_text()), runtime_evidence="Configuration snapshot, not live verification",
                    budgets=dict(max_calls=1024, max_completion_tokens=131072, off_max_tokens=1024, thinking_max_tokens=8192, http_timeout=180, task_deadline=180),
                    budget_interpretation="Common ceilings, not matched realized compute; policies differ in requests, prompt lengths and grading work",
                    selection="Freeze on first feedback pass or feedback-only final ranking; holdout graded once after selection, never repaired or fed to model",
                    scheduling="Persistent slot pairs one model endpoint and CPU-grader host. Rotate task arms; all arms of a task use its same pair.",
                    scope="Mixed four-slot batch wall is not arm-specific saturated throughput; report actual client/server cost and grading errors",
                    stop_on_solution=True, server_metrics=True, output=str(directory), cases=cases)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True)
    metadata["git_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
    if not args.run:
        print(json.dumps(metadata, indent=2))
        return 0
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    results, lock, failures = [], threading.Lock(), []
    def worker(slot):
        for case in (c for c in cases if c["slot"] == slot):
            row = coding_metrics(case, execute(case, 180))
            with lock:
                results.append(row)
                (directory / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
                with (directory / "summary.csv").open("w", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=FIELDS + EXTRA_FIELDS)
                    writer.writeheader()
                    writer.writerows({k: json.dumps(v) if isinstance(v, dict) else v for k, v in item.items()} for item in results)
                print(f"{len(results)}/{len(cases)} {case['task_id']} {case['arm']} {row['status']} holdout={row['holdout_passed']}/{row['holdout_total']} calls={row['calls']} wall={row['wall_seconds']:.2f}s", flush=True)
                if row["controller_stop"] and row["server_idle_after"] is not True:
                    failures.append(dict(slot=slot, endpoint=case["endpoint"], host=case["grader_host"], reason="Idle not confirmed after cancellation"))
                    break
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(worker, range(args.jobs)))
    metadata.update(batch_wall_seconds=time.monotonic() - started, completed_cases=len(results),
                    completed_utc=datetime.now(timezone.utc).isoformat(), final_source_hashes=source_hashes(),
                    slot_failures=failures, incomplete=len(results) != len(cases),
                    missing_cases=[c["events"] for c in cases if c["events"] not in {r["events"] for r in results}])
    metadata["source_changed_during_run"] = metadata["source_hashes"] != metadata["final_source_hashes"]
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return int(bool(failures) or any(r["controller_error"] or (r["returncode"] != 0 and not r["controller_stop"]) for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
