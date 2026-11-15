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
import urllib.request
from urllib.parse import urlsplit

HERE = Path(__file__).resolve().parent
ARMS = {
    "direct_off": ("direct", 1, False), "direct_thinking": ("direct", 1, True),
    "solo_steps_off": ("independent", 1, False), "solo_steps_thinking": ("independent", 1, True),
    "direct_thinking_8k": ("direct", 1, True),
    "solo_steps_thinking_8k": ("independent", 1, True),
    "independent8": ("independent", 8, False),
    "independent_rounds8": ("independent_rounds", 8, False),
    "democracy8": ("democracy", 8, False), "shared8": ("shared", 8, False),
    "ensemble4_thinking_8k": ("ensemble", 4, True),
    "ensemble2_thinking_8k": ("ensemble", 2, True),
    **{f"{arm}{n}": (method, n, False) for n in (32, 100)
       for arm, method in (("independent", "independent"), ("democracy", "democracy"), ("shared", "shared"))},
    **{f"cascade{n}": ("cascade", n, False) for n in (8, 32, 100)},
}
FIELDS = ["task_id", "split", "arm", "seed", "endpoint", "solved", "observed_solved",
          "successful_paths", "calls", "completed_calls", "unfinished_calls", "prompt_tokens",
          "completion_tokens", "charged_completion_tokens", "missing_prompt_usage",
          "missing_completion_usage", "wall_seconds", "status", "stop_reason", "deadline",
          "budget_denials", "infrastructure_failures", "response_errors", "length_finishes",
          "returncode", "controller_error", "malformed_lines", "events", "controller_stop",
          "time_to_verified_solution_seconds", "process_wall_seconds", "server_prompt_tokens",
          "server_completion_tokens", "server_cost_known", "server_cost_reason", "server_idle_after", "drain_seconds",
          "server_metrics_before", "server_metrics_after"]


def hashes():
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
            for name in ("run_benchmark.py", "harness.py", "direct_solver.py",
                         "shared_search.py", "ensemble_solver.py", "runtime.json", "make_tasks.py")}


def read_trace(path):
    rows, malformed = [], 0
    for line in path.read_text(errors="replace").splitlines() if path.exists() else []:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            malformed += 1
    return rows, malformed


def verified(rows):
    return any(r.get("type") in ("reward", "puzzle_end", "run_end") and
               type(r.get("solved")) in (bool, int) and r["solved"] > 0 for r in rows)


def server_metrics(endpoint, timeout=.8):
    keys = {"prompt_tokens_total": "prompt", "generation_tokens_total": "completion",
            "num_requests_running": "running", "num_requests_waiting": "waiting"}
    result = dict(timestamp_utc=datetime.now(timezone.utc).isoformat())
    try:
        url = urlsplit(endpoint)
        with urllib.request.urlopen(f"{url.scheme}://{url.netloc}/metrics", timeout=timeout) as response:
            for line in response.read().decode().splitlines():
                if line.startswith("#") or not line.strip():
                    continue
                name, value = line.split()[:2]
                key = keys.get(name.split("{")[0].removeprefix("vllm:"))
                if key:
                    result[key] = result.get(key, 0) + float(value)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return result


def drain(endpoint):
    start, snapshot, first_idle = time.monotonic(), {}, None
    while time.monotonic() - start < 10:
        snapshot = server_metrics(endpoint, min(.8, max(.01, 10 - (time.monotonic() - start))))
        if not snapshot.get("error") and snapshot.get("running") == snapshot.get("waiting") == 0:
            now = time.monotonic()
            if first_idle is not None and now - first_idle >= .2:
                return snapshot, True, now - start
            first_idle = now if first_idle is None else first_idle
        else:
            first_idle = None
        time.sleep(min(.2, max(0, 10 - (time.monotonic() - start))))
    return snapshot, (False if "running" in snapshot and "waiting" in snapshot else None), time.monotonic() - start


def server_cost(before, after, idle, client):
    reason = "metrics_unavailable"
    if before and after and not before.get("error") and not after.get("error"):
        reason = "endpoint_not_confirmed_idle"
        if idle and before.get("running") == before.get("waiting") == 0:
            reason = "missing_or_reset_counters"
            if all(k in before and k in after and after[k] >= before[k] for k in ("prompt", "completion")):
                delta = {k: after[k] - before[k] for k in ("prompt", "completion")}
                if all(delta[k] >= client[k + "_tokens"] for k in delta):
                    return dict(server_cost_known=True, server_cost_reason="idle_counter_deltas",
                                server_prompt_tokens=int(delta["prompt"]), server_completion_tokens=int(delta["completion"]))
                reason = "server_delta_below_completed_client_usage"
    return dict(server_cost_known=False, server_cost_reason=reason,
                server_prompt_tokens=None, server_completion_tokens=None)


