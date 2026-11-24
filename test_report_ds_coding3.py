"""Offline tests for inkling/report_ds_coding3.py on synthetic run directories (energy mocked)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_ds_coding3 as rep  # noqa: E402

KEYS = [(f'eva-t{i}', s) for s in (19, 20, 21) for i in range(24)]


def ds_row(task, seed, fb, ho, **changes):
    row = dict(task_id=task, seed=seed, feedback_pass=fb, holdout_pass=ho, charged_completion_tokens=1000,
               controller_error=None, malformed_lines=0, infrastructure_failures=0, returncode=0, controller_stop=False,
               deadline=False, calls=1, unfinished_calls=0, status='complete')
    row.update(changes)
    return row


NODES = {n: dict(joules=9000, coverage=1.0) for n in ('01', '02', '03', '04')}
GOOD_ENERGY = lambda a, b: dict(total_wh=50.0, nodes=NODES)


def write(root, ds_outcome, r2_outcome, r1_outcome, ds_changes=None, meta=None, keys=None):
    """outcome(i) -> (answered, solved) for the i-th case."""
    (root / 'datasets').mkdir()
    (root / 'datasets' / 'tasks.json').write_text(json.dumps(dict(tasks=[dict(id=f'eva-t{i}', split='evaluation')
                                                                         for i in range(24)] + [dict(id='dev-x', split='development')])))
    (root / rep.PLAN).write_text(json.dumps(dict(tasks='datasets/tasks.json', seeds=[19, 20, 21])))
    ds = root / 'runs' / rep.STUDY
    ds.mkdir(parents=True)
    rows = []
    for i, (t, s) in enumerate(keys or KEYS):
        fb, ho = ds_outcome(i)
        rows.append(ds_row(t, s, fb, ho, **((ds_changes or {}).get(i, {}))))
    (ds / 'summary.json').write_text(json.dumps(rows))
    (ds / 'metadata.json').write_text(json.dumps(meta or dict(started_utc='2026-11-24T21:00:00+00:00',
                                                               completed_utc='2026-11-24T22:00:00.500000+00:00', errors=[])))
    for name, outcome, tokens in (('coding-roll3-v1-r2', r2_outcome, 720000), ('coding-roll3-v1-r1', r1_outcome, 360000)):
        d = root / 'runs' / name
        d.mkdir()
        (d / 'cases.json').write_text(json.dumps([dict(task_id=t, seed=s, answered=outcome(i)[0], solved=outcome(i)[1])
                                                  for i, (t, s) in enumerate(KEYS)]))
        (d / 'arm_accounting.json').write_text(json.dumps(dict(runner_wall_seconds=3000.0, energy=dict(total_wh=100.0),
                                                               server=dict(total=dict(generation_tokens=tokens)))))


class DsCoding3Tests(unittest.TestCase):
    def build(self, root, **kw):
        return rep.build(root, dict(ds=f'runs/{rep.STUDY}', r2='runs/coding-roll3-v1-r2', r1='runs/coding-roll3-v1-r1'),
                         energy_window=kw.get('energy', GOOD_ENERGY))

    def test_full_report(self):
        # DS: solves 0..59, wrong 60..63 (feedback pass, hidden fail), unanswered 64..71
        ds = lambda i: (True, True) if i < 60 else (True, False) if i < 64 else (False, False)
        # R2: solves all but 0-1 (unanswered) and 2 (wrong); R1: solves all but 64-67 (unanswered)
        r2 = lambda i: (False, False) if i < 2 else (True, False) if i == 2 else (True, True)
        r1 = lambda i: (False, False) if 64 <= i < 68 else (True, True)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, ds, r2, r1)
            s = self.build(root)
            with patch.object(rep.energy, 'window', GOOD_ENERGY), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = rep.main(['--root', d])
            md = (root / 'results' / rep.STUDY / 'REPORT.md').read_text()
        self.assertEqual((s['status'], code), ('complete', 0))
        self.assertEqual({k: (v['solved'], v['wrong'], v['unanswered']) for k, v in s['systems'].items()},
                         dict(DS=(60, 4, 8), R2=(69, 1, 2), R1=(68, 0, 4)))
        self.assertEqual(s['paired']['DS_vs_R2'], dict(cases=72, ds_only=3, swarm_only=12, sign_test_p=rep.sign_test(3, 12)))
        # hybrid R2: 69 + DS solves among R2-unanswered {0, 1} = 71; wrong = R2 wrong 1 + DS wrong there 0
        self.assertEqual(s['hybrid']['R2+DS'], dict(cases=72, solved=71, wrong=1, ds_calls=2, unanswered=0))
        # hybrid R1: 68 + DS on {64..67}: DS unanswered there -> 68 solved, 0 wrong, 4 unanswered
        self.assertEqual(s['hybrid']['R1+DS'], dict(cases=72, solved=68, wrong=0, ds_calls=4, unanswered=4))
        c = s['systems']['DS']['cost']
        self.assertEqual((c['client_completion_tokens_per_case'], c['wall_seconds'], c['wh'], c['wh_per_solved']),
                         (1000, 3600.5, 50.0, 50.0 / 60))
        self.assertIn('Hybrid', md)

    def test_infra_fault_makes_it_incomplete(self):
        ok = lambda i: (True, True)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, ok, ok, ok, ds_changes={5: dict(infrastructure_failures=1)})
            s = self.build(root)
        self.assertEqual(s['status'], 'incomplete')
        self.assertIn('infrastructure fault', ' '.join(s['systems']['DS']['reasons']))
        self.assertNotIn('paired', s)

    def test_energy_failure_or_missing_samples_is_incomplete(self):
        ok = lambda i: (True, True)

        def broken(a, b):
            raise OSError('ssh: connect refused')
        partial = lambda a, b: dict(total_wh=40.0, nodes=dict(NODES, **{'03': dict(joules=None, coverage=0.0)}))
        empty = lambda a, b: dict(total_wh=0, nodes={})
        for energy, msg in ((broken, 'connect refused'), (partial, "['03']"), (empty, 'missing or incomplete')):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                write(root, ok, ok, ok)
                s = self.build(root, energy=energy)
            self.assertEqual(s['status'], 'incomplete', msg)
            self.assertIn(msg, ' '.join(s['systems']['DS']['reasons']))
            self.assertIsNone(s['systems']['DS']['cost']['wh'])
            self.assertNotIn('paired', s)

    def test_case_sets_must_equal_the_frozen_plan(self):
        ok = lambda i: (True, True)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            other = KEYS[:71] + [('eva-other', 19)]
            write(root, ok, ok, ok, keys=other)
            s = self.build(root)
        self.assertEqual(s['status'], 'incomplete')
        self.assertIn("cases differ from the frozen plan's 72 (1 missing, 1 extra)", ' '.join(s['systems']['DS']['reasons']))
        self.assertNotIn('hybrid', s)

    def test_bad_timestamps_are_incomplete(self):
        ok = lambda i: (True, True)
        for meta in (dict(started_utc='nonsense', completed_utc='2026-11-24T22:00:00+00:00', errors=[]),
                     dict(started_utc='2026-11-24T21:00:00', completed_utc='2026-11-24T22:00:00', errors=[])):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d)
                write(root, ok, ok, ok, meta=meta)
                s = self.build(root)
            self.assertEqual(s['status'], 'incomplete')
            self.assertIn('timestamps', ' '.join(s['systems']['DS']['reasons']))

    def test_defaults_resolve_under_the_repo_root(self):
        captured = {}

        def fake_build(root, dirs, energy_window=None):
            captured.update(root=root, dirs=dirs)
            return dict(status='incomplete', systems={})
        with tempfile.TemporaryDirectory() as d, patch.object(rep, 'build', fake_build), \
                patch.object(rep, 'markdown', lambda s: ''), contextlib.redirect_stdout(io.StringIO()):
            rep.main(['--out', d])
        self.assertEqual(captured['root'], rep.ROOT.resolve())
        self.assertEqual(rep.ROOT, Path(rep.__file__).resolve().parent.parent)
        self.assertEqual(captured['dirs'], dict(ds='runs/deepseek-coding3-v1', r2='runs/coding-roll3-v1-r2', r1='runs/coding-roll3-v1-r1'))

    def test_incomplete_run_and_missing_cases(self):
        ok = lambda i: (True, True)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root, ok, ok, ok, meta=dict(started_utc='2026-11-24T21:00:00+00:00', errors=[]))
            s = self.build(root)
        self.assertEqual(s['status'], 'incomplete')
        self.assertIn('not completed', ' '.join(s['systems']['DS']['reasons']))


if __name__ == '__main__':
    unittest.main()
