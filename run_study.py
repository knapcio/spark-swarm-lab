#!/usr/bin/env python3
"""Finite arithmetic method study. Print a plan by default; --run starts requests."""
import argparse
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from harness import apply_action, solved

HERE = Path(__file__).resolve().parent
# Verification witnesses stay in metadata; they are never sent to workers.
PUZZLES = [
    ("2,3,5,9:28", "(9+5)*2", [(3,2,"+"),(2,0,"*")]),
    ("3,5,7,9:24", "3+5+7+9", [(0,1,"+"),(0,1,"+"),(0,1,"+")]),
    ("2,4,7,9,25,50:684", "(50+25)*9+7+4-2", [(5,4,"+"),(4,3,"*"),(3,2,"+"),(2,1,"+"),(1,0,"-")]),
]


def verify_puzzles():
    for puzzle, _, actions in PUZZLES:
        numbers, target = puzzle.split(":")
        state = tuple(Fraction(int(x)) for x in numbers.split(","))
        for i, j, op in actions:
            state = apply_action(state, dict(i=i, j=j, op=op))
        assert solved(state, int(target)), puzzle


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(path):
    records, malformed = [], 0
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                malformed += 1
    requests = [r for r in records if r.get("type") == "request_end"]
    ends = [r for r in records if r.get("type") == "run_end"]
    return dict(status=ends[-1].get("status") if ends else "missing_run_end",
                solved=ends[-1].get("solved") if ends else None,
                calls=sum(r.get("type") == "request_start" for r in records),
                completed_calls=len(requests),
                reported_prompt_tokens=sum(r.get("usage", {}).get("prompt_tokens", 0) for r in requests),
                reported_completion_tokens=sum(r.get("usage", {}).get("completion_tokens", 0) for r in requests),
                missing_prompt_usage=sum("prompt_tokens" not in r.get("usage", {}) for r in requests),
                missing_completion_usage=sum("completion_tokens" not in r.get("usage", {}) for r in requests),
                charged_completion_tokens=sum(r.get("completion_tokens_charged", 0) for r in requests),
                infrastructure_failures=ends[-1].get("infrastructure_failures") if ends else None,
                budget_denials=ends[-1].get("budget_denials") if ends else None,
                malformed_event_lines=malformed)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Execute; default prints plan without creating files")
    parser.add_argument("--endpoint", action="append", help="Repeat base URLs; default localhost ports 18081–18084")
    parser.add_argument("--output", type=Path, help="New study directory; must not exist")
    parser.add_argument("--method", choices=("independent", "democracy"), help="Run only this method")
    parser.add_argument("--accept-verified-solution", action="store_true", help="Forward opt-in terminal-proposal guard")
    parser.add_argument("--include-guarded", action="store_true", help="Interleave independent, democracy and guarded democracy")
    args = parser.parse_args(argv)
    if args.include_guarded and (args.method or args.accept_verified_solution):
        parser.error("--include-guarded cannot combine with --method or --accept-verified-solution")
    verify_puzzles()
    endpoints = args.endpoint or [f"http://127.0.0.1:{port}/v1" for port in range(18081, 18085)]
    directory = args.output or HERE / "runs" / ("study-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6])
    runs = []
    for puzzle_index, (puzzle, _, _) in enumerate(PUZZLES):
        for seed in (1, 2):
            policies = ([("independent", False), ("democracy", False), ("democracy", True)]
                        if args.include_guarded else [(m, args.accept_verified_solution) for m in ("independent", "democracy")])
            for method, accept_verified in (policies if seed == 1 else reversed(policies)):
                if args.method and method != args.method:
                    continue
                name = f"p{puzzle_index + 1}-s{seed}-{method}"
                if args.include_guarded and accept_verified:
                    name += "-guarded"
                events = directory / (name + ".jsonl")
                command = [sys.executable, str(HERE / "harness.py"), "--method", method,
                           "--puzzle", puzzle, "--model", "nemotron-lightning", "--agents", "100",
                           "--per-endpoint-concurrency", "25", "--rounds", "5", "--max-tokens", "192",
                           "--max-calls", "500", "--max-completion-tokens", "96000", "--timeout", "90",
                           "--seed", str(seed), "--events", str(events)]
                if accept_verified:
                    command.append("--accept-verified-solution")
                for endpoint in endpoints:
                    command.extend(["--endpoint", endpoint])
                runs.append(dict(name=name, puzzle=puzzle, seed=seed, method=method,
                                 events=str(events), accept_verified_solution=accept_verified, command=command))
    if not args.run:
        print(json.dumps(dict(mode="dry_run", puzzle_witnesses_verified=3,
                              include_guarded=args.include_guarded,
                              accept_verified_solution=None if args.include_guarded else args.accept_verified_solution,
                              method_filter=args.method, runs=runs), indent=2))
        return 0
    directory.mkdir(parents=True, exist_ok=False)
    runtime = HERE / "runtime.json"
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True)
    metadata = dict(schema_version=1, started_utc=datetime.now(timezone.utc).isoformat(),
                    git_revision=revision.stdout.strip() if revision.returncode == 0 else None,
                    source_hashes={p.name: digest(p) for p in (Path(__file__), HERE / "harness.py", runtime)},
                    runtime=json.loads(runtime.read_text()),
                    runtime_evidence="Configuration snapshot only; attach live serving probe separately.",
                    budget_interpretation="Same ceilings, not matched actual cost; democracy spends calls on votes.",
                    thinking=False, agents=100, max_calls=500, max_completion_tokens=96000,
                    include_guarded=args.include_guarded,
                    accept_verified_solution=None if args.include_guarded else args.accept_verified_solution,
                    method_filter=args.method,
                    puzzle_witnesses={p: expression for p, expression, _ in PUZZLES}, runs=runs)
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    results = []
    for run in runs:
        started = time.monotonic()
        returncode, controller_error = None, None
        with (directory / (run["name"] + ".stdout.log")).open("w") as stdout, \
             (directory / (run["name"] + ".stderr.log")).open("w") as stderr:
            try:
                result = subprocess.run(run["command"], stdout=stdout, stderr=stderr, timeout=600)
                returncode = result.returncode
            except subprocess.TimeoutExpired:
                controller_error = "600-second run timeout; subprocess killed"
        row = dict(name=run["name"], puzzle=run["puzzle"], seed=run["seed"], method=run["method"],
                   accept_verified_solution=run["accept_verified_solution"],
                   events=run["events"], wall_seconds=round(time.monotonic() - started, 6),
                   returncode=returncode, controller_error=controller_error, **summarize(Path(run["events"])))
        results.append(row)
        (directory / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
        print(json.dumps(row), flush=True)
    return int(any(r["returncode"] != 0 or r["infrastructure_failures"] != 0 for r in results))


if __name__ == "__main__":
    raise SystemExit(main())