def append_controller_stop(trace, records, row, case):
    assert not row["solved"] or verified(records)
    event = dict(event_id=next((r["event_id"] for r in reversed(records) if "event_id" in r), 0) + 1,
                 timestamp=datetime.now(timezone.utc).isoformat(),
                 run_id=next((r["run_id"] for r in reversed(records) if "run_id" in r), None),
                 method=next((r["method"] for r in reversed(records) if "method" in r), None),
                 type="controller_stop", source="controller", arm=case["arm"])
    event.update({k: row[k] for k in ("status", "solved", "deadline", "unfinished_calls", "server_cost_known",
                  "server_cost_reason", "server_prompt_tokens", "server_completion_tokens", "server_idle_after",
                  "time_to_verified_solution_seconds", "wall_seconds", "returncode")})
    raw = trace.read_bytes() if trace.exists() else b""
    with trace.open("ab") as output:
        output.write((b"\n" if raw and not raw.endswith(b"\n") else b"") + json.dumps(event).encode() + b"\n")


def terminate(process):
    if process.poll() is not None:
        return process.returncode
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    except ProcessLookupError:
        pass
    return process.wait()


def metrics(records, deadline=False, success_early=False):
    requests = [r for r in records if r.get("type") == "request_end"]
    ends = [r for r in records if r.get("type") == "run_end"]
    puzzles = [r for r in records if r.get("type") == "puzzle_end"]
    end = ends[-1] if ends else {}
    observed = verified(records)
    outcomes = [o for p in puzzles for o in p.get("outcomes", [])]
    paths = sum(bool(o.get("solved")) for o in outcomes) if outcomes else sum(
        bool(r.get("solved")) for r in records if r.get("type") == "reward" and r.get("agent_id") is not None)
    calls = sum(r.get("type") == "request_start" for r in records)
    return dict(solved=observed, observed_solved=observed, successful_paths=paths,
                calls=calls, completed_calls=len(requests), unfinished_calls=calls - len(requests),
                prompt_tokens=sum(r.get("usage", {}).get("prompt_tokens", 0) for r in requests),
                completion_tokens=sum(r.get("usage", {}).get("completion_tokens", 0) for r in requests),
                charged_completion_tokens=sum(r.get("completion_tokens_charged", 0) for r in requests),
                missing_prompt_usage=sum("prompt_tokens" not in r.get("usage", {}) for r in requests),
                missing_completion_usage=sum("completion_tokens" not in r.get("usage", {}) for r in requests),
                status="success_early" if success_early else "deadline" if deadline else end.get("status", "missing_run_end"),
                stop_reason="controller_verified_solution" if success_early else "controller_180_second_deadline" if deadline else next(
                    (r.get("reason") for r in reversed(records) if r.get("type") == "halt"),
                    "solved" if observed else end.get("error", end.get("status", "missing_run_end"))),
                deadline=deadline, budget_denials=sum(r.get("type") == "budget_exhausted" for r in records),
                infrastructure_failures=end.get("infrastructure_failures"),
                response_errors=sum(bool(r.get("error")) for r in requests),
                length_finishes=sum(r.get("finish_reason") == "length" for r in requests))


