"""Offline tests for inkling/report_reserve_coding.py on synthetic coding run directories."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_reserve_coding as rep  # noqa: E402
from test_report_aot_coding import CASES, TASKS, plan  # noqa: E402
from test_report_relay_swarm import acct  # noqa: E402

STUDY = rep.STUDY
XL_CUT = dict(budget_forced=True, forced_finish_reason='length', first_finish_reason='length')
XL_FORCED = dict(budget_forced=True, forced_finish_reason='stop', first_finish_reason='length')
SELF = dict(budget_forced=False, answer_continued=False, first_finish_reason='stop')
RES_FORCED = dict(budget_forced=True, answer_continued=False, answer_steps=2, answer_cut=False, first_finish_reason='length')


def write_arm(root, k, p, outcomes, tokens):
    """outcomes: {case: (result, puzzle_end path fields)}; result is 'solved' | 'wrong' | 'none'."""
    d = root / rep.ARMS[k]['dir']
    d.mkdir(parents=True)
    (root / rep.ARMS[k]['plan']).write_text(json.dumps(p))
    summary, cases = [], []
    for (task, seed), (out, path) in outcomes.items():
        events = d / f'{task}-s{seed}-a0.jsonl'
        events.write_text(json.dumps(dict(type='puzzle_end', feedback_pass=out != 'none', holdout_pass=out == 'solved',
                                          **path)) + '\n')
        summary.append(dict(task_id=task, seed=seed, agent=0, events=f'/x/{events.name}', controller_error=None,
                            malformed_lines=0, infrastructure_failures=0, returncode=0, controller_stop=False,
                            deadline=False, calls=1, unfinished_calls=0, status='complete', feedback_pass=out != 'none',
                            holdout_pass=out == 'solved', cancelled=False, completion_tokens=100))
        cases.append(dict(task_id=task, seed=seed, answered=out != 'none', solved=out == 'solved',
                          winner_agent=0 if out != 'none' else None))
    (d / 'summary.json').write_text(json.dumps(summary))
    (d / 'cases.json').write_text(json.dumps(cases))
    (d / 'metadata.json').write_text(json.dumps(dict(protocol=p, completed_utc='2026-11-26T03:00:00+00:00', errors=[],
                                                     source_changed_during_run=False)))
    (d / 'arm_accounting.json').write_text(json.dumps(acct(tokens, prompt=10000, prefill=3000)))


def study(root, p_out=None, a_out=None, p_tokens=1000, a_tokens=1000, variant='code_reserve'):
    (root / 'corpus.json').write_text(json.dumps(dict(tasks=TASKS)))
    p_out = p_out or {c: (('solved', SELF) if i < 5 else ('wrong', XL_FORCED) if i == 5 else ('none', XL_CUT))
                      for i, c in enumerate(CASES)}
    a_out = a_out or {c: (('solved', SELF) if i < 5 else ('wrong', RES_FORCED) if i == 5 else ('solved', RES_FORCED))
                      for i, c in enumerate(CASES)}
    write_arm(root, 'P', plan('code_xl'), p_out, p_tokens)
    write_arm(root, 'A', plan(variant), a_out, a_tokens)


class ReserveReportTests(unittest.TestCase):
    def build(self, root, variant='code_reserve'):
        return rep.build(root, {k: v['dir'] for k, v in rep.ARMS.items()}, variant=variant)

    def test_adopted_with_answer_paths(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            s = self.build(root)
            with contextlib.redirect_stdout(io.StringIO()):
                rep.main(['--root', d])
            md = (root / 'results' / STUDY / 'REPORT.md').read_text()
        P, A = s['arms']['P'], s['arms']['A']
        self.assertEqual((P['status'], A['status']), ('complete', 'complete'), (P.get('reasons'), A.get('reasons')))
        self.assertEqual((P['solved'], P['wrong'], P['unanswered'], A['solved'], A['wrong'], A['unanswered']),
                         (5, 1, 2, 7, 1, 0))
        self.assertEqual(s['decision'], dict(unanswered_at_most_plain=True, solved_at_least_plain_minus_1=True,
                                             wrong_at_most_plain_plus_1=True, tokens_at_most_100pct=True,
                                             reserve_adopted=True))
        self.assertEqual((P['answers']['answer_cut'], P['answers']['answer_cut_failed'], A['answers']['answer_cut']), (2, 2, 0))
        self.assertEqual(A['wrong_paths'], [dict(task_id=CASES[5][0], seed=CASES[5][1], agent=0, path='forced',
                                                 answer_steps=2, answer_cut=False)])
        self.assertEqual(P['wrong_paths'][0]['path'], 'forced')
        self.assertIn('keeps the 32,768-token agent budget', md)

    def test_rules_are_exact(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, a_tokens=1001)
            self.assertFalse(self.build(root)['decision']['tokens_at_most_100pct'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # solved P - 2, more unanswered
            study(root, a_out={c: (('solved', SELF) if i < 3 else ('none', RES_FORCED)) for i, c in enumerate(CASES)})
            dec = self.build(root)['decision']
            self.assertEqual((dec['solved_at_least_plain_minus_1'], dec['unanswered_at_most_plain']), (False, False))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)  # wrong P + 2
            study(root, a_out={c: (('solved', SELF) if i < 5 else ('wrong', RES_FORCED)) for i, c in enumerate(CASES)})
            self.assertFalse(self.build(root)['decision']['wrong_at_most_plain_plus_1'])

    def test_variant_must_match_the_plan_and_elastic_is_disclosed(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, variant='code_elastic')
            self.assertIn('expected only code_reserve', ' '.join(self.build(root)['arms']['A']['reasons']))
            s = self.build(root, 'code_elastic')
            self.assertTrue(s['decision']['reserve_adopted'])
            self.assertIn('8,192 more tokens', rep.markdown(s))
        with self.assertRaises(ValueError):
            rep.build(Path('/nonexistent'), {}, variant='code_xl')

    def test_unpaired_arms_are_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'corpus.json').write_text(json.dumps(dict(tasks=TASKS)))
            write_arm(root, 'P', plan('code_xl'), {c: ('solved', SELF) for c in CASES}, 1000)
            write_arm(root, 'A', plan('code_reserve', agent_seed_offset=1), {c: ('solved', SELF) for c in CASES}, 900)
            s = self.build(root)
        self.assertIn("frozen plans differ in ['agent_seed_offset']", s['decision'])


if __name__ == '__main__':
    unittest.main()
