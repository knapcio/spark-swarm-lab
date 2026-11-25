"""Offline tests for inkling/ds_switch_inkling.py start-deepseek (ssh mocked; no network, no node contact)."""
import contextlib
import hashlib
import inspect
import io
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import ds_switch_inkling as ds  # noqa: E402

SCRIPT = 'echo start\n'


def done(rc=0, out='', err=''):
    return subprocess.CompletedProcess([], rc, out, err)


class FakeFleet:
    def __init__(self, guards=True, gpu=None, query_rc=0, garbage=False, running=(), absent=(), inspect_fail=(),
                 inspect_raise=False, start_rc=0, healthy_after=2, old_docker=False, procs=None, scan_fail=(),
                 healthy_state='serving 1795 http://127.0.0.1:8888/v1\n200'):
        self.calls, self.health_polls = [], 0
        self.guards, self.gpu, self.query_rc, self.garbage = guards, gpu or {}, query_rc, garbage
        self.running, self.absent, self.inspect_fail, self.inspect_raise = running, absent, inspect_fail, inspect_raise
        self.start_rc, self.healthy_after, self.old_docker = start_rc, healthy_after, old_docker
        self.procs, self.scan_fail, self.healthy_state = procs or {}, scan_fail, healthy_state

    def __call__(self, node, command, timeout=120):
        self.calls.append((node, command))
        if 'no-autostart' in command:
            return done(out=f'{ds.OWNER}\n{ds.OWNER}\n' if self.guards else 'BAD\nBAD\n')
        if command.startswith('nvidia-smi'):
            if self.query_rc:
                return done(self.query_rc, err='NVIDIA-SMI has failed')
            if self.garbage:
                return done(out='No devices were found\n')
            return done(out=self.gpu.get(node, ''))
        if command.startswith('docker inspect'):
            name = command.split()[-1]
            if self.inspect_raise:
                raise subprocess.TimeoutExpired(command, timeout)
            if (node, name) in self.inspect_fail:
                return done(1, out='\n', err='Cannot connect to the Docker daemon at unix:///var/run/docker.sock')
            if (node, name) in self.absent:
                msg = f'Error: No such object: {name}' if self.old_docker else f'error: no such object: {name}'
                return done(1, out='\n', err=msg + '\n')
            return done(out='true\n' if (node, name) in self.running else 'false\n')
        if command.startswith('for d in /proc/'):
            if node in self.scan_fail:
                return done(255, err='ssh: connect to host')
            return done(out=self.procs.get(node, '') + 'END-OF-SCAN\n')
        if command.startswith('bash -c '):
            return done(self.start_rc, out='service: serving', err='')
        if 'service/run/state' in command:
            self.health_polls += 1
            return done(out=self.healthy_state if self.health_polls >= self.healthy_after else 'starting 1795 x\n000')
        if 'docker start' in command or 'docker stop' in command or 'service.sh stop' in command:
            raise AssertionError('start-deepseek must not start/stop containers or stop the native service')
        raise AssertionError(f'unexpected command {command!r}')


