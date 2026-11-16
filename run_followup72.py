#!/usr/bin/env python3
"""Fixed 168-case development comparison; plan-only by default."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from followup72 import VARIANTS
from run_benchmark import FIELDS, execute

HERE = Path(__file__).resolve().parent
DATASET = HERE / 'datasets/arithmetic-v1/tasks.json'
PROTOCOL = HERE / 'FOLLOWUP72_DEVELOPMENT_PLAN.json'
SOURCES = ('run_followup72.py', 'followup72_worker.py', 'followup72.py', 'followup72_client.py', 'harness.py',
           'direct_solver.py', 'run_benchmark.py', 'runtime.json',
           'FOLLOWUP72_DEVELOPMENT_PLAN.json', 'datasets/arithmetic-v1/tasks.json')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes():
    return {n: sha(HERE / n) for n in SOURCES}


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def make_cases(dataset, directory, endpoints):
    require(len(endpoints) == len(set(endpoints)) == 4, 'Four distinct endpoints required')
    tasks = [t for t in dataset['tasks'] if t['split'] == 'development']
    require(len(tasks) == len({t['id'] for t in tasks}) == 8, 'Exactly eight distinct development tasks')
    require([len(t['numbers']) for t in tasks] == [4, 6] * 4, 'Preserve balanced generator task order')
    cases = []
    for seed in (1, 2, 3):
        for task in tasks:
            block = (seed - 1) * 8 + tasks.index(task)
            rotation = (block // 4) % len(VARIANTS)
            order = VARIANTS[rotation:] + VARIANTS[:rotation]
            for position, variant in enumerate(order):
                slot = (7 * block + position) % 4
                stem = f"{task['id']}-{variant}-s{seed}"
                events = directory / (stem + '.jsonl')
                command = [sys.executable, str(HERE / 'followup72_worker.py'), '--run',
                           '--variant', variant, '--puzzle', ','.join(map(str, task['numbers'])) + ':' + str(task['target']),
                           '--endpoint', endpoints[slot], '--seed', str(seed), '--events', str(events),
                           '--timeout', '210', '--model', 'nemotron-lightning']
                cases.append(dict(task_id=task['id'], split='development', arm=variant, seed=seed,
                                  block=block, position=position, slot=slot, endpoint=endpoints[slot], command=command,
                                  events=str(events), stdout=str(directory / (stem + '.stdout.log')),
                                  stderr=str(directory / (stem + '.stderr.log')),
                                  server_metrics=True, stop_on_solution=False))
    require(len(cases) == 168, 'Wrong development matrix')
    return cases


def schedule_sha(cases):
    rows = [dict(block=c['block'], position=c['position'], task_id=c['task_id'],
                 seed=c['seed'], variant=c['arm'], node=c['slot'] + 1) for c in cases]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def operational_fault(row):
    # A controlled deadline, truncated answer or verifier failure remains a task outcome.
    if (row['controller_error'] or row['malformed_lines'] or row['infrastructure_failures']
            or (row['returncode'] != 0 and not row['controller_stop'])):
        return 'controller_or_transport_failure'
    if not (1 <= row['calls'] <= 2 and 0 <= row['completed_calls'] <= row['calls']
            and row['unfinished_calls'] == row['calls'] - row['completed_calls']):
        return 'missing_or_inconsistent_request_lifecycle'
    if not row['deadline'] and (row['unfinished_calls'] or row['infrastructure_failures'] is None
                               or row['status'] not in ('complete', 'budget_limited')):
        return 'unexpected_completion_state'
    if row['server_idle_after'] is not True or row['server_cost_known'] is not True:
        return 'endpoint_drain_or_counter_accounting_unknown'
    return None


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--endpoint', action='append')
    p.add_argument('--admission', type=Path)
    p.add_argument('--plan-file', type=Path)
    p.add_argument('--run', action='store_true')
    args = p.parse_args(argv)
    directory = args.output.resolve()
    endpoints = args.endpoint or [f'http://127.0.0.1:{port}/v1' for port in range(18081, 18085)]
    plan = json.loads(PROTOCOL.read_text())
    require(plan['protocol'] == 'nemotron72-development-v1', 'Wrong protocol')
    before = source_hashes()
    cases = make_cases(json.loads(DATASET.read_text()), directory, endpoints)
    require(plan['matrix']['dataset_sha256'] == sha(DATASET), 'Protocol dataset differs')
    require(plan['matrix']['variants'] == list(VARIANTS), 'Protocol variant order differs')
    require(plan['scheduling']['canonical_schedule_sha256'] == schedule_sha(cases), 'Schedule differs')
    meta = dict(protocol=plan, mode='run' if args.run else 'plan', cases=cases, attempts=168,
                distinct_development_tasks=8, seeds=[1, 2, 3], source_sha256=before,
                source_revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=HERE, text=True).strip(),
                controller_deadline_seconds=180, request_timeout_seconds=210,
                global_completion_cap_per_case=8192, maximum_calls_per_case=2,
                scheduling='24 seven-variant blocks; barrier after each block; one active case per node',
                stop_policy='Stop new case admission after a fault; admitted cases may finish; no next block',
                scope='Development recipe selection, not untouched generalization or fleet throughput',
                schedule_sha256=schedule_sha(cases), output=str(directory))
    if not args.run:
        if args.plan_file:
            require(not args.plan_file.exists(), 'Plan file already exists')
            write_json(args.plan_file, meta)
        print(json.dumps(dict(mode='plan', cases=168, tasks=8, variants=list(VARIANTS), model_calls=0)))
        return 0
    require(plan['status'] == 'FROZEN', 'Protocol must be frozen before inference')
    require(not directory.exists() and args.admission, 'New output and fresh admission required')
    admission = json.loads(args.admission.read_text())
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(admission['verified_utc'])).total_seconds()
    require(admission.get('verified') is True and 0 <= age <= 900, 'Runtime admission absent/stale')
    require(admission['source_sha256'] == before and admission['endpoints'] == endpoints,
            'Admission does not bind this source and endpoints')
    require(admission.get('runtime_identical_to_study_v032') is True, 'Unqualified serving recipe')
    directory.mkdir(parents=True)
    meta.update(started_utc=datetime.now(timezone.utc).isoformat(), admission_sha256=sha(args.admission),
                admission=admission)
    write_json(directory / 'metadata.json', meta)
    rows, errors, attempted, lock, stop = [], [], [], threading.Lock(), threading.Event()

    def slot_worker(slot, block):
        for case in (c for c in cases if c['block'] == block and c['slot'] == slot):
            with lock:
                if stop.is_set():
                    return
                attempted.append(case['events'])
            try:
                row = execute(case, deadline_seconds=180)
                with lock:
                    rows.append(row)
                    write_json(directory / 'summary.json', rows)
                    with (directory / 'summary.csv').open('w', newline='') as stream:
                        writer = csv.DictWriter(stream, fieldnames=FIELDS)
                        writer.writeheader()
                        writer.writerows({k: json.dumps(v) if isinstance(v, dict) else v for k, v in r.items()} for r in rows)
                    reason = operational_fault(row)
                    if reason:
                        stop.set()
                        errors.append(dict(events=case['events'], reason=reason))
                    print(json.dumps(dict(completed=len(rows), total=168, task_id=case['task_id'],
                                          variant=case['arm'], seed=case['seed'], status=row['status'])), flush=True)
            except Exception as exc:
                stop.set()
                with lock:
                    errors.append(dict(events=case['events'], reason='controller_exception',
                                       detail=f'{type(exc).__name__}: {exc}'))
                return

    start = time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for block in range(24):
                if source_hashes() != before:
                    errors.append(dict(reason='source_changed_before_block', block=block))
                    break
                list(pool.map(lambda slot: slot_worker(slot, block), range(4)))
                if errors:
                    break
    except Exception as exc:
        errors.append(dict(reason='controller_exception', detail=f'{type(exc).__name__}: {exc}'))
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), batch_wall_seconds=time.monotonic() - start,
                completed_cases=len(rows), incomplete=len(rows) != 168, errors=errors,
                attempted_case_events=attempted,
                final_source_sha256=source_hashes())
    meta['source_changed_during_run'] = before != meta['final_source_sha256']
    meta['output_sha256'] = {x.name: sha(x) for x in directory.iterdir() if x.is_file() and x.name != 'metadata.json'}
    write_json(directory / 'metadata.json', meta)
    return int(bool(errors) or meta['incomplete'] or meta['source_changed_during_run'])


if __name__ == '__main__':
    raise SystemExit(main())
