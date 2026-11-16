#!/usr/bin/env python3
"""Independent-agent replay (generic worker arguments) on the known arithmetic suite.

Same matrix, placement and accounting as run_swarm72.py; the plan supplies the worker
arguments, so workers without the frozen 210 s HTTP timeout can run. Wall deadline is a
catastrophe stop only.

Each case is attacked by K independent agents. Every agent is one unchanged
frozen `followup72_worker.py` process (source 638b9f3) with its own budget
Budget(2, 8192), its own sampling seed and no shared memory. A case counts as
solved when at least one agent's plan passes the original exact verifier.

All agents run to completion (no early stop), so success for every swarm size
k <= K can be read from the same raw data. Agents of one case are spread over
all four replicas. The binding budget is tokens per agent; the wall deadline is
a safety stop only, because per-request speed depends on concurrency.

No CPU search, teacher, gold answers or cross-case memory. Plan-only by default.
"""
import argparse
import csv
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from run_benchmark import FIELDS, execute, server_metrics
from run_nemotron72_known import REVISION, SOLVER, read, require, sha, write

HERE = Path(__file__).resolve().parent
PROTOCOL = 'nemotron72-known-agents-v2'


def git(source, *args):
    return subprocess.check_output(['git', *args], cwd=source, text=True)


def validate_source(source, revision):
    """Clean checkout at the planned revision; the frozen 638b9f3 solver files are byte-identical."""
    require(source.is_absolute() and source.is_dir(), 'Absolute existing source required')
    require(git(source, 'rev-parse', 'HEAD').strip() == revision, 'Wrong source revision')
    dirty = [line for line in git(source, 'status', '--porcelain').splitlines() if '__pycache__' not in line]
    require(not dirty, 'Source has local or untracked changes')
    require(git(source, 'diff', '--name-only', REVISION, revision, '--', *SOLVER).strip() == '',
            'Frozen solver files differ from ' + REVISION)


CONTROLLER = ('run_agents72.py', 'run_benchmark.py', 'run_nemotron72_known.py')


def hashes(source):
    """Solver source plus the main-repo controller files that actually run."""
    tracked = git(source, 'ls-files').split()
    result = {name: sha(source / name) for name in tracked if name.endswith(('.py', '.json'))}
    result.update({'controller/' + name: sha(HERE / name) for name in CONTROLLER})
    return result


def agent_seed(case_seed, agent, offset=0):
    """Seeds never collide with the single-agent seeds 1, 2, 3; offset separates experiments."""
    return 1000 * case_seed + offset + agent


def make_jobs(tasks, output, endpoints, source, plan):
    variants = plan['agent_variants']
    seeds = plan['matrix']['seeds']
    require(len(endpoints) == len(set(endpoints)) == 4, 'Four distinct endpoints required')
    expected = plan['matrix'].get('expected_task_ids_in_stored_order')
    if expected is not None:
        require([t['id'] for t in tasks] == expected, 'Wrong stored evaluation task IDs')
    else:  # corpus generated after the plan froze: count and balance are fixed instead
        require(len(tasks) == plan['matrix']['tasks'] and len({t['id'] for t in tasks}) == len(tasks),
                'Wrong evaluation task count')
    jobs = []
    for si, seed in enumerate(seeds):
        for ti, task in enumerate(tasks):
            case_index = si * len(tasks) + ti
            for agent, variant in enumerate(variants):
                slot = (case_index + agent) % 4
                stem = f"{task['id']}-s{seed}-a{agent}-{variant}"
                command = [sys.executable, str(source / plan['workers'][variant]), '--run', '--variant', variant,
                           '--puzzle', ','.join(map(str, task['numbers'])) + ':' + str(task['target']),
                           '--endpoint', endpoints[slot], '--seed', str(agent_seed(seed, agent, plan.get('agent_seed_offset', 0))),
                           '--events', str(output / (stem + '.jsonl')), *plan.get('extra_worker_args', []),
                           '--model', 'nemotron-lightning']
                jobs.append(dict(task_id=task['id'], split='evaluation', arm=variant, seed=seed, agent=agent,
                                 agent_seed=agent_seed(seed, agent, plan.get('agent_seed_offset', 0)), case_index=case_index, slot=slot,
                                 endpoint=endpoints[slot], command=command, events=str(output / (stem + '.jsonl')),
                                 stdout=str(output / (stem + '.stdout.log')), stderr=str(output / (stem + '.stderr.log')),
                                 shared_endpoint=True, stop_on_solution=False))
    return jobs


def operational_fault(row):
    if row['controller_error'] or row['malformed_lines'] or row['infrastructure_failures']:
        return 'controller_or_transport_failure'
    if row['returncode'] != 0 and not row['controller_stop']:
        return 'process_failure'
    if not row['deadline'] and (row['calls'] < 1 or row['unfinished_calls'] or
                                row['status'] not in ('complete', 'budget_limited')):
        return 'unexpected_completion_state'
    return None


def prefix_curve(rows, order):
    """Case success using the first k agents of a fixed agent order (fixed before any call)."""
    cases = {}
    for row in rows:
        cases.setdefault((row['task_id'], row['seed']), {})[row['agent']] = bool(row['solved'])
    result = {}
    for k in range(1, len(order) + 1):
        chosen = order[:k]
        complete = [c for c in cases.values() if all(a in c for a in chosen)]
        result[k] = dict(cases=len(complete), solved=sum(any(c[a] for a in chosen) for c in complete))
    return result


