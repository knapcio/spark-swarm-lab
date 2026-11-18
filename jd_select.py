#!/usr/bin/env python3
"""Judge-on-disagreement selection for the coding swarm (arbiter-free; Nemotron judges concrete outputs).

Uses the frozen CX v2 observations (runs/cx-selection-v2/observations.json): feedback-passing programs grouped
by identical outputs on model-written inputs. Where at least two groups exist, a tournament decides:
champion = the group the current rule would pick (group of the first feedback-passing agent); every other group,
largest first, challenges it on up to 3 inputs where their outputs differ. For each input a Nemotron thinking
judge sees the PUBLIC spec and examples, the input and the two outputs (order randomized by a fixed seed) and
answers which output the specification requires. The challenger replaces the champion only if it wins a strict
majority of the judged inputs. Selected = earliest agent of the final champion. Cases with fewer than two
groups keep the current rule. Hidden holdout results score the frozen selections afterwards.
"""
import argparse
import hashlib
import json
import os
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cx_select as cx  # noqa: E402

SYSTEM = 'You check program outputs against a specification. Return only the requested JSON object.'
ENDPOINTS = cx.ENDPOINTS


def judge_prompt(task, args, out_a, out_b):
    return (f"Function name: {task['function_name']}\nSpecification: {task['spec']}\n"
            f"Examples (args -> expected): {json.dumps(task['examples'])}\n\n"
            f"Input args: {json.dumps(args)}\nTwo implementations disagree on this input.\n"
            f"Output A: {out_a}\nOutput B: {out_b}\n"
            "Work out from the specification what the function must return for this input (an 'e:Name' output means "
            "the function raised exception Name). Return only a JSON object {\"correct\": \"A\"} or {\"correct\": \"B\"}, "
            "or {\"correct\": \"neither\"} if neither matches the specification.")


def ask(task, args, out_a, out_b, endpoint, events_path, seed):
    if str(cx.SOURCE_LONG) not in sys.path:
        sys.path.insert(0, str(cx.SOURCE_LONG))
    import forced72
    from harness import Budget, Events

    class Client(forced72.ForcedClient):
        def chat_prompt_ids(self, prompt):
            messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]
            with self.post('/tokenize', dict(model=self.model, messages=messages, add_generation_prompt=True,
                                             chat_template_kwargs={'enable_thinking': True}), 60) as response:
                return json.load(response)['tokens']

    events = Events(events_path, 'jd_judge')
    try:
        client = Client(endpoint, 'nemotron-lightning', Budget(2, 12000), events, seed)
        ids = client.chat_prompt_ids(judge_prompt(task, args, out_a, out_b))
        first = client.complete(0, 'judge', ids, 10240)
        answer = first['answer']
        if answer is None and first['finish_reason'] == 'length' and first['error'] is None:
            second = client.complete(0, 'judge_forced', ids + first['token_ids'] + client.force_ids(),
                                     12000 - client.budget.snapshot()['completion_tokens_charged'], thinking_closed=True)
            answer = second['answer']
        verdict = None
        try:
            value = json.loads((answer or '').strip().strip('`').removeprefix('json').strip())
            verdict = value.get('correct') if isinstance(value, dict) else None
        except ValueError:
            pass
        return verdict if verdict in ('A', 'B', 'neither') else None, client.infra_failures
    finally:
        events.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    tasks = {t['id']: t for t in json.loads((HERE / 'datasets/coding-hard-v1/tasks.json').read_text())['tasks']}
    cases = cx.load_candidates()
    obs = json.loads((HERE / 'runs/cx-selection-v2/observations.json').read_text())
    work = []
    for key, case in sorted(cases.items()):
        stem = f'{key[0]}-s{key[1]}'
        rec = obs.get(stem) or {}
        sigs = rec.get('signatures') or {}
        groups = {}
        for ag in sorted(case):
            if case[ag]['feedback_pass'] and sigs.get(str(ag)) is not None:
                groups.setdefault(json.dumps(sigs[str(ag)]), []).append(ag)
        if len(groups) >= 2:
            work.append((key, stem, list(groups.values()), rec['inputs'], [sigs[str(g[0])] for g in groups.values()]))
    if not a.run:
        print(json.dumps(dict(mode='plan', tournament_cases=len(work), model_calls=0)))
        return 0
    a.output.mkdir(parents=True)
    (a.output / 'judges').mkdir()
    results, lock, faults = {}, threading.Lock(), []

    def run_case(item):
        index, (key, stem, groups, inputs, gsigs) = item
        task = tasks[key[0]]
        case = cases[key]
        first = min(ag for g in groups for ag in g)
        order = sorted(range(len(groups)), key=lambda i: (-len(groups[i]), min(groups[i])))
        champ = next(i for i in range(len(groups)) if first in groups[i])
        log, infra = [], 0
        for ch in [i for i in order if i != champ]:
            diff = [j for j in range(len(inputs)) if gsigs[champ][j] != gsigs[ch][j]][:3]
            wins = 0
            for n, j in enumerate(diff):
                rng = random.Random(f'{stem}:{champ}:{ch}:{j}')
                swap = rng.random() < 0.5
                oa, ob = (gsigs[ch][j], gsigs[champ][j]) if swap else (gsigs[champ][j], gsigs[ch][j])
                verdict, bad = ask(task, inputs[j], oa, ob, ENDPOINTS[(index + n) % 4],
                                   a.output / 'judges' / f'{stem}-g{champ}v{ch}-i{j}.jsonl', 88000 + 100 * index + 10 * ch + n)
                infra += bad
                challenger_wins = verdict == ('A' if swap else 'B')
                champion_wins = verdict == ('B' if swap else 'A')
                wins += challenger_wins - champion_wins
                log.append(dict(champion=groups[champ], challenger=groups[ch], input=j, verdict=verdict, swap=swap,
                                challenger_wins=challenger_wins, champion_wins=champion_wins))
            if diff and wins > 0:
                champ = ch
        selected = min(groups[champ])
        with lock:
            results[stem] = dict(selected=selected, champion=groups[champ], log=log, infra=infra)
            if infra:
                faults.append(stem)
            print(json.dumps(dict(done=len(results), total=len(work), case=stem, selected=selected, infra=infra)), flush=True)

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(run_case, enumerate(work)))
    selections = {}
    for key, case in sorted(cases.items()):
        stem = f'{key[0]}-s{key[1]}'
        first = next((ag for ag in sorted(case) if case[ag]['feedback_pass']), None)
        selections[stem] = results[stem]['selected'] if stem in results else first
    (a.output / 'selections.json').write_text(json.dumps(dict(selections=selections, tournaments=results), indent=1))
    base = sum(bool(f is not None and cases[k][f]['holdout_pass']) for k, f in
               ((k, next((ag for ag in sorted(c) if c[ag]['feedback_pass']), None)) for k, c in cases.items()))
    jd = sum(bool(selections[f'{k[0]}-s{k[1]}'] is not None and cases[k][selections[f'{k[0]}-s{k[1]}']]['holdout_pass'])
             for k in cases)
    meta = dict(completed_utc=datetime.now(timezone.utc).isoformat(), tournament_cases=len(work), infra_cases=faults,
                score=dict(first_passing=base, judge_on_disagreement=jd,
                           oracle=sum(any(c[x]['holdout_pass'] for x in c) for c in cases.values())),
                script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (a.output / 'summary.json').write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))
    return 1 if faults else 0


if __name__ == '__main__':
    raise SystemExit(main())
