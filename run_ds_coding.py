#!/usr/bin/env python3
"""DeepSeek coding reference on coding-hard-v1 evaluation (24 tasks x 3 seeds, one call each). Plan-only by default."""
import argparse, json, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from run_agents72 import agent_seed, operational_fault, read, require, sha, write
from run_benchmark import execute, read_trace

HERE = Path(__file__).resolve().parent
HOSTS = ['Spark_01', 'Spark_02', 'Spark_03', 'Spark_04']


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--endpoint', default='http://127.0.0.1:18889/v1')
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    plan = read(a.plan)
    require(plan['protocol'] == 'deepseek-coding-reference-v1', 'Wrong protocol')
    tasks_path, tests_path = HERE / plan['tasks'], HERE / plan['tests']
    require(sha(tasks_path) == plan['tasks_sha256'] and sha(tests_path) == plan['tests_sha256'], 'Corpus hash differs')
    tasks = [t for t in read(tasks_path)['tasks'] if t['split'] == 'evaluation']
    out = a.output.resolve()
    jobs = []
    for seed in plan['seeds']:
        for i, t in enumerate(tasks):
            stem = f"{t['id']}-s{seed}-a0-ds_code"
            jobs.append(dict(task_id=t['id'], split='evaluation', arm='ds_code', seed=seed, agent=0, endpoint=a.endpoint,
                             command=[sys.executable, str(HERE / 'ds_coding_worker.py'), '--run', '--tasks', str(tasks_path),
                                      '--tests', str(tests_path), '--task-id', t['id'], '--endpoint', a.endpoint,
                                      '--host', HOSTS[(i + seed) % 4], '--model', plan['model'],
                                      '--seed', str(agent_seed(seed, 0, plan['agent_seed_offset'])),
                                      '--max-tokens', str(plan['max_tokens']), '--events', str(out / (stem + '.jsonl'))],
                             events=str(out / (stem + '.jsonl')), stdout=str(out / (stem + '.stdout.log')),
                             stderr=str(out / (stem + '.stderr.log')), shared_endpoint=True, stop_on_solution=False))
    if not a.run:
        print(json.dumps(dict(mode='plan', jobs=len(jobs), model_calls=0)))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not out.exists(), 'Frozen plan, admission, new output')
    adm = read(a.admission)
    require(adm.get('verified') is True and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(adm['verified_utc'])).total_seconds() <= 900, 'Fresh admission')
    out.mkdir(parents=True)
    meta = dict(protocol=plan, started_utc=datetime.now(timezone.utc).isoformat(), worker_sha256=sha(HERE / 'ds_coding_worker.py'),
                stream_sha256=sha(HERE / 'ds_stream_worker.py'), admission=adm)
    write(out / 'metadata.json', meta)
    rows, errors, lock, stop, queue = [], [], threading.Lock(), threading.Event(), iter(jobs)

    def worker():
        while True:
            with lock:
                job = next(queue, None)
                if job is None or stop.is_set():
                    return
            row = execute(job, deadline_seconds=plan['agent_wall_deadline_seconds'])
            recs, _ = read_trace(Path(job['events']))
            end = next((r for r in reversed(recs) if r.get('type') == 'puzzle_end'), {})
            row.update(agent=0, parsed=bool(end.get('parsed')), feedback_pass=bool(end.get('feedback_pass')),
                       holdout_pass=bool(end.get('holdout_pass')), finish_reason=end.get('finish_reason'))
            with lock:
                rows.append(row)
                reason = operational_fault(row)
                if reason:
                    stop.set(); errors.append(dict(reason=reason, events=job['events']))
                write(out / 'summary.json', rows)
                print(json.dumps(dict(done=len(rows), total=len(jobs), task=row['task_id'], fb=row['feedback_pass'], ho=row['holdout_pass'])), flush=True)

    with ThreadPoolExecutor(plan['concurrency']) as pool:
        for f in [pool.submit(worker) for _ in range(plan['concurrency'])]:
            f.result()
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), completed_jobs=len(rows), errors=errors,
                solved=sum(r['feedback_pass'] and r['holdout_pass'] for r in rows), holdout_pass=sum(r['holdout_pass'] for r in rows))
    write(out / 'metadata.json', meta)
    print(json.dumps(dict(done=len(rows), solved=meta['solved'], errors=errors)))
    return int(bool(errors) or len(rows) != len(jobs))


if __name__ == '__main__':
    raise SystemExit(main())
