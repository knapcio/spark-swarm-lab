"""Idea #4 falsifier: the frozen selection rule (synthetic recorded runs) and the report's rule."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import fork_plans as fp  # noqa: E402
import report_fork_screen as rep  # noqa: E402

GOOD = {'moves': [{'i': 0, 'j': 1, 'op': '+'}]}  # 2 + 3 = 5
TRAILING = {'moves': [{'i': 0, 'j': 1, 'op': '+'}, {'i': 7, 'j': 8, 'op': '+'}]}
BAD = {'moves': [{'i': 0, 'j': 2, 'op': '+'}]}


def write_run(root, name, corpus, rows, variant='xl_forced_original'):
    """rows: task_id, seed, agents {slot: (verdict, verifier_solved)}."""
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
            sink.write(json.dumps(dict(policy='roll12fair', task_id=r['task_id'], seed=r['seed'], agents=[
                dict(slot=s, verdict=v, verifier_solved=ok) for s, (v, ok) in r['agents'].items()])) + '\n')
            for s in r['agents']:
                ev = [dict(type='run_start', config=dict(variant=variant, puzzle='2,3,7:5', seed=s)),
                      dict(type='request_start', stage='plan', prompt_ids_sha256=f"p-{r['task_id']}-{r['seed']}-{s}")]
                (d / 'agents' / f"{r['task_id']}-s{r['seed']}-roll12fair-a{s}.jsonl").write_text(
                    ''.join(json.dumps(e) + '\n' for e in ev))


class SelectionTests(unittest.TestCase):
    def test_contested_rule_and_pins(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_run(root, 'r1', 'c1', [
                dict(task_id='t1', seed=1, agents={0: (False, False), 1: (None, None), 2: (True, True)}),
                dict(task_id='t1', seed=2, agents={0: (False, False), 1: (False, False)}),  # t1: 1/4 -> contested
                dict(task_id='t2', seed=1, agents={0: (True, True), 1: (True, True), 2: (False, False),
                                                   3: (False, False)}),  # 2/4 = 0.5 -> contested
                dict(task_id='t3', seed=1, agents={0: (True, True), 1: (True, True), 2: (True, True),
                                                   3: (False, False)}),  # 3/4 -> too easy
                dict(task_id='t4', seed=1, agents={0: (False, False), 1: (False, False), 2: (False, False),
                                                   3: (False, False)}),  # 0 wins -> excluded
                dict(task_id='t5', seed=1, agents={0: (True, True), 1: (False, False), 2: (False, False)}),  # 3 judged
                dict(task_id='t6', seed=1, agents={0: (True, False), 1: (False, False), 2: (False, False),
                                                   3: (False, False)})])  # accepted but not solved: no win
            pool = fp.contested(root, runs=('r1',))
            self.assertEqual(sorted(k[1] for k in pool), ['t1', 't2'])
            self.assertEqual(pool[('c1', 't1')]['prompt_ids_sha256'], 'p-t1-1-0')  # first judged: seed 1, slot 0
            self.assertEqual((pool[('c1', 't1')]['judged'], pool[('c1', 't1')]['wins']), (4, 1))
            items, eligible = fp.select(root, runs=('r1',), n=1)
            self.assertEqual(eligible, 2)
            first = min(['c1:t1', 'c1:t2'], key=lambda k: fp.sha(f'{fp.SELECTION_SEED}:{k}'))
            self.assertEqual(items[0]['puzzle_key'], first)
            self.assertGreaterEqual(items[0]['seed_base'], fp.SEED_OFFSET)

    def test_other_variant_is_not_pinned(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_run(root, 'r1', 'c1', [dict(task_id='t1', seed=1, agents={
                0: (True, True), 1: (False, False), 2: (False, False), 3: (False, False)})], variant='long_x')
            self.assertEqual(fp.contested(root, runs=('r1',)), {})


class ReportTests(unittest.TestCase):
    PLAN = dict(study='s', items=[dict(item_id=f'y{i}', puzzle_key=f'p{i}', numbers=[2, 3, 7], target=5)
                                  for i in range(2)])

    def run_dir(self, d, outcomes, tokens=None, complete=True, drained=True, extra=(), drop=()):
        """outcomes {(item, arm, index): (verdict, plan)}; every other planned unit is a rejected BAD candidate."""
        run = Path(d)
        (run / 'run').mkdir(parents=True)
        (run / 'metadata.json').write_text(json.dumps(dict(plan=self.PLAN)))
        (run / 'summary.json').write_text(json.dumps(dict(drain_confirmed=drained, complete=complete)))
        recs = []
        for key in sorted(rep.planned(self.PLAN), key=str):
            if key in drop:
                continue
            item, arm, index = key
            verdict, plan = outcomes.get(key, (False, BAD))
            n = (tokens or {}).get(arm, 100)
            rec = dict(item=item, arm=arm, index=index, error=None, tokens_generated=n, judge_tokens=0,
                       forced_reply='json')
            if arm == 'stem':
                rec.update(forked=True, candidate=None)
            else:
                rec.update(verdict=verdict, candidate=dict(plan=plan), judge_tokens=10)
            recs.append(rec)
        (run / 'run' / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs + list(extra)))
        return run

    def test_rule(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            both = {('y0', 'fresh', 1): (True, GOOD), ('y0', 'fork', 3): (True, GOOD)}
            # fresh: 4 x 100 + 4 x 10 = 440 per item; fork: 2 x 100 (stems) + 4 x 60 + 40 = 480 -> no saving
            r = rep.build(self.PLAN, self.run_dir(d / 'a', both, tokens=dict(fresh=100, stem=100, fork=60)))
            self.assertEqual((r['coverage_fresh'], r['coverage_fork'], r['decision']), (1, 1, 'STOP'))
            self.assertIn('no net compute saving', r['stop_reasons'][0])
            r = rep.build(self.PLAN, self.run_dir(d / 'b', both, tokens=dict(fresh=100, stem=40, fork=60)))
            self.assertTrue(r['decision'].startswith('PASS'))  # equal coverage, 400 < 440 per item
            self.assertEqual(r['arms']['fork']['stems_forked'], 4)
            lower = {('y0', 'fresh', 1): (True, GOOD), ('y1', 'fresh', 0): (True, GOOD),
                     ('y0', 'fork', 0): (True, GOOD)}
            r = rep.build(self.PLAN, self.run_dir(d / 'c', lower, tokens=dict(fresh=100, stem=40, fork=60)))
            self.assertEqual((r['coverage_fresh'], r['coverage_fork'], r['decision']), (2, 1, 'STOP'))
            # strict verifier: an accepted trailing-illegal plan neither covers nor counts as a success
            trail = {('y0', 'fresh', 1): (True, GOOD), ('y0', 'fork', 2): (True, TRAILING)}
            r = rep.build(self.PLAN, self.run_dir(d / 'e', trail, tokens=dict(fresh=100, stem=40, fork=60)))
            self.assertEqual((r['coverage_fork'], r['arms']['fork']['wrong'], r['decision']), (0, 1, 'STOP'))

    def test_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for name, kw, needle in (('a', dict(complete=False), 'summary is not complete'),
                                     ('b', dict(drained=False), 'drain was not confirmed'),
                                     ('c', dict(drop=[('y1', 'stem', 0)]), "('y1', 'stem', 0) missing"),
                                     ('d', dict(extra=[dict(item='y9', arm='fork', index=0)]), 'outside the plan')):
                r = rep.build(self.PLAN, self.run_dir(d / name, {}, **kw))
                self.assertEqual(r['status'], 'incomplete')
                self.assertIn(needle, ' '.join(r['problems']))
            faulted = dict(item='y0', arm='fresh', index=0, error=None, not_started=True)
            r = rep.build(self.PLAN, self.run_dir(d / 'e', {}, extra=[faulted], drop=[('y0', 'fresh', 0)]))
            self.assertIn('not started', ' '.join(r['problems']))


if __name__ == '__main__':
    unittest.main()
