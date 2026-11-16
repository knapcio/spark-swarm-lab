#!/usr/bin/env python3
"""One balanced CSP cohort; plan-only unless --run is supplied and gates pass."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from csp_tasks import load_tasks, verify_assignment
from reference_worker import verify_gate
from run_benchmark import execute, drain, read_trace, server_metrics, FIELDS

HERE = Path(__file__).resolve().parent
ENDPOINTS = [f"http://127.0.0.1:{port}/v1" for port in range(18081, 18085)]
SOURCE_FILES = ("run_csp_search.py", "csp_search.py", "csp_social.py", "csp_tasks.py",
                "harness.py", "run_benchmark.py", "reference_worker.py", "runtime.json",
                "SEARCH_SELECTION.json", "datasets/csp-v1/tasks.json",
                "datasets/csp-v1/reference-witnesses.json", "test_run_csp_search.py",
                "test_csp_search.py", "test_csp_social.py", "test_csp_tasks.py",
                "csp_classical.py", "test_csp_classical.py", "test_csp_guided.py", "GUIDED_FORMAT_CONTROL.md")
EXTRA_FIELDS = ["profile", "case_valid", "halt_reason", "candidate_count", "review_count",
                "derived_count", "verified_assignment_count", "client_usage_complete",
                "first_candidate_verified_seconds", "source_changed_after_case"]


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    return {name: sha(HERE / name) for name in SOURCE_FILES}


def source_identity():
    revision = subprocess.check_output(["git", "-C", str(HERE), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(HERE), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    tracked = set(subprocess.check_output(["git", "-C", str(HERE), "ls-files"], text=True).splitlines())
    return dict(revision=revision, tracked_clean=not dirty,
                source_files_tracked=set(SOURCE_FILES) <= tracked, sha256=source_hashes())


def load_selection():
    selection = json.loads((HERE / "SEARCH_SELECTION.json").read_text())
    if selection.get("protocol") != "csp-search-selection-v1":
        raise ValueError("unexpected CSP selection protocol")
    for name, expected in selection["frozen_files_sha256"].items():
        if sha(HERE / name) != expected:
            raise ValueError(f"preregistered file hash mismatch: {name}")
    return selection


def build_plan(profile, split, seed, output, gate_root):
    selection = load_selection()
    if profile not in selection["profiles"]:
        raise ValueError("unknown profile")
    recipe = selection["profiles"][profile]
    if recipe.get("request_timeout_seconds") != recipe["deadline_seconds"] + 30:
        raise ValueError("request timeout must exceed the case deadline by exactly30seconds")
    if split not in recipe["splits_and_seeds"] or seed not in recipe["splits_and_seeds"][split]:
        raise ValueError("split/seed is outside the preregistered profile")
    dataset = HERE / "datasets/csp-v1/tasks.json"
    tasks = sorted(load_tasks(dataset, split), key=lambda t: t["id"])
    expected_count = 4 if split == "development" else 12
    if len(tasks) != expected_count or any(not re.fullmatch(r"[A-Za-z0-9_-]+", t["id"]) for t in tasks):
        raise ValueError("unexpected task count or unsafe task identifier")
    # Deterministic rotation/reversal changes assignment and order across seeds.
    offset = (seed - 1) % len(tasks)
    tasks = tasks[offset:] + tasks[:offset]
    if seed % 2 == 0:
        tasks.reverse()
    arms = list(recipe["arms"])
    if seed % 2 == 0:
        arms.reverse()
    cases = []
    output = Path(output).resolve()
    runtime = json.loads((HERE / "runtime.json").read_text())
    for index, task in enumerate(tasks):
        rotation = (index + seed - 1) % len(arms)
        order = arms[rotation:] + arms[:rotation]
        slot = index % 4
        for arm in order:
            stem = f"{task['id']}-{arm}-s{seed}"
            trace = output / (stem + ".jsonl")
            command = [sys.executable, str(HERE / "csp_search.py"), "--dataset", str(dataset),
                       "--split", split, "--task-id", task["id"], "--arm", arm,
                       "--endpoint", ENDPOINTS[slot], "--events", str(trace),
                       "--model", runtime["served_model_name"], "--seed", str(seed),
                       "--max-tokens", str(recipe["max_tokens"]), "--max-calls", str(recipe["max_calls"]),
                       "--timeout", str(recipe["request_timeout_seconds"])]
            if recipe["thinking"]:
                command.append("--thinking")
            if recipe.get("guided_format"):
                command.append("--guided-format")
            cases.append(dict(task_id=task["id"], task=task, split=split, arm=arm, seed=seed,
                              slot=slot, endpoint=ENDPOINTS[slot], events=str(trace), command=command,
                              stdout=str(output / (stem + ".stdout.log")),
                              stderr=str(output / (stem + ".stderr.log")),
                              server_metrics=True, stop_on_solution=False, shared_endpoint=False))
    return dict(protocol=selection["protocol"], profile=profile, split=split, seed=seed,
                recipe=recipe, cases=cases, planned_cases=len(cases), jobs=4,
                output=str(output), gate_root=str(Path(gate_root).resolve()), endpoints=ENDPOINTS,
                dataset_sha256=sha(dataset), selection_sha256=sha(HERE / "SEARCH_SELECTION.json"),
                runtime=runtime, runtime_sha256=sha(HERE / "runtime.json"),
                runtime_evidence="Pinned configuration only; parent verifies live Docker identities before first cohort.",
                scheduling="One persistent slot per endpoint; each task's arms sequential; seed-dependent rotations.",
                scope="Quality/latency with four endpoint-owned case slots; not saturated fleet throughput.",
                stop_policy="Worker finishes dispatched batches; controller only terminates whole-case deadlines.",
                transport_timeout_policy="Per-request HTTP timeout is case deadline+30seconds; controller deadline, budgets and polling unchanged.",
                timing="Candidate verification seconds start at worker search entry; controller proof time includes worker startup and polling delay.",
                unknown_cost_policy="Unknown server costs are null; incomplete client usage remains a lower bound.")


def assess_attempt(case, row, records, max_calls):
    """Replay all assignment proofs, reconcile requests, retain genuine deadlines."""
    fault = None
    starts = [r for r in records if r.get("type") == "request_start"]
    ends = [r for r in records if r.get("type") == "request_end"]
    run_starts = [r for r in records if r.get("type") == "run_start"]
    run_ends = [r for r in records if r.get("type") == "run_end"]
    assignments = [r for r in records if r.get("type") in ("candidate", "derived_candidate")]
    start_ids = [r.get("request_id") for r in starts]
    end_ids = [r.get("request_id") for r in ends]
    proof_ids, true_proofs, times, review_ids = set(), {}, [], set()
    for record in records:
        kind = record.get("type")
        if kind in ("candidate", "derived_candidate"):
            if record.get("id") in proof_ids or not record.get("id"):
                fault = "duplicate_or_missing_candidate_id"
                break
            if not set(record.get("parents", [])) <= proof_ids or not set(record.get("review_ids", [])) <= review_ids:
                fault = "candidate_parent_or_review_used_before_recorded"
                break
            proof_ids.add(record["id"])
            proof = verify_assignment(case["task"], record.get("payload"))
            if proof != record.get("verification"):
                fault = "candidate_verification_replay_mismatch"
                break
            if proof["solved"]:
                true_proofs[record["id"]] = proof
                value = record.get("verified_elapsed_seconds")
                if type(value) in (int, float) and value >= 0:
                    times.append(value)
        elif kind == "review":
            if (not record.get("id") or record["id"] in review_ids
                    or record.get("reviewer_candidate_id") not in proof_ids
                    or not set(record.get("target_ids", [])) <= proof_ids):
                fault = "review_source_missing_or_used_before_recorded"
                break
            review_ids.add(record["id"])
        elif kind == "reward" and record.get("solved") is True and record.get("node_id") not in true_proofs:
            fault = "reward_without_preceding_exact_proof"
            break
        elif kind in ("run_end", "search_end") and record.get("solved") is True and not true_proofs:
            fault = "completion_without_preceding_exact_proof"
            break
    if fault is None and (row.get("controller_error") or row.get("malformed_lines") or row.get("infrastructure_failures")):
        fault = "controller_or_infrastructure_fault"
    if fault is None and any(e.get("error") and e.get("response") is None and e.get("finish_reason") != "length" for e in ends):
        fault = "observed_or_ambiguous_transport_failure"
    if fault is None and (len(run_starts) != 1 or run_starts[0].get("task") != case["task"]):
        fault = "missing_or_mismatched_worker_task"
    if fault is None and (not all(isinstance(i, str) and i for i in start_ids + end_ids)
            or len(set(start_ids)) != len(start_ids) or len(set(end_ids)) != len(end_ids)
            or not set(end_ids) <= set(start_ids) or len(starts) > max_calls
            or any(r.get("puzzle_id") != case["task_id"] for r in starts)
            or row.get("calls") != len(starts) or row.get("completed_calls") != len(ends)
            or row.get("unfinished_calls") != len(starts) - len(ends)):
        fault = "request_accounting_mismatch"
    if fault is None:
        by_id = {r["request_id"]: r for r in starts}
        if any(any(e.get(k) != by_id[e["request_id"]].get(k) for k in ("agent_id", "stage", "puzzle_id")) for e in ends):
            fault = "request_context_mismatch"
    deadline = row.get("deadline") is True
    if fault is None and deadline:
        if not (row.get("controller_stop") is True and row.get("status") == "deadline"
                and row.get("returncode") in (0, -15, -9, 143, 137)
                and any(r.get("type") == "controller_stop" and r.get("deadline") is True
                        and r.get("returncode") == row.get("returncode") for r in records)):
            fault = "deadline_without_controlled_exit_receipt"
    elif fault is None and not (row.get("status") == "complete" and row.get("returncode") == 0
            and len(run_ends) == 1 and row.get("infrastructure_failures") == 0
            and len(starts) == len(ends)):
        fault = "unexpected_worker_completion_state"
    if fault is None and not deadline:
        end = run_ends[0]
        if (end.get("calls") != len(starts) or end.get("max_calls") != max_calls
                or end.get("candidate_count") != sum(r.get("type") == "candidate" for r in assignments)
                or (not true_proofs and not row.get("budget_denials") and len(starts) != max_calls)):
            fault = "worker_budget_or_candidate_count_mismatch"
    if fault is None and row.get("solved") and not true_proofs:
        fault = "summary_success_without_exact_proof"
    if fault is None and row.get("server_idle_after") is not True:
        fault = "endpoint_not_confirmed_idle"
    return dict(case_valid=fault is None, halt_reason=fault,
                candidate_count=sum(r.get("type") == "candidate" for r in assignments),
                derived_count=sum(r.get("type") == "derived_candidate" for r in assignments),
                review_count=sum(r.get("type") == "review" for r in records),
                verified_assignment_count=len(true_proofs),
                first_candidate_verified_seconds=min(times) if times else None,
                client_usage_complete=not row.get("unfinished_calls") and not row.get("missing_prompt_usage")
                                      and not row.get("missing_completion_usage"))


def atomic_text(path, text):
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="") as stream:
        stream.write(text)
        stream.flush()
    temporary.replace(path)


def write_json(path, value):
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_summaries(directory, results, cases):
    order = {case["events"]: i for i, case in enumerate(cases)}
    rows = sorted(results, key=lambda row: order[row["events"]])
    write_json(directory / "summary.json", rows)
    output = io.StringIO(newline="")
    fields = FIELDS + EXTRA_FIELDS
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: (json.dumps(row.get(key)) if row.get(key) is None or
                         isinstance(row.get(key), (dict, list, bool)) else row[key]) for key in fields})
    atomic_text(directory / "summary.csv", output.getvalue())


def run_cohort(plan, before, gate):
    directory = Path(plan["output"])
    directory.mkdir(parents=True, exist_ok=False)
    metadata = dict(plan, mode="run", started_utc=utc_now(), source_before=before, gate=gate)
    write_json(directory / "metadata.json", metadata)
    results, faults = [], []
    lock, stop = threading.Lock(), threading.Event()
    start = time.monotonic()
    def idle_probe(endpoint):
        try:
            return drain(endpoint)
        except Exception as exc:
            return {"error": f"{type(exc).__name__}:{str(exc)[:200]}"}, None, 0.0
    with ThreadPoolExecutor(max_workers=4) as pool:
        snapshots = list(pool.map(idle_probe, ENDPOINTS))
    metadata["initial_idle_checks"] = [dict(endpoint=endpoint, snapshot=snapshot, idle=idle,
        drain_seconds=seconds) for endpoint, (snapshot, idle, seconds) in zip(ENDPOINTS, snapshots)]
    if any(idle is not True for _, idle, _ in snapshots):
        faults.append(dict(reason="all_four_endpoints_must_be_idle_before_cohort"))
        stop.set()
    write_json(directory / "metadata.json", metadata)

    def fail(reason, case=None):
        stop.set()
        with lock:
            faults.append(dict(reason=reason, events=case["events"] if case else None))

    def worker(slot):
        for case in (c for c in plan["cases"] if c["slot"] == slot):
            if stop.is_set():
                break
            try:
                if source_hashes() != before["sha256"]:
                    fail("source_changed_before_dispatch", case)
                    break
                idle = server_metrics(case["endpoint"], timeout=3)
                if idle.get("error") or idle.get("running") != 0 or idle.get("waiting") != 0:
                    fail("endpoint_not_idle_before_dispatch", case)
                    break
                if stop.is_set():
                    break
                row = execute(case, plan["recipe"]["deadline_seconds"])
                records, malformed = read_trace(Path(case["events"]))
                if malformed:
                    row["malformed_lines"] = malformed
                row.update(assess_attempt(case, row, records, plan["recipe"]["max_calls"]))
                row["profile"] = plan["profile"]
                row["source_changed_after_case"] = source_hashes() != before["sha256"]
                if row["source_changed_after_case"]:
                    row.update(case_valid=False, halt_reason="source_changed_after_case")
                if not row.get("server_cost_known"):
                    row["server_prompt_tokens"] = row["server_completion_tokens"] = None
                if row["deadline"]:
                    # Shared helper's historical reason names 180 even for other deadlines.
                    row["stop_reason"] = f"controller_{plan['recipe']['deadline_seconds']}_second_deadline"
                if not row["case_valid"]:
                    stop.set()
                with lock:
                    results.append(row)
                    if not row["case_valid"]:
                        faults.append(dict(reason=row["halt_reason"], events=case["events"]))
                    write_summaries(directory, results, plan["cases"])
            except Exception as exc:
                fail(f"controller_exception:{type(exc).__name__}:{str(exc)[:200]}", case)
                break

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(worker, range(4)))
    try:
        after = source_identity()
    except Exception as exc:
        after = dict(error=type(exc).__name__, sha256=None)
    changed = (after.get("sha256") != before["sha256"] or after.get("revision") != before["revision"]
               or not after.get("tracked_clean") or not after.get("source_files_tracked"))
    if changed:
        faults.append(dict(reason="final_source_identity_changed"))
    completed = {row["events"] for row in results}
    metadata.update(completed_utc=utc_now(), batch_wall_seconds=time.monotonic() - start,
                    completed_cases=len(results), valid_cases=sum(row["case_valid"] for row in results),
                    missing_cases=[c["events"] for c in plan["cases"] if c["events"] not in completed],
                    incomplete=len(results) != len(plan["cases"]), source_after=after,
                    source_changed_during_run=changed, faults=faults,
                    verified=not faults and len(results) == len(plan["cases"]) and all(r["case_valid"] for r in results),
                    abort_policy="Stop new case dispatch on first fault; already running bounded cases finish and drain.")
    write_summaries(directory, results, plan["cases"])
    write_json(directory / "metadata.json", metadata)
    return 0 if metadata["verified"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("core_off16", "extended_off64", "thinking_on16", "core_guided_off16"), required=True)
    parser.add_argument("--split", choices=("development", "evaluation"), required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--gate-root", type=Path, default=HERE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    gate_root = args.gate_root.resolve()
    output = (args.output or gate_root / "runs" / f"csp-{args.profile}-{args.split}-s{args.seed}").resolve()
    plan = build_plan(args.profile, args.split, args.seed, output, gate_root)
    before = source_identity()
    if not args.run:
        print(json.dumps(dict(plan, mode="plan", source_before=before), indent=2))
        return 0
    if output.exists():
        raise FileExistsError("output already exists; no overwrite or resume")
    if not before["tracked_clean"] or not before["source_files_tracked"]:
        raise RuntimeError("run requires a clean tracked source snapshot")
    if not output.is_relative_to(gate_root / "runs"):
        raise ValueError("run output must be inside gate-root/runs")
    gate = verify_gate(gate_root)
    return run_cohort(plan, before, gate)


if __name__ == "__main__":
    raise SystemExit(main())
