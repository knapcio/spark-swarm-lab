"""bugbench agent matrix runner (cases x seeds x policies) over the four Nemotron replicas.

Plan-only by default: prints the matrix, budgets and endpoints and contacts nothing.
``--run`` executes it.  Output goes to a NEW directory (never overwritten):

  <out>/plan.json                the frozen plan (written before any call)
  <out>/attempts/<id>.jsonl      every event of one attempt (prompts, requests, raw text, grades)
  <out>/attempts.jsonl           one result record per finished attempt
  <out>/summary.json             per-policy aggregates (written once at the end)

Admission stops at the first infrastructure fault (transport, tokenizer, accounting,
self-check or grading infrastructure); attempts already in flight finish.  A bad
candidate (garbled, truncated, invalid or wrong patch) is an outcome, not a fault.

Model patches must be graded in the container: ``--docker-host`` is required for
``--run`` unless ``--unsafe-local-grading`` is given (authored fixtures only).
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agents as a  # noqa: E402
import bugbench_grader as g  # noqa: E402


def attempt_id(case_id, policy, seed):
    return f"{case_id}__{policy}__s{seed}"


def build_plan(args):
    cases = args.cases or g.list_cases()
    unknown = sorted(set(cases) - set(g.list_cases()))
    if unknown:
        raise SystemExit(f"unknown cases: {unknown}")
    policies = args.policies
    for policy in policies:
        if policy not in a.POLICIES:
            raise SystemExit(f"unknown policy {policy}; choose from {sorted(a.POLICIES)}")
    # seed-major order: a partial run still covers every case and policy evenly
    matrix = [dict(id=attempt_id(c, p, s), case_id=c, policy=p, seed=s)
              for s in args.seeds for c in cases for p in policies]
    default_calls = 48 if args.max_calls is None else args.max_calls
    default_tokens = 256_000 if args.max_completion_tokens is None else args.max_completion_tokens

    def policy_entry(p):
        spec = a.POLICIES[p]
        entry = dict(kwargs=spec["kwargs"], nominal_max_calls=spec["max_calls"])
        if "budget" in spec or "selection" in spec:  # T1/T3/V3 only; S1/S3/W1 entries stay as before
            budget = spec.get("budget", {})
            entry.update(selection=spec.get("selection"), attempt_budget=dict(
                max_calls=budget.get("max_calls", default_calls) if args.max_calls is None else args.max_calls,
                max_completion_tokens=budget.get("max_completion_tokens", default_tokens)
                if args.max_completion_tokens is None else args.max_completion_tokens))
        return entry
    sources = {name: hashlib.sha256(open(os.path.join(a.g.ROOT, name), "rb").read()).hexdigest()
               for name in ("agents.py", "bugbench_grader.py", "run_agents.py")}
    return dict(
        created=datetime.now().astimezone().isoformat(), model=args.model, endpoints=args.endpoints,
        per_endpoint_concurrency=args.per_endpoint, parallel_attempts=args.parallel_attempts,
        grading=("docker:" + args.docker_host) if args.docker_host else "local (unsafe; fixtures only)",
        oracle=not args.no_oracle,
        budgets=dict(context_limit=a.CONTEXT_LIMIT, max_completion_per_call=a.MAX_COMPLETION,
                     patch_answer_reserve_min=a.PATCH_ANSWER_RESERVE, json_answer_reserve=a.JSON_ANSWER_RESERVE,
                     idle_timeout_s=args.idle_timeout, wall_clock_quality_cutoff=None,
                     attempt_max_calls=default_calls, attempt_max_completion_tokens=default_tokens),
        policies={p: policy_entry(p) for p in policies},
        selection="valid -> passes public tests -> largest cluster of identical normalized diffs -> earliest",
        source_sha256=sources, attempts=matrix)


def attempt_budget(plan, policy):
    """(max_calls, max_completion_tokens) for one attempt: the policy's own budget (T3/V3) or the global one."""
    budgets = plan["budgets"]
    own = (plan["policies"].get(policy) or {}).get("attempt_budget")
    if own:
        return own["max_calls"], own["max_completion_tokens"]
    return budgets["attempt_max_calls"], budgets["attempt_max_completion_tokens"]


def summarize(records):
    by = {}
    for r in records:
        by.setdefault(r["policy"], []).append(r)
    out = {}
    for policy, rows in sorted(by.items()):
        done = [r for r in rows if r["status"] == "completed"]
        n = len(done)

        def mean(values):
            values = list(values)
            return round(sum(values) / len(values), 2) if values else None
        out[policy] = dict(
            attempts=len(rows), completed=n,
            infrastructure_faults=sum(r["status"] == "infrastructure_fault" for r in rows),
            prompt_too_long=sum(r["status"] == "prompt_too_long" for r in rows),
            fixed=sum(bool(r.get("fixed")) for r in done),
            fix_rate=round(sum(bool(r.get("fixed")) for r in done) / n, 4) if n else None,
            no_valid_patch=sum(r.get("selected") is None for r in done),
            mean_calls=mean(r["usage"]["calls"] for r in done),
            mean_completion_tokens=mean(r["usage"]["completion_tokens"] for r in done),
            forced_calls=sum(r["usage"]["forced"] for r in done),
            truncated_calls=sum(r["usage"]["truncated"] for r in done),
            mean_wall_s=mean(r["wall_s"] for r in done),
            ORACLE_hindsight_any_candidate_passed=sum(bool((r.get("oracle") or {}).get("any_passed")) for r in done),
            per_case={c: dict(fixed=sum(bool(r.get("fixed")) for r in done if r["case_id"] == c),
                              attempts=sum(r["case_id"] == c for r in done))
                      for c in sorted({r["case_id"] for r in done})})
    return dict(label="fix_rate uses exactly one hidden grade of the frozen selection; ORACLE_* is a hindsight "
                      "upper bound and never influenced selection", policies=out)


