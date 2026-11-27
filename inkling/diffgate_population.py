#!/usr/bin/env python3
"""Frozen population of DIFFGATE_PLAN.json (mechanical, no model call): the accepted cases of the plan's runs, all
wrong ones plus the first N_CORRECT correct ones in the order sha256(SEED + ':' + run + ':' + task_id + ':' + seed),
each with every public-test passer's final code (puzzle_end.code with feedback_pass true), the generator payload (the
task's {function_name, spec}) and (amendment) its cross-case references: the public-test passers of the same task in
OTHER cases of the runs, code different from the accepted code, identical code once, the first K_REFERENCES in the
order sha256(REF_SEED + ':' + item_id + ':' + run + ':' + seed + ':' + agent).

usage: diffgate_population.py [--plan DIFFGATE_PLAN.json] [--root DIR] --output DIFFGATE_POPULATION.json
"""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SEED, N_CORRECT = '2026112705', 60
REF_SEED, K_REFERENCES = '2026112706', 8


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def trace_end(path):
    end = None
    try:
        lines = Path(path).read_text().splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get('type') == 'puzzle_end':
            end = event
    return end


def resolve(run_dir, events):
    path = Path(events)
    return path if path.exists() else Path(run_dir) / path.name


def passers(run_dir, rows):
    out = []
    for row in sorted(rows, key=lambda r: r['agent']):
        path = resolve(run_dir, row['events'])
        end = trace_end(path)
        if end and end.get('feedback_pass') is True and isinstance(end.get('code'), str) and end['code'].strip():
            out.append(dict(agent=row['agent'], events=str(path), code=end['code'], code_sha256=sha(end['code']),
                            holdout_pass=bool(end.get('holdout_pass'))))
    return out


def references(item, by_task):
    """The item's cross-case references (frozen rule; see the module doc)."""
    accepted = {p['code_sha256'] for p in item['passers']}
    pool = [r for r in by_task.get(item['task_id'], []) if (r['run'], r['seed']) != (item['run'], item['seed'])
            and r['code_sha256'] not in accepted]
    pool.sort(key=lambda r: sha(f"{REF_SEED}:{item['item_id']}:{r['run']}:{r['seed']}:{r['agent']}"))
    out, seen = [], set()
    for r in pool:
        if r['code_sha256'] in seen:
            continue
        seen.add(r['code_sha256'])
        out.append(r)
        if len(out) == K_REFERENCES:
            break
    return out


def population(plan, root):
    tasks = {t['id']: t for t in json.loads((Path(root) / 'datasets/coding-hard-v1/tasks.json').read_text())['tasks']}
    wrong, correct, by_task = [], [], {}
    for run in plan['runs']:
        d = Path(root) / 'runs' / run
        cases = json.loads((d / 'cases.json').read_text())
        rows = json.loads((d / 'summary.json').read_text())
        for case in cases:
            if not case.get('answered'):
                continue
            mine = [r for r in rows if (r['task_id'], r['seed']) == (case['task_id'], case['seed'])]
            task = tasks[case['task_id']]
            found = passers(d, mine)
            by_task.setdefault(case['task_id'], []).extend(dict(p, run=run, seed=case['seed']) for p in found)
            item = dict(run=run, task_id=case['task_id'], seed=case['seed'], winner_agent=case.get('winner_agent'),
                        kind='correct' if case.get('solved') else 'wrong',
                        payload=json.dumps({'function_name': task['function_name'], 'spec': task['spec']},
                                           ensure_ascii=False),
                        function_name=task['function_name'], passers=found)
            (correct if case.get('solved') else wrong).append(item)
    correct.sort(key=lambda i: sha(f"{SEED}:{i['run']}:{i['task_id']}:{i['seed']}"))
    items = wrong + correct[:N_CORRECT]
    for n, item in enumerate(items):
        item['item_id'] = f'g{n:03d}'
        item['references'] = references(item, by_task)
    return dict(protocol='diffgate-population-v1', plan='DIFFGATE_PLAN.json', status='FROZEN', selection_seed=SEED,
                n_correct=N_CORRECT, reference_seed=REF_SEED, k_references=K_REFERENCES,
                accepted_cases=len(wrong) + len(correct), wrong_cases=len(wrong),
                correct_cases=len(correct), items=items)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--plan', type=Path, default=ROOT / 'DIFFGATE_PLAN.json')
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    if a.output.exists():
        p.error('output exists')
    pop = population(json.loads(a.plan.read_text()), a.root)
    a.output.write_text(json.dumps(pop, indent=1) + '\n')
    multi = sum(len(i['passers']) >= 2 for i in pop['items'])
    print(json.dumps(dict(items=len(pop['items']), wrong=pop['wrong_cases'], correct=pop['correct_cases'],
                          with_two_or_more_passers=multi)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
