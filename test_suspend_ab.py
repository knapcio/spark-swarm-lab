"""Idea #5 live A/B: frozen plans (generator), the hold_dispatch offline bound, the arm driver's fleet controls
(lease, admission, raw idle gauges, fenced drain, signals) and the report's frozen rule. No fleet, no network."""
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import report_suspend_ab as rep  # noqa: E402
import suspend_arms as sa  # noqa: E402
import suspend_plans as sp  # noqa: E402

HERE = Path(__file__).resolve().parent
IDLE = 'sglang:num_running_reqs{a="b"} 0\nsglang:num_queue_reqs{a="b"} 0\n'
BUSY = 'sglang:num_running_reqs{a="b"} 3\nsglang:num_queue_reqs{a="b"} 0\n'


class Guarded(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('no network in tests'))
        guard.start()
        self.addCleanup(guard.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)


def ts(t):
    return (datetime(2026, 11, 27, tzinfo=timezone.utc) + timedelta(seconds=t)).isoformat()


class PlanTests(Guarded):
    def make(self, extra_seed_use=None):
        shutil.copy(HERE / sp.BASE_PLAN, self.root / sp.BASE_PLAN)
        if extra_seed_use:
            (self.root / 'OTHER_PLAN.json').write_text(json.dumps(dict(matrix=dict(
                tasks='datasets/coding-hard-v1/tasks.json', seeds=extra_seed_use))))
        with patch.object(sp, 'hold_bound', lambda root: dict(hold_dispatch_share=0.12)), \
                patch.object(sp, 'worker_hashes', lambda root, rev: {'w.py': 'x'}):
            return sp.make(self.root, 'a' * 40, generator_root=HERE)

    def test_plans_differ_only_in_the_arm_fields(self):
        plans = self.make()
        control, hold = plans['control'], plans['hold']
        self.assertEqual(rep.arm_view(control), rep.arm_view(hold))
        self.assertEqual((control.get('suspend_siblings'), hold['suspend_siblings']), (None, 'hold_dispatch'))
        base = json.loads((HERE / sp.BASE_PLAN).read_text())
        for key in ('limits', 'scheduling', 'agent_variants', 'rolling', 'acceptance', 'judge', 'early_stop'):
            self.assertEqual(control[key], base[key])  # the production judge-only path, same budgets and judge
        self.assertEqual(control['matrix']['seeds'], [58, 59, 60])
        self.assertEqual(control['matrix']['tasks_sha256'], base['matrix']['tasks_sha256'])
        self.assertEqual(control['status'], 'FROZEN')
        self.assertIn('inkling/suspend_arms.py', control['code_sha256'])

    def test_used_seeds_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'seeds already used'):
            self.make(extra_seed_use=[59])


class BoundTests(Guarded):
    def test_hold_bound_counts_dispatches_inside_accepted_windows(self):
        run = self.root / 'runs' / 'r'
        run.mkdir(parents=True)

        def trace(name, rows):
            (run / name).write_text(''.join(json.dumps(r) + '\n' for r in rows))
            return str(run / name)
        winner = trace('a0.jsonl', [dict(type='judge_start', timestamp=ts(100)),
                                    dict(type='acceptance', accepted=True, timestamp=ts(200))])
        sibling = trace('a1.jsonl', [
            dict(type='request_start', request_id='p', timestamp=ts(0)),
            dict(type='request_end', request_id='p', timestamp=ts(150), usage=dict(completion_tokens=1500)),
            dict(type='request_start', request_id='f', timestamp=ts(150)),  # dispatched inside the window
            dict(type='request_end', request_id='f', timestamp=ts(200), usage=dict(completion_tokens=500))])
        (run / 'summary.json').write_text(json.dumps([
            dict(task_id='t', seed=1, agent=0, winner=True, events=winner),
            dict(task_id='t', seed=1, agent=1, winner=False, events=sibling)]))
        (run / 'arm_accounting.json').write_text(json.dumps(dict(server=dict(total=dict(generation_tokens=10000)),
                                                                 energy=dict(total_wh=1.0))))
        b = sp.hold_bound(self.root, 'r')
        self.assertEqual(b['hold_dispatch_share'], 0.05)  # the 500 tokens dispatched inside [100, 200]
        self.assertEqual(b['true_suspension_share'], 0.1)  # + 500 of the in-flight stream over [100, 150]


