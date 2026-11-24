"""Offline tests for inkling/ds_switch_inkling.py stop-deepseek (ssh mocked; no network, no node contact)."""
import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import ds_switch_inkling as ds  # noqa: E402

CONTAINERS = {n: [f'c{n[-1]}aaaa', f's{n[-1]}bbbb'] for n in ds.NODES}


class FakeFleet:
    def __init__(self, gpu_busy_polls=2, running=False, guards=True, stray_app=False, stop_rc=0, query_rc=0,
                 query_garbage=False):
        self.calls, self.polls, self.busy = [], 0, gpu_busy_polls
        self.running, self.guards, self.stray = running, guards, stray_app
        self.stop_rc, self.query_rc, self.garbage = stop_rc, query_rc, query_garbage

    def __call__(self, node, command, timeout=120):
        self.calls.append((node, command))
        out = ''
        if 'no-autostart' in command:
            out = (f'{ds.OWNER}\n{ds.OWNER}\n' if self.guards else 'BAD\nBAD\n')
        elif 'service.sh stop' in command:
            return subprocess.CompletedProcess([], self.stop_rc, 'stopped' if not self.stop_rc else '', 'err' if self.stop_rc else '')
        elif command.startswith('nvidia-smi') and self.query_rc:
            return subprocess.CompletedProcess([], self.query_rc, '', 'NVIDIA-SMI has failed')
        elif command.startswith('nvidia-smi') and self.garbage:
            return subprocess.CompletedProcess([], 0, 'No devices were found\n', '')
        elif command.startswith('nvidia-smi'):
            if node == 'Spark_01':
                self.polls += 1
            busy = self.polls <= self.busy or (self.stray and node == 'Spark_03')
            out = '123, python3\n' if busy else ''
        elif command.startswith('for c in swarm-inkling'):
            n = node[-1]
            r = 'true' if self.running else 'false'
            out = f'c{n}aaaa111 {r} false 0\ns{n}bbbb222 {r} false 0\n'
        elif 'docker start' in command or 'docker stop' in command:
            raise AssertionError('stop-deepseek must not start or stop the swarm containers')
        return subprocess.CompletedProcess([], 0, out, '')


class StopDeepseekTests(unittest.TestCase):
    def run_stop(self, fleet, log_path=None):
        with tempfile.TemporaryDirectory() as d, patch.object(ds, 'ssh', fleet), patch.object(ds, 'CONTAINERS', CONTAINERS), \
                patch.object(ds, 'LOG', log_path(Path(d)) if log_path else Path(d) / 'receipts' / 'log.jsonl'), \
                patch.object(ds.time, 'sleep', lambda s: None), contextlib.redirect_stdout(io.StringIO()):
            try:
                result = ds.stop_deepseek()
            except SystemExit as exc:
                result = exc
            path = log_path(Path(d)) if log_path else Path(d) / 'receipts' / 'log.jsonl'
            log = path.read_text() if path.is_file() else ''
        return result, log

    def test_stops_native_and_leaves_the_fleet_empty(self):
        fleet = FakeFleet()
        receipt, log = self.run_stop(fleet)
        self.assertTrue(receipt['ok'] and receipt['guards_ok'])
        self.assertEqual(receipt['step'], 'deepseek-stopped')
        self.assertEqual({n: v['gpu'] for n, v in receipt['nodes'].items()}, {n: [] for n in ds.NODES})
        self.assertTrue(all(not v['container']['running'] for v in receipt['nodes'].values()))
        stops = [c for c in fleet.calls if 'service.sh stop' in c[1]]
        self.assertEqual(stops, [('Spark_01', f'env FLEET=/home/knapcio/dsgb10/fleet.conf {ds.SERVICE} stop')])
        self.assertFalse(any('docker start' in c[1] for c in fleet.calls))
        self.assertIn('"step": "native-stop"', log)

    def test_guard_failure_stops_before_anything(self):
        fleet = FakeFleet(guards=False)
        result, log = self.run_stop(fleet)
        self.assertIsInstance(result, SystemExit)
        self.assertFalse(any('service.sh' in c[1] for c in fleet.calls))

    def test_gpu_still_busy_fails(self):
        fleet = FakeFleet(gpu_busy_polls=10 ** 6)
        result, log = self.run_stop(fleet)
        self.assertIsInstance(result, SystemExit)
        self.assertIn('GPU still busy', str(result))

    def test_running_swarm_container_is_not_ok(self):
        result, log = self.run_stop(FakeFleet(running=True))
        self.assertIsInstance(result, SystemExit)
        self.assertIn('"ok": false', log)

    def test_nonzero_native_stop_fails(self):
        fleet = FakeFleet(stop_rc=1)
        result, log = self.run_stop(fleet)
        self.assertIsInstance(result, SystemExit)
        self.assertIn('native stop exited 1', str(result))
        self.assertIn('"step": "deepseek-stopped", "ok": false', log)

    def test_failed_or_unparsable_gpu_query_is_not_idle(self):
        for fleet in (FakeFleet(query_rc=255), FakeFleet(query_garbage=True)):
            result, log = self.run_stop(fleet)
            self.assertIsInstance(result, SystemExit)
            self.assertIn('GPU query failing', str(result))
            queries = sum(c[1].startswith('nvidia-smi') for c in fleet.calls)
            self.assertGreater(queries, 4 * ds.GPU_QUERY_TRIES)  # retried, then polled again

    def test_receipt_log_written_before_the_stop(self):
        fleet = FakeFleet()

        def blocked(d):
            (d / 'file').write_text('x')
            return d / 'file' / 'log.jsonl'  # its parent is a file: cannot be created
        result, _ = self.run_stop(fleet, log_path=blocked)
        self.assertIsInstance(result, SystemExit)
        self.assertIn('cannot be written', str(result))
        self.assertFalse(any('service.sh' in c[1] for c in fleet.calls))
        receipt, log = self.run_stop(FakeFleet())
        self.assertLess(log.index('stop-deepseek-start'), log.index('native-stop'))

    def test_existing_steps_unchanged(self):
        self.assertTrue(callable(ds.to_inkling) and callable(ds.to_deepseek) and callable(ds.precheck))
        import inspect
        src = inspect.getsource(ds.to_inkling)
        self.assertIn("docker start swarm-inkling swarm-inkling-shim", src)


if __name__ == '__main__':
    unittest.main()
