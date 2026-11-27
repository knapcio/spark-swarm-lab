"""Live differential-gate A/B: the gate (CaseGate), the gate runner (run_coding_diffgate.py) with fake workers, the
generator process wrapper, the arm driver, the frozen plans and the report. No fleet, no network, no model code."""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import run_coding_diffgate as dg

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import diffgate_arms as da  # noqa: E402
import diffgate_live_plans as lp  # noqa: E402
import report_diffgate_live as rep  # noqa: E402

TASK = dict(id='t1', function_name='f', spec='Inputs: x. Return x.')
FAMILY = ('arithmetic', 'number', 'target', 'puzzle', 'countdown', 'shell', 'table', 'path', 'cache')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class FakeSandbox:
    """generate -> inputs (or an error); outputs -> outcomes by the code's behaviour tag ('# B:x')."""

    def __init__(self, inputs=True, infra=False):
        self.inputs, self.infra, self.calls = inputs, infra, []

    def __call__(self, mode, code, name, host, inputs=None, **kw):
        self.calls.append((mode, host))
        if self.infra:
            return dict(status='error', infrastructure=True, error='ssh down')
        if mode == 'generate':
            return dict(status='ok', inputs=[{'args': [1]}, {'args': [2]}], container_seconds=0.5) if self.inputs \
                else dict(status='error', error='no list', container_seconds=0.1)
        tag = code.split('# B:')[-1].strip() if '# B:' in code else None
        if tag == 'broken':
            return dict(status='error', error='load', container_seconds=0.2)
        return dict(status='ok', outcomes=[dict(sha256=f'{tag}-{i}', preview='') for i in range(len(inputs))],
                    container_seconds=0.3)


class FakeGenerator:
    def __init__(self, outcome='ok', fault=False):
        self.outcome, self.fault, self.calls = outcome, fault, []

    def __call__(self, cfg, item, endpoint, events, stop):
        self.calls.append((item['item_id'], endpoint))
        if self.fault:
            raise dg.GateFault('generator fault: lost')
        return dict(outcome=self.outcome, reply='```python\ndef generate_inputs(): return []\n```', tokens_generated=77)


def gate_of(tmp, sandbox=None, generator=None):
    return dg.CaseGate(('t1', 70), TASK, 'http://n0/v1', 'Spark_01', tmp, {}, threading.Event(),
                       runner=sandbox or FakeSandbox(), generator=generator or FakeGenerator())


