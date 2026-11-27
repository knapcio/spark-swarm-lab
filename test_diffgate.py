"""Differential gate: sandbox runner protocol (its trusted runner exercised on trusted test snippets only, through a
faked ssh), the sandbox step, the report's frozen rule and the generator plan. No fleet, no network, no model code."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import diffgate_exec as de  # noqa: E402
import diffgate_gen_plan as gp  # noqa: E402
import report_diffgate as rep  # noqa: E402
import sandbox_outputs as so  # noqa: E402

GEN = 'def generate_inputs():\n    return [{"args": [1]}, {"args": [2]}, {"args": [0]}, {"args": [3], "kwargs": {}}]'
F_OK = 'def f(x):\n    return 10 // x'
F_OTHER = 'def f(x):\n    return 10 // x if x != 3 else -1'
F_SLOW = 'def f(x):\n    while x == 2:\n        pass\n    return 10 // x'
FAMILY = ('arithmetic', 'number', 'target', 'puzzle', 'countdown', 'shell', 'table', 'path', 'cache')


STATE = dict(Running=False, ExitCode=0, OOMKilled=False, StartedAt='2026-11-27T10:00:00.000000Z',
             FinishedAt='2026-11-27T10:00:01.500000Z')


class FakeHost:
    """Stands in for sandbox_code._ssh: answers the identity probe as spark-0N and, for the host script, runs the
    trusted RUNNER locally on the payload (only test snippets reach it) and appends the container state."""

    def __init__(self, identity=None, state=None):
        self.identity, self.state, self.commands = identity, state or STATE, []

    def __call__(self, host, command, payload=None, timeout=15):
        self.commands.append((host, command, payload))
        script = command[-1]
        if script.startswith('hostname;'):
            name = self.identity or so.FLEET[host]
            return subprocess.CompletedProcess(command, 0, f'{name}\n{name} DAEMON-{host}\n', '')
        run = subprocess.run([sys.executable, '-I', '-S', '-c', so.RUNNER], input=payload, capture_output=True,
                             text=True, timeout=timeout)
        return subprocess.CompletedProcess(command, 0, run.stdout + so.STATE_MARK + json.dumps(self.state), '')


class Guarded(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('no network in tests'))
        guard.start()
        self.addCleanup(guard.stop)
        identity = getattr(so, '_IDENTITY', {})
        identity.clear()
        self.addCleanup(identity.clear)
        self.host = FakeHost()
        p = patch.object(so.sc, '_ssh', self.host)
        p.start()
        self.addCleanup(p.stop)


class ReviewSandboxTests(Guarded):
    def test_review_only_frozen_fleet_hosts_with_a_verified_identity(self):
        """Blocker 1: arbitrary aliases are refused; a host whose hostname or Docker daemon is not spark-0N gets no
        code."""
        for host in ('myalias', 'Spark_05', 'spark-01', 'user@Spark_01'):
            with self.assertRaises(ValueError):
                so.run('outputs', F_OK, 'f', host, inputs=[{'args': [1]}])
        so._IDENTITY.clear()
        liar = FakeHost(identity='controller')
        with patch.object(so.sc, '_ssh', liar), self.assertRaises(so.HostIdentityError):
            so.run('outputs', F_OK, 'f', 'Spark_02', inputs=[{'args': [1]}])
        self.assertTrue(all(payload is None for _, _, payload in liar.commands))  # no code was sent
        self.assertEqual(len(liar.commands), 1)

    def test_review_host_side_deadline_cap_and_label_verified_cleanup(self):
        """Blocker 2: the host enforces the deadline, caps the output and removes the container itself."""
        so.run('outputs', F_OK, 'f', 'Spark_01', inputs=[{'args': [1]}], total_timeout=60)
        script = self.host.commands[-1][1][-1]
        lines = script.splitlines()
        run_line = next(i for i, line in enumerate(lines) if 'docker run' in line)
        self.assertTrue(lines[0].startswith('[ "$(hostname)" = spark-01 ]'))  # identity before the code
        self.assertIn('DAEMON-Spark_01', lines[1])
        self.assertLess(1, run_line)
        self.assertTrue(lines[run_line].startswith('timeout -k 5 65 docker run'))
        run_cmd = script[script.index('timeout -k 5 65 docker run'):script.index('printf %s')]
        self.assertTrue(run_cmd.rstrip().endswith(f'| head -c {so.OUTPUT_CAP}'))  # capped on the host
        self.assertIn('trap cleanup EXIT HUP INT TERM', script)
        self.assertIn('swarm-lab.code-owner', script.split('trap')[0])
        self.assertIn('swarm-lab.code-task', script.split('trap')[0])

    def test_review_timers_cover_encoding_and_serialization(self):
        slow = ('import time\nclass Slow:\n    def __repr__(self):\n        time.sleep(5)\n        return "x"\n'
                'def f(x):\n    return Slow()')
        t0 = __import__('time').monotonic()
        out = so.run('outputs', slow, 'f', 'Spark_01', inputs=[{'args': [1]}], per_input=0.3, total_timeout=10)
        self.assertEqual(out['outcomes'][0]['preview'], 'timeout')  # the encoding ran under the per-input timer
        self.assertLess(__import__('time').monotonic() - t0, 4)
        big = 'def generate_inputs():\n    return [{"args": ["x" * 50000]} for _ in range(10)]'
        self.assertIn('size cap', so.run('generate', big, 'generate_inputs', 'Spark_01')['error'])

    def test_review_output_cap_and_host_deadline_outcomes(self):
        self.assertEqual(so.parse_host_output('abc' + so.STATE_MARK + '{"Running": false}'),
                         ('abc', {'Running': False}))
        with patch.object(so, 'OUTPUT_CAP', 10):
            self.assertIn('over the cap', so.run('outputs', F_OK, 'f', 'Spark_01', inputs=[{'args': [1]}])['error'])
        stuck = FakeHost(state=dict(STATE, Running=True))
        with patch.object(so.sc, '_ssh', stuck):
            self.assertEqual(so.run('outputs', F_OK, 'f', 'Spark_01', inputs=[{'args': [1]}])['status'], 'timeout')

    def test_should_container_seconds_from_the_host_state(self):
        self.assertEqual(so.run('outputs', F_OK, 'f', 'Spark_01', inputs=[{'args': [1]}])['container_seconds'], 1.5)


class SandboxTests(Guarded):
    def test_generate_and_outputs(self):
        gen = so.run('generate', GEN, 'generate_inputs', 'Spark_01', total_timeout=10)
        self.assertEqual((gen['status'], len(gen['inputs'])), ('ok', 4))
        self.assertEqual(gen['container_seconds'], 1.5)
        out = so.run('outputs', F_OK, 'f', 'Spark_01', inputs=gen['inputs'])
        kinds = [o['preview'].split(':')[0] for o in out['outcomes']]
        self.assertEqual(kinds, ['I', 'I', 'exception', 'I'])
        self.assertEqual(out['outcomes'][2]['preview'], 'exception:ZeroDivisionError')
        other = so.run('outputs', F_OTHER, 'f', 'Spark_01', inputs=gen['inputs'])
        self.assertEqual([a['sha256'] == b['sha256'] for a, b in zip(out['outcomes'], other['outcomes'])],
                         [True, True, True, False])

    def test_per_input_timeout_is_an_outcome_and_load_errors_are_unavailable(self):
        inputs = [{'args': [1]}, {'args': [2]}]
        out = so.run('outputs', F_SLOW, 'f', 'Spark_01', inputs=inputs, per_input=0.3, total_timeout=5)
        self.assertEqual([o['preview'] for o in out['outcomes']], ['I:10', 'timeout'])
        self.assertEqual(so.run('outputs', 'def g(): pass', 'f', 'Spark_01', inputs=inputs)['status'], 'error')
        self.assertEqual(so.run('outputs', F_SLOW, 'f', 'Spark_01', inputs=[{'args': [2]}] * 5, per_input=1,
                                total_timeout=1.5)['status'], 'timeout')
        bad = so.run('generate', 'def generate_inputs():\n    return [{"x": 1}]', 'generate_inputs', 'Spark_01')
        self.assertEqual(bad['status'], 'error')

    def test_type_tags_and_never_the_controller_host(self):
        code = ('def f(x):\n    return [True, 1, 1.0, "1", None, {"b": 1, "a": (1,)}][x]')
        out = so.run('outputs', code, 'f', 'Spark_01', inputs=[{'args': [i]} for i in range(6)])
        self.assertEqual([o['preview'] for o in out['outcomes']],
                         ['B:true', 'I:1', 'F:1.0', 'S:"1"', 'N', 'D{S:"a":O:tuple:(1,),S:"b":I:1}'])
        for host in ('localhost', 'user@127.0.0.1', 'bad host'):
            with self.assertRaises(ValueError):
                so.run('outputs', F_OK, 'f', host, inputs=[{'args': [1]}])


def item(kind='wrong', refs=4):
    return dict(item_id='g000', run='r', task_id='t', seed=1, kind=kind, function_name='f',
                passers=[dict(agent=0, code=F_OK, code_sha256='a')],
                references=[dict(run='r2', seed=s, agent=0, code=F_OTHER if s % 2 else F_OK, code_sha256=f'r{s}',
                                 holdout_pass=True) for s in range(refs)])


def sha_file(path):
    import hashlib
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifacts(root, items, gen_records=None, gen_complete=True):
    """Frozen plan, population, generator plan and a generator run bound to them."""
    (root / 'plan.json').write_text(json.dumps(dict(study='diffgate-v1', status='FROZEN')))
    (root / 'pop.json').write_text(json.dumps(dict(status='FROZEN', items=items)))
    (root / 'gen_plan.json').write_text(json.dumps(dict(status='FROZEN',
                                                        population_sha256=sha_file(root / 'pop.json'))))
    gen = root / 'gen'
    (gen / 'run').mkdir(parents=True)
    (gen / 'metadata.json').write_text(json.dumps(dict(plan_sha256=sha_file(root / 'gen_plan.json'))))
    (gen / 'summary.json').write_text(json.dumps(dict(complete=gen_complete, drain_confirmed=True)))
    rows = gen_records if gen_records is not None else [dict(item=i['item_id'], outcome='ok', reply=GEN,
                                                             tokens_generated=100, error=None) for i in items]
    (gen / 'run' / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    return gen


def exec_argv(root, out='ex'):
    return ['--plan', str(root / 'plan.json'), '--gen-plan', str(root / 'gen_plan.json'), '--population',
            str(root / 'pop.json'), '--generations', str(root / 'gen'), '--hosts', 'Spark_01', '--output',
            str(root / out)]


class ExecTests(Guarded):
    def test_run_item_fence_and_unavailable_paths(self):
        rec, fault = de.run_item(item(), dict(outcome='ok', reply='Here:\n```python\n' + GEN + '\n```\n'), 'Spark_01')
        self.assertIsNone(fault)
        self.assertEqual((rec['inputs_status'], len(rec['programs'])), ('ok', 5))
        self.assertEqual(rec['programs'][0]['role'], 'accepted')
        self.assertFalse(any('holdout_pass' in p for p in rec['programs']))  # SHOULD: no hidden labels
        self.assertEqual(de.run_item(item(), dict(outcome='truncated', reply=GEN), 'Spark_01')[0]['inputs_status'],
                         'generator reply truncated')
        self.assertTrue(de.run_item(item(), dict(outcome='ok', reply='def nope(): pass'), 'Spark_01')[0]
                        ['inputs_status'].startswith('error'))

    def test_infrastructure_fault_stops_and_resume(self):
        def infra(*a, **k):
            return dict(status='error', infrastructure=True, error='ssh down')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            artifacts(root, [item()])
            argv = exec_argv(root)
            self.assertEqual(de.main(argv, runner=infra), 1)
            self.assertEqual(json.loads((root / 'ex' / 'summary.json').read_text())['faults'][0]['item'], 'g000')
            self.assertEqual(de.main(argv), 0)  # resumed: the item is now recorded
            self.assertTrue(json.loads((root / 'ex' / 'summary.json').read_text())['complete'])
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                de.main(argv[:-4] + ['--hosts', 'localhost', '--output', str(root / 'ex2')])

    def test_review_rows_are_bound_and_stale_rows_are_refused(self):
        """Blocker 3: rows carry the plan, population, generator plan and generation record bindings; a resume
        refuses rows bound to anything else; a missing generator record stops the run (never 'unavailable')."""
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            artifacts(root, [item()])
            self.assertEqual(de.main(exec_argv(root)), 0)
            row = json.loads((root / 'ex' / 'records.jsonl').read_text())
            self.assertEqual(set(row['bindings']), {'plan_sha256', 'population_sha256', 'gen_plan_sha256',
                                                    'generation_sha256'})
            (root / 'gen' / 'run' / 'records.jsonl').write_text(json.dumps(dict(
                item='g000', outcome='ok', reply=GEN + '\n# another reply', tokens_generated=100, error=None)) + '\n')
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                de.main(exec_argv(root))  # the recorded row is bound to the old generation record: stale
            (root / 'gen' / 'run' / 'records.jsonl').write_text('')
            with self.assertRaises(SystemExit), patch('sys.stderr'):
                de.main(exec_argv(root, out='ex3'))  # no generator record: refused, nothing recorded
            self.assertFalse((root / 'ex3' / 'records.jsonl').exists())


def record(statuses, accepted_ok=True, agree=(), inputs='ok'):
    """statuses: per reference 'ok' or 'error'; agree: indices of references whose outcomes equal the accepted."""
    acc = dict(role='accepted', status='ok' if accepted_ok else 'timeout', outcomes=['x', 'y'])
    refs = [dict(role='reference', status=s, outcomes=['x', 'y'] if i in agree else ['x', 'z'])
            for i, s in enumerate(statuses)]
    return dict(item='g000', inputs_status=inputs, inputs=[{}, {}], programs=[acc] + refs, sandbox_seconds=2.0)


class ReportTests(unittest.TestCase):
    def test_gate_rule(self):
        self.assertEqual(rep.gate(record(['ok'] * 4, agree=(0, 1)))[:3], ('pass', 2, 4))  # 2 of 4 is not a majority
        self.assertEqual(rep.gate(record(['ok'] * 4, agree=(0,)))[:3], ('flag', 3, 4))
        self.assertTrue(rep.gate(record(['ok'] * 4, agree=(0, 1, 2)))[3])  # any-reference variant
        self.assertEqual(rep.gate(record(['ok', 'ok', 'error', 'error'], agree=(0, 1)))[0], 'unavailable')
        self.assertEqual(rep.gate(record(['ok', 'error', 'ok', 'ok'], agree=(0, 2, 3)))[:3], ('pass', 0, 3))
        self.assertEqual(rep.gate(record(['ok'] * 4, accepted_ok=False))[0], 'flag')
        self.assertEqual(rep.gate(record(['ok'] * 4, inputs='error: x'))[0], 'unavailable')

    def build(self, kinds_and_records, gen_complete=True, exec_complete=True, gen_drop=(), unbind=()):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            items = [dict(item(kind), item_id=f'g{n:03d}') for n, (kind, _) in enumerate(kinds_and_records)]
            gens = [dict(item=i['item_id'], outcome='ok', reply=GEN, tokens_generated=100, error=None)
                    for i in items if i['item_id'] not in gen_drop]
            gen = artifacts(root, items, gen_records=gens, gen_complete=gen_complete)
            shas = (sha_file(root / 'plan.json'), sha_file(root / 'pop.json'), sha_file(root / 'gen_plan.json'))
            by = {g['item']: g for g in gens}
            recs = []
            for it, (_, rec) in zip(items, kinds_and_records):
                bound = de.bindings(*shas, by.get(it['item_id'], {}))
                if it['item_id'] in unbind:
                    bound = dict(bound, generation_sha256='0' * 64)
                recs.append(dict(rec, item=it['item_id'], bindings=bound))
            (root / 'ex').mkdir()
            (root / 'ex' / 'summary.json').write_text(json.dumps(dict(complete=exec_complete)))
            (root / 'ex' / 'records.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in recs))
            return rep.build(dict(status='FROZEN', items=items), gen, root / 'ex', root / 'plan.json',
                             root / 'gen_plan.json', root / 'pop.json')

    def test_review_unbound_rows_and_missing_generator_records_are_incomplete(self):
        ok = record(['ok'] * 4, agree=(0, 1, 2, 3))
        r = self.build([('wrong', ok), ('correct', ok)], unbind=('g001',))
        self.assertTrue(r['decision'].startswith('INCOMPLETE'))
        self.assertIn('not bound', ' '.join(r['problems']))
        r = self.build([('wrong', ok), ('correct', ok)], gen_drop=('g000',))
        self.assertTrue(r['decision'].startswith('INCOMPLETE'))  # never an 'unavailable' gate
        self.assertIn('generator records are not exactly one per item', ' '.join(r['problems']))

    def test_kill_rule(self):
        flag, ok = record(['ok'] * 4, agree=()), record(['ok'] * 4, agree=(0, 1, 2, 3))
        r = self.build([('wrong', flag), ('wrong', ok), ('correct', ok)] + [('correct', ok)] * 9)
        self.assertEqual((r['flagged_wrong']['rate'], r['flagged_correct']['rate'], r['decision'][:8]),
                         (0.5, 0.0, 'SURVIVES'))
        r = self.build([('wrong', flag), ('wrong', ok), ('wrong', ok), ('correct', ok)])  # 1 of 3 < 40 %
        self.assertEqual(r['decision'], 'KILL')
        r = self.build([('wrong', flag), ('correct', flag)] + [('correct', ok)] * 8)  # 1 of 9 > 10 %
        self.assertEqual(r['decision'], 'KILL')
        self.assertEqual((r['generator_tokens'], r['sandbox_seconds']), (1000, 20.0))
        self.assertEqual(r['per_run']['r']['sandbox_seconds'], 20.0)  # SHOULD: per-run breakdown

    def test_incomplete(self):
        ok = record(['ok'] * 4, agree=(0, 1, 2, 3))
        self.assertTrue(self.build([('wrong', ok)], gen_complete=False)['decision'].startswith('INCOMPLETE'))
        self.assertTrue(self.build([('wrong', ok)], exec_complete=False)['decision'].startswith('INCOMPLETE'))


class GenPlanTests(unittest.TestCase):
    def test_plan_is_generic_and_carries_only_the_payload(self):
        root = Path(__file__).resolve().parent
        if not (root / 'DIFFGATE_POPULATION.json').exists():
            self.skipTest('no frozen population in this tree')
        plan = gp.make('0' * 40, root)
        added = (plan['system'] + ' ' + plan['user'].replace('{payload}', '')).lower()
        self.assertEqual([w for w in FAMILY if w in added], [])
        self.assertTrue(all(set(json.loads(i['payload'])) == {'function_name', 'spec'} for i in plan['items']))
        self.assertEqual((plan['per_node'], plan['think_tokens'], plan['total_tokens']), (20, 8192, 10240))
        self.assertEqual(set(plan['judge_code_sha256']), {'inkling/fleet_lease.py', 'inkling/admit.py'})


if __name__ == '__main__':
    unittest.main()