class StartDeepseekTests(unittest.TestCase):
    def run_start(self, fleet, script=SCRIPT, sha=None, log_path=None):
        with tempfile.TemporaryDirectory() as d:
            start = Path(d) / 'start.sh'
            start.write_text(script)
            path = log_path(Path(d)) if log_path else Path(d) / 'receipts' / 'log.jsonl'
            with patch.object(ds, 'ssh', fleet), patch.object(ds, 'START_SCRIPT', start), \
                    patch.object(ds, 'START_SHA', sha or hashlib.sha256(SCRIPT.encode()).hexdigest()), \
                    patch.object(ds, 'LOG', path), patch.object(ds.time, 'sleep', lambda s: None), \
                    contextlib.redirect_stdout(io.StringIO()):
                try:
                    result = ds.start_deepseek()
                except SystemExit as exc:
                    result = exc
            log = path.read_text() if path.is_file() else ''
        return result, log

    @staticmethod
    def started(fleet):
        return [c for c in fleet.calls if c[1].startswith('bash -c ')]

    def assert_nothing_started(self, fleet, result, text='preflight failed; nothing was started'):
        self.assertIsInstance(result, SystemExit)
        self.assertIn(text, str(result))
        self.assertEqual(self.started(fleet), [])

    def test_starts_native_with_the_pinned_script_and_waits_for_health(self):
        fleet = FakeFleet()
        receipt, log = self.run_start(fleet)
        self.assertTrue(receipt['ok'])
        self.assertEqual(receipt['step'], 'native-healthy')
        self.assertEqual(self.started(fleet), [('Spark_01', "bash -c 'echo start\n'")])
        for step in ('start-deepseek-start', 'start-preflight', 'native-start', 'native-healthy'):
            self.assertIn(f'"step": "{step}"', log)
        self.assertLess(log.index('start-preflight'), log.index('native-start'))
        inspected = {(n, c.split()[-1]) for n, c in fleet.calls if c.startswith('docker inspect')}
        self.assertEqual(inspected, {(n, c) for n in ds.NODES for c in ds.SWARM_CONTAINERS})

    def test_guard_failure_starts_nothing(self):
        fleet = FakeFleet(guards=False)
        result, log = self.run_start(fleet)
        self.assert_nothing_started(fleet, result)
        self.assertIn('head guards changed', str(result))

    def test_gpu_app_on_any_node_starts_nothing(self):
        for node in ds.NODES:
            fleet = FakeFleet(gpu={node: '123, python3\n'})
            result, _ = self.run_start(fleet)
            self.assert_nothing_started(fleet, result)
            self.assertIn(f'{node}: GPU compute apps present', str(result))

    def test_failed_or_unparsable_gpu_query_starts_nothing(self):
        for fleet in (FakeFleet(query_rc=255), FakeFleet(garbage=True)):
            result, _ = self.run_start(fleet)
            self.assert_nothing_started(fleet, result)
            self.assertIn('GPU query failed', str(result))

    def test_any_running_swarm_container_starts_nothing(self):
        for name in ('swarm-inkling', 'swarm-recipe', 'swarm-inkling-shim'):
            fleet = FakeFleet(running={('Spark_03', name)})
            result, _ = self.run_start(fleet)
            self.assert_nothing_started(fleet, result)
            self.assertIn(f'Spark_03: swarm container running: {name}', str(result))

    def test_absent_containers_by_exact_docker_text_are_fine(self):
        absent = {(n, 'swarm-inkling') for n in ds.NODES} | {('Spark_02', 'swarm-recipe')}
        for old in (False, True):
            fleet = FakeFleet(absent=absent, old_docker=old)
            receipt, log = self.run_start(fleet)
            self.assertTrue(receipt['ok'], log)
            self.assertIn('"swarm-inkling": null', log)

    def test_other_inspection_failures_start_nothing(self):
        fleet = FakeFleet(inspect_fail={('Spark_04', 'swarm-recipe')})
        result, _ = self.run_start(fleet)
        self.assert_nothing_started(fleet, result)
        self.assertIn('Spark_04: container inspection failed', str(result))
        fleet = FakeFleet(inspect_raise=True)
        result, _ = self.run_start(fleet)
        self.assert_nothing_started(fleet, result)

    def test_absent_text_must_match_the_name_exactly(self):
        out = done(1, '\n', 'error: no such object: swarm-recipe-old\n')
        self.assertFalse(ds._docker_absent('swarm-recipe', out))
        self.assertFalse(ds._docker_absent('swarm-recipe', done(1, '\n', 'error: no such object: swarm-recipe; also x')))
        self.assertFalse(ds._docker_absent('swarm-recipe', done(0, '\n', 'error: no such object: swarm-recipe')))
        self.assertTrue(ds._docker_absent('swarm-recipe', done(1, '\n', 'Error: No such container: swarm-recipe\n')))

    def test_start_script_hash_mismatch_starts_nothing(self):
        fleet = FakeFleet()
        result, _ = self.run_start(fleet, sha='0' * 64)
        self.assert_nothing_started(fleet, result)
        self.assertIn('start script hash differs', str(result))

    def test_nonzero_native_start_fails(self):
        fleet = FakeFleet(start_rc=1)
        result, log = self.run_start(fleet)
        self.assertIsInstance(result, SystemExit)
        self.assertIn('native start returned nonzero', str(result))
        self.assertEqual(len(self.started(fleet)), 1)

    def test_never_healthy_fails_after_the_wait(self):
        fleet = FakeFleet(healthy_after=10 ** 6)
        result, log = self.run_start(fleet)
        self.assertIsInstance(result, SystemExit)
        self.assertIn('did not become healthy', str(result))
        self.assertGreaterEqual(fleet.health_polls, 90)

    def test_unwritable_receipt_log_starts_nothing(self):
        fleet = FakeFleet()

        def blocked(d):
            (d / 'file').write_text('x')
            return d / 'file' / 'log.jsonl'
        result, _ = self.run_start(fleet, log_path=blocked)
        self.assert_nothing_started(fleet, result, 'cannot be written')
        self.assertEqual(fleet.calls, [])

    def test_running_native_process_or_failed_scan_starts_nothing(self):
        fleet = FakeFleet(procs={'Spark_02': '4242 dsgb10_rank\n'})
        result, _ = self.run_start(fleet)
        self.assert_nothing_started(fleet, result)
        self.assertIn('Spark_02: native process already running', str(result))
        fleet = FakeFleet(scan_fail={'Spark_04'})
        result, _ = self.run_start(fleet)
        self.assert_nothing_started(fleet, result)
        self.assertIn('Spark_04: process scan failed', str(result))

    def test_executed_bytes_are_the_hashed_bytes(self):
        fleet = FakeFleet()
        receipt, log = self.run_start(fleet)
        sha = hashlib.sha256(SCRIPT.encode()).hexdigest()
        self.assertEqual(receipt['launcher_sha'], sha)
        self.assertIn(f'"launcher_sha": "{sha}"', log.split('"step": "native-start"')[1].split('\n')[0])

        class Flipping:  # preflight sees the pinned bytes, the start would see others
            name = 'flipping.sh'

            def __init__(self):
                self.n = 0

            def read_bytes(self):
                self.n += 1
                return SCRIPT.encode() if self.n == 1 else b'echo other\n'
        fleet = FakeFleet()
        with patch.object(ds, 'START_SCRIPT', Flipping()):
            with tempfile.TemporaryDirectory() as d, patch.object(ds, 'ssh', fleet), \
                    patch.object(ds, 'START_SHA', sha), patch.object(ds, 'LOG', Path(d) / 'l.jsonl'), \
                    patch.object(ds.time, 'sleep', lambda s: None), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    ds.start_deepseek()
        self.assertIn('start script hash differs', str(cm.exception))
        self.assertEqual(self.started(fleet), [])

    def test_health_needs_serving_and_exactly_200(self):
        for state in ('starting 1795 x\n200', 'serving 1795 x\n1200', 'serving 1795 x\n000', '200', ''):
            self.assertFalse(ds.native_healthy(state), state)
        self.assertTrue(ds.native_healthy('serving 1795 http://127.0.0.1:8888/v1\n200'))
        fleet = FakeFleet(healthy_state='lent 1795 x\n200')
        result, _ = self.run_start(fleet)
        self.assertIn('did not become healthy', str(result))

    def test_official_flag_runs_the_official_launcher_with_its_own_pin(self):
        official = 'echo official\n'
        with tempfile.TemporaryDirectory() as d:
            ablit, off = Path(d) / 'a.sh', Path(d) / 'o.sh'
            ablit.write_text(SCRIPT)
            off.write_text(official)
            sha_a, sha_o = (hashlib.sha256(x.encode()).hexdigest() for x in (SCRIPT, official))
            for flag, want, pin_ok in ((True, official, True), (False, SCRIPT, True), (True, official, False)):
                fleet = FakeFleet()
                with patch.object(ds, 'ssh', fleet), patch.object(ds, 'START_SCRIPT', ablit), \
                        patch.object(ds, 'START_SHA', sha_a), patch.object(ds, 'START_SCRIPT_OFFICIAL', off), \
                        patch.object(ds, 'START_SHA_OFFICIAL', sha_o if pin_ok else sha_a), \
                        patch.object(ds, 'LOG', Path(d) / f'l{flag}{pin_ok}.jsonl'), \
                        patch.object(ds.time, 'sleep', lambda s: None), contextlib.redirect_stdout(io.StringIO()):
                    try:
                        result = ds.start_deepseek(official=flag)
                    except SystemExit as exc:
                        result = exc
                if pin_ok:
                    self.assertEqual(self.started(fleet), [('Spark_01', 'bash -c ' + shlex.quote(want))])
                    self.assertEqual(result['launcher'], (off if flag else ablit).name)
                    self.assertEqual(result['launcher_sha'], sha_o if flag else sha_a)
                else:  # the official launcher against the ablit pin: refused, nothing started
                    self.assertIsInstance(result, SystemExit)
                    self.assertEqual(self.started(fleet), [])

    def test_cli_accepts_only_known_forms(self):
        import runpy
        for argv in (['x', 'start-deepseek', '--ablit'], ['x', 'stop-native', '--official'], ['x']):
            with patch.object(sys, 'argv', argv), self.assertRaises((SystemExit, KeyError, IndexError)):
                runpy.run_path(str(Path(ds.__file__)), run_name='__main__')

    def test_existing_steps_unchanged(self):
        self.assertIn("docker stop -t 60 swarm-inkling-shim swarm-inkling", inspect.getsource(ds.to_deepseek))
        self.assertIn("docker start swarm-inkling swarm-inkling-shim", inspect.getsource(ds.to_inkling))
        self.assertNotIn('docker', inspect.getsource(ds.start_deepseek))
        self.assertNotIn('service.sh', inspect.getsource(ds.start_deepseek))


if __name__ == '__main__':
    unittest.main()