class DriverTests(Guarded):
    def plan(self):
        plan = dict(study='coding-suspend-v1-hold', status='FROZEN', source_revision='r' * 40,
                    source_path='.runtime/coding-suspend-source')
        path = self.root / 'plan.json'
        path.write_text(json.dumps(plan))
        return path

    def harness(self, fetches, runner_polls=2, signal_at=None, admission_ok=True, raise_in_loop=False):
        order = []
        fetch_iter = iter(fetches)

        def fetch(i):
            text = next(fetch_iter) if i == 0 else IDLE
            return text

        class Lease:
            @staticmethod
            @contextlib.contextmanager
            def lease(root, holder):
                order.append('lease')
                try:
                    yield
                finally:
                    order.append('release')

        class Runner:
            def __init__(self, *a, **k):
                self.n, self.returncode = 0, None
                order.append('runner')

            def poll(self):
                self.n += 1
                if signal_at is not None and self.n == signal_at:
                    sa.on_signal(15, None)
                if raise_in_loop and self.n == 2:
                    raise RuntimeError('controller loop failed')
                if self.n > runner_polls:
                    self.returncode = self.returncode if self.returncode is not None else 0
                return self.returncode

            def terminate(self):
                order.append('terminate')
                self.returncode = -15

        def admit(cmd, **kw):
            out = Path(cmd[cmd.index('--output') + 1])
            plan_path = Path(cmd[cmd.index('--plan') + 1])
            out.write_text(json.dumps(dict(verified=admission_ok, allow_busy=False,
                                           verified_utc=datetime.now(timezone.utc).isoformat(),
                                           plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
                                           source_revision='r' * 40)))
            return type('R', (), dict(returncode=0, stderr=''))()

        def drain_spy(fetch_fn, poll=2.0, warn_every=600):
            order.append('drain')
            return real_drain(fetch_fn, poll=0, warn_every=0)
        real_drain = sa.drain
        out = self.root / 'out'
        del sa.SIGNALS[:]
        saved = sa.signal.getsignal(sa.signal.SIGINT), sa.signal.getsignal(sa.signal.SIGTERM)
        try:
            with patch.object(sa, 'fleet_lease', Lease), patch.object(sa, 'freeze_problem', lambda *a: None), \
                    patch.object(sa.subprocess, 'run', admit), patch.object(sa.arms, 'flush_caches', lambda: {}), \
                    patch.object(sa.energy, 'window', lambda a, b: dict(total_wh=1.0, nodes={})), \
                    patch.object(sa, 'drain', drain_spy), patch.object(sa.time, 'sleep', lambda s: None), \
                    patch.object(sa, 'ROOT', self.root), contextlib.redirect_stdout(io.StringIO()):
                (self.root / '.runtime').mkdir(exist_ok=True)
                try:
                    code = sa.main(['--plan', str(self.plan()), '--output', str(out)], fetch=fetch, popen=Runner)
                except (SystemExit, RuntimeError) as exc:
                    code = exc
        finally:
            sa.signal.signal(sa.signal.SIGINT, saved[0])
            sa.signal.signal(sa.signal.SIGTERM, saved[1])
        record = json.loads((out / 'arm_accounting.json').read_text()) if (out / 'arm_accounting.json').exists() \
            else None
        return order, code, record

    def test_lease_is_held_until_the_fenced_drain_confirms_idle(self):
        # before: idle; after the runner: busy twice, then idle
        order, code, record = self.harness([IDLE, BUSY, BUSY, IDLE])
        self.assertEqual(order, ['lease', 'runner', 'drain', 'release'])
        self.assertEqual(code, 0)
        self.assertTrue(record['drain_confirmed'] and not record['stopped_by_signal'])

    def test_missing_raw_gauges_block_the_start(self):
        order, code, _ = self.harness(['vllm:num_requests_running 0\n'])  # shim-style gauges only
        self.assertNotIn('runner', order)
        self.assertIn('raw gauges missing', str(code))
        order, code, _ = self.harness([BUSY])
        self.assertNotIn('runner', order)

    def test_a_failed_admission_never_starts_the_runner(self):
        order, code, _ = self.harness([IDLE], admission_ok=False)
        self.assertEqual(order, ['lease', 'release'])
        self.assertIn('admission not verified', str(code))

    def test_a_signal_stops_the_runner_and_still_drains(self):
        order, code, record = self.harness([IDLE, BUSY, IDLE], runner_polls=5, signal_at=1)
        self.assertEqual(order, ['lease', 'runner', 'terminate', 'drain', 'release'])
        self.assertTrue(record['stopped_by_signal'])
        self.assertNotEqual(code, 0)

    def test_an_exception_in_the_runner_loop_still_drains_before_release(self):
        order, code, _ = self.harness([IDLE, BUSY, IDLE], runner_polls=5, raise_in_loop=True)
        self.assertEqual(order, ['lease', 'runner', 'terminate', 'drain', 'release'])
        self.assertIsInstance(code, RuntimeError)

    def test_drain_warning_failures_never_escape(self):
        texts = iter([BUSY, IDLE])
        with patch('builtins.print', side_effect=OSError('stdout closed')), patch.object(sa.time, 'sleep',
                                                                                         lambda s: None):
            snap, _ = sa.drain(lambda i: next(texts) if i == 0 else IDLE, poll=0, warn_every=0)
        self.assertTrue(sa.idle(snap))

    def test_the_signal_handler_only_latches(self):
        del sa.SIGNALS[:]
        with patch('builtins.print', side_effect=OSError('stdout closed')):
            sa.on_signal(2, None)
        self.assertEqual(sa.SIGNALS, [2])
        del sa.SIGNALS[:]

    def test_freeze_problem_requires_a_frozen_plan(self):
        self.assertEqual(sa.freeze_problem(self.root / 'x.json', dict(status='DRAFT')), 'plan is not FROZEN')


