"""Idea #1 confirmation plan generator (not frozen by default) and the report's confirmation label."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import extend_confirm_plans as cp  # noqa: E402
import report_extend_screen as rep  # noqa: E402
from test_extend_screen import write_run  # noqa: E402

REV = '0' * 40


def corpus(root, run, corpus_name, n_tasks, failing):
    """A complete run of n_tasks x seeds 1, 2; tasks in `failing` are unsolved with one forced rejected agent."""
    rows = []
    for t in range(n_tasks):
        for seed in (1, 2):
            fail = f't{t}' in failing
            rows.append(dict(task_id=f't{t}', seed=seed, solved=not fail, agents={0: False if fail else True}))
    write_run(root, run, corpus_name, rows)


class ConfirmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def screen(self, decision='PASS AS A SCREEN (adoption needs a fresh confirmation)', status='complete', keys=()):
        (self.root / 'EXTEND_SCREEN_PLAN.json').write_text(json.dumps(dict(items=[dict(puzzle_key=k) for k in keys])))
        report = self.root / cp.SCREEN_REPORT
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(dict(status=status, decision=decision)))

    def test_draft_by_default_with_problems(self):
        corpus(self.root, 'v27', 'c27', 20, {f't{i}' for i in range(7)})
        self.screen()
        plan = cp.make(self.root, REV, runs=('v27',))
        self.assertEqual(plan['status'], 'DRAFT')
        self.assertEqual(len(plan['items']), 7)
        self.assertIn('only 7 eligible puzzles (12 required)', plan['draft_problems'])
        self.assertTrue(all(i['item_id'].startswith('c') for i in plan['items']))
        with self.assertRaisesRegex(ValueError, 'refusing to freeze'):
            cp.make(self.root, REV, runs=('v27',), freeze=True)

    def test_freeze_needs_a_passed_screen_complete_runs_and_no_overlap(self):
        corpus(self.root, 'v27', 'c27', 20, {f't{i}' for i in range(7)})
        corpus(self.root, 'v28', 'c28', 20, {f't{i}' for i in range(6)})
        self.screen()
        plan = cp.make(self.root, REV, runs=('v27', 'v28'), freeze=True)
        self.assertEqual((plan['status'], len(plan['items']), plan['eligible_puzzles']), ('FROZEN', 12, 13))
        self.assertEqual(plan['screen'], 'idea-1-confirmation')
        self.screen(decision='STOP')
        with self.assertRaisesRegex(ValueError, 'the screen did not pass'):
            cp.make(self.root, REV, runs=('v27', 'v28'), freeze=True)
        self.screen(keys=['c27:t0'])
        with self.assertRaisesRegex(ValueError, 'shared with the screen'):
            cp.make(self.root, REV, runs=('v27', 'v28'), freeze=True)
        self.screen()
        lines = (self.root / 'runs' / 'v28' / 'cases.jsonl').read_text().splitlines()
        (self.root / 'runs' / 'v28' / 'cases.jsonl').write_text('\n'.join(lines[:-1]) + '\n')  # an unfinished run
        with self.assertRaisesRegex(ValueError, '19 of 20 planned cases|39 of 40 planned cases'):
            cp.make(self.root, REV, runs=('v27', 'v28'), freeze=True)

    def test_the_selection_rule_is_the_screens(self):
        corpus(self.root, 'v27', 'c27', 30, {f't{i}' for i in range(14)})
        self.screen()
        plan = cp.make(self.root, REV, runs=('v27',))
        items, _ = cp.ep.select(self.root, runs=('v27',))
        self.assertEqual([i['puzzle_key'] for i in plan['items']], [i['puzzle_key'] for i in items])
        self.assertEqual(plan['selection_seed'], cp.ep.SELECTION_SEED)

    def test_report_label(self):
        plan = dict(study='s', screen='idea-1-confirmation',
                    items=[dict(item_id='c0', puzzle_key='p0', numbers=[2, 3, 7], target=5)])
        run = self.root / 'run'
        (run / 'run').mkdir(parents=True)
        (run / 'metadata.json').write_text(json.dumps(dict(plan=plan)))
        (run / 'summary.json').write_text(json.dumps(dict(drain_confirmed=True, complete=True)))
        good, bad = {'moves': [{'i': 0, 'j': 1, 'op': '+'}]}, {'moves': [{'i': 0, 'j': 2, 'op': '+'}]}
        recs = [dict(item='c0', arm=arm, attempt=k, error=None, verdict=arm == 'extension' and k == 1,
                     candidate=dict(plan=good if arm == 'extension' and k == 1 else bad), forced_reply='json')
                for arm in rep.ARMS for k in rep.ATTEMPTS]
        (run / 'run' / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs))
        self.assertEqual(rep.build(plan, run)['decision'], 'PASS (confirmation)')
        plan2 = dict(plan, screen='idea-1')
        (run / 'metadata.json').write_text(json.dumps(dict(plan=plan2)))
        self.assertTrue(rep.build(plan2, run)['decision'].startswith('PASS AS A SCREEN'))


if __name__ == '__main__':
    unittest.main()