def execute(plan, out_dir, pool, executor=None, grade_fn=None, selfcheck=None, parallel=4, log=print):
    """Run the plan's attempts; never overwrites; stops admission at the first infrastructure fault."""
    os.makedirs(out_dir, exist_ok=False)
    os.makedirs(os.path.join(out_dir, "attempts"))
    with open(os.path.join(out_dir, "plan.json"), "x", encoding="utf-8") as handle:
        json.dump(plan, handle, indent=1)
    results_file = open(os.path.join(out_dir, "attempts.jsonl"), "x", encoding="utf-8")
    lock, halt, records = threading.Lock(), threading.Event(), []

    def one(item):
        record = a.run_attempt(
            item["case_id"], item["policy"], item["seed"], pool,
            events_path=os.path.join(out_dir, "attempts", item["id"] + ".jsonl"),
            executor=executor, grade_fn=grade_fn, selfcheck=selfcheck, oracle=plan["oracle"],
            budget=a.Budget(*attempt_budget(plan, item["policy"])))
        record.pop("events", None)
        record["attempt_id"] = item["id"]
        with lock:
            records.append(record)
            results_file.write(json.dumps(record, default=str) + "\n")
            results_file.flush()
        if record["status"] == "infrastructure_fault":
            halt.set()
        log(f"[{time.strftime('%H:%M:%S')}] {item['id']}: {record['status']} fixed={record.get('fixed')} "
            f"calls={record['usage']['calls']} tokens={record['usage']['completion_tokens']}")
        return record

    queue = list(plan["attempts"])
    skipped = []
    with ThreadPoolExecutor(max_workers=parallel) as workers:
        running = set()
        while queue or running:
            while queue and len(running) < parallel and not halt.is_set():
                running.add(workers.submit(one, queue.pop(0)))
            if halt.is_set() and queue:
                skipped, queue = [item["id"] for item in queue], []
                log(f"infrastructure fault: admission stopped, {len(skipped)} attempts not started")
            if not running:
                break
            done, running = wait(running, return_when=FIRST_COMPLETED)
            for future in done:
                future.result()
    results_file.close()
    summary = dict(summarize(records), halted=halt.is_set(), not_started=skipped,
                   finished=datetime.now().astimezone().isoformat())
    with open(os.path.join(out_dir, "summary.json"), "x", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=1)
    return summary


def preflight(transports, model):
    """Cheap live check before admitting attempts: every replica serves ``model``."""
    import urllib.request
    for transport in transports:
        with urllib.request.urlopen(transport.base + "/v1/models", timeout=15) as response:
            served = [m.get("id") for m in json.load(response).get("data", [])]
        if model not in served:
            raise SystemExit(f"{transport.endpoint} does not serve {model!r}: {served}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", nargs="*", help="case ids (default: all)")
    parser.add_argument("--policies", nargs="+", default=["S1", "S3", "W1"], choices=sorted(a.POLICIES),
                        help="S1/S3/W1 baselines; T1 test-first agent, T3 8 test-first chains + cross-validation, "
                             "V3 S3 + one model review per distinct patch")
    parser.add_argument("--seeds", nargs="+", type=int, default=[1])
    parser.add_argument("--endpoints", nargs="+", default=list(a.ENDPOINTS))
    parser.add_argument("--model", default=a.MODEL)
    parser.add_argument("--per-endpoint", type=int, default=8, help="concurrent requests per replica")
    parser.add_argument("--parallel-attempts", type=int, default=4)
    parser.add_argument("--idle-timeout", type=float, default=a.IDLE_TIMEOUT)
    parser.add_argument("--max-calls", type=int, default=None,
                        help="per-attempt logical call cap (default 48; T3 64 and V3 56 unless given)")
    parser.add_argument("--max-completion-tokens", type=int, default=None,
                        help="per-attempt cap (default 256000; T3 512000 and V3 320000 unless given)")
    parser.add_argument("--docker-host", help="grade and self-check in the pinned container on this SSH host")
    parser.add_argument("--unsafe-local-grading", action="store_true",
                        help="run model patches in a local subprocess (NOT a sandbox)")
    parser.add_argument("--no-oracle", action="store_true", help="skip hindsight grading of all candidates")
    parser.add_argument("--out", help="new output directory (must not exist)")
    parser.add_argument("--run", action="store_true", help="execute (default: print the plan only)")
    args = parser.parse_args(argv)
    plan = build_plan(args)
    if not args.run:
        shown = dict(plan, attempts=[item["id"] for item in plan["attempts"]])
        print(json.dumps(shown, indent=1))
        print(f"\nplan only: {len(plan['attempts'])} attempts; add --run --out DIR --docker-host HOST to execute",
              file=sys.stderr)
        return 0
    if not args.out:
        raise SystemExit("--run needs --out (a new directory)")
    if os.path.exists(args.out):
        raise SystemExit(f"{args.out} exists; refusing to overwrite")
    if not args.docker_host and not args.unsafe_local_grading:
        raise SystemExit("--run grades model patches: pass --docker-host HOST (or --unsafe-local-grading)")
    executor = g.DockerExecutor(args.docker_host) if args.docker_host else None
    transports = [a.HTTPTransport(e, args.model, args.idle_timeout) for e in args.endpoints]
    preflight(transports, args.model)
    pool = a.EndpointPool(transports, args.per_endpoint)
    summary = execute(plan, args.out, pool, executor=executor, parallel=args.parallel_attempts)
    print(json.dumps(summary, indent=1))
    return 1 if summary["halted"] else 0


if __name__ == "__main__":
    sys.exit(main())
