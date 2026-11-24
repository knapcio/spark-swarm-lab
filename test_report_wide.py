"""Offline tests for inkling/report_wide.py on synthetic run directories."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_wide as rep  # noqa: E402
from test_report_relay_swarm import acct, write_run  # noqa: E402

STUDY = 'swarm-wide-hard20-v1'
TASKS = [dict(id=f't{i}', split='evaluation', numbers=[3, 15, 55, 7, 2, 9], target=822) for i in range(3)]


def row(task, policy, slot=None, solved=True, wrong=False, **extra):
    answered = slot is not None
    agents = [dict(slot=slot if answered else 0, plan=None, verdict=True if answered else None, verifier_solved=solved,
                   started=True, cancelled=False, tokens=10, finished_s=100.0, judged_s=100.0 + extra.pop('lat', 10))]
    return dict(dict(task_id=task, seed=1, policy=policy, answered=answered, solved=answered and solved,
                     wrong=answered and wrong, infra=0, selected_slot=slot, agents=agents), **extra)


def study(root, w_wall=90.0, g_wall=100.0, w_rows=None):
    (root / 'data.json').write_text(json.dumps(dict(protocol='p', tasks=TASKS)))
    plan = dict(study=STUDY, dataset=str(root / 'data.json'), dataset_protocol='p', split='evaluation', tasks=3, seeds=[1],
                policies=list(rep.ARMS.values()), agent_variant='xl_forced_original',
                seed_offsets={p: 20400 for p in rep.ARMS.values()}, decision_rule='W replaces G if ...')
    (root / rep.PLAN).write_text(json.dumps(plan))
    runs = root / 'runs'
    write_run(runs / f'{STUDY}-roll12cancel', plan, 'roll12cancel',
              [row('t0', 'roll12cancel', 0), row('t1', 'roll12cancel', 5), row('t2', 'roll12cancel')],
              acct(1200, prompt=30000, prefill=9000, wall=g_wall, wh=2.0))
    write_run(runs / f'{STUDY}-roll12wide', plan, 'roll12wide',
              w_rows or [row('t0', 'roll12wide', 0, max_in_flight=4, widened_agents=0, widened_at_s=None),
                         row('t1', 'roll12wide', 6, max_in_flight=8, widened_agents=4, widened_at_s=300.0, lat=30),
                         row('t2', 'roll12wide', max_in_flight=8, widened_agents=4, widened_at_s=500.0, lat=50)],
              acct(1230, prompt=31000, prefill=9300, wall=w_wall, wh=1.8))


class WideReportTests(unittest.TestCase):
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
        G, W = s['arms']['G'], s['arms']['W']
        self.assertEqual([(a['status'], a['solved']) for a in (G, W)], [('complete', 2), ('complete', 2)])
        self.assertEqual((W['widened_cases'], W['widened_agents'], W['widened_at_s_median']), (2, 8, 400.0))
        self.assertEqual(W['max_in_flight_histogram'], {'4': 1, '8': 2})
        self.assertEqual((W['judge_latency_p90'], W['wh_per_solved']), (50, 0.9))
        self.assertEqual(s['facts']['wall_ratio_w_over_g'], 0.9)
        self.assertEqual(s['decision'], dict(zero_wrong=True, solved_within_noise=True, wall_at_most_95pct_of_G=True,
                                             W_replaces_G=True))
        self.assertIn('Widening (W)', md)
        self.assertIn('never elapsed time', md)

    def test_wall_gate_exact(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, w_wall=95.0, g_wall=100.0)  # exactly 0.95 x passes
            self.assertTrue(self.build(root)['decision']['wall_at_most_95pct_of_G'])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, w_wall=95.001, g_wall=100.0)
            s = self.build(root)
        self.assertFalse(s['decision']['wall_at_most_95pct_of_G'])
        self.assertFalse(s['decision']['W_replaces_G'])
        self.assertTrue(rep.wall_within(95_000_000, 100_000_000))
        self.assertFalse(rep.wall_within(95_000_001, 100_000_000))

    def test_noise_band_and_wrong(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, w_rows=[row('t0', 'roll12wide'), row('t1', 'roll12wide'), row('t2', 'roll12wide')])
            s = self.build(root)
        self.assertTrue(s['decision']['solved_within_noise'])  # 0 >= 2 - 2
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root, w_rows=[row('t0', 'roll12wide', 0), row('t1', 'roll12wide', 4, solved=False, wrong=True),
                                row('t2', 'roll12wide')])
            s = self.build(root)
        self.assertFalse(s['decision']['zero_wrong'])

    def test_incomplete_when_input_counter_or_wh_missing(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            study(root)
            f = root / 'runs' / f'{STUDY}-roll12wide' / 'arm_accounting.json'
            rec = json.loads(f.read_text())
            rec['energy'] = dict(error='ssh down')
            f.write_text(json.dumps(rec))
            s = self.build(root)
        self.assertEqual(s['arms']['W']['status'], 'incomplete')
        self.assertTrue(s['decision'].startswith('incomplete'))


if __name__ == '__main__':
    unittest.main()
