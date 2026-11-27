#!/usr/bin/env python3
"""Frozen population of DIFFGATE_PLAN.json (mechanical, no model call): the accepted cases of the plan's runs, all
wrong ones plus the first N_CORRECT correct ones in the order sha256(SEED + ':' + run + ':' + task_id + ':' + seed),
each with every public-test passer's final code (puzzle_end.code with feedback_pass true) and the generator payload
(the task's {function_name, spec}).

usage: diffgate_population.py [--plan DIFFGATE_PLAN.json] [--root DIR] --output DIFFGATE_POPULATION.json
"""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SEED, N_CORRECT = '2026112705', 60


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


def population(plan, root):
    tasks = {t['id']: t for t in json.loads((Path(root) / 'datasets/coding-hard-v1/tasks.json').read_text())['tasks']}
    wrong, correct = [], []
    for run in plan['runs']:
        d = Path(root) / 'runs' / run
        cases = json.loads((d / 'cases.json').read_text())
        rows = json.loads((d / 'summary.json').read_text())
        for case in cases:
            if not case.get('answered'):
                continue
            mine = [r for r in rows if (r['task_id'], r['seed']) == (case['task_id'], case['seed'])]
            task = tasks[case['task_id']]
            item = dict(run=run, task_id=case['task_id'], seed=case['seed'], winner_agent=case.get('winner_agent'),
                        kind='correct' if case.get('solved') else 'wrong',
                        payload=json.dumps({'function_name': task['function_name'], 'spec': task['spec']},
                                           ensure_ascii=False),
                        function_name=task['function_name'], passers=passers(d, mine))
            (correct if case.get('solved') else wrong).append(item)
    correct.sort(key=lambda i: sha(f"{SEED}:{i['run']}:{i['task_id']}:{i['seed']}"))
    items = wrong + correct[:N_CORRECT]
    for n, item in enumerate(items):
        item['item_id'] = f'g{n:03d}'
    return dict(protocol='diffgate-population-v1', plan='DIFFGATE_PLAN.json', status='FROZEN', selection_seed=SEED,
                n_correct=N_CORRECT, accepted_cases=len(wrong) + len(correct), wrong_cases=len(wrong),
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
