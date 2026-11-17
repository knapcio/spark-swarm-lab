#!/usr/bin/env python3
"""Development screen of swarm variants (all arbiter-free; a Nemotron thinking judge selects).

Policies, each with 4 deep agents (long_forced_original, 16K) per case:
  deep4      4 identical independent agents -> judge -> first accepted
  strategy4  4 independent agents, each with a different task-agnostic strategy hint
  repair4    sequential: agent -> judge with reason -> if rejected, next agent sees its plan + critique
  board2x2   round 1: 2 agents; if none accepted, round 2: 2 agents see all round-1 plans + critiques
The exact verifier never influences decisions; it only scores the selected plan.
"""
import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from run_agents72 import read, require, sha, validate_source, write
from run_arbiterfree import ENDPOINTS, Slots, plan_of
from run_benchmark import execute
import run_judge

HERE = Path(__file__).resolve().parent
STRATEGIES = [
    'Strategy hint: work backward from the target. Factor it or write it as a sum/difference of numbers you can build.',
    'Strategy hint: look for a product of two available numbers (or of a number and a small built value) close to the target, then adjust.',
    'Strategy hint: consider using every number; subtraction and division can create the small values you need.',
    'Strategy hint: build one large intermediate from the biggest numbers first, then correct it with the small numbers.',
]
JUDGE_TAIL = 'Return only a JSON object {"valid": true} if every move is legal and the target appears, otherwise {"valid": false}.'
REASON_TAIL = ('Return only a JSON object {"valid": true} if every move is legal and the target appears; otherwise '
               '{"valid": false, "reason": "<one sentence: the first illegal move, or why the target never appears>"}.')


def judge_with_reason(candidate, endpoint, events_path, seed):
    """Same thinking judge as run_judge.judge, but asks for a one-sentence reason when rejecting."""
    events = run_judge.Events(events_path, 'judge_reason')
    try:
        client = run_judge.ChatJudge(endpoint, 'nemotron-lightning', run_judge.Budget(2, 8192), events, seed)
        prompt = run_judge.judge_prompt(candidate['numbers'], candidate['target'], candidate['plan'])
        require(prompt.endswith(JUDGE_TAIL), 'judge prompt changed')
        prompt = prompt[:-len(JUDGE_TAIL)] + REASON_TAIL
        ids = client.chat_prompt_ids(prompt, thinking=True)
        first = client.complete(0, 'judge', ids, 6144)
        answer = first['answer']
        if answer is None and first['finish_reason'] == 'length' and first['error'] is None:
            second = client.complete(0, 'judge_forced', ids + first['token_ids'] + client.force_ids(),
                                     8192 - client.budget.snapshot()['completion_tokens_charged'], thinking_closed=True)
            answer = second['answer']
        verdict, reason = None, ''
        try:
            value = json.loads((answer or '').strip().strip('`').removeprefix('json').strip())
            if isinstance(value, dict) and isinstance(value.get('valid'), bool):
                verdict, reason = value['valid'], str(value.get('reason', ''))[:300]
        except ValueError:
            pass
        out = dict(verdict=verdict, reason=reason, infra=client.infra_failures,
                   tokens=client.budget.snapshot()['completion_tokens_charged'])
        events.emit('judge_end', **out)
        return out
    finally:
        events.close()


def run_agent(plan, source, out, task, seed, case_index, policy, slot, extra, slots, seed_offset):
    endpoint = ENDPOINTS[(case_index + slot) % 4]
    stem = f"{task['id']}-s{seed}-{policy}-a{slot}"
    events = out / 'agents' / (stem + '.jsonl')
    extra_file = None
    if extra:
        extra_file = out / 'extra' / (stem + '.txt')
        extra_file.write_text(extra)
    command = [sys.executable, str(source / 'forced72_worker.py'), '--run', '--variant', plan['agent_variant'],
               '--puzzle', ','.join(map(str, task['numbers'])) + ':' + str(task['target']), '--endpoint', endpoint,
               '--seed', str(1000 * seed + seed_offset + slot), '--events', str(events), '--model', 'nemotron-lightning']
    if extra_file:
        command[2:2] = ['--extra-file', str(extra_file)]
    job = dict(task_id=task['id'], split='development', arm=policy, seed=seed, endpoint=endpoint, command=command,
               events=str(events), stdout=str(events).replace('.jsonl', '.stdout.log'),
               stderr=str(events).replace('.jsonl', '.stderr.log'), shared_endpoint=True, stop_on_solution=False)
    with slots(endpoint):
        row = execute(job, deadline_seconds=plan['agent_wall_deadline_seconds'])
    info = plan_of(events)
    if row.get('controller_error') or (row.get('returncode') not in (0, None) and not row['deadline']):
        info['infra'] += 1  # worker process failure: stop admissions, never a silent 'no plan'
    info.update(slot=slot, extra=bool(extra), deadline=bool(row['deadline']), verdict=None, reason='', judge_tokens=0, judge_infra=0)
    if info['plan'] is not None:
        cand = dict(numbers=task['numbers'], target=task['target'], plan=info['plan'])
        with slots(endpoint):
            j = judge_with_reason(cand, endpoint, out / 'judges' / (stem + '.jsonl'), 90000 + 1000 * seed + 10 * case_index + slot)
        info.update(verdict=j['verdict'], reason=j['reason'], judge_tokens=j['tokens'], judge_infra=j['infra'])
    return info