class CaseGateTests(unittest.TestCase):
    def test_two_agreeing_distinct_passers_accept_the_first(self):
        with tempfile.TemporaryDirectory() as d:
            gen = FakeGenerator()
            g = gate_of(d, generator=gen)
            self.assertIsNone(g.add(0, 'def f(x): return x  # B:a', 1.0))
            self.assertIsNone(g.add(3, 'def f(x): return x  # B:a', 2.0))  # identical code: counted once
            self.assertEqual(g.duplicates, 1)
            self.assertEqual(g.add(2, 'def f(x):\n    return x  # B:a', 3.0), 0)  # agreement: the earliest member
            self.assertEqual(g.decision, dict(agent=0, rule='class', class_size=2))
            self.assertEqual(len(gen.calls), 1)  # one generator call per case, inputs reused
            g2 = gate_of(d, generator=FakeGenerator())
            g2.add(0, 'x  # B:a', 1.0, endpoint='http://n2/v1')
            self.assertEqual(g2.generator.calls[0][1], 'http://n2/v1')  # on the passer's own node
            self.assertEqual(g.summary()['generator_tokens'], 77)

    def test_disagreement_keeps_spawning_and_the_next_passer_joins_the_vote(self):
        with tempfile.TemporaryDirectory() as d:
            g = gate_of(d)
            self.assertIsNone(g.add(0, 'def f(x): pass  # B:a', 1.0))
            self.assertIsNone(g.add(1, 'def f(x): pass  # B:b', 2.0))  # disagree
            self.assertIsNone(g.add(2, 'def f(x): pass  # B:broken', 3.0))  # cannot run: never votes
            self.assertEqual(g.add(4, 'def f(y): pass  # B:b', 4.0), 1)  # class b reaches 2: its first member
            self.assertFalse(g.summary()['all_passers_agree'])

    def test_unusable_inputs_twice_falls_back_to_two_distinct_passers(self):
        with tempfile.TemporaryDirectory() as d:
            gen = FakeGenerator()
            g = gate_of(d, sandbox=FakeSandbox(inputs=False), generator=gen)
            self.assertIsNone(g.add(0, 'a', 1.0))
            self.assertEqual(len(gen.calls), 2)  # one more call after unusable inputs
            self.assertTrue(g.fallback)
            self.assertEqual(g.add(1, 'b', 2.0), 0)
            self.assertEqual(g.decision['rule'], 'fallback')

    def test_truncated_generator_replies_count_as_unusable(self):
        with tempfile.TemporaryDirectory() as d:
            g = gate_of(d, generator=FakeGenerator(outcome='truncated'))
            g.add(0, 'a', 1.0)
            self.assertTrue(g.fallback)

    def test_faults_are_never_acceptances(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(dg.GateFault):
                gate_of(d, sandbox=FakeSandbox(infra=True)).add(0, 'a  # B:a', 1.0)
            with self.assertRaises(dg.GateFault):
                gate_of(d, generator=FakeGenerator(fault=True)).add(0, 'a  # B:a', 1.0)


class GeneratorProcessTests(unittest.TestCase):
    def test_record_fault_and_stop(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cfg = dict(system='s', user='u {payload}', think_tokens=1, total_tokens=2, source_path='.')

            def popen_writing(record, running=0):
                class P:
                    def __init__(self, cmd, cwd=None, stdout=None, stderr=None, start_new_session=False):
                        assert start_new_session and '--one' in cmd
                        stdout.write(json.dumps(record) + '\n')
                        stdout.flush()
                        self.left, self.pid, self.returncode = running, 0, None

                    def poll(self):
                        if self.left > 0:
                            self.left -= 1
                            return None
                        self.returncode = 0
                        return 0
                return P
            rec = dg.run_generator(cfg, dict(item_id='i', payload='{}'), 'http://n/v1', root / 'a.jsonl',
                                   threading.Event(), popen=popen_writing(dict(outcome='ok', reply='x')), poll=0)
            self.assertEqual(rec['outcome'], 'ok')
            with self.assertRaises(dg.GateFault):
                dg.run_generator(cfg, dict(item_id='i', payload='{}'), 'http://n/v1', root / 'b.jsonl',
                                 threading.Event(), popen=popen_writing(dict(error='lost')), poll=0)
            stop = threading.Event()
            stop.set()
            with patch.object(dg, 'terminate', lambda p: 0), self.assertRaises(dg.GateFault):
                dg.run_generator(cfg, dict(item_id='i', payload='{}'), 'http://n/v1', root / 'c.jsonl', stop,
                                 popen=popen_writing(dict(outcome='ok'), running=5), poll=0)


class RunnerTests(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('no network in tests'))
        guard.start()
        self.addCleanup(guard.stop)
        del dg.base.ABORT[:]
        self.addCleanup(lambda: dg.base.ABORT.__delitem__(slice(None)))

    def run_main(self, outcomes, plan_extra=None, agents=4, admission_extra=None, abort_at=None, timing=None,
                 faulted=()):
        """outcomes[(task, agent)] = None (fails public tests) or a behaviour tag; timing[(task, agent)] = (public-pass
        time, seconds until the worker exits); faulted: agents whose row carries a controller error."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tasks = root / 'tasks.json'
            tasks.write_text(json.dumps(dict(tasks=[dict(id=t, split='evaluation', function_name='f', spec='s')
                                                    for t in ('t1', 't2')])))
            tests = root / 'tests.json'
            tests.write_text('{}')
            plan = dict(protocol=dg.PROTOCOL, early_stop='first_feedback_pass_in_time', status='FROZEN',
                        source_revision='x', agent_variants=['code_elastic'] * agents, agent_seed_offset=70700,
                        rolling=dict(width=2), runner='run_coding_diffgate.py',
                        differential_gate=dict(rule=dg.GATE, system='s', user='u {payload}', think_tokens=1,
                                               total_tokens=2, source_path='.', source_revision='y'),
                        matrix=dict(tasks=str(tasks), tests=str(tests), tasks_sha256=sha(tasks),
                                    tests_sha256=sha(tests), split='evaluation', tasks_count=2, seeds=[70]),
                        scheduling=dict(concurrent_agents_per_node=2), limits=dict(agent_wall_deadline_seconds=60))
            plan.update(plan_extra or {})
            plan_path = root / 'plan.json'
            plan_path.write_text(json.dumps(plan))
            adm = root / 'adm.json'
            adm.write_text(json.dumps(dict(dict(verified=True, verified_utc=datetime.now(timezone.utc).isoformat(),
                                                plan_sha256=sha(plan_path), allow_busy=False, source_revision='x'),
                                           **(admission_extra or {}))))
            started = []

            def agent_of(events):
                return int(Path(events).name.split('-a')[1].split('-')[0])

            def execute(job, deadline, cancel, announce):
                key = (job['task_id'], job['agent'])
                started.append(key)
                if abort_at is not None and len(started) == abort_at:
                    dg.base.on_signal(15, None)
                pass_ts, wait = (timing or {}).get(key, (float(job['agent']), 0.05))
                if outcomes.get(key) is not None:
                    announce(pass_ts)  # the public pass, before holdout grading
                for _ in range(int(wait / .01) + 1):
                    if cancel.is_set() or dg.base.ABORT:
                        aborted = bool(dg.base.ABORT) and not cancel.is_set()
                        return dict(cancelled=True, aborted=aborted, deadline=False, controller_error=None,
                                    returncode=-15, controller_stop=True, status='cancelled', calls=1,
                                    unfinished_calls=1, infrastructure_failures=None, completion_tokens=0)
                    real_sleep(.01)
                return dict(cancelled=False, aborted=False, deadline=False,
                            controller_error='boom' if key in faulted else None, returncode=0,
                            controller_stop=False, status='complete', calls=1, unfinished_calls=0,
                            infrastructure_failures=0, completion_tokens=10)

            def outcome(events):
                key = (Path(events).name.split('-s')[0], agent_of(events))
                tag = outcomes.get(key)
                return dict(parsed=True, feedback_pass=tag is not None, holdout_pass=tag == 'good',
                            budget_forced=False)

            def code(events):
                key = (Path(events).name.split('-s')[0], agent_of(events))
                return f'def f(x): pass  # {key[1]} # B:{outcomes.get(key)}'
            real_sleep = time.sleep
            with patch.object(dg, 'execute_gated', execute), patch.object(dg, 'agent_outcome', outcome), \
                    patch.object(dg, 'final_code', code), patch.object(dg, 'validate_source', lambda *a: None), \
                    patch.object(dg, 'hashes', lambda s: {}), patch.object(dg, 'server_metrics', lambda *a, **k: {}), \
                    patch.object(dg.time, 'sleep', lambda s: None), contextlib.redirect_stdout(io.StringIO()):
                code_ = dg.main(['--plan', str(plan_path), '--output', str(root / 'out'), '--source', str(root),
                                 '--admission', str(adm), '--run'], generator=FakeGenerator(), runner=FakeSandbox())
            cases = json.loads((root / 'out' / 'cases.json').read_text())
            gate_cases = json.loads((root / 'out' / 'gate_cases.json').read_text())
            meta = json.loads((root / 'out' / 'metadata.json').read_text())
        return code_, {c['task_id']: c for c in cases}, started, gate_cases, meta

    def test_first_pass_does_not_end_the_case_and_agreement_accepts(self):
        outs = {('t1', 0): 'good', ('t1', 1): None, ('t1', 2): 'good', ('t2', 0): 'good', ('t2', 1): 'good'}
        code, cases, started, gates, meta = self.run_main(outs)
        self.assertEqual(code, 0)
        self.assertTrue(cases['t1']['answered'] and cases['t1']['solved'])
        self.assertIn(('t1', 2), started)  # a replacement started after the first pass
        self.assertEqual(cases['t1']['winner_agent'], 0)  # the class member that passed first
        self.assertEqual(meta['gate']['generator_calls'], 2)  # one per case

    def test_disagreement_to_the_cap_abstains(self):
        outs = {('t1', 0): 'good', ('t1', 1): 'bad', ('t1', 2): None, ('t1', 3): None, ('t2', 0): 'good',
                ('t2', 1): 'good'}
        code, cases, started, gates, meta = self.run_main(outs)
        self.assertFalse(cases['t1']['answered'])  # no class of 2 by the cap of 4 agents: unanswered
        self.assertEqual(sum(1 for t, _ in started if t == 't1'), 4)
        self.assertTrue(cases['t2']['answered'])

    def test_a_single_passer_abstains(self):
        code, cases, *_ = self.run_main({('t1', 0): 'good', ('t2', 0): 'good', ('t2', 1): 'good'})
        self.assertFalse(cases['t1']['answered'])

    def test_a_signal_stops_admissions_and_cancels_running_workers(self):
        outs = {('t1', 0): None, ('t1', 1): None, ('t2', 0): None, ('t2', 1): None}
        code, cases, started, gates, meta = self.run_main(outs, abort_at=1)
        self.assertNotEqual(code, 0)
        self.assertTrue(any(e['reason'] == 'signal' for e in meta['errors']))
        self.assertLessEqual(len(started), 4)  # no replacement after the latch

    def test_review_passers_vote_in_public_pass_order_not_exit_order(self):
        """Live review blocker 1: agent 1 passed the public tests first but its holdout grading is slow; agent 0
        exits first. Both agree: the answer is agent 1 (the earliest public pass), not the first to exit."""
        outs = {('t1', 0): 'good', ('t1', 1): 'good', ('t2', 0): 'good', ('t2', 1): 'good'}
        timing = {('t1', 0): (5.0, 0.0), ('t1', 1): (1.0, 0.3)}
        code, cases, *_ = self.run_main(outs, timing=timing)
        self.assertEqual(cases['t1']['winner_agent'], 1)

    def test_review_a_faulted_worker_never_votes_and_no_winner_after_the_latch(self):
        """Live review blocker 2: the worker's own fault is checked before it votes; a fault latches the stop and no
        winner is published behind it."""
        outs = {('t1', 0): 'good', ('t1', 1): 'good', ('t2', 0): None, ('t2', 1): None}
        code, cases, started, gates, meta = self.run_main(outs, faulted={('t1', 1)},
                                                          timing={('t1', 0): (0.0, 0.0), ('t1', 1): (1.0, 0.1)})
        self.assertNotEqual(code, 0)
        self.assertFalse(cases['t1']['answered'])
        self.assertTrue(any(e['reason'] != 'signal' for e in meta['errors']))

    def test_plan_checks(self):
        with self.assertRaisesRegex(ValueError, 'gate runner needs'):
            self.run_main({}, plan_extra=dict(differential_gate=dict(rule='other')))
        with self.assertRaisesRegex(ValueError, 'Admission not bound'):
            self.run_main({}, admission_extra=dict(plan_sha256='0' * 64))


class ExecuteGatedTests(unittest.TestCase):
    def test_review_a_running_executor_sees_the_signal_and_reaps_the_worker(self):
        """Live review blocker 2: a SIGTERM latch stops a running worker at the next poll (no 7,200 s wait)."""
        del dg.base.ABORT[:]
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            events = root / 'a.jsonl'
            script = ('import json, sys, time\n'
                      'p = sys.argv[1]\n'
                      'open(p, "a").write(json.dumps(dict(type="evaluation_end", phase="feedback", '
                      'timestamp="2026-11-27T10:00:00+00:00", report=dict(status="passed"))) + chr(10))\n'
                      'time.sleep(30)\n')
            job = dict(command=[sys.executable, '-c', script, str(events)], events=str(events),
                       stdout=str(root / 'o'), stderr=str(root / 'e'), task_id='t1', seed=70, agent=0,
                       arm='code_elastic', endpoint='http://n/v1')
            seen = []
            threading.Timer(0.5, dg.base.on_signal, args=(15, None)).start()
            t0 = time.monotonic()
            row = dg.execute_gated(job, 7200, threading.Event(), announce=seen.append, poll=.05)
            del dg.base.ABORT[:]
        self.assertLess(time.monotonic() - t0, 5)
        self.assertTrue(row['aborted'] and row['cancelled'])
        self.assertEqual(seen, [datetime.fromisoformat('2026-11-27T10:00:00+00:00').timestamp()])  # announced first


class OrderTests(unittest.TestCase):
    def test_process_holds_later_passers_until_the_earlier_one_is_ready(self):
        with tempfile.TemporaryDirectory() as d:
            g = gate_of(d)
            g.announce(1, 1.0)
            g.announce(0, 2.0)
            with g.lock:
                g.ready(0, 'x  # B:a')
                self.assertIsNone(g.process())  # agent 1 (earlier public pass) is still in holdout grading
                self.assertEqual(g.passers, [])
                g.ready(1, 'y  # B:a')
                self.assertEqual(g.process(), 1)  # then both vote in public-pass order: the answer is agent 1
            g2 = gate_of(d)
            g2.announce(1, 1.0)
            g2.announce(0, 2.0)
            with g2.lock:
                g2.ready(1, None)  # cancelled or faulted: never votes
                g2.ready(0, 'x  # B:a')
                self.assertIsNone(g2.process())
                self.assertEqual([p['agent'] for p in g2.passers], [0])


IDLE = 'sglang:num_running_reqs{a="b"} 0\nsglang:num_queue_reqs{a="b"} 0\n'


class ArmsDriverTests(unittest.TestCase):
    def test_review_the_lease_is_released_only_after_drain_and_a_clean_sweep(self):
        order = []
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            plan_path = root / 'plan.json'
            plan_path.write_text(json.dumps(dict(study='coding-diffgate-v1-gate', runner='run_coding_diffgate.py',
                                                 status='FROZEN', source_revision='r', source_path='src')))

            class Lease:
                @staticmethod
                @contextlib.contextmanager
                def lease(root_, holder):
                    order.append('lease')
                    try:
                        yield
                    finally:
                        order.append('release')

            class Runner:
                def __init__(self, cmd, **kw):
                    order.append(('runner', Path(cmd[1]).name))
                    self.returncode = 0

                def poll(self):
                    return 0

                def wait(self):
                    order.append('wait')
                    return 0

            def admit(cmd, **kw):
                Path(cmd[cmd.index('--output') + 1]).write_text(json.dumps(dict(endpoints=da.CANONICAL)))
                return type('R', (), dict(returncode=0, stderr=''))()
            del da.sa.SIGNALS[:]
            saved = da.signal.getsignal(da.signal.SIGINT), da.signal.getsignal(da.signal.SIGTERM)
            try:
                with patch.object(da.sa, 'fleet_lease', Lease), \
                        patch.object(da.sa, 'freeze_problem', lambda *a: None), \
                        patch.object(da.sa, 'admission_problem', lambda *a: None), \
                        patch.object(da.subprocess, 'run', admit), \
                        patch.object(da.sa.arms, 'flush_caches', lambda: {}), \
                        patch.object(da.sa, 'drain', lambda f: order.append('drain') or (da.sa.snapshot(f), 0)), \
                        patch.object(da, 'sweep_until_clean', lambda: order.append('sweep') or dict(rounds=1)), \
                        patch.object(da.sa.energy, 'window', lambda a, b: dict(total_wh=1.0, nodes={})), \
                        patch.object(da.sa.arms, 'delta', lambda a, b: dict(total={})), \
                        patch.object(da, 'ROOT', root), patch.object(da.time, 'sleep', lambda s: None), \
                        contextlib.redirect_stdout(io.StringIO()):
                    (root / '.runtime').mkdir()
                    da.main(['--plan', str(plan_path), '--output', str(root / 'out')], fetch=lambda i: IDLE,
                            popen=Runner)
            finally:
                da.signal.signal(da.signal.SIGINT, saved[0])
                da.signal.signal(da.signal.SIGTERM, saved[1])
        self.assertEqual(order, ['lease', ('runner', 'run_coding_diffgate.py'), 'wait', 'drain', 'sweep', 'release'])

    def test_review_sweep_until_no_sandbox_container_is_left(self):
        rounds = iter([{'Spark_01': 1, 'Spark_02': 0}, {'Spark_01': None, 'Spark_02': 0},
                       {'Spark_01': 0, 'Spark_02': 0}])
        with patch.object(da.time, 'sleep', lambda s: None):
            out = da.sweep_until_clean(sweep=lambda: next(rounds), poll=0)
        self.assertEqual(out['rounds'], 3)

    def test_unknown_runner_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            plan = Path(d) / 'p.json'
            plan.write_text(json.dumps(dict(study='s', runner='run_other.py', status='FROZEN')))
            with self.assertRaisesRegex(SystemExit, 'unknown runner'):
                da.main(['--plan', str(plan), '--output', str(Path(d) / 'o')])
        self.assertEqual(da.CANONICAL, [f'http://127.0.0.1:{p}/v1' for p in range(18081, 18085)])


class PlanTests(unittest.TestCase):
    def test_arm_plans(self):
        root = Path(__file__).resolve().parent
        with patch.object(lp, 'blob_sha', lambda tree, rev, name: 'x' * 64):
            plans = lp.make('a' * 40, root)
        c, g = plans['control'], plans['gate']
        self.assertEqual(rep.arm_view(c), rep.arm_view(g))
        self.assertEqual((c['runner'], g['runner']), ('run_coding_earlystop.py', 'run_coding_diffgate.py'))
        base = json.loads((root / lp.BASE_PLAN).read_text())
        for key in ('limits', 'scheduling', 'agent_variants', 'rolling', 'early_stop', 'source_revision', 'serving'):
            self.assertEqual(c[key], base[key])  # the production path
        self.assertEqual((c['matrix']['seeds'], c['agent_seed_offset']), (list(range(70, 79)), 70700))
        added = (g['differential_gate']['system'] + ' ' + g['differential_gate']['user'].replace('{payload}', ''))
        self.assertEqual([w for w in FAMILY if w in added.lower()], [])
        self.assertIn('run_coding_diffgate.py', c['code_sha256'])


def receipts(plan, shared=()):
    keys = [(t, s) for s in plan['matrix']['seeds'] for t in ('a', 'b')]
    return [dict(task_id=t, seed=s, passers=2, all_passers_agree=(t, s) in shared,
                 decision=dict(rule='class', agent=0, class_size=2)) for t, s in keys]


def write_arm(root, name, plan, solved, wrong, wh, gate_cases=None, joules=None):
    d = root / name
    d.mkdir()
    cases = []
    keys = [(t, s) for s in plan['matrix']['seeds'] for t in ('a', 'b')]
    for i, (task, seed) in enumerate(keys):
        cases.append(dict(task_id=task, seed=seed, solved=i < solved, answered=i < solved + wrong))
    (d / 'cases.json').write_text(json.dumps(cases))
    (d / 'summary.json').write_text(json.dumps([{}] * 6))
    (d / 'metadata.json').write_text(json.dumps(dict(protocol=plan, errors=[], gate=dict(
        generator_calls=4, generator_tokens=400, sandbox_seconds=3.0, fallback_cases=0))))
    if gate_cases is not None:
        (d / 'gate_cases.json').write_text(json.dumps(gate_cases))
    nodes = {n: dict(coverage=1.0, joules=(joules or {}).get(n, wh * 900)) for n in ('01', '02', '03', '04')}
    (d / 'arm_accounting.json').write_text(json.dumps(dict(
        runner_exit=0, drain_confirmed=True, stopped_by_signal=False, runner_wall_seconds=10,
        server=dict(total=dict(generation_tokens=1000)),
        energy=dict(total_wh=round(sum(n['joules'] for n in nodes.values()) / 3600, 2), nodes=nodes))))
    return d


class ReportTests(unittest.TestCase):
    def plans(self, root):
        tasks = root / 'tasks.json'
        tasks.write_text(json.dumps(dict(tasks=[dict(id='a', split='evaluation'), dict(id='b', split='evaluation')])))
        base = dict(study_group='g', decision_rule='r', matrix=dict(tasks='tasks.json', tasks_sha256=sha(tasks),
                                                                     split='evaluation', tasks_count=2, seeds=[70, 71]))
        return (dict(base, study='c', ab_arm='control', runner='run_coding_earlystop.py'),
                dict(base, study='g', ab_arm='gate', runner='run_coding_diffgate.py', differential_gate={}))

    def test_rule_and_shared_bug(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c, g = self.plans(root)
            cr = write_arm(root, 'c', c, solved=2, wrong=2, wh=20.0)
            r = rep.build(c, g, cr, write_arm(root, 'g', g, solved=2, wrong=1, wh=29.0,
                                              gate_cases=receipts(g, shared={('a', 71)})), root)
            self.assertEqual(r['decision'], 'PASS')  # 1 <= 0.6 x 2, 2 >= -1, 14.5 <= 15
            self.assertEqual(r['shared_bug_cases'][0]['task_id'], 'a')
            r = rep.build(c, g, cr, write_arm(root, 'g2', g, solved=2, wrong=2, wh=20.0, gate_cases=receipts(g)),
                          root)
            self.assertEqual((r['decision'], r['checks']['wrong']), ('STOP', False))
            r = rep.build(c, g, cr, write_arm(root, 'g3', g, solved=2, wrong=0, wh=30.2, gate_cases=receipts(g)),
                          root)
            self.assertEqual((r['decision'], r['checks']['energy']), ('STOP', False))

    def test_review_energy_decision_uses_unrounded_node_joules(self):
        """Live review blocker 5: total_wh is rounded to 0.01 Wh by energy.py; the decision uses the node joules."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c, g = self.plans(root)
            cr = write_arm(root, 'c', c, solved=2, wrong=2, wh=0, joules={n: 9000 for n in ('01', '02', '03', '04')})
            # control 10.0 Wh / 2 solved = 5.0; gate 15.004 Wh / 2 = 7.502 > 1.5 x 5 = 7.5, but energy.py's total_wh
            # rounds it to 15.0 (7.5: it would pass)
            gj = {n: 13503.6 for n in ('01', '02', '03', '04')}
            r = rep.build(c, g, cr, write_arm(root, 'g', g, solved=2, wrong=0, wh=0, joules=gj,
                                              gate_cases=receipts(g)), root)
            self.assertAlmostEqual(r['arms']['gate']['energy_wh'], 4 * 13503.6 / 3600)
            self.assertEqual((r['checks']['energy'], r['decision']), (False, 'STOP'))

    def test_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            c, g = self.plans(root)
            cr = write_arm(root, 'c', c, solved=2, wrong=0, wh=20.0)
            r = rep.build(c, g, cr, write_arm(root, 'g', g, solved=2, wrong=0, wh=20.0), root)
            self.assertIn('gate: gate_cases.json is not exactly one receipt per frozen case', r['problems'])
            r = rep.build(c, g, cr, write_arm(root, 'g1', g, solved=2, wrong=0, wh=20.0, gate_cases=[]), root)
            self.assertIn('gate: gate_cases.json is not exactly one receipt per frozen case', r['problems'])  # SHOULD
            r = rep.build(c, dict(g, limits={'x': 1}), cr, write_arm(root, 'g2', dict(g, limits={'x': 1}), solved=2,
                                                                     wrong=0, wh=20.0, gate_cases=receipts(g)), root)
            self.assertIn('the two plans differ beyond their arm fields', r['problems'])


if __name__ == '__main__':
    unittest.main()
