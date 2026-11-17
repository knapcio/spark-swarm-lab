#!/usr/bin/env python3
"""Nemotron as its own judge: can the model tell correct arithmetic plans from wrong ones?

Candidates are the parsed plans of the budget-forced agents in confirm-v2-v1 and confirm-hard-v1.
The judge sees only the public task and the candidate's raw JSON plan; the exact verifier's verdict
is used ONLY to score the judge afterwards, never shown to it. Two judge modes:
  fast  : thinking off, one call, up to 512 tokens
  think : thinking on via budget forcing (think cap 6144, total 8192), same sequence continuation
Outputs per-candidate JSONL + summary; analysis: accuracy, precision/recall, and arbiter-free
selection = first agent (fixed order) whose plan the judge accepts.
"""
import argparse
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = Path(os.environ.get('SWARM_LONG_SOURCE', HERE / '.runtime/nemotron-long-source'))  # CI checks it out elsewhere
from harness import Budget, Events, canonical  # noqa: E402
from fractions import Fraction  # noqa: E402

ENDPOINTS = [f'http://127.0.0.1:{p}/v1' for p in range(18081, 18085)]
SYSTEM = 'You check arithmetic plans carefully. Return only the requested JSON object.'


def judge_prompt(numbers, target, plan):
    state = dict(enumerate(canonical(tuple(map(Fraction, numbers)))))
    return (f'Target {target}. Starting indexed numbers: {state}. A solver proposed the plan below. Rules: each move '
            'takes the numbers at two different current indices i and j and computes (value at i) op (value at j) in that '
            'order with op in +,-,*,/; both are removed and the result is appended at the end; the remaining numbers keep '
            'their order and are reindexed from zero. Every result must be a positive integer (no zero, negatives or '
            'fractions). Unused numbers are allowed. The plan succeeds if the target appears among the numbers after some '
            'move. Check the plan move by move, tracking the indexed list. '
            f'Plan: {json.dumps(plan)}\nReturn only a JSON object {{"valid": true}} if every move is legal and the target '
            'appears, otherwise {"valid": false}.')


def parse_verdict(text):
    if text is None:
        return None
    try:
        value = json.loads(text.strip().strip('`').removeprefix('json').strip())
        return value.get('valid') if isinstance(value, dict) and isinstance(value.get('valid'), bool) else None
    except (ValueError, AttributeError):
        return None


def candidates(runs):
    out = []
    for run in runs:
        rows = json.loads((HERE / 'runs' / run / 'summary.json').read_text())
        meta = json.loads((HERE / 'runs' / run / 'metadata.json').read_text())
        tasks = {t['id']: t for t in json.loads(Path(meta['dataset']).read_text())['tasks']}
        for r in rows:
            if r['arm'] != 'forced_explicit':
                continue
            events = [json.loads(line) for line in Path(r['events']).read_text().splitlines()]
            end = next(e for e in events if e['type'] == 'puzzle_end')
            plan = end.get('plan')
            if not (isinstance(plan, dict) and isinstance(plan.get('moves'), list) and plan['moves']):
                continue
            task = tasks[r['task_id']]
            out.append(dict(run=run, task_id=r['task_id'], seed=r['seed'], agent=r['agent'], numbers=task['numbers'],
                            target=task['target'], plan=plan, truth=bool(end['solved'])))
    return out


def _forced72():
    """Load the pinned agent source only when a judge is actually used (keeps offline test imports clean)."""
    if str(SOURCE) not in sys.path:
        sys.path.insert(0, str(SOURCE))
    import forced72
    return forced72


_CHAT_JUDGE = None


def ChatJudge(*args, **kwargs):  # noqa: N802 - factory kept under the original class name
    global _CHAT_JUDGE
    if _CHAT_JUDGE is None:
        forced72 = _forced72()

        class _ChatJudge(forced72.ForcedClient):
            def chat_prompt_ids(self, prompt, thinking=True):
                messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]
                with self.post('/tokenize', dict(model=self.model, messages=messages, add_generation_prompt=True,
                                                 chat_template_kwargs={'enable_thinking': thinking}), 60) as response:
                    return json.load(response)['tokens']

        _CHAT_JUDGE = _ChatJudge
    return _CHAT_JUDGE(*args, **kwargs)


def judge(candidate, mode, endpoint, events_path, seed):
    events = Events(events_path, 'judge_' + mode)
    try:
        client = ChatJudge(endpoint, 'nemotron-lightning', Budget(2, 8192), events, seed)
        prompt = judge_prompt(candidate['numbers'], candidate['target'], candidate['plan'])
        events.emit('judge_start', mode=mode, **{k: candidate[k] for k in ('run', 'task_id', 'seed', 'agent')})
        if mode == 'fast':
            ids = client.chat_prompt_ids(prompt, thinking=False)
            first = client.complete(0, 'judge', ids, 512, thinking_closed=True)
            answer = first['answer']
        else:
            ids = client.chat_prompt_ids(prompt, thinking=True)
            first = client.complete(0, 'judge', ids, 6144)
            answer = first['answer']
            if answer is None and first['finish_reason'] == 'length' and first['error'] is None:
                second = client.complete(0, 'judge_forced', ids + first['token_ids'] + client.force_ids(),
                                         8192 - client.budget.snapshot()['completion_tokens_charged'], thinking_closed=True)
                answer = second['answer']
        verdict = parse_verdict(answer)
        result = dict(verdict=verdict, infra=client.infra_failures, tokens=client.budget.snapshot()['completion_tokens_charged'])
        events.emit('judge_end', **result)
        return result
    finally:
        events.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--modes', default='fast,think')
    p.add_argument('--per-node', type=int, default=20)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    cands = candidates(['confirm-v2-v1', 'confirm-hard-v1'])
    modes = a.modes.split(',')
    jobs = [(m, c) for m in modes for c in cands]
    if not a.run:
        print(json.dumps(dict(mode='plan', candidates=len(cands), jobs=len(jobs), correct=sum(c['truth'] for c in cands))))
        return 0
    if a.output.exists():
        raise SystemExit('output exists')
    a.output.mkdir(parents=True)
    meta = dict(started_utc=datetime.now(timezone.utc).isoformat(), script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                source=str(SOURCE), modes=modes, candidates=len(cands))
    (a.output / 'metadata.json').write_text(json.dumps(meta, indent=2))
    rows, lock, stop = [], threading.Lock(), threading.Event()

    def work(index_job):
        index, (mode, c) = index_job
        if stop.is_set():
            return
        endpoint = ENDPOINTS[index % 4]
        stem = f"{mode}-{c['run']}-{c['task_id']}-s{c['seed']}-a{c['agent']}"
        res = judge(c, mode, endpoint, a.output / (stem + '.jsonl'), 5000 + index)
        row = dict(mode=mode, **{k: c[k] for k in ('run', 'task_id', 'seed', 'agent', 'truth')}, **res)
        with lock:
            rows.append(row)
            if res['infra']:
                stop.set()
            if len(rows) % 50 == 0:
                (a.output / 'summary.json').write_text(json.dumps(rows))
                print(json.dumps(dict(done=len(rows), total=len(jobs))), flush=True)

    with ThreadPoolExecutor(max_workers=a.per_node * 4) as pool:
        list(pool.map(work, enumerate(jobs)))
    (a.output / 'summary.json').write_text(json.dumps(rows))
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), done=len(rows), stopped=stop.is_set())
    (a.output / 'metadata.json').write_text(json.dumps(meta, indent=2))
    print(json.dumps(dict(done=len(rows), stopped=stop.is_set())))


if __name__ == '__main__':
    main()
