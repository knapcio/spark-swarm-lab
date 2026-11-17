#!/usr/bin/env python3
"""DeepSeek reference agents on the fresh arithmetic corpora (single owned endpoint).

Each agent is one unchanged frozen 638b9f3 followup72_worker process, variant index_original
(the earlier DeepSeek reference method: original prompt, one thinking call, 8192 cap, 210 s HTTP
timeout), model deepseek-v4.1-flash. Agents are independent; all run to completion.
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from run_agents72 import agent_seed, operational_fault, prefix_curve, read, require, sha, write
from run_benchmark import execute, server_metrics
from run_nemotron72_known import REVISION, hashes, validate_source

HERE = Path(__file__).resolve().parent
PROTOCOL = 'deepseek-fresh-reference-v1'
STREAM_WORKER = HERE / 'ds_stream_worker.py'


def make_jobs(corpora, output, source, plan, endpoint):
    jobs = []
    for corpus_name, tasks in corpora:
        for si, seed in enumerate(plan['seeds']):
            for ti, task in enumerate(tasks):
                for agent, variant in enumerate(plan['agent_variants']):
                    stem = f"{corpus_name}-{task['id']}-s{seed}-a{agent}-{variant}"
                    events = output / (stem + '.jsonl')
                    puzzle = ','.join(map(str, task['numbers'])) + ':' + str(task['target'])
                    agent_seed_value = str(agent_seed(seed, agent, plan['agent_seed_offset']))
                    if plan.get('transport') == 'stream':  # same method, streamed, no wall-clock cutoff
                        command = [sys.executable, str(HERE / 'ds_stream_worker.py'), '--run', '--puzzle', puzzle,
                                   '--endpoint', endpoint, '--seed', agent_seed_value, '--events', str(events),
                                   '--model', plan['model'], '--max-tokens', str(plan.get('max_tokens', 8192))]
                    else:
                        command = [sys.executable, str(source / 'followup72_worker.py'), '--run', '--variant', variant,
                                   '--puzzle', puzzle, '--endpoint', endpoint, '--seed', agent_seed_value,
                                   '--events', str(events), '--timeout', '210', '--model', plan['model']]
                    jobs.append(dict(task_id=task['id'], corpus=corpus_name, split='evaluation', arm=variant, seed=seed,
                                     agent=agent, endpoint=endpoint, command=command, events=str(events),
                                     stdout=str(output / (stem + '.stdout.log')), stderr=str(output / (stem + '.stderr.log')),
                                     shared_endpoint=True, stop_on_solution=False))
    return jobs


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, default=HERE / '.runtime/nemotron72-followup-source')
    p.add_argument('--endpoint', default='http://127.0.0.1:18889/v1')
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    plan = read(a.plan)
    require(plan['protocol'] == PROTOCOL, 'Wrong protocol')
    source, output = a.source.resolve(), a.output.resolve()
    validate_source(source)
    before = hashes(source)
    if plan.get('transport') == 'stream':
        before['ds_stream_worker.py'] = sha(STREAM_WORKER)
    corpora = []
    for name, rel in plan['corpora'].items():
        if name not in plan.get('run_corpora', plan['corpora']):
            continue
        data = read(HERE / rel)
        if isinstance(plan['corpora_sha256'], dict):
            require(sha(HERE / rel) == plan['corpora_sha256'][name], 'Corpus hash differs: ' + name)
        else:  # corpus generated after the plan froze: check its protocol, hash is recorded in run metadata
            require(data.get('protocol') == plan.get('corpora_protocol', {}).get(name), 'Wrong corpus protocol: ' + name)
        corpora.append((name, [t for t in data['tasks'] if t['split'] == 'evaluation']))
    jobs = make_jobs(corpora, output, source, plan, a.endpoint)
    if plan.get('case_filter_file'):  # e.g. hybrid routing: only cases the Nemotron swarm abstained on (+ a baseline seed)
        keep = {(t, int(sd)) for t, sd in read(HERE / plan['case_filter_file'])}
        jobs = [j for j in jobs if (j['task_id'], int(j['seed'])) in keep]
    meta = dict(protocol=plan, plan_sha256=sha(a.plan), jobs=len(jobs), source_sha256=before, solver_revision=REVISION,
                endpoint=a.endpoint, output=str(output))
    if not a.run:
        print(json.dumps(dict(mode='plan', jobs=len(jobs), model_calls=0)))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not output.exists(), 'Frozen plan, admission, new output')
    admission = read(a.admission)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(admission['verified_utc'])).total_seconds()
    require(admission.get('verified') is True and 0 <= age <= 900, 'Fresh admission required')
    output.mkdir(parents=True)
    meta.update(started_utc=datetime.now(timezone.utc).isoformat(), admission=admission,
                server_before=server_metrics(a.endpoint, timeout=3))
    write(output / 'metadata.json', meta)
    rows, errors, lock, stop = [], [], threading.Lock(), threading.Event()
    queue = iter(jobs)
    start = time.monotonic()

    def worker():
        while True:
            with lock:
                job = next(queue, None)
                if job is None or stop.is_set():
                    return
                current = hashes(source)
                if plan.get('transport') == 'stream':
                    current['ds_stream_worker.py'] = sha(STREAM_WORKER)
                if current != before:
                    stop.set()
                    errors.append(dict(reason='source_changed'))
                    return
            try:
                row = execute(job, deadline_seconds=plan['agent_wall_deadline_seconds'])
                row.update(agent=job['agent'], corpus=job['corpus'])
            except Exception as exc:
                with lock:
                    stop.set()
                    errors.append(dict(reason='controller_exception', detail=str(exc)[:300]))
                return
            with lock:
                rows.append(row)
                reason = operational_fault(row)
                if reason:
                    stop.set()
                    errors.append(dict(reason=reason, events=job['events']))
                write(output / 'summary.json', rows)
                print(json.dumps(dict(done=len(rows), total=len(jobs), corpus=row['corpus'], task_id=row['task_id'],
                                      agent=row['agent'], solved=row['solved'], status=row['status'])), flush=True)

    with ThreadPoolExecutor(max_workers=plan['concurrency']) as pool:
        for future in [pool.submit(worker) for _ in range(plan['concurrency'])]:
            future.result()
    curves = {name: prefix_curve([r for r in rows if r['corpus'] == name], list(range(len(plan['agent_variants']))))
              for name in plan['corpora']}
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), batch_wall_seconds=time.monotonic() - start,
                completed_jobs=len(rows), incomplete=len(rows) != len(jobs), errors=errors, curves=curves,
                server_after=server_metrics(a.endpoint, timeout=3),
                final_source_sha256=dict(hashes(source), **({'ds_stream_worker.py': sha(STREAM_WORKER)} if plan.get('transport') == 'stream' else {})))
    meta['source_changed_during_run'] = before != meta['final_source_sha256']
    write(output / 'metadata.json', meta)
    print(json.dumps(curves))
    return int(bool(errors) or meta['incomplete'] or meta['source_changed_during_run'])


if __name__ == '__main__':
    raise SystemExit(main())
