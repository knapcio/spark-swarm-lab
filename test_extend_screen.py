"""Idea #1 screen: the frozen selection rule (synthetic recorded runs) and the report's rule."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import extend_plans as ep  # noqa: E402
import report_extend_screen as rep  # noqa: E402


def write_run(root, name, corpus, rows):
    d = root / 'runs' / name
    (d / 'agents').mkdir(parents=True)
    tasks = sorted({r['task_id'] for r in rows})
    data = root / 'datasets' / corpus / 'tasks.json'
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(json.dumps(dict(protocol=corpus, tasks=[dict(id=t, split='evaluation', numbers=[1, 2]) for t in tasks])))
    (d / 'metadata.json').write_text(json.dumps(dict(protocol=dict(dataset=f'datasets/{corpus}/tasks.json',
                                                                   dataset_protocol=corpus, split='evaluation',
                                                                   tasks=len(tasks), seeds=[1, 2]))))
    with (d / 'cases.jsonl').open('w') as sink:
        for r in rows:
            sink.write(json.dumps(dict(policy='roll12fair', task_id=r['task_id'], seed=r['seed'], solved=r['solved'],
                                       agents=[dict(slot=s, verdict=v) for s, v in r['agents'].items()])) + '\n')
    for r in rows:
        for s, v in r['agents'].items():
            forced, n = r.get('forced', {}).get(s, True), r.get('tokens', {}).get(s, ep.THINK)
            ev = [dict(type='run_start', config=dict(puzzle='1,2:3', seed=1000 * r['seed'] + s)),
                  dict(type='request_start', request_id='q', stage='plan', prompt_ids_sha256='p'),
                  dict(type='request_end', request_id='q', stage='plan', finish_reason='length', closed_thinking=False,
                       token_ids=[7] * n, error=None)]
            if forced:
                ev.append(dict(type='budget_forced'))
            (d / 'agents' / f"{r['task_id']}-s{r['seed']}-roll12fair-a{s}.jsonl").write_text(
                ''.join(json.dumps(e) + '\n' for e in ev))


class SelectionTests(unittest.TestCase):
    def test_mechanical_selection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_run(root, 'r1', 'c1', [
                dict(task_id='t1', seed=1, solved=False, agents={0: None, 1: False, 2: False}),   # first: slot 1
                dict(task_id='t1', seed=2, solved=False, agents={0: False}),                       # same puzzle
                dict(task_id='t2', seed=1, solved=True, agents={0: False}),                        # solved case
                dict(task_id='t3', seed=1, solved=False, agents={0: False}, forced={0: False}),    # not forced
                dict(task_id='t4', seed=1, solved=False, agents={0: False}, tokens={0: 100}),      # not at the cap
                dict(task_id='t5', seed=1, solved=False, agents={0: True, 1: False})])
            write_run(root, 'r2', 'c2', [dict(task_id='t1', seed=1, solved=False, agents={3: False})])  # other corpus
            fails = ep.failures(root, runs=('r1', 'r2'))
            self.assertEqual([(f['corpus'], f['task_id'], f['seed'], f['slot']) for f in fails],
                             [('c1', 't1', 1, 1), ('c1', 't1', 1, 2), ('c1', 't5', 1, 1), ('c1', 't1', 2, 0),
                              ('c2', 't1', 1, 3)])  # run, seed, task, slot
            items, eligible = ep.select(root, runs=('r1', 'r2'), n=2)
            self.assertEqual(eligible, 3)
            keys = sorted(['c1:t1', 'c1:t5', 'c2:t1'], key=lambda k: ep.sha(f'{ep.SELECTION_SEED}:{k}'))
            self.assertEqual([i['puzzle_key'] for i in items], keys[:2])
            first = next(i for i in ep.select(root, runs=('r1', 'r2'), n=3)[0] if i['puzzle_key'] == 'c1:t1')
            self.assertEqual((first['seed'], first['slot'], first['recorded_tokens']), (1, 1, ep.THINK))


class ReportTests(unittest.TestCase):
    GOOD = {'moves': [{'i': 0, 'j': 1, 'op': '+'}]}  # 2 + 3 = 5
    TRAILING = {'moves': [{'i': 0, 'j': 1, 'op': '+'}, {'i': 7, 'j': 8, 'op': '+'}]}  # 5, then an illegal move
    BAD = {'moves': [{'i': 0, 'j': 2, 'op': '+'}]}  # 9

    def run_dir(self, d, plan, outcomes, drained=True, complete=True, extra=()):
        run = Path(d)
        (run / 'run').mkdir(parents=True)
        (run / 'metadata.json').write_text(json.dumps(dict(plan=plan)))
        (run / 'summary.json').write_text(json.dumps(dict(drain_confirmed=drained, complete=complete)))
        recs = [dict(item=i, arm=a, attempt=k, error=None, verdict=v, candidate=dict(plan=self.GOOD if s is True else
                                                                                    self.TRAILING if s == 'trail'
                                                                                    else self.BAD),
                     verifier_solved=bool(s), tokens_generated=10, forced_reply='json')
                for (i, a, k), (v, s) in outcomes.items()] + list(extra)
        (run / 'run' / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs))
        return run

    def test_rule(self):
        plan = dict(study='s', items=[dict(item_id=f'x{i}', puzzle_key=f'p{i}', numbers=[2, 3, 7], target=5)
                                      for i in range(3)])
        base = {(f'x{i}', a, k): (False, False) for i in range(3) for a in rep.ARMS for k in rep.ATTEMPTS}
        with tempfile.TemporaryDirectory() as d:
            win = {**base, ('x0', 'extension', 2): (True, True), ('x1', 'extension', 1): (True, True),
                   ('x1', 'fresh', 1): (True, True), ('x2', 'fresh', 2): (True, False)}
            r = rep.build(plan, self.run_dir(Path(d) / 'a', plan, win))
            self.assertEqual((r['extension_rescues'], r['fresh_rescues'], r['decision'][:4]), (2, 1, 'PASS'))
            self.assertEqual(r['arms']['fresh']['wrong'], 1)  # accepted, not solved: no rescue, a wrong acceptance
            tie = {**base, ('x0', 'extension', 1): (True, True), ('x0', 'fresh', 2): (True, True)}
            self.assertEqual(rep.build(plan, self.run_dir(Path(d) / 'b', plan, tie))['decision'], 'STOP')
            missing = dict(base)
            del missing[('x2', 'fresh', 2)]
            self.assertEqual(rep.build(plan, self.run_dir(Path(d) / 'c', plan, missing))['status'], 'incomplete')
            self.assertEqual(rep.build(plan, self.run_dir(Path(d) / 'e', plan, base, drained=False))['status'],
                             'incomplete')
            # sol review: the driver's own verdict and exactly the planned records
            self.assertIn('summary is not complete', ' '.join(rep.build(
                plan, self.run_dir(Path(d) / 'f', plan, win, complete=False))['problems']))
            stray = dict(item='x9', arm='fresh', attempt=1, error=None, verdict=True)
            self.assertIn('outside the plan', ' '.join(rep.build(
                plan, self.run_dir(Path(d) / 'g', plan, win, extra=[stray]))['problems']))
            # strict verifier: a plan that reaches the target and then makes an illegal move is a wrong acceptance
            trail = {**base, ('x0', 'extension', 1): (True, 'trail')}
            r = rep.build(plan, self.run_dir(Path(d) / 'h', plan, trail))
            self.assertEqual((r['extension_rescues'], r['arms']['extension']['wrong']), (0, 1))
            self.assertEqual(r['arms']['extension']['forced_replies'], {'json': 6})


if __name__ == '__main__':
    unittest.main()
