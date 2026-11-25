"""Offline tests for inkling/ds_switch_inkling.py stop-native (ssh mocked; no network, no node contact)."""
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


def done(rc=0, out='', err=''):
    return subprocess.CompletedProcess([], rc, out, err)


class FakeFleet:
    def __init__(self, guards=True, stop_rc=0, stopped_after=2, final_state='stopped 1795 by service.sh stop\n000',
                 procs_forever=None, gpu_forever=None, query_rc=0, scan_rc=0):
        self.calls, self.polls = [], 0
        self.guards, self.stop_rc, self.stopped_after, self.final_state = guards, stop_rc, stopped_after, final_state
        self.procs_forever, self.gpu_forever, self.query_rc, self.scan_rc = procs_forever, gpu_forever, query_rc, scan_rc

    def __call__(self, node, command, timeout=120):
        self.calls.append((node, command))
        if 'no-autostart' in command:
            return done(out=f'{ds.OWNER}\n{ds.OWNER}\n' if self.guards else 'BAD\nBAD\n')
        if 'service.sh stop' in command:
            return done(self.stop_rc, out='stopped')
        if 'service/run/state' in command:
            self.polls += 1
            return done(out=self.final_state if self.polls >= self.stopped_after else 'stopping 1795 x\n200')
        if command.startswith('for d in /proc/'):
            if self.scan_rc:
                return done(self.scan_rc, err='scan failed')
            busy = self.polls < self.stopped_after or node == self.procs_forever
            return done(out=('77 dsgb10_rank\n' if busy else '') + 'END-OF-SCAN\n')
        if command.startswith('nvidia-smi'):
            if self.query_rc:
                return done(self.query_rc, err='NVIDIA-SMI has failed')
            busy = self.polls < self.stopped_after or node == self.gpu_forever
            return done(out='77, dsgb10_rank\n' if busy else '')
        if 'docker' in command or command.startswith('bash -c '):
            raise AssertionError('stop-native must not touch containers or start anything')
        raise AssertionError(f'unexpected command {command!r}')


class StopNativeTests(unittest.TestCase):
    def run_stop(self, fleet, log_path=None):
        with tempfile.TemporaryDirectory() as d:
            path = log_path(Path(d)) if log_path else Path(d) / 'r' / 'log.jsonl'
            with patch.object(ds, 'ssh', fleet), patch.object(ds, 'LOG', path), patch.object(ds, 'CONTAINERS', None), \
                    patch.object(ds.time, 'sleep', lambda s: None), contextlib.redirect_stdout(io.StringIO()):
                try:
                    result = ds.stop_native()
                except SystemExit as exc:
                    result = exc
            log = path.read_text() if path.is_file() else ''
        return result, log

    def test_confirmed_shutdown_without_a_container_manifest(self):
        fleet = FakeFleet()
        receipt, log = self.run_stop(fleet)
        self.assertTrue(receipt['ok'])
        self.assertEqual(receipt['step'], 'native-stopped')
        self.assertTrue(all(v['procs_ok'] and not v['procs'] and v['gpu_query_ok'] and not v['gpu']
                            for v in receipt['nodes'].values()))
        self.assertEqual([c for c in fleet.calls if 'service.sh stop' in c[1]],
                         [('Spark_01', f'env FLEET=/home/knapcio/dsgb10/fleet.conf {ds.SERVICE} stop')])
        self.assertLess(log.index('stop-native-start'), log.index('"native-stop"'))

    def test_guards_or_unwritable_log_stop_nothing(self):
        fleet = FakeFleet(guards=False)
        result, _ = self.run_stop(fleet)
        self.assertIn('guards changed; nothing was stopped', str(result))
        self.assertFalse(any('service.sh' in c[1] for c in fleet.calls))
        fleet = FakeFleet()

        def blocked(d):
            (d / 'f').write_text('x')
            return d / 'f' / 'log.jsonl'
        result, _ = self.run_stop(fleet, log_path=blocked)
        self.assertIn('cannot be written', str(result))
        self.assertEqual(fleet.calls, [])

    def test_nonzero_stop_fails(self):
        result, _ = self.run_stop(FakeFleet(stop_rc=3))
        self.assertIn('native stop exited 3', str(result))

    def test_unconfirmed_shutdown_fails(self):
        cases = [FakeFleet(final_state='failed 1795 rank 0 exited\n000'), FakeFleet(final_state='stopped 1795 x\n200'),
                 FakeFleet(procs_forever='Spark_03'), FakeFleet(gpu_forever='Spark_04'), FakeFleet(query_rc=255),
                 FakeFleet(scan_rc=255), FakeFleet(final_state='')]
        for fleet in cases:
            result, log = self.run_stop(fleet)
            self.assertIsInstance(result, SystemExit)
            self.assertIn('native shutdown not confirmed', str(result))
            self.assertIn('"step": "stop-native", "ok": false', log)


if __name__ == '__main__':
    unittest.main()
