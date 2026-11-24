"""Offline tests for inkling/account_cmd.py (admission, ssh flush, metrics and energy mocked; no network)."""
import contextlib
import io
import itertools
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import account_cmd as ac  # noqa: E402

NODES = ('01', '02', '03', '04')
SGLANG_FLUSHED = ('Cache flushed.\nPlease check backend logs for more details. (When there are running or waiting '
                  'requests, the operation will not be performed.)')
OK = [sys.executable, 'ok.py']
SCRIPTS = {'ok.py': 'print(1)\n', 'exit7.py': 'raise SystemExit(7)\n',
           'echo.py': 'import sys\nprint("hello", sys.argv[1:])\n'}


def metrics(generated=0.0, running=0.0, drop=None, value=None):
    lines = ['# HELP sglang:generation_tokens_total x']
    for name, (metric, label) in ac.arms.COUNTERS.items():
        if metric == drop:
            continue
        x = generated if name == 'generation_tokens' else running if name == 'running' else \
            0.0 if name == 'queued' else 1.0
        if value is not None and name == 'prompt_tokens':
            x = value
        lines.append(f'{metric}{{{label}}} {x}' if label else f'{metric} {x}')
    return '\n'.join(lines) + '\n'


def flush_ok(node, remote):
    return subprocess.CompletedProcess([], 0, SGLANG_FLUSHED + '\n200', '')


def energy_ok(start, end):
    return dict(start=start, end=end, total_wh=1.5, nodes={n: dict(joules=100, coverage=1.0) for n in NODES})