def execute(case, deadline_seconds=180):
    start = time.monotonic()
    deadline, early, error, returncode, proof_time = False, False, None, None, None
    trace = Path(case["events"])
    before = server_metrics(case["endpoint"], timeout=3) if case.get("server_metrics") or case.get("stop_on_solution") else None
    process_start, proof_before_stop = time.monotonic(), False
    with Path(case["stdout"]).open("x") as stdout, Path(case["stderr"]).open("x") as stderr:
        try:
            process = subprocess.Popen(case["command"], cwd=HERE, stdout=stdout, stderr=stderr,
                                       start_new_session=True)
            while True:
                records, _ = read_trace(trace)
                proof_before_stop = verified(records)
                elapsed = time.monotonic() - process_start
                if proof_before_stop and proof_time is None:
                    proof_time = elapsed
                if case.get("stop_on_solution") and proof_before_stop and elapsed < deadline_seconds:
                    early = True
                    returncode = terminate(process)
                    break
                if process.poll() is not None:
                    returncode = process.returncode
                    break
                if elapsed >= deadline_seconds:
                    deadline, returncode = True, terminate(process)
                    break
                time.sleep(.1)
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
    process_wall = time.monotonic() - process_start
    records, malformed = read_trace(trace)
    if proof_time is None and verified(records):
        proof_time = process_wall
    after, idle, drain_time = drain(case["endpoint"]) if before is not None or early or deadline else (None, None, 0)
    row = {k: case[k] for k in ("task_id", "split", "arm", "seed", "endpoint", "events")}
    row.update(metrics(records, deadline, early), wall_seconds=round(time.monotonic() - start, 6),
               returncode=returncode, controller_error=error, malformed_lines=malformed, controller_stop=early or deadline,
               time_to_verified_solution_seconds=proof_time, process_wall_seconds=round(process_wall, 6),
               server_idle_after=idle, drain_seconds=round(drain_time, 6),
               server_metrics_before=before, server_metrics_after=after)
    row.update(server_cost(before, after, idle, row))
    if deadline and not proof_before_stop:
        row["solved"] = False
    if not early and not deadline and (error or returncode != 0):
        row["status"] = "controller_error" if error else "process_error"
    if row["controller_stop"]:
        append_controller_stop(trace, records, row, case)
    return row


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Public tasks.json; never reference-witnesses.json")
    parser.add_argument("--split", choices=("development", "evaluation"), required=True)
    parser.add_argument("--arms", action="append", help="Repeat or comma-separate arm names; default original eight")
    parser.add_argument("--endpoint", action="append", help="Repeat; default four local /v1 tunnels")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--output", type=Path, help="New output directory; never overwrite")
    parser.add_argument("--run", action="store_true", help="Execute; otherwise print plan without writing files")
    parser.add_argument("--stop-on-solution", action="store_true", help="Stop own process group on verifier proof; collect server metrics")
    parser.add_argument("--server-metrics", action="store_true", help="Read endpoint counters before/after each case; no generation requests")
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
    arms = [a.strip() for part in args.arms for a in part.split(",")] if args.arms else [
        "direct_off", "direct_thinking", "solo_steps_off", "solo_steps_thinking", "independent8",
        "independent_rounds8", "democracy8", "shared8"]
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
                       "--per-endpoint-concurrency", "25", "--rounds", "5", "--max-tokens",
                       "8192" if arm.endswith("_8k") else "4096" if thinking else "192",
                       "--max-calls", "1280", "--max-completion-tokens", "32768", "--timeout", "180",
                       "--seed", str(args.seed), "--events", str(trace), "--endpoint", endpoints[slot]]
            if thinking:
                command.append("--thinking")
            if arm.startswith("democracy"):
                command.append("--accept-verified-solution")
            cases.append(dict(task_id=task["id"], split=args.split, arm=arm, seed=args.seed, slot=slot,
                              endpoint=endpoints[slot], events=str(trace), command=command,
                              stop_on_solution=args.stop_on_solution, server_metrics=args.server_metrics,
                              stdout=str(directory / (name + ".stdout.log")), stderr=str(directory / (name + ".stderr.log"))))
    metadata = dict(schema_version=1, mode="run" if args.run else "dry_run", started_utc=started_utc,
                    dataset=str(args.dataset.resolve()), dataset_sha256=hashlib.sha256(raw).hexdigest(),
                    dataset_protocol=dataset["protocol"], split=args.split, arms=arms, seed=args.seed,
                    jobs=args.jobs, source_hashes=hashes(), runtime=json.loads((HERE / "runtime.json").read_text()),
                    runtime_evidence="Configuration snapshot, not a live serving probe", temperature=0.8,
                    scheduling="Fixed endpoint per persistent slot; each task's rotated arms run sequentially on its assigned slot",
                    scope="Latency/quality calibration with four job slots; NOT a saturated fleet-throughput measurement",
                    budget="1280 calls/32768 completion tokens per case; prompt usage measured, no input-token cap",
                    stop_on_solution=args.stop_on_solution, server_metrics=args.server_metrics or args.stop_on_solution,
                    proof_timing="First verifier event observed by controller polling every 0.1s; never raw model claims",
                    partial_trace_accounting="Verifier success remains valid on deadline; unfinished client usage unknown; server deltas require idle/exclusive endpoint",
                    controller_deadline_seconds=180, output=str(directory), cases=cases)
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True)
    metadata["git_revision"] = revision.stdout.strip() if revision.returncode == 0 else None
    if not args.run:
        print(json.dumps(metadata, indent=2))
        return 0
    directory.mkdir(parents=True, exist_ok=False)
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    results, lock, slot_failures = [], threading.Lock(), []
    def worker(slot):
        for case in (c for c in cases if c["slot"] == slot):
            row = execute(case)
            with lock:
                results.append(row)
                (directory / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
                with (directory / "summary.csv").open("w", newline="") as output:
                    writer = csv.DictWriter(output, fieldnames=FIELDS)
                    writer.writeheader()
                    writer.writerows({k: json.dumps(v) if isinstance(v, dict) else v for k, v in r.items()} for r in results)
                print(f"{len(results)}/{len(cases)} {case['task_id']} {case['arm']} {row['status']} solved={int(row['solved'])} calls={row['calls']} wall={row['wall_seconds']:.2f}s", flush=True)
                if row["controller_stop"] and row["server_idle_after"] is not True:
                    slot_failures.append(dict(slot=slot, endpoint=case["endpoint"], reason="Idle not confirmed within 10s after cancellation"))
                    break
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(worker, range(args.jobs)))
    metadata.update(batch_wall_seconds=time.monotonic() - start, completed_cases=len(results),
                    completed_utc=datetime.now(timezone.utc).isoformat(), final_source_hashes=hashes(), slot_failures=slot_failures,
                    incomplete=len(results) != len(cases), missing_cases=[c["events"] for c in cases if c["events"] not in {r["events"] for r in results}])
    metadata["source_changed_during_run"] = metadata["source_hashes"] != metadata["final_source_hashes"]
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    return int(bool(slot_failures) or any(r["controller_error"] or (r["returncode"] != 0 and not r["controller_stop"]) for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
