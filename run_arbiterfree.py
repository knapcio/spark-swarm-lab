#!/usr/bin/env python3
"""Arbiter-free Nemotron swarm with escalation, run live (no external verifier in the loop).

Per case: stage A runs 4 short budget-forced agents (forced_explicit, 8K). Every parsed plan is
judged by a Nemotron thinking judge (run_judge.judge, mode 'think') that sees only the task and the
raw plan. If the judge accepts any plan, the first accepted plan in agent order is the answer.
Otherwise stage B runs 4 deep agents (long_forced_original, 16K) and judges them the same way.
If nothing is accepted, the swarm gives no answer. The exact verifier only SCORES the selected plan
afterwards (each worker's own replay result is recorded but never read by the controller logic).
Plan-only by default.
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from run_agents72 import agent_seed, read, require, sha, validate_source, write
from run_benchmark import execute, read_trace
import run_judge

HERE = Path(__file__).resolve().parent
ENDPOINTS = [f'http://127.0.0.1:{p}/v1' for p in range(18081, 18085)]


class Slots:
    """Per-endpoint cap on concurrent model requests (agents and judges share it)."""
    def __init__(self, per_endpoint):
        self.sem = {e: threading.BoundedSemaphore(per_endpoint) for e in ENDPOINTS}

    def __call__(self, endpoint):
        return self.sem[endpoint]


def agent_job(plan, source, out, task, seed, case_index, stage, agent, variant, offset):
    endpoint = ENDPOINTS[(case_index + agent) % 4]
    stem = f"{task['id']}-s{seed}-{stage}{agent}-{variant}"
    events = out / 'agents' / (stem + '.jsonl')
    command = [sys.executable, str(source / 'forced72_worker.py'), '--run', '--variant', variant,
               '--puzzle', ','.join(map(str, task['numbers'])) + ':' + str(task['target']),
               '--endpoint', endpoint, '--seed', str(agent_seed(seed, agent, offset)),
               '--events', str(events), '--model', 'nemotron-lightning']
    return dict(task_id=task['id'], split='evaluation', arm=variant, seed=seed, endpoint=endpoint, command=command,
                events=str(events), stdout=str(events).replace('.jsonl', '.stdout.log'),
                stderr=str(events).replace('.jsonl', '.stderr.log'), shared_endpoint=True, stop_on_solution=False)


def plan_of(events_path):
    records, _ = read_trace(Path(events_path))
    end = next((r for r in reversed(records) if r.get('type') == 'puzzle_end'), {})
    plan = end.get('plan')
    parsed = isinstance(plan, dict) and isinstance(plan.get('moves'), list) and bool(plan['moves'])
    run_end = next((r for r in reversed(records) if r.get('type') == 'run_end'), {})
    tokens = sum(r.get('usage', {}).get('completion_tokens', 0) for r in records if r.get('type') == 'request_end')
    # 'verifier_solved' is recorded for scoring only; the controller never reads it.
    return dict(plan=plan if parsed else None, verifier_solved=bool(end.get('solved')), tokens=tokens,
                infra=run_end.get('infrastructure_failures') or 0)


def run_stage(plan, source, out, task, seed, case_index, stage, variant, offset, slots, judge_offset):
    results = [None] * 4

    def one(agent):
        job = agent_job(plan, source, out, task, seed, case_index, stage, agent, variant, offset)
        with slots(job['endpoint']):
            row = execute(job, deadline_seconds=plan['agent_wall_deadline_seconds'])
        info = plan_of(job['events'])
        info.update(agent=agent, stage=stage, variant=variant, deadline=bool(row['deadline']),
                    controller_error=row['controller_error'], verdict=None, judge_tokens=0, judge_infra=0)
        if info['plan'] is not None:
            candidate = dict(run=stage, task_id=task['id'], seed=seed, agent=agent, numbers=task['numbers'],
                             target=task['target'], plan=info['plan'], truth=None)  # truth deliberately absent
            with slots(job['endpoint']):
                verdict = run_judge.judge(candidate, 'think', job['endpoint'],
                                          out / 'judges' / (Path(job['events']).stem + '-judge.jsonl'),
                                          judge_offset + 1000 * seed + 10 * case_index + agent)
            info.update(verdict=verdict['verdict'], judge_tokens=verdict['tokens'], judge_infra=verdict['infra'])
        results[agent] = info

    threads = [threading.Thread(target=one, args=(a,)) for a in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def run_case(plan, source, out, task, seed, case_index, slots):
    record = dict(task_id=task['id'], seed=seed, started_utc=datetime.now(timezone.utc).isoformat())
    stages = []
    selected = None
    for stage, variant, offset, judge_offset in (('A', plan['stage_a_variant'], plan['stage_a_seed_offset'], 70000),
                                                  ('B', plan['stage_b_variant'], plan['stage_b_seed_offset'], 80000)):
        results = run_stage(plan, source, out, task, seed, case_index, stage, variant, offset, slots, judge_offset)
        stages.append(dict(stage=stage, variant=variant, agents=results))
        accepted = [r for r in results if r['verdict'] is True]
        if accepted:
            selected = accepted[0]  # first accepted in agent order
            break
    all_agents = [a for s in stages for a in s['agents']]
    record.update(stages=stages, escalated=len(stages) == 2, answered=selected is not None,
                  selected=dict(stage=selected['stage'], agent=selected['agent']) if selected else None,
                  solved=bool(selected and selected['verifier_solved']),
                  wrong_answer=bool(selected and not selected['verifier_solved']),
                  oracle_any=any(a['verifier_solved'] for a in all_agents),
                  agent_tokens=sum(a['tokens'] for a in all_agents), judge_tokens=sum(a['judge_tokens'] for a in all_agents),
                  infra=sum(a['infra'] + a['judge_infra'] for a in all_agents) + sum(bool(a['controller_error']) for a in all_agents),
                  deadlines=sum(a['deadline'] for a in all_agents), completed_utc=datetime.now(timezone.utc).isoformat())
    return record


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    plan = read(a.plan)
    require(plan['protocol'] == 'arbiter-free-swarm-v1', 'Wrong protocol')
    source, out = a.source.resolve(), a.output.resolve()
    validate_source(source, plan['source_revision'])
    dataset = HERE / plan['dataset']
    require(read(dataset).get('protocol') == plan['dataset_protocol'], 'Wrong corpus protocol')
    tasks = [t for t in read(dataset)['tasks'] if t['split'] == plan.get('split', 'evaluation')]
    require(len(tasks) == plan['tasks'], 'Wrong task count')
    cases = [(t, s, si * len(tasks) + ti) for si, s in enumerate(plan['seeds']) for ti, t in enumerate(tasks)]
    if not a.run:
        print(json.dumps(dict(mode='plan', cases=len(cases), model_calls=0)))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not out.exists(), 'Frozen plan, admission, new output')
    adm = read(a.admission)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(adm['verified_utc'])).total_seconds()
    require(adm.get('verified') is True and 0 <= age <= 900, 'Fresh admission required')
    (out / 'agents').mkdir(parents=True)
    (out / 'judges').mkdir()
    meta = dict(protocol=plan, plan_sha256=sha(a.plan), runner_sha256=sha(Path(__file__)), judge_sha256=sha(HERE / 'run_judge.py'),
                dataset_sha256=sha(dataset), started_utc=datetime.now(timezone.utc).isoformat(), admission=adm)
    write(out / 'metadata.json', meta)
    slots = Slots(plan['concurrent_requests_per_endpoint'])
    lock, stop, rows = threading.Lock(), threading.Event(), []

    def work(item):
        task, seed, index = item
        if stop.is_set():
            return
        try:
            rec = run_case(plan, source, out, task, seed, index, slots)
        except Exception as exc:
            with lock:
                stop.set()
                rows.append(dict(task_id=task['id'], seed=seed, error=f'{type(exc).__name__}: {exc}'))
            return
        with lock:
            rows.append(rec)
            if rec['infra']:
                stop.set()
            with (out / 'cases.jsonl').open('a') as stream:
                stream.write(json.dumps(rec) + '\n')
            print(json.dumps(dict(done=len(rows), total=len(cases), task=rec['task_id'], seed=rec['seed'], escalated=rec['escalated'],
                                  answered=rec['answered'], solved=rec['solved'])), flush=True)

    start = time.monotonic()
    with ThreadPoolExecutor(plan['concurrent_cases']) as pool:
        list(pool.map(work, cases))
    done = [r for r in rows if 'error' not in r]
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=time.monotonic() - start, cases_done=len(done),
                errors=[r for r in rows if 'error' in r], stopped=stop.is_set(),
                solved=sum(r['solved'] for r in done), wrong_answers=sum(r['wrong_answer'] for r in done),
                unanswered=sum(not r['answered'] for r in done), escalated=sum(r['escalated'] for r in done),
                oracle_any=sum(r['oracle_any'] for r in done))
    write(out / 'metadata.json', meta)
    print(json.dumps({k: meta[k] for k in ('cases_done', 'solved', 'wrong_answers', 'unanswered', 'escalated', 'oracle_any', 'stopped')}))
    return int(bool(meta['errors']) or meta['stopped'] or len(done) != len(cases))


if __name__ == '__main__':
    raise SystemExit(main())
