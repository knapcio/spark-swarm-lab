#!/usr/bin/env python3
"""Coding swarm with early stop: run_coding_agents.py, plus a per-case stop as soon as one agent's proposal passes ALL
public feedback cases. The remaining agents of that case are terminated at once (process group; the shim closes the
upstream stream and SGLang aborts) and queued agents of that case never start. Answer = the first feedback-passing
proposal in TIME order; the case is solved if it passes the hidden holdout (graded by the worker, never read by the
controller). Same jobs, seeds, endpoints, grading and fault rules as run_coding_agents.py; a terminated agent is a
controller decision, not an operational fault. Optional plan field stagger = {"first": k, "after_seconds": T}: agents
k.. of a case start only if the case has no passing proposal T seconds after its first agent started. Plan-only by default.
"""
import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from run_agents72 import operational_fault, read, require, sha, validate_source, write
from run_benchmark import read_trace, server_metrics
from run_coding_agents import ENDPOINTS, HERE, PROTOCOL, agent_outcome, hashes, make_jobs
from run_variants import execute_cancellable


def fault(row):
    if row.get('cancelled'):
        return 'controller_or_transport_failure' if row['controller_error'] or row['malformed_lines'] else None
    return operational_fault(row)


def cases_summary(rows, jobs):
    cases = {}
    for job in jobs:
        cases.setdefault((job['task_id'], job['seed']), dict(agents=0))['agents'] += 1
    for (task, seed), case in cases.items():
        mine = [r for r in rows if (r['task_id'], r['seed']) == (task, seed)]
        winner = next((r for r in mine if r.get('winner')), None)
        case.update(task_id=task, seed=seed, answered=winner is not None,
                    solved=bool(winner and winner['holdout_pass']), winner_agent=winner['agent'] if winner else None,
                    started=len(mine), cancelled=sum(bool(r.get('cancelled')) for r in mine),
                    never_started=case['agents'] - len(mine),
                    completion_tokens=sum(r['completion_tokens'] or 0 for r in mine),
                    stop_seconds=winner['stop_seconds'] if winner else None)
    return list(cases.values())


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    plan = read(a.plan)
    require(plan['protocol'] == PROTOCOL and plan.get('early_stop') == 'first_feedback_pass_in_time', 'Wrong protocol')
    source, output = a.source.expanduser().resolve(), a.output.resolve()
    validate_source(source, plan['source_revision'])
    before = hashes(source)
    tasks_path, tests_path = HERE / plan['matrix']['tasks'], HERE / plan['matrix']['tests']
    require(sha(tasks_path) == plan['matrix']['tasks_sha256'] and sha(tests_path) == plan['matrix']['tests_sha256'],
            'Corpus hash differs')
    tasks = [t for t in read(tasks_path)['tasks'] if t['split'] == plan['matrix']['split']]
    if plan['matrix'].get('task_ids'):  # optional subset (smoke plans)
        tasks = [t for t in tasks if t['id'] in plan['matrix']['task_ids']]
    require(len(tasks) == plan['matrix']['tasks_count'], 'Wrong task count')
    jobs = make_jobs(tasks, output, source, plan, tasks_path, tests_path)
    per_node, deadline = plan['scheduling']['concurrent_agents_per_node'], plan['limits']['agent_wall_deadline_seconds']
    meta = dict(protocol=plan, plan_sha256=sha(a.plan), jobs=len(jobs), source_sha256=before, output=str(output),
                runner_sha256=sha(Path(__file__)))
    if not a.run:
        print(json.dumps(dict(mode='plan', jobs=len(jobs), model_calls=0, agents=len(plan['agent_variants']))))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not output.exists(), 'Frozen plan, admission and new output required')
    admission = read(a.admission)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(admission['verified_utc'])).total_seconds()
    require(admission.get('verified') is True and 0 <= age <= 900, 'Fresh admission required')
    output.mkdir(parents=True)
    meta.update(started_utc=datetime.now(timezone.utc).isoformat(), admission=admission,
                server_before={e: server_metrics(e, timeout=3) for e in ENDPOINTS})
    write(output / 'metadata.json', meta)
    rows, errors, lock, stop = [], [], threading.Lock(), threading.Event()
    cancel = {(j['task_id'], j['seed']): threading.Event() for j in jobs}
    first_start, first_done = {}, {}
    stagger = plan.get('stagger')
    first_k = stagger['first'] if stagger else len(plan['agent_variants'])
    queues = {e: iter([j for j in jobs if j['endpoint'] == e and j['agent'] < first_k]) for e in ENDPOINTS}
    later = {e: [j for j in jobs if j['endpoint'] == e and j['agent'] >= first_k] for e in ENDPOINTS}
    start = time.monotonic()

    def take(endpoint):
        """Next job for this endpoint (caller holds the lock): a due later agent of an open case first, else the next
        first-wave agent of an open case. Returns (job, waiting) where waiting means later agents are not due yet."""
        pending = later[endpoint]
        pending[:] = [j for j in pending if not cancel[(j['task_id'], j['seed'])].is_set()]  # answered: never start
        now = time.monotonic()
        for j in pending:
            k = (j['task_id'], j['seed'])
            if k in first_start and (now - first_start[k] >= stagger['after_seconds'] or first_done.get(k, 0) >= first_k):
                pending.remove(j)
                return j, False
        job = next(queues[endpoint], None)
        while job is not None and cancel[(job['task_id'], job['seed'])].is_set():
            job = next(queues[endpoint], None)  # case already answered: this agent never starts
        return job, bool(pending)

    def worker(endpoint):
        while True:
            with lock:
                if stop.is_set():
                    return
                job, waiting = take(endpoint)
            if job is None:
                if not waiting:
                    return
                time.sleep(2)
                continue
            with lock:
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
                key = (job['task_id'], job['seed'])
                first_start.setdefault(key, time.monotonic())
            try:
                row = execute_cancellable(job, deadline, cancel[key])
                row.update({k: job[k] for k in ('task_id', 'split', 'arm', 'seed', 'endpoint', 'events')},
                           agent=job['agent'], case_index=job['case_index'], malformed_lines=read_trace(Path(job['events']))[1],
                           **agent_outcome(job['events']))
                if row['cancelled']:
                    row.update(feedback_pass=False, holdout_pass=False)  # a terminated agent has no answer
            except Exception as exc:
                with lock:
                    stop.set()
                    errors.append(dict(reason='controller_exception', events=job['events'], detail=str(exc)[:300]))
                return
            with lock:
                if job['agent'] < first_k:
                    first_done[key] = first_done.get(key, 0) + 1
                row['winner'] = False
                if row['feedback_pass'] and not cancel[key].is_set():
                    row.update(winner=True, stop_seconds=round(time.monotonic() - first_start[key], 1))
                    cancel[key].set()
                rows.append(row)
                reason = fault(row)
                if reason:
                    stop.set()
                    errors.append(dict(reason=reason, events=job['events']))
                write(output / 'summary.json', rows)
                print(json.dumps(dict(done=len(rows), total=len(jobs), task_id=row['task_id'], agent=row['agent'],
                                      feedback=row['feedback_pass'], cancelled=row['cancelled'], winner=row['winner'],
                                      status=row['status'])), flush=True)

    with ThreadPoolExecutor(max_workers=per_node * 4) as pool:
        for future in [pool.submit(worker, e) for e in ENDPOINTS for _ in range(per_node)]:
            future.result()
    cases = cases_summary(rows, jobs)
    write(output / 'cases.json', cases)
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), batch_wall_seconds=time.monotonic() - start,
                started_jobs=len(rows), errors=errors, server_after={e: server_metrics(e, timeout=3) for e in ENDPOINTS},
                final_source_sha256=hashes(source),
                summary=dict(cases=len(cases), solved=sum(c['solved'] for c in cases), answered=sum(c['answered'] for c in cases),
                             cancelled=sum(c['cancelled'] for c in cases), never_started=sum(c['never_started'] for c in cases)))
    meta['source_changed_during_run'] = before != meta['final_source_sha256']
    write(output / 'metadata.json', meta)
    print(json.dumps(meta['summary']))
    return int(bool(errors) or meta['source_changed_during_run'])


if __name__ == '__main__':
    raise SystemExit(main())