def summarize(rows, variants):
    """Mixed curve over all agents, homogeneous curve per variant, per-agent rate and token cost."""
    by_variant = {v: [a for a, name in enumerate(variants) if name == v] for v in dict.fromkeys(variants)}
    solved_cases = {(r['task_id'], r['seed']) for r in rows if r['solved']}
    return dict(
        mixed=prefix_curve(rows, list(range(len(variants)))),
        per_variant={v: prefix_curve(rows, order) for v, order in by_variant.items()},
        per_agent_success={v: dict(runs=sum(r['arm'] == v for r in rows), solved=sum(r['arm'] == v and bool(r['solved']) for r in rows))
                           for v in by_variant},
        completion_tokens=sum(r['completion_tokens'] or 0 for r in rows),
        solved_cases=len(solved_cases),
        completion_tokens_per_solved_case=(sum(r['completion_tokens'] or 0 for r in rows) / len(solved_cases)) if solved_cases else None)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    plan = read(a.plan)
    require(plan['protocol'] == PROTOCOL, 'Wrong protocol')
    source, output = a.source.expanduser().resolve(), a.output.resolve()
    validate_source(source, plan['source_revision'])
    before = hashes(source)
    if 'dataset_sha256' in plan['matrix']:
        dataset = source / plan['matrix']['dataset']
        require(sha(dataset) == plan['matrix']['dataset_sha256'], 'Corpus hash differs')
    else:  # fresh corpus in the main repo; its protocol is pinned and its hash is recorded
        dataset = HERE / plan['matrix']['dataset']
        require(read(dataset).get('protocol') == plan['matrix']['dataset_protocol'], 'Wrong corpus protocol')
    tasks = [t for t in read(dataset)['tasks'] if t['split'] == plan['matrix'].get('split', 'evaluation')]
    endpoints = [f'http://127.0.0.1:{port}/v1' for port in range(18081, 18085)]
    jobs = make_jobs(tasks, output, endpoints, source, plan)
    per_node = plan['scheduling']['concurrent_agents_per_node']
    deadline = plan['limits']['agent_wall_deadline_seconds']
    meta = dict(protocol=plan, plan_sha256=sha(a.plan), runner_sha256=sha(Path(__file__)), jobs=len(jobs),
                dataset=str(dataset), dataset_sha256=sha(dataset),
                source_sha256=before, source_revision=plan['source_revision'], output=str(output))
    if not a.run:
        print(json.dumps(dict(mode='plan', jobs=len(jobs), model_calls=0, agents=len(plan['agent_variants']))))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not output.exists(),
            'Frozen plan, admission and new output required')
    admission = read(a.admission)
    stamp = datetime.fromisoformat(admission['verified_utc'])
    require(stamp.utcoffset() is not None and stamp.utcoffset().total_seconds() == 0, 'UTC admission stamp required')
    age = (datetime.now(timezone.utc) - stamp).total_seconds()
    require(admission.get('verified') is True and admission.get('all_four_owned_healthy_idle') is True
            and 0 <= age <= 900 and admission.get('source_sha256') == before, 'Fresh admission required')
    output.mkdir(parents=True)
    meta.update(started_utc=datetime.now(timezone.utc).isoformat(), admission=admission,
                admission_sha256=sha(a.admission),
                server_before={e: server_metrics(e, timeout=3) for e in endpoints})
    write(output / 'metadata.json', meta)
    rows, errors, lock, stop = [], [], threading.Lock(), threading.Event()
    queues = {e: iter([j for j in jobs if j['endpoint'] == e]) for e in endpoints}
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
                    errors.append(dict(reason='source_check_exception', detail=f'{type(exc).__name__}: {exc}'))
                    return
                if changed:
                    stop.set()
                    errors.append(dict(reason='source_changed', events=job['events']))
                    return
            run(job)

    def run(job):
        try:
            row = execute(job, deadline_seconds=deadline)
        except Exception as exc:  # local controller fault: stop new admissions
            with lock:
                stop.set()
                errors.append(dict(reason='controller_exception', events=job['events'],
                                   detail=f'{type(exc).__name__}: {exc}'))
            return
        row.update(agent=job['agent'], agent_seed=job['agent_seed'], case_index=job['case_index'])
        with lock:
            rows.append(row)
            reason = operational_fault(row)
            if reason:
                stop.set()
                errors.append(dict(reason=reason, events=job['events']))
            write(output / 'summary.json', rows)
            print(json.dumps(dict(done=len(rows), total=len(jobs), task_id=row['task_id'], seed=row['seed'],
                                  agent=row['agent'], solved=row['solved'], status=row['status'])), flush=True)

    # Per-replica queues in case order; exactly `per_node` agents in flight on each replica.
    with ThreadPoolExecutor(max_workers=per_node * 4) as pool:
        for future in [pool.submit(worker, e) for e in endpoints for _ in range(per_node)]:
            future.result()
    fields = FIELDS + ['agent', 'agent_seed', 'case_index']
    with (output / 'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows({k: json.dumps(v) if isinstance(v, dict) else v for k, v in r.items()} for r in rows)
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), batch_wall_seconds=time.monotonic() - start,
                completed_jobs=len(rows), incomplete=len(rows) != len(jobs), errors=errors,
                server_after={e: server_metrics(e, timeout=3) for e in endpoints},
                final_source_sha256=hashes(source), swarm_summary=summarize(rows, plan['agent_variants']))
    meta['source_changed_during_run'] = before != meta['final_source_sha256']
    write(output / 'metadata.json', meta)
    print(json.dumps(meta['swarm_summary']))
    return int(bool(errors) or meta['incomplete'] or meta['source_changed_during_run'])


if __name__ == '__main__':
    raise SystemExit(main())
