"""Idea #2 falsifier: the frozen selection rule (synthetic recorded runs) and the report's rule."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_restate_screen as rep  # noqa: E402
import restate_plans as rp  # noqa: E402

GOOD = {'moves': [{'i': 0, 'j': 1, 'op': '+'}]}  # 2 + 3 = 5
TRAILING = {'moves': [{'i': 0, 'j': 1, 'op': '+'}, {'i': 7, 'j': 8, 'op': '+'}]}
BAD = {'moves': [{'i': 0, 'j': 2, 'op': '+'}]}
FAMILY = ('arithmetic', 'number', 'target', 'move', 'json', 'plan', 'integer', 'operator', 'puzzle', 'countdown')


def write_run(root, name, corpus, rows):
    """rows: task_id, seed, answered, agents {slot: started}."""
    d = root / 'runs' / name
    (d / 'agents').mkdir(parents=True)
    tasks = sorted({r['task_id'] for r in rows})
    data = root / 'datasets' / corpus / 'tasks.json'
    data.parent.mkdir(parents=True, exist_ok=True)
    data.write_text(json.dumps(dict(protocol=corpus, tasks=[dict(id=t, split='evaluation', numbers=[2, 3, 7])
                                                            for t in tasks])))
    (d / 'metadata.json').write_text(json.dumps(dict(protocol=dict(dataset=f'datasets/{corpus}/tasks.json',
                                                                   dataset_protocol=corpus, split='evaluation',
                                                                   tasks=len(tasks), seeds=[1, 2]))))
    with (d / 'cases.jsonl').open('w') as sink:
        for r in rows:
            sink.write(json.dumps(dict(policy='roll12fair', task_id=r['task_id'], seed=r['seed'],
                                       answered=r['answered'], agents=[dict(slot=s) for s in r['agents']])) + '\n')
            for s, started in r['agents'].items():
                ev = [dict(type='run_start', config=dict(variant='xl_forced_original', puzzle='2,3,7:5', seed=s))]
                if started:
                    ev.append(dict(type='request_start', stage='plan',
                                   prompt_ids_sha256=f"p-{r['task_id']}-{r['seed']}-{s}"))
                (d / 'agents' / f"{r['task_id']}-s{r['seed']}-roll12fair-a{s}.jsonl").write_text(
                    ''.join(json.dumps(e) + '\n' for e in ev))


class SelectionTests(unittest.TestCase):
    def test_abstentions_rule_and_pins(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_run(root, 'r1', 'c1', [
                dict(task_id='t1', seed=1, answered=True, agents={0: True}),
                dict(task_id='t1', seed=2, answered=False, agents={0: False, 1: True}),  # pin: slot 1 (first started)
                dict(task_id='t2', seed=1, answered=False, agents={0: True}),
                dict(task_id='t2', seed=2, answered=False, agents={0: True}),  # same puzzle: first abstention kept
                dict(task_id='t3', seed=1, answered=True, agents={0: True})])
            write_run(root, 'r2', 'c2', [dict(task_id='t1', seed=1, answered=False, agents={2: True})])
            found = rp.abstentions(root, runs=('r1', 'r2'))
            self.assertEqual([(a['corpus'], a['task_id'], a['seed']) for a in found],
                             [('c1', 't2', 1), ('c1', 't1', 2), ('c1', 't2', 2), ('c2', 't1', 1)])
            self.assertEqual(found[1]['prompt_ids_sha256'], 'p-t1-2-1')
            items, eligible = rp.select(root, runs=('r1', 'r2'), n=2)
            self.assertEqual(eligible, 3)
            keys = sorted(['c1:t1', 'c1:t2', 'c2:t1'], key=lambda k: rp.sha(f'{rp.SELECTION_SEED}:{k}'))
            self.assertEqual([i['puzzle_key'] for i in items], keys[:2])
            self.assertTrue(all(i['seed_base'] >= rp.SEED_OFFSET for i in items))

    def test_restatement_prompt_is_generic(self):
        text = (rp.RESTATE_SYSTEM + ' ' + rp.RESTATE_USER).lower()
        self.assertEqual([w for w in FAMILY if w in text], [])


class ReportTests(unittest.TestCase):
    PLAN = dict(study='s', items=[dict(item_id=f'z{i}', puzzle_key=f'p{i}', numbers=[2, 3, 7], target=5)
                                  for i in range(3)])

    def run_dir(self, d, outcomes, complete=True, drained=True, extra=(), drop=()):
        run = Path(d)
        (run / 'run').mkdir(parents=True)
        (run / 'metadata.json').write_text(json.dumps(dict(plan=self.PLAN)))
        (run / 'summary.json').write_text(json.dumps(dict(drain_confirmed=drained, complete=complete)))
        recs = []
        for i in self.PLAN['items']:
            for arm in rep.ARMS:
                for k in rep.WORKERS:
                    key = (i['item_id'], arm, k)
                    if key in drop:
                        continue
                    verdict, plan = outcomes.get(key, (False, BAD))
                    recs.append(dict(item=key[0], arm=arm, index=k, error=None, verdict=verdict,
                                     candidate=None if plan is None else dict(plan=plan), tokens_generated=100,
                                     restate_tokens=20 if arm == 'restated' else 0, judge_tokens=10,
                                     restatement_empty=plan is None, forced_reply='json'))
        (run / 'run' / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs + list(extra)))
        return run

    def test_rule(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            tie = {('z0', 'original', 0): (True, GOOD), ('z0', 'restated', 1): (True, GOOD)}
            r = rep.build(self.PLAN, self.run_dir(d / 'a', tie))
            self.assertEqual((r['original_rescues'], r['restated_rescues'], r['decision']), (1, 1, 'STOP'))
            win = {**tie, ('z1', 'restated', 0): (True, GOOD)}
            r = rep.build(self.PLAN, self.run_dir(d / 'b', win))
            self.assertTrue(r['decision'].startswith('PASS'))
            self.assertEqual(r['restated_only'], 1)
            trail = {**tie, ('z1', 'restated', 0): (True, TRAILING), ('z2', 'restated', 1): (False, None)}
            r = rep.build(self.PLAN, self.run_dir(d / 'c', trail))
            self.assertEqual((r['restated_rescues'], r['arms']['restated']['wrong'], r['decision']), (1, 1, 'STOP'))
            self.assertEqual(r['arms']['restated']['empty_restatements'], 1)
            self.assertEqual(r['arms']['restated']['restate_tokens'], 120)

    def test_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, kw, needle in (('a', dict(complete=False), 'summary is not complete'),
                                     ('b', dict(drained=False), 'drain was not confirmed'),
                                     ('c', dict(drop=[('z1', 'restated', 0)]), "('z1', 'restated', 0) missing"),
                                     ('d', dict(extra=[dict(item='z9', arm='original', index=0)]), 'outside the plan')):
                r = rep.build(self.PLAN, self.run_dir(d / name, {}, **kw))
                self.assertEqual(r['status'], 'incomplete')
                self.assertIn(needle, ' '.join(r['problems']))


if __name__ == '__main__':
    unittest.main()
