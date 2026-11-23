"""Offline tests for inkling/account_cmd.py (admission, ssh flush, metrics and energy mocked; no network)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import account_cmd as ac  # noqa: E402

FLUSHED = {n: 'Cache flushed.\nPlease check backend logs for more details.' for n in ('01', '02', '03', '04')}


def metrics(generated=0.0, running=0.0, drop=None):
    lines = ['# HELP sglang:generation_tokens_total x']
    for name, (metric, label) in ac.arms.COUNTERS.items():
        if metric == drop:
            continue
        value = generated if name == 'generation_tokens' else running if name == 'running' else \
            0.0 if name == 'queued' else 1.0
        lines.append(f'{metric}{{{label}}} {value}' if label else f'{metric} {value}')
    return '\n'.join(lines) + '\n'


class AccountCmdTests(unittest.TestCase):
    def run_main(self, command, texts, flush=FLUSHED, admit_error=None, energy_error=False, drain=1):
        """texts: callable(call_number, node_index) -> metrics text."""
        calls = dict(n=0, admit=[])

        def fetch(i):
            calls['n'] += 1
            return texts(calls['n'], i)

        def admit(plan_path, source, admission, note):
            calls['admit'].append((str(plan_path), str(admission)))
            if admit_error:
                raise ac.AccountingError(admit_error)

        def window(start, end):
            if energy_error:
                raise OSError('ssh down')
            return dict(start=start, end=end, total_wh=1.5)
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'plan.json').write_text(json.dumps(dict(study='swarm-x-v1', source_revision='r')))
            out = root / 'runs' / 'screen-v1'
            out.parent.mkdir()
            with patch.object(ac, 'fetch_metrics', fetch), patch.object(ac, 'admit', admit), \
                    patch.object(ac.arms, 'flush_caches', lambda: flush), patch.object(ac.energy, 'window', window), \
                    patch.object(ac.time, 'sleep', lambda s: None), contextlib.redirect_stdout(buf):
                code = ac.main(['--plan', str(root / 'plan.json'), '--output', str(out), '--drain-seconds', str(drain),
                                '--'] + command)
            record = json.loads((out / 'arm_accounting.json').read_text()) if (out / 'arm_accounting.json').exists() else None
            log = Path(str(out) + '.log').read_text() if Path(str(out) + '.log').exists() else None
        return code, record, log, calls

    def test_full_sequence_and_schema(self):
        # before: idle, 0 generated; after the command: idle, 500 generated per node
        texts = lambda n, i: metrics(generated=0.0 if n <= 4 else 500.0)
        cmd = [sys.executable, '-c', 'import sys; print("hello", sys.argv[1:])', '{admission}', '{output}']
        code, rec, log, calls = self.run_main(cmd, texts)
        self.assertEqual(code, 0)
        self.assertEqual(rec['protocol'], 'swarm-arm-accounting-v1')
        for key in ('plan', 'study', 'arm', 'output', 'runner_exit', 'runner_wall_seconds', 'admission', 'cache_flush',
                    'before', 'after', 'idle_after', 'server', 'energy', 'resumed_from', 'command'):
            self.assertIn(key, rec)
        self.assertEqual((rec['study'], rec['arm'], rec['idle_after']), ('swarm-x-v1', 'screen-v1', True))
        self.assertEqual(rec['server']['total']['generation_tokens'], 2000.0)
        self.assertEqual(rec['energy']['total_wh'], 1.5)
        self.assertTrue(rec['admission'].endswith('SWARM_X_V1_SCREEN_V1_ADMISSION.JSON'))
        self.assertEqual(rec['command'][3:], [rec['admission'], rec['output']])  # placeholders substituted
        self.assertIn('hello', log)
        self.assertEqual(len(calls['admit']), 1)
        self.assertNotIn('accounting_error', rec)

    def test_command_exit_code_is_returned(self):
        code, rec, _, _ = self.run_main([sys.executable, '-c', 'raise SystemExit(7)'], lambda n, i: metrics())
        self.assertEqual((code, rec['runner_exit']), (7, 7))

    def test_failed_flush_or_admission_never_runs_the_command(self):
        bad = dict(FLUSHED, **{'03': 'curl: (7) Failed to connect'})
        for kwargs in (dict(flush=bad), dict(flush={'01': FLUSHED['01']}), dict(admit_error='node 02 busy')):
            code, rec, log, _ = self.run_main([sys.executable, '-c', 'print(1)'], lambda n, i: metrics(), **kwargs)
            self.assertEqual((code, rec, log), (2, None, None), kwargs)

    def test_missing_counters_before_never_run_the_command(self):
        code, rec, log, _ = self.run_main([sys.executable, '-c', 'print(1)'],
                                          lambda n, i: metrics(drop='shim:client_cancels' if i == 2 else None))
        self.assertEqual((code, rec, log), (2, None, None))

    def test_busy_fleet_before_never_runs_the_command(self):
        code, rec, log, _ = self.run_main([sys.executable, '-c', 'print(1)'], lambda n, i: metrics(running=3.0))
        self.assertEqual((code, rec), (2, None))

    def test_drain_timeout_after_is_nonzero_with_record(self):
        texts = lambda n, i: metrics(running=0.0 if n <= 4 else 2.0)
        import itertools
        clock = itertools.count(0, 10)
        with patch.object(ac.time, 'monotonic', lambda: next(clock)):
            code, rec, _, _ = self.run_main([sys.executable, '-c', 'print(1)'], texts, drain=5)
        self.assertEqual(code, 3)
        self.assertIn('not idle', rec['accounting_error'])
        self.assertFalse(rec['idle_after'])

    def test_missing_counters_after_is_nonzero(self):
        texts = lambda n, i: metrics(drop=None if n <= 4 else 'sglang:prompt_tokens_total')
        code, rec, _, _ = self.run_main([sys.executable, '-c', 'print(1)'], texts)
        self.assertEqual(code, 3)
        self.assertIn('counters missing', rec['accounting_error'])
        self.assertIsNone(rec['server'])

    def test_energy_failure_keeps_token_accounting(self):
        code, rec, _, _ = self.run_main([sys.executable, '-c', 'print(1)'], lambda n, i: metrics(), energy_error=True)
        self.assertEqual(code, 0)
        self.assertIn('ssh down', rec['energy']['error'])
        self.assertIsNotNone(rec['server'])

    def test_requires_a_command_and_a_new_output(self):
        with self.assertRaises(SystemExit):
            ac.main(['--plan', 'p.json', '--output', 'o'])
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / 'plan.json').write_text(json.dumps(dict(study='s')))
            with self.assertRaisesRegex(SystemExit, 'exists'):
                ac.main(['--plan', str(Path(d) / 'plan.json'), '--output', d, '--', 'true'])

    def test_missing_counters_matches_labels(self):
        self.assertEqual(ac.missing_counters(metrics()), [])
        no_decode = metrics().replace('{mode="decode"}', '{mode="other"}')
        self.assertEqual(ac.missing_counters(no_decode), ['decode_tokens'])
        self.assertEqual(ac.missing_counters(metrics(drop='shim:requests')), ['shim_requests'])


if __name__ == '__main__':
    unittest.main()
