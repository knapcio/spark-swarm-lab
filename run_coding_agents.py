#!/usr/bin/env python3
"""Independent coding agents: K agents per (task, seed), each one coding_forced_worker process.

Agents never communicate. Each proposal is graded on feedback cases and once on holdout cases
in the CPU sandbox on the node that served it. Swarm selection (analysis only): the first agent in
the fixed order whose proposal passes ALL feedback cases; the case is solved if that proposal
passes ALL holdout cases. Plan-only by default.
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from run_agents72 import agent_seed, git, operational_fault, read, require, sha, validate_source, write
from run_benchmark import execute, read_trace, server_metrics

HERE = Path(__file__).resolve().parent
PROTOCOL = 'coding-agents-v1'
CONTROLLER = ('run_coding_agents.py', 'run_benchmark.py', 'run_agents72.py')
ENDPOINTS = [f'http://127.0.0.1:{port}/v1' for port in range(18081, 18085)]
HOSTS = ['Spark_01', 'Spark_02', 'Spark_03', 'Spark_04']


def hashes(source):
    tracked = git(source, 'ls-files').split()
    result = {name: sha(source / name) for name in tracked if name.endswith(('.py', '.json'))}
    result.update({'controller/' + name: sha(HERE / name) for name in CONTROLLER})
    return result


def make_jobs(tasks, output, source, plan, tasks_path, tests_path):
    jobs = []
    for si, seed in enumerate(plan['matrix']['seeds']):
        for ti, task in enumerate(tasks):
            case_index = si * len(tasks) + ti
            for agent, variant in enumerate(plan['agent_variants']):
                slot = (case_index + agent) % 4
                stem = f"{task['id']}-s{seed}-a{agent}-{variant}"
                events = output / (stem + '.jsonl')
                command = [sys.executable, str(source / 'coding_forced_worker.py'), '--run', '--variant', variant,
                           '--tasks', str(tasks_path), '--tests', str(tests_path), '--task-id', task['id'],
                           '--endpoint', ENDPOINTS[slot], '--host', HOSTS[slot],
                           '--seed', str(agent_seed(seed, agent, plan.get('agent_seed_offset', 0))),
                           '--events', str(events), '--model', 'nemotron-lightning']
                jobs.append(dict(task_id=task['id'], split=plan['matrix']['split'], arm=variant, seed=seed, agent=agent,
                                 case_index=case_index, slot=slot, endpoint=ENDPOINTS[slot], command=command,
                                 events=str(events), stdout=str(output / (stem + '.stdout.log')),
                                 stderr=str(output / (stem + '.stderr.log')), shared_endpoint=True, stop_on_solution=False))
    return jobs


def agent_outcome(events_path):
    records, _ = read_trace(Path(events_path))
    end = next((r for r in reversed(records) if r.get('type') == 'puzzle_end'), {})
    return dict(parsed=bool(end.get('parsed')), feedback_pass=bool(end.get('feedback_pass')),
                holdout_pass=bool(end.get('holdout_pass')), budget_forced=bool(end.get('budget_forced')))


def selection_curve(rows, order):
    """Case solved at size k = holdout result of the first of agents order[:k] that passes feedback."""
    cases = {}
    for row in rows:
        cases.setdefault((row['task_id'], row['seed']), {})[row['agent']] = row
    curve = {}
    for k in range(1, len(order) + 1):
        chosen = order[:k]
        full = [c for c in cases.values() if all(a in c for a in chosen)]
        solved = 0
        for case in full:
            pick = next((case[a] for a in chosen if case[a]['feedback_pass']), None)
            solved += bool(pick and pick['holdout_pass'])
        curve[k] = dict(cases=len(full), solved=solved)
    return curve


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    p.add_argument('--resume-from', type=Path, help='previous output: skip its agents that finished without an operational fault')
    a = p.parse_args(argv)
    plan = read(a.plan)
    require(plan['protocol'] == PROTOCOL, 'Wrong protocol')
    source, output = a.source.expanduser().resolve(), a.output.resolve()
    validate_source(source, plan['source_revision'])
    before = hashes(source)
    tasks_path, tests_path = HERE / plan['matrix']['tasks'], HERE / plan['matrix']['tests']
    require(sha(tasks_path) == plan['matrix']['tasks_sha256'] and sha(tests_path) == plan['matrix']['tests_sha256'],
            'Corpus hash differs')
    tasks = [t for t in read(tasks_path)['tasks'] if t['split'] == plan['matrix']['split']]
    require(len(tasks) == plan['matrix']['tasks_count'], 'Wrong task count')
    jobs = make_jobs(tasks, output, source, plan, tasks_path, tests_path)
    resumed = None
    if a.resume_from:  # continuation after an infrastructure stop: same plan, same seeds, only unfinished agents
        previous = read(a.resume_from / 'summary.json')
        finished = {Path(r['events']).name for r in previous if not operational_fault(r)}
        jobs = [j for j in jobs if Path(j['events']).name not in finished]
        resumed = dict(resumed_from=str(a.resume_from.resolve()), skipped_finished=len(finished))
    per_node, deadline = plan['scheduling']['concurrent_agents_per_node'], plan['limits']['agent_wall_deadline_seconds']
    meta = dict(protocol=plan, plan_sha256=sha(a.plan), jobs=len(jobs), source_sha256=before, output=str(output),
                resume=resumed)
    if not a.run:
        print(json.dumps(dict(mode='plan', jobs=len(jobs), model_calls=0, agents=len(plan['agent_variants']))))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not output.exists(), 'Frozen plan, admission and new output required')
    admission = read(a.admission)
    stamp = datetime.fromisoformat(admission['verified_utc'])
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    require(admission.get('verified') is True and 0 <= age <= 900, 'Fresh admission required')
    output.mkdir(parents=True)
    meta.update(started_utc=datetime.now(timezone.utc).isoformat(), admission=admission,
                server_before={e: server_metrics(e, timeout=3) for e in ENDPOINTS})
    write(output / 'metadata.json', meta)
    rows, errors, lock, stop = [], [], threading.Lock(), threading.Event()
    queues = {e: iter([j for j in jobs if j['endpoint'] == e]) for e in ENDPOINTS}
    start = time.monotonic()

    def worker(endpoint):
        while True:
            with lock:
                job = next(queues[endpoint], None)
                if job is None or stop.is_set():
                    return
                try:
                    changed = hashes(source) != before
                except Exception as exc:
                    stop.set()
                    errors.append(dict(reason='source_check_exception', detail=str(exc)[:300]))
                    return
                if changed:
                    stop.set()
                    errors.append(dict(reason='source_changed', events=job['events']))
                    return
            try:
                row = execute(job, deadline_seconds=deadline)
                row.update(agent=job['agent'], case_index=job['case_index'], **agent_outcome(job['events']))
            except Exception as exc:
                with lock:
                    stop.set()
                    errors.append(dict(reason='controller_exception', events=job['events'], detail=str(exc)[:300]))
                return
            with lock:
                rows.append(row)
                reason = operational_fault(row)
                if reason:
                    stop.set()
                    errors.append(dict(reason=reason, events=job['events']))
                write(output / 'summary.json', rows)
                print(json.dumps(dict(done=len(rows), total=len(jobs), task_id=row['task_id'], agent=row['agent'],
                                      feedback=row['feedback_pass'], holdout=row['holdout_pass'], status=row['status'])), flush=True)

    with ThreadPoolExecutor(max_workers=per_node * 4) as pool:
        for future in [pool.submit(worker, e) for e in ENDPOINTS for _ in range(per_node)]:
            future.result()
    variants = plan['agent_variants']
    groups = {v: [i for i, n in enumerate(variants) if n == v] for v in dict.fromkeys(variants)}
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), batch_wall_seconds=time.monotonic() - start,
                completed_jobs=len(rows), incomplete=len(rows) != len(jobs), errors=errors,
                server_after={e: server_metrics(e, timeout=3) for e in ENDPOINTS}, final_source_sha256=hashes(source),
                selection_curves={v: selection_curve(rows, order) for v, order in groups.items()},
                per_agent={v: dict(runs=sum(r['arm'] == v for r in rows), parsed=sum(r['arm'] == v and r['parsed'] for r in rows),
                                   feedback_pass=sum(r['arm'] == v and r['feedback_pass'] for r in rows),
                                   holdout_pass=sum(r['arm'] == v and r['holdout_pass'] for r in rows)) for v in groups})
    meta['source_changed_during_run'] = before != meta['final_source_sha256']
    write(output / 'metadata.json', meta)
    print(json.dumps(dict(curves=meta['selection_curves'], per_agent=meta['per_agent'])))
    return int(bool(errors) or meta['incomplete'] or meta['source_changed_during_run'])


if __name__ == '__main__':
    raise SystemExit(main())
