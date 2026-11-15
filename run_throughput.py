#!/usr/bin/env python3
"""Single-arm arithmetic fleet throughput cohort. Default plan only; --run starts it."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

from run_benchmark import ARMS, execute, FIELDS, drain, server_cost

HERE = Path(__file__).resolve().parent
EXTRA = ["cluster_id", "node_index", "slot", "queue_wait_seconds", "service_wall_seconds",
         "total_latency_seconds", "end_to_end_first_proof_seconds", "admitted_utc", "finished_utc"]
SOURCES = ("run_throughput.py", "run_benchmark.py", "harness.py", "direct_solver.py",
           "shared_search.py", "ensemble_solver.py", "runtime.json", "make_tasks.py")


def hashes():
    return {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest() for name in SOURCES}


def idle_all(endpoints):
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(drain, endpoints))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True, help="Public arithmetic tasks.json")
    parser.add_argument("--split", choices=("development", "evaluation"), required=True)
    parser.add_argument("--arm", choices=ARMS, required=True, help="Exactly one policy per cohort")
    parser.add_argument("--seeds", default="1,2,3,4")
    parser.add_argument("--jobs-per-node", type=int, choices=range(1, 26), default=1)
    parser.add_argument("--endpoint", action="append", help="Exactly four distinct model endpoint bases")
    parser.add_argument("--output", type=Path, help="New directory; never overwrite")
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    try: seeds = [int(value.strip()) for value in args.seeds.split(",")]
    except ValueError: parser.error("seeds must be comma-separated integers")
    if not seeds or len(set(seeds)) != len(seeds): parser.error("seeds must be unique")
    raw = args.dataset.read_bytes()
    dataset = json.loads(raw)
    if dataset.get("protocol") != "synthetic-countdown-v1" or any(key in dataset for key in ("witnesses", "references")):
        parser.error("expected public synthetic-countdown-v1 tasks.json")
    tasks = [t for t in dataset.get("tasks", []) if t.get("split") == args.split]
    if len(dataset["tasks"]) != 32 or any(sum(t.get("split") == s for t in dataset["tasks"]) != n
                                         for s, n in (("development",8),("evaluation",24))):
        parser.error("dataset requires 8 development and 24 evaluation tasks")
    if len({t["id"] for t in dataset["tasks"]}) != 32 or any(not re.fullmatch(r"[A-Za-z0-9_-]+",t["id"])
        or len(t.get("numbers",[])) not in (4,6) or any(type(n) is not int or n<=0 for n in t["numbers"])
        or type(t.get("target")) is not int for t in dataset["tasks"]): parser.error("invalid public task schema")
    endpoints = args.endpoint or [f"http://127.0.0.1:{p}/v1" for p in range(18081,18085)]
    if len(endpoints) != 4 or len(set(endpoints)) != 4: parser.error("exactly four distinct endpoints required")
    for endpoint in endpoints:
        url = urlsplit(endpoint)
        if url.scheme not in ("http","https") or not url.netloc or url.username or url.password: parser.error("credential-free HTTP(S) endpoints required")
    directory = (args.output or HERE/"runs"/("throughput-"+args.split+"-"+args.arm+"-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f"))).resolve()
    if directory.exists(): parser.error("output directory already exists")
    if args.run and "shared_endpoint" not in inspect.getsource(execute): parser.error("executor needs the shared_endpoint hook before running this cohort")
    method, agents, thinking = ARMS[args.arm]
    runtime, cases = json.loads((HERE/"runtime.json").read_text()), []
    for task_index, task in enumerate(tasks):
        order = seeds[task_index%len(seeds):]+seeds[:task_index%len(seeds)]
        for seed in order:
            index = len(cases)
            node, slot = index%4, (index%4)*args.jobs_per_node+(index//4)%args.jobs_per_node
            name = f"{task['id']}-{args.arm}-s{seed}"
            trace = directory/(name+".jsonl")
            command = [sys.executable,str(HERE/"harness.py"),"--method",method,"--puzzle",
                       ",".join(map(str,task["numbers"]))+":"+str(task["target"]),"--model","nemotron-lightning",
                       "--agents",str(agents),"--per-endpoint-concurrency","25","--rounds","5","--max-tokens",
                       "8192" if args.arm.endswith("_8k") else "4096" if thinking else "192",
                       "--max-calls","1280","--max-completion-tokens","32768","--timeout","180",
                       "--seed",str(seed),"--events",str(trace),"--endpoint",endpoints[node]]
            if thinking: command.append("--thinking")
            if args.arm.startswith("democracy"): command.append("--accept-verified-solution")
            cases.append(dict(task_id=task["id"],cluster_id=task["id"],split=args.split,arm=args.arm,seed=seed,
                              node_index=node,slot=slot,endpoint=endpoints[node],events=str(trace),command=command,
                              shared_endpoint=True,stop_on_solution=True,server_metrics=False,
                              stdout=str(directory/(name+".stdout.log")),stderr=str(directory/(name+".stderr.log"))))
    metadata = dict(schema_version=1,domain="arithmetic",mode="run" if args.run else "dry_run",
                    started_utc=datetime.now(timezone.utc).isoformat(),dataset=str(args.dataset.resolve()),
                    dataset_sha256=hashlib.sha256(raw).hexdigest(),dataset_protocol=dataset["protocol"],
                    split=args.split,arm=args.arm,seeds=seeds,unique_tasks=len(tasks),attempts=len(cases),
                    jobs_per_node=args.jobs_per_node,total_slots=4*args.jobs_per_node,model_agents_per_case=agents,
                    source_hashes=hashes(),runtime=runtime,runtime_evidence="Configuration snapshot, not live verification",
                    scheduling="All cases queued at common t0; task positions round-robin over 4 nodes, then persistent slots per node; per-task seed order rotates",
                    budgets="1280 calls/32768 completion tokens per case, no input-token cap; request timeout180s and case deadline180s AFTER admission",
                    scope="One arm per cohort: fleet wall includes scheduling, cases and final parallel drain. Configured jobs and N are not an optimal-admission claim; vLLM queues excess model requests.",
                    clustering="Repeated seeds are attempts clustered by task_id, not independent problems; evaluation 24 tasks x4 seeds gives96 attempts, not96 independent tasks",
                    counter_scope="Only global endpoint idle counter deltas; no per-case server attribution. Assumes no outside generation traffic during cohort.",
                    warmup="Metrics/idle preflight only; no extra generation warmup",preflight_max_seconds=10,post_drain_max_seconds=10,
                    proof_timing="Queue wait plus executor-observed proof (0.1s polling); queue time excluded from each 180s admission deadline",
                    output=str(directory),cases=cases)
    revision = subprocess.run(["git","rev-parse","HEAD"],cwd=HERE,capture_output=True,text=True)
    metadata["git_revision"] = revision.stdout.strip() if revision.returncode==0 else None
    if not args.run:
        print(json.dumps(metadata,indent=2)); return 0
    directory.mkdir(parents=True,exist_ok=False)
    before = idle_all(endpoints)
    metadata["preflight"] = [dict(endpoint=e,metrics=item[0],idle=item[1],seconds=item[2]) for e,item in zip(endpoints,before)]
    if not all(item[1] is True for item in before):
        metadata.update(status="preflight_not_idle",completed_cases=0,no_generation_started=True)
        (directory/"metadata.json").write_text(json.dumps(metadata,indent=2)+"\n")
        print(json.dumps(dict(status="preflight_not_idle",output=str(directory)))); return 1
    metadata["queued_utc"] = datetime.now(timezone.utc).isoformat()
    t0 = time.monotonic()
    (directory/"metadata.json").write_text(json.dumps(metadata,indent=2)+"\n")
    results, lock = [], threading.Lock()
    def worker(slot):
        for case in (c for c in cases if c["slot"]==slot):
            admitted = time.monotonic()
            admitted_utc = datetime.now(timezone.utc).isoformat()
            row = execute(case,180)
            finished = time.monotonic()
            queue = admitted-t0
            proof = row.get("time_to_verified_solution_seconds")
            row.update(cluster_id=case["cluster_id"],node_index=case["node_index"],slot=slot,
                       queue_wait_seconds=round(queue,6),service_wall_seconds=row["wall_seconds"],
                       total_latency_seconds=round(finished-t0,6),end_to_end_first_proof_seconds=queue+proof if proof is not None else None,
                       admitted_utc=admitted_utc,finished_utc=datetime.now(timezone.utc).isoformat(),
                       server_prompt_tokens=None,server_completion_tokens=None,server_cost_known=False,
                       server_cost_reason="shared_endpoint_global_counters_only",server_idle_after=None)
            with lock:
                results.append(row)
                (directory/"summary.json").write_text(json.dumps(results,indent=2)+"\n")
                with (directory/"summary.csv").open("w",newline="") as output:
                    writer=csv.DictWriter(output,fieldnames=FIELDS+EXTRA);writer.writeheader()
                    writer.writerows({k:json.dumps(v) if isinstance(v,dict) else v for k,v in r.items()} for r in results)
                print(f"{len(results)}/{len(cases)} {case['task_id']} seed={case['seed']} solved={int(row['solved'])} queue={queue:.2f}s service={row['wall_seconds']:.2f}s",flush=True)
    with ThreadPoolExecutor(max_workers=4*args.jobs_per_node) as pool:
        list(pool.map(worker,range(4*args.jobs_per_node)))
    after = idle_all(endpoints)
    wall = time.monotonic()-t0
    nodes = []
    for index, endpoint in enumerate(endpoints):
        subset = [r for r in results if r["endpoint"]==endpoint]
        floor = {k:sum(r[k] for r in subset) for k in ("prompt_tokens","completion_tokens")}
        nodes.append(dict(endpoint=endpoint,before=before[index][0],after=after[index][0],idle_after=after[index][1],
                          post_drain_seconds=after[index][2],completed_client_floor=floor,
                          **server_cost(before[index][0],after[index][0],after[index][1],floor)))
    known = all(n["server_cost_known"] for n in nodes)
    metadata.update(completed_utc=datetime.now(timezone.utc).isoformat(),completed_cases=len(results),
                    batch_wall_seconds=wall,final_source_hashes=hashes(),status="complete",nodes=nodes)
    metadata["source_changed_during_run"] = metadata["source_hashes"]!=metadata["final_source_hashes"]
    metadata["incomplete"] = len(results)!=len(cases)
    cohort = dict(arm=args.arm,split=args.split,seeds=seeds,unique_tasks=len(tasks),attempts=len(cases),completed_cases=len(results),
                  verified_successes=sum(bool(r["solved"]) for r in results),batch_wall_seconds=wall,
                  fully_drained=all(n["idle_after"] is True for n in nodes),server_cost_known=known,
                  server_prompt_tokens=sum(n["server_prompt_tokens"] for n in nodes) if known else None,
                  server_completion_tokens=sum(n["server_completion_tokens"] for n in nodes) if known else None,
                  completed_client_prompt_tokens=sum(r["prompt_tokens"] for r in results),completed_client_completion_tokens=sum(r["completion_tokens"] for r in results),
                  controller_errors=sum(bool(r["controller_error"]) or r["returncode"]!=0 and not r["controller_stop"] for r in results),
                  known_infrastructure_failures=sum(r["infrastructure_failures"] or 0 for r in results),
                  missing_client_usage=sum(r["missing_prompt_usage"]+r["missing_completion_usage"] for r in results))
    cohort["successes_per_minute"] = cohort["verified_successes"]*60/wall
    cohort["throughput_scope_valid"] = cohort["fully_drained"] and not metadata["incomplete"] and not metadata["source_changed_during_run"] and not cohort["controller_errors"]
    cohort["rate_note"] = "Observed verified attempt completions/minute over whole cohort incl drain; incomplete/not-drained cohorts are not completed-cohort throughput"
    metadata["cohort"] = cohort
    (directory/"cohort.json").write_text(json.dumps(cohort,indent=2)+"\n")
    (directory/"metadata.json").write_text(json.dumps(metadata,indent=2)+"\n")
    print(json.dumps(cohort),flush=True)
    return int(not cohort["throughput_scope_valid"] or any(r["controller_error"] or r["returncode"]!=0 and not r["controller_stop"] for r in results))


if __name__=="__main__": raise SystemExit(main())