class AccountCmdTests(unittest.TestCase):
    def run_main(self, command, texts, flush=flush_ok, admit_error=None, window=energy_ok, drain=1, output='runs/screen-v1',
                 extra=(), plan=None, setup=None):
        """texts: callable(call_number, node_index) -> metrics text (or raises)."""
        calls = dict(n=0, admit=[])

        def fetch(i):
            calls['n'] += 1
            return texts(calls['n'], i)

        def admit(plan_path, source, admission, note):
            calls['admit'].append(str(admission))
            if admit_error:
                raise ac.AccountingError(admit_error)
            Path(admission).write_text('{}')  # as admit.py does: fails if the wrapper did not create .runtime
        buf = io.StringIO()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'runs').mkdir()  # .runtime is created by the wrapper
            for name, code in SCRIPTS.items():
                (root / name).write_text(code)
            (root / 'plan.json').write_text(json.dumps(plan or dict(study='swarm-x-v1', source_revision='r')))
            if setup:
                setup(root)
            with patch.object(ac, 'ROOT', root), patch.object(ac, 'fetch_metrics', fetch), patch.object(ac, 'admit', admit), \
                    patch.object(ac, 'ssh', flush), patch.object(ac.energy, 'window', window), \
                    patch.object(ac.time, 'sleep', lambda s: None), contextlib.redirect_stdout(buf):
                code = ac.main(['--plan', str(root / 'plan.json'), '--output', output, '--drain-seconds', str(drain)]
                               + list(extra) + ['--'] + command)
            out = root / output
            record = json.loads((out / 'arm_accounting.json').read_text()) if (out / 'arm_accounting.json').exists() else None
            log = Path(str(out) + '.log').read_text() if Path(str(out) + '.log').exists() else None
        return code, record, log, calls

    def test_full_sequence_and_schema(self):
        texts = lambda n, i: metrics(generated=0.0 if n <= 4 else 500.0)
        cmd = [sys.executable, 'echo.py', '{admission}', '{output}']
        code, rec, log, calls = self.run_main(cmd, texts)
        self.assertEqual(code, 0)
        self.assertEqual(rec['protocol'], 'swarm-arm-accounting-v1')
        for key in ('plan', 'study', 'arm', 'output', 'runner_exit', 'runner_wall_seconds', 'admission', 'cache_flush',
                    'before', 'after', 'idle_after', 'server', 'energy', 'resumed_from', 'command'):
            self.assertIn(key, rec)
        self.assertEqual((rec['study'], rec['arm'], rec['idle_after'], rec['runner_exit']), ('swarm-x-v1', 'screen-v1', True, 0))
        self.assertEqual(rec['server']['total']['generation_tokens'], 2000.0)
        self.assertEqual(rec['cache_flush']['01'], dict(exit=0, http_status='200', body=SGLANG_FLUSHED))
        self.assertTrue(rec['admission'].endswith('SWARM_X_V1_SCREEN_V1_ADMISSION.JSON'))
        self.assertEqual(rec['command'][2:], [rec['admission'], rec['output']])
        self.assertIn('hello', log)
        self.assertNotIn('accounting_error', rec)
        self.assertNotIn('energy_error', rec)

    def test_command_exit_code_is_returned(self):
        code, rec, _, _ = self.run_main([sys.executable, 'exit7.py'], lambda n, i: metrics())
        self.assertEqual((code, rec['runner_exit']), (7, 7))

    def test_flush_checks_exit_status_http_status_and_body(self):
        cases = (lambda n, r: subprocess.CompletedProcess([], 255, '', 'ssh: connect refused'),
                 lambda n, r: subprocess.CompletedProcess([], 22, 'curl: (22) error\n500', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, 'Internal error\n200', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, 'Cache flushed.\n503', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, 'Cache flushed failed\n200', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, 'Cache flushed\n200', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, 'Cache flushed. Internal Error on rank 1\n200', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, 'Cache flushed.\nOperation was skipped.\n200', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, SGLANG_FLUSHED + ' Operation was skipped.\n200', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, ' ' + SGLANG_FLUSHED + '\n200', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, SGLANG_FLUSHED.replace('will not', 'will') + '\n200', ''),
                 lambda n, r: subprocess.CompletedProcess([], 0, 'Cache flushed.\n200', ''),
                 lambda n, r: flush_ok(n, r) if n != '03' else (_ for _ in ()).throw(subprocess.TimeoutExpired('ssh', 60)))
        for flush in cases:
            code, rec, log, _ = self.run_main(OK, lambda n, i: metrics(), flush=flush)
            self.assertEqual((code, log, rec['command_started']), (2, None, False))
            self.assertIn('flush failed', rec['accounting_error'])

    def test_pre_command_faults_write_a_record_and_never_run_the_command(self):
        for kwargs, texts, msg in ((dict(admit_error='node 02 busy'), lambda n, i: metrics(), 'busy'),
                                   ({}, lambda n, i: metrics(drop='shim:client_cancels' if i == 2 else None), 'missing'),
                                   ({}, lambda n, i: metrics(running=3.0), 'not idle')):
            code, rec, log, _ = self.run_main(OK, texts, **kwargs)
            self.assertEqual((code, log), (2, None), msg)
            self.assertIn(msg, rec['accounting_error'])

    def test_drain_only_counts_idle_samples_before_the_deadline(self):
        clock = itertools.count(0, 10)  # every monotonic() call advances 10 s; the drain limit is 5 s
        texts = lambda n, i: metrics()  # always idle, but the idle sample after CMD completes after the deadline
        with patch.object(ac.time, 'monotonic', lambda: next(clock)):
            code, rec, _, _ = self.run_main(OK, texts, drain=5)
        self.assertEqual(code, 2)  # already the pre-command idle sample was late
        self.assertIn('not idle within', rec['accounting_error'])

    def test_drain_timeout_after_command_is_exit_3_with_record(self):
        texts = lambda n, i: metrics(running=0.0 if n <= 4 else 2.0)
        code, rec, _, _ = self.run_main(OK, texts, drain=1)
        self.assertEqual(code, 3)
        self.assertIn('not idle', rec['accounting_error'])
        self.assertFalse(rec['idle_after'])
        self.assertIsNone(rec['server'])

    def test_metrics_transport_and_parse_errors_after_command_are_recorded(self):
        def refused(n, i):
            if n > 4:
                raise OSError('Connection refused')
            return metrics()
        for texts, msg in ((refused, 'Connection refused'),
                           (lambda n, i: metrics() if n <= 4 else metrics().replace(' 1.0', ' abc', 1), 'metrics unavailable'),
                           (lambda n, i: metrics(value=float('nan') if n > 4 else None), 'non-finite'),
                           (lambda n, i: metrics(drop=None if n <= 4 else 'sglang:prompt_tokens_total'), 'counters missing')):
            code, rec, _, _ = self.run_main(OK, texts)
            self.assertEqual(code, 3, msg)
            self.assertIn(msg, rec['accounting_error'])
            self.assertIsNone(rec['server'], msg)

    def test_negative_delta_counter_reset_is_exit_3(self):
        texts = lambda n, i: metrics(generated=500.0 if n <= 4 else 10.0)
        code, rec, _, _ = self.run_main(OK, texts)
        self.assertEqual(code, 3)
        self.assertIn('negative or non-finite counter deltas', rec['accounting_error'])

    def test_energy_failure_or_missing_node_is_exit_4(self):
        def partial(start, end):
            e = energy_ok(start, end)
            e['nodes']['02'] = dict(joules=None, coverage=0.0)
            return e

        def low(start, end):
            e = energy_ok(start, end)
            e['nodes']['04']['coverage'] = 0.5
            return e

        def down(start, end):
            raise OSError('ssh down')
        for window, msg in ((down, 'ssh down'), (partial, "['02']"), (low, "['04']")):
            code, rec, _, _ = self.run_main(OK, lambda n, i: metrics(), window=window)
            self.assertEqual(code, 4, msg)
            self.assertIn(msg, rec['energy_error'])
            self.assertIsNotNone(rec['server'])  # token accounting kept

    def test_paths_and_placeholders(self):
        ok = OK
        for output in ('elsewhere/x', 'runs/../x', '/tmp/x'):
            with self.assertRaisesRegex(SystemExit, 'must be under'):
                self.run_main(ok, lambda n, i: metrics(), output=output)
        with self.assertRaisesRegex(SystemExit, 'output or its log exists'):
            self.run_main(ok, lambda n, i: metrics(), setup=lambda root: (root / 'runs' / 'screen-v1').mkdir())
        with self.assertRaisesRegex(SystemExit, 'receipt exists'):
            self.run_main(ok, lambda n, i: metrics(),
                          setup=lambda root: ((root / '.runtime').mkdir(),
                                              (root / '.runtime' / 'SWARM_X_V1_SCREEN_V1_ADMISSION.JSON').write_text('{}')))
        for bad in (dict(study='../x', source_revision='r'), dict(study='a b', source_revision='r')):
            with self.assertRaisesRegex(SystemExit, 'letters, digits'):
                self.run_main(ok, lambda n, i: metrics(), plan=bad)
        with self.assertRaisesRegex(SystemExit, 'letters, digits'):
            self.run_main(ok, lambda n, i: metrics(), extra=['--label', 'x/../../y'])
        with self.assertRaisesRegex(SystemExit, 'whole argument'):
            self.run_main(ok + ['--admission={admission}'], lambda n, i: metrics())
        # whole-element substitution keeps shell metacharacters inert (no shell)
        code, rec, log, _ = self.run_main([sys.executable, 'echo.py', '$(echo hi); {x}'],
                                          lambda n, i: metrics())
        self.assertEqual(code, 0)
        self.assertIn('$(echo hi); {x}', log)

    def test_flush_body_matches_the_recorded_receipts_exactly(self):
        runs = next((d for d in (Path(__file__).resolve().parent / 'runs', Path(__file__).resolve().parents[2] / 'runs')
                     if (d / 'swarm-loop-hard15-v1-l-roll12strategy' / 'arm_accounting.json').exists()), None)
        if runs is not None:
            recorded = json.loads((runs / 'swarm-loop-hard15-v1-l-roll12strategy' / 'arm_accounting.json').read_text())
            self.assertEqual(set(recorded['cache_flush'].values()), {ac.FLUSH_OK})
        for stdout in (SGLANG_FLUSHED + '\n200', SGLANG_FLUSHED + '\n\n204', SGLANG_FLUSHED + '  \n200'):
            code, _, _, _ = self.run_main(OK, lambda n, i: metrics(),
                                          flush=lambda n, r, o=stdout: subprocess.CompletedProcess([], 0, o, ''))
            self.assertEqual(code, 0, repr(stdout))

    def test_shells_and_inline_code_are_refused(self):
        for cmd, msg in ((['sh', '-c', '{output}'], 'shell'), (['/bin/bash', 'x.sh'], 'shell'), (['zsh'], 'shell'),
                         (['dash', '-c', 'true'], 'shell'), (['env', 'A=1', 'bash', '-c', 'true'], 'shell'),
                         (['/usr/bin/env', '-i', 'sh', 'ok.py'], 'shell'), ([sys.executable, '-c', 'print(1)'], 'inline'),
                         (['python3', '-c', 'print(1)'], 'inline'), (['python3.12', '-Ic', 'print(1)'], 'inline'),
                         (['python', '-'], 'inline'), (['perl', '-e', '1'], 'inline'), (['node', '--eval', '1'], 'inline'),
                         ([sys.executable, 'missing.py'], 'script not found'), ([sys.executable, '-u'], 'without a script'),
                         (['env'], 'empty')):
            with self.assertRaisesRegex(SystemExit, msg):
                self.run_main(cmd, lambda n, i: metrics())
        # allowed: script paths (also via env and with interpreter options), python -m, real programs
        for cmd in (OK, ['env', 'PYTHONHASHSEED=0', sys.executable, '-u', 'ok.py'], [sys.executable, '-m', 'json.tool', '-h']):
            code, rec, _, _ = self.run_main(cmd, lambda n, i: metrics())
            self.assertEqual(code, 0, cmd)

    def test_admission_directory_is_created(self):
        def setup(root):
            self.assertFalse((root / '.runtime').exists())
        code, rec, _, calls = self.run_main(OK, lambda n, i: metrics(), setup=setup)
        self.assertEqual(code, 0)  # the mocked admission wrote the receipt into the created .runtime
        self.assertTrue(calls['admit'][0].endswith('/.runtime/SWARM_X_V1_SCREEN_V1_ADMISSION.JSON'))

    def test_requires_a_command(self):
        with self.assertRaises(SystemExit):
            ac.main(['--plan', 'p.json', '--output', 'runs/o'])

    def test_missing_counters_matches_labels(self):
        self.assertEqual(ac.missing_counters(metrics()), [])
        no_decode = metrics().replace('{mode="decode"}', '{mode="other"}')
        self.assertEqual(ac.missing_counters(no_decode), ['decode_tokens'])
        self.assertEqual(ac.missing_counters(metrics(drop='shim:requests')), ['shim_requests'])


if __name__ == '__main__':
    unittest.main()