def parallel(fns):
    results = [None] * len(fns)
    threads = [threading.Thread(target=lambda i=i, f=f: results.__setitem__(i, f())) for i, f in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def critique(info):
    if info['plan'] is None:
        return 'A previous attempt produced no complete plan.'
    return f"A previous attempt proposed {json.dumps(info['plan'])}; a careful checker rejected it: {info['reason'] or 'invalid'}."


def run_policy(plan, source, out, task, seed, case_index, policy, slots):
    off = plan['seed_offsets'][policy]
    agent = lambda slot, extra='': run_agent(plan, source, out, task, seed, case_index, policy, slot, extra, slots, off)
    if policy == 'deep4':
        agents = parallel([lambda s=s: agent(s) for s in range(4)])
    elif policy == 'strategy4':
        agents = parallel([lambda s=s: agent(s, STRATEGIES[s]) for s in range(4)])
    elif policy == 'repair4':
        agents, extra = [], ''
        for s in range(4):
            info = agent(s, extra)
            agents.append(info)
            if info['verdict'] is True:
                break
            extra = 'Earlier attempts on this exact task failed:\n' + '\n'.join(critique(a) for a in agents) + \
                    '\nAvoid these mistakes and give a corrected complete plan.'
    elif policy == 'board2x2':
        agents = parallel([lambda s=s: agent(s) for s in range(2)])
        if not any(a['verdict'] is True for a in agents):
            board = 'Shared board from other solvers on this exact task (all rejected by a checker):\n' + \
                    '\n'.join(critique(a) for a in agents) + '\nUse what is useful, avoid their mistakes, and give a complete valid plan.'
            agents += parallel([lambda s=s: agent(s, board) for s in (2, 3)])
    else:
        raise ValueError(policy)
    selected = next((a for a in agents if a['verdict'] is True), None)
    return dict(policy=policy, agents=agents, answered=selected is not None,
                solved=bool(selected and selected['verifier_solved']), wrong=bool(selected and not selected['verifier_solved']),
                oracle=any(a['verifier_solved'] for a in agents), calls=len(agents),
                tokens=sum(a['tokens'] + a['judge_tokens'] for a in agents),
                infra=sum(a['infra'] + a['judge_infra'] for a in agents), deadlines=sum(a['deadline'] for a in agents))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--admission', type=Path)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    plan = read(a.plan)
    require(plan['protocol'] == 'swarm-variants-screen-v1', 'Wrong protocol')
    source, out = a.source.resolve(), a.output.resolve()
    validate_source(source, plan['source_revision'])
    data = read(HERE / plan['dataset'])
    require(data.get('protocol') == plan['dataset_protocol'], 'Wrong corpus')
    tasks = [t for t in data['tasks'] if t['split'] == plan['split']]
    require(len(tasks) == plan['tasks'], 'Wrong task count')
    jobs = [(t, s, si * len(tasks) + ti, pol) for si, s in enumerate(plan['seeds']) for ti, t in enumerate(tasks) for pol in plan['policies']]
    if not a.run:
        print(json.dumps(dict(mode='plan', policy_cases=len(jobs), model_calls=0)))
        return 0
    require(plan['status'] == 'FROZEN' and a.admission and not out.exists(), 'Frozen plan, admission, new output')
    adm = read(a.admission)
    require(adm.get('verified') is True and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(adm['verified_utc'])).total_seconds() <= 900, 'Fresh admission')
    for d in ('agents', 'judges', 'extra'):
        (out / d).mkdir(parents=True, exist_ok=d != 'agents')
    write(out / 'metadata.json', dict(protocol=plan, runner_sha256=sha(Path(__file__)), started_utc=datetime.now(timezone.utc).isoformat(), admission=adm))
    slots, lock, stop, rows = Slots(plan['concurrent_requests_per_endpoint']), threading.Lock(), threading.Event(), []

    def work(job):
        task, seed, index, pol = job
        if stop.is_set():
            return
        try:
            rec = run_policy(plan, source, out, task, seed, index, pol, slots)
        except Exception as exc:
            with lock:
                stop.set()
                rows.append(dict(task_id=task['id'], seed=seed, policy=pol, error=f'{type(exc).__name__}: {exc}'))
            return
        rec.update(task_id=task['id'], seed=seed)
        with lock:
            rows.append(rec)
            if rec['infra']:
                stop.set()
            with (out / 'cases.jsonl').open('a') as stream:
                stream.write(json.dumps(rec) + '\n')
            print(json.dumps(dict(done=len(rows), total=len(jobs), policy=pol, task=task['id'], seed=seed, solved=rec['solved'], wrong=rec['wrong'])), flush=True)

    start = time.monotonic()
    with ThreadPoolExecutor(plan['concurrent_policy_cases']) as pool:
        list(pool.map(work, jobs))
    meta = read(out / 'metadata.json')
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=time.monotonic() - start, stopped=stop.is_set(),
                errors=[r for r in rows if 'error' in r],
                summary={pol: dict(cases=sum(r.get('policy') == pol and 'error' not in r for r in rows),
                                   solved=sum(r.get('policy') == pol and r.get('solved', False) for r in rows),
                                   wrong=sum(r.get('policy') == pol and r.get('wrong', False) for r in rows))
                         for pol in plan['policies']})
    write(out / 'metadata.json', meta)
    print(json.dumps(meta['summary']))
    return int(bool(meta['errors']) or meta['stopped'])


if __name__ == '__main__':
    raise SystemExit(main())
