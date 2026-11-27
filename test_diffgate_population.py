"""Differential-consensus gate: the frozen population rule on synthetic recorded runs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import diffgate_population as dp  # noqa: E402


def write_run(root, run, cases):
    """cases: (task, seed, answered, solved, {agent: (feedback_pass, code)})"""
    d = root / 'runs' / run
    d.mkdir(parents=True)
    rows, out = [], []
    for task, seed, answered, solved, agents in cases:
        out.append(dict(task_id=task, seed=seed, answered=answered, solved=solved, winner_agent=0 if answered else None))
        for agent, (fb, code) in agents.items():
            events = d / f'{task}-s{seed}-a{agent}.jsonl'
            end = dict(type='puzzle_end', feedback_pass=fb, holdout_pass=solved, code=code)
            events.write_text(json.dumps(dict(type='run_start')) + '\n' + json.dumps(end) + '\n')
            rows.append(dict(task_id=task, seed=seed, agent=agent, events=str(events)))
    (d / 'cases.json').write_text(json.dumps(out))
    (d / 'summary.json').write_text(json.dumps(rows))


class PopulationTests(unittest.TestCase):
    def test_rule(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            data = root / 'datasets' / 'coding-hard-v1' / 'tasks.json'
            data.parent.mkdir(parents=True)
            data.write_text(json.dumps(dict(tasks=[dict(id=t, function_name='f', spec='s ' + t, examples=[1])
                                                   for t in ('a', 'b', 'c')])))
            write_run(root, 'r1', [('a', 1, True, False, {0: (True, 'def f(): 1'), 1: (True, 'def f(): 2'),
                                                           2: (False, 'def f(): 3')}),
                                   ('b', 1, True, True, {0: (True, 'def f(): 4')}),
                                   ('c', 1, False, False, {0: (False, 'x')})])
            write_run(root, 'r2', [(t, 2, True, True, {0: (True, 'def f(): 5'), 1: (True, '')}) for t in 'abc'])
            with patch_n(2):
                pop = dp.population(dict(runs=['r1', 'r2']), root)
        self.assertEqual((pop['wrong_cases'], pop['correct_cases'], len(pop['items'])), (1, 4, 3))
        wrong = pop['items'][0]
        self.assertEqual((wrong['kind'], [p['agent'] for p in wrong['passers']]), ('wrong', [0, 1]))  # agent 2 failed
        self.assertEqual(json.loads(wrong['payload']), {'function_name': 'f', 'spec': 's a'})  # no examples
        correct = [i for i in pop['items'] if i['kind'] == 'correct']
        order = sorted([('r1', 'b', 1)] + [('r2', t, 2) for t in 'abc'],
                       key=lambda k: dp.sha(f'{dp.SEED}:{k[0]}:{k[1]}:{k[2]}'))[:2]
        self.assertEqual([(i['run'], i['task_id'], i['seed']) for i in correct], order)
        self.assertTrue(all(len(i['passers']) == 1 for i in correct if i['run'] == 'r2'))  # empty code is no passer


class patch_n:
    def __init__(self, n):
        self.n = n

    def __enter__(self):
        self.old, dp.N_CORRECT = dp.N_CORRECT, self.n

    def __exit__(self, *a):
        dp.N_CORRECT = self.old


if __name__ == '__main__':
    unittest.main()