class ReportTests(Guarded):
    def plans(self):
        base = dict(study_group='g', matrix=dict(tasks_count=2, seeds=[58, 59]), decision_rule=sp.RULE)
        return dict(base, study='c', ab_arm='control'), dict(base, study='h', ab_arm='hold',
                                                              suspend_siblings='hold_dispatch')

    def arm_run(self, name, plan, solved, wrong, wh, drained=True, coverage=1.0, errors=(), drop=0, signal=False):
        d = self.root / name
        d.mkdir()
        cases = []
        for i, (task, seed) in enumerate([(t, s) for s in (58, 59) for t in ('a', 'b')]):
            cases.append(dict(task_id=task, seed=seed, solved=i < solved, answered=i < solved + wrong))
        (d / 'cases.json').write_text(json.dumps(cases[:len(cases) - drop]))
        (d / 'metadata.json').write_text(json.dumps(dict(protocol=plan, errors=list(errors), holds=dict(cases=1))))
        (d / 'arm_accounting.json').write_text(json.dumps(dict(
            runner_exit=0, drain_confirmed=drained, stopped_by_signal=signal, runner_wall_seconds=10,
            server=dict(total=dict(generation_tokens=1000 if name == 'c' else 880, requests=5)),
            energy=dict(total_wh=wh, nodes={n: dict(coverage=coverage) for n in ('01', '02', '03', '04')}))))
        return d

    def test_rule(self):
        control, hold = self.plans()
        c = self.arm_run('c', control, solved=4, wrong=0, wh=40.0)
        r = rep.build(control, hold, c, self.arm_run('h1', hold, solved=4, wrong=0, wh=35.0))
        self.assertEqual((r['decision'], r['energy_per_solved_ratio']), ('PASS', 0.875))
        self.assertEqual(r['server_generation_token_saving'], 0.12)
        r = rep.build(control, hold, c, self.arm_run('h2', hold, solved=4, wrong=0, wh=37.0))
        self.assertEqual((r['decision'], r['checks']['energy']), ('STOP', False))  # 0.925 > 0.90
        r = rep.build(control, hold, c, self.arm_run('h3', hold, solved=3, wrong=1, wh=20.0))
        self.assertEqual((r['decision'], r['checks']['no_additional_wrong']), ('STOP', False))
        r = rep.build(control, hold, c, self.arm_run('h4', hold, solved=3, wrong=0, wh=20.0))
        self.assertEqual(r['decision'], 'PASS')  # one solved case fewer is allowed
        r2 = self.arm_run('c2', control, solved=4, wrong=0, wh=40.0)
        r = rep.build(control, hold, r2, self.arm_run('h5', hold, solved=2, wrong=0, wh=10.0))
        self.assertEqual((r['decision'], r['checks']['solved']), ('STOP', False))

    def test_incomplete(self):
        control, hold = self.plans()
        c = self.arm_run('c', control, solved=4, wrong=0, wh=40.0)
        for name, kw, needle in (('a', dict(drained=False), 'drain not confirmed'),
                                 ('b', dict(coverage=0.5), 'energy not covered'),
                                 ('d', dict(errors=[dict(reason='x')]), 'runner errors'),
                                 ('e', dict(drop=1), '3 of 4 planned cases'),
                                 ('f', dict(signal=True), 'stopped by a signal')):
            r = rep.build(control, hold, c, self.arm_run(name, hold, solved=4, wrong=0, wh=30.0, **kw))
            self.assertEqual(r['status'], 'incomplete')
            self.assertIn(needle, ' '.join(r['problems']))
        r = rep.build(control, dict(hold, judge=dict(thinking_tokens=1)), c,
                      self.arm_run('g', dict(hold, judge=dict(thinking_tokens=1)), solved=4, wrong=0, wh=30.0))
        self.assertIn('differ beyond their arm fields', ' '.join(r['problems']))


if __name__ == '__main__':
    unittest.main()
