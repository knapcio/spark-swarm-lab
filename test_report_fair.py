"""Offline tests for inkling/report_fair.py on synthetic run directories."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_fair as rep  # noqa: E402
from test_report_relay_swarm import acct, write_run  # noqa: E402

STUDY = rep.STUDY
TASKS = [dict(id=f't{i}', split='evaluation', numbers=[3, 15, 55, 7, 2, 9], target=822) for i in range(3)]


def row(task, policy, slot=None, solved=True, wrong=False, answer_s=None, start_s=None, **extra):
    answered = slot is not None
    agents = [dict(slot=slot if answered else 0, plan=None, verdict=True if answered else None, verifier_solved=solved,
                   started=True, cancelled=False, tokens=10, finished_s=100.0, judged_s=110.0)]
    r = dict(task_id=task, seed=1, policy=policy, answered=answered, solved=answered and solved, wrong=answered and wrong,
             infra=0, selected_slot=slot, agents=agents, answer_seconds=answer_s, **extra)
    if start_s is not None:
        r['case_start_s'] = start_s
    return r


def study(root, f_wall=90.0, w_wall=100.0, f_tokens=1000, w_tokens=1000, f_rows=None):
    (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=TASKS)))
    plan = dict(study=STUDY, dataset=str(root / 'data.json'), dataset_protocol='p', split='evaluation', tasks=3, seeds=[1],
                policies=list(rep.ARMS.values()), agent_variant='xl_forced_original',
                seed_offsets={p: 22400 for p in rep.ARMS.values()}, decision_rule='F replaces W if ...')
    (root / rep.PLAN).write_text(json.dumps(plan))
    runs = root / 'runs'
    write_run(runs / f'{STUDY}-roll12wide', plan, 'roll12wide',
              [row('t0', 'roll12wide', 0, answer_s=100.0, start_s=0.0, max_in_flight=4),
               row('t1', 'roll12wide', 5, answer_s=400.0, start_s=300.0, max_in_flight=8),
               row('t2', 'roll12wide', max_in_flight=8)], acct(w_tokens, prompt=30000, prefill=9000, wall=w_wall, wh=2.0))
    write_run(runs / f'{STUDY}-roll12fair', plan, 'roll12fair',
              f_rows or [row('t0', 'roll12fair', 0, answer_s=120.0, start_s=0.0, max_in_flight=4, first_failure_s=None),
                         row('t1', 'roll12fair', 5, answer_s=300.0, start_s=0.0, max_in_flight=8, first_failure_s=80.0),
                         row('t2', 'roll12fair', max_in_flight=8, first_failure_s=60.0)],
              acct(f_tokens, prompt=29000, prefill=8800, wall=f_wall, wh=1.7))


class FairReportTests(unittest.TestCase):
    def build(self, root):
        return rep.build(root, {k: f'runs/{STUDY}-{p}' for k, p in rep.ARMS.items()})

    def test_full_study(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            s = self.build(root)
            with contextlib.redirect_stdout(io.StringIO()):
                rep.main(['--root', d])
            md = (root / 'results' / STUDY / 'REPORT.md').read_text()
        W, F = s['arms']['W'], s['arms']['F']
        self.assertEqual((W['status'], F['status']), ('complete', 'complete'), (W.get('reasons'), F.get('reasons')))
        self.assertEqual(s['decision'], dict(zero_wrong=True, solved_within_noise=True, wall_at_most_95pct_of_W=True,
                                             tokens_at_most_100pct_of_W=True, F_replaces_W=True))
        self.assertEqual(F['answer_time_s']['from_segment_start'], dict(n=2, mean=210.0, median=210.0, p90=300.0))
        self.assertEqual(W['answer_time_s']['from_segment_start'], dict(n=2, mean=400.0, median=400.0, p90=700.0))
        self.assertEqual(W['answer_time_s']['from_case_start']['median'], 250.0)
        self.assertEqual(F['first_failure_s_median'], 70.0)
        self.assertIn('Time to an answer', md)
        self.assertIn('fewest agents in flight', md)

    def test_rules_are_exact(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, f_wall=95.000001)
            self.assertFalse(self.build(root)['decision']['wall_at_most_95pct_of_W'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, f_wall=95.0)
            self.assertTrue(self.build(root)['decision']['wall_at_most_95pct_of_W'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, f_tokens=1001)
            self.assertFalse(self.build(root)['decision']['tokens_at_most_100pct_of_W'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, f_rows=[row('t0', 'roll12fair', 0, solved=False, wrong=True), row('t1', 'roll12fair', 5),
                                row('t2', 'roll12fair')])
            self.assertFalse(self.build(root)['decision']['zero_wrong'])

    def test_pairing_must_be_complete(self):
        w = {('t0', 1): {}, ('t1', 1): {}}
        self.assertIn('case sets differ', ' '.join(rep.pairing(dict(W=dict(rows=w), F=dict(rows={('t0', 1): {}})))))
        self.assertIn('no paired cases', rep.pairing(dict(W=dict(rows={}), F=dict(rows={}))))
        self.assertTrue(rep.decision(dict(W=dict(status='complete'), F=dict(status='complete')),
                                     ['no paired cases']).startswith('incomplete'))

    def test_missing_arm_is_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            s = rep.build(root, dict(W=f'runs/{STUDY}-roll12wide', F='runs/missing'))
        self.assertEqual(s['arms']['F']['status'], 'not run')
        self.assertTrue(s['decision'].startswith('incomplete'))


if __name__ == '__main__':
    unittest.main()
